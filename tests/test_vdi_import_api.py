"""Staged VDI imports remain isolated from ServiceNow and use disposable fixtures."""
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import vdi_data as data
import vdi_data_api as api
from sqlite_fixture import connect as fixture_connect
from test_vdi_data import csv_bytes, device, directory, user


BASE = '/api/vdi-data/import'
TOKEN = {'x-atlas-token': 'fictional-token'}


class VdiImportApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'persistent' / 'office_atlas.db'
        self.db.parent.mkdir()
        with fixture_connect(self.db) as con:
            directory(con)
        app = FastAPI()

        def token(request):
            if request.headers.get('x-atlas-token') != TOKEN['x-atlas-token']:
                raise HTTPException(403, 'Missing local administrator token')

        api.register(app, SimpleNamespace(MASTER_DB=self.db, jobs={}, queue_jobs={}), token)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def preview(self, rows, *, full=False, filename='Citrix VDI.csv'):
        headers = {**TOKEN, 'x-file-name': filename}
        response = self.client.post(BASE + '/preview', params={'full_snapshot': str(full).lower()}, content=csv_bytes(rows), headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIs(response.json()['full_snapshot'], full)
        return response.json()

    def apply(self, preview, *, mode=None):
        if mode is None:
            mode = preview['full_snapshot']
        return self.client.post(BASE + '/apply/' + preview['id'], json={'full_snapshot': mode}, headers=TOKEN)

    def saved(self, rows, *, full=False):
        preview = self.preview(rows, full=full)
        response = self.apply(preview)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def snapshot(self):
        with fixture_connect(self.db) as con:
            return {table: con.execute('select * from ' + table + ' order by 1,2').fetchall()
                    for table in ('vdi_devices', 'vdi_user_refs', 'vdi_links')}

    def servicenow(self):
        with fixture_connect(self.db) as con:
            return {table: con.execute('select * from ' + table + ' order by 1').fetchall()
                    for table in ('users', 'user_aliases', 'machines', 'assignments')}

    def test_preview_apply_and_delete_require_local_administrator_token(self):
        payload = csv_bytes([device()])
        self.assertEqual(self.client.post(BASE + '/preview', content=payload).status_code, 403)
        preview = self.preview([device()])
        self.assertEqual(self.client.post(BASE + '/apply/' + preview['id'], json={'full_snapshot': False}).status_code, 403)
        self.assertEqual(self.client.delete(BASE + '/preview/' + preview['id']).status_code, 403)
        self.assertEqual(self.snapshot()['vdi_devices'], [])
        self.assertEqual(self.apply(preview).status_code, 200)

    def test_full_snapshot_confirmation_is_a_boolean_and_matches_preview_mode(self):
        preview = self.preview([device()], full=True)
        self.assertEqual(self.apply(preview, mode=False).status_code, 409)
        for body in ({}, {'full_snapshot': 'true'}, {'full_snapshot': 1}, {'full_snapshot': None}):
            with self.subTest(body=body):
                response = self.client.post(BASE + '/apply/' + preview['id'], json=body, headers=TOKEN)
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.snapshot()['vdi_devices'], [])
        self.assertEqual(self.apply(preview).status_code, 200)
        invalid = self.client.post(BASE + '/preview?full_snapshot=definitely', content=csv_bytes([device()]), headers={**TOKEN, 'x-file-name': 'export.csv'})
        self.assertIn(invalid.status_code, (400, 422))

    def test_incremental_omission_keeps_devices_but_supplied_blank_users_clear_assignments(self):
        before = self.servicenow()
        self.saved([device('INTRANET\\VDI-A'), device('INTRANET\\VDI-B')])
        self.saved([device('INTRANET\\VDI-A', '')])
        with fixture_connect(self.db) as con:
            con.row_factory = sqlite3.Row
            current = data.load(con)
            self.assertEqual(len(current), 2)
            linked = data.machines_for_user(con, 'uid:g0123456')
            self.assertEqual([row['name'] for row in linked], ['VDI-B'])
            self.assertEqual(con.execute("select count(*) from vdi_user_refs where machine_key='netbios:intranet\\vdi-a'").fetchone()[0], 0)
        self.assertEqual(self.servicenow(), before)

    def test_full_snapshot_replaces_only_vdi_records_refs_and_links(self):
        before = self.servicenow()
        self.saved([device('INTRANET\\VDI-A'), device('INTRANET\\VDI-B')])
        self.saved([device('INTRANET\\VDI-A', '')], full=True)
        with fixture_connect(self.db) as con:
            current = data.load(con)
            self.assertEqual(set(current), {'netbios:intranet\\vdi-a'})
            self.assertEqual(con.execute('select count(*) from vdi_user_refs').fetchone()[0], 0)
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
        self.assertEqual(self.servicenow(), before)

    def test_directory_identity_and_generation_changes_require_fresh_preview(self):
        mutations = ["update users set user_id='G9999999',user_id_norm='g9999999' where id=1",
                     "update metadata set value='fictional-directory-2' where key='generation'"]
        for sql in mutations:
            with self.subTest(sql=sql):
                preview = self.preview([device()])
                with fixture_connect(self.db) as con:
                    con.execute(sql)
                self.assertEqual(self.apply(preview).status_code, 409)
                self.assertEqual(self.snapshot()['vdi_devices'], [])

    def test_reused_directory_ids_cannot_change_alias_ownership_after_preview(self):
        with fixture_connect(self.db) as con:
            user(con, 2, 'G7654321', name='Different Account')
        preview = self.preview([device()])
        with fixture_connect(self.db) as con:
            # Canonical accounts, aliases and generation are unchanged; their
            # numeric identity mapping is an input to account-alias matching.
            con.execute('update users set id=3 where id=1')
            con.execute('update users set id=1 where id=2')
            con.execute('update users set id=2 where id=3')
        self.assertEqual(self.apply(preview).status_code, 409)
        self.assertEqual(self.snapshot()['vdi_devices'], [])

    def test_changed_vdi_raw_provenance_refs_or_links_requires_fresh_preview(self):
        self.saved([device()])
        mutations = ["update vdi_devices set raw_json='{}'",
                     "update vdi_devices set source_rows_json='{}'",
                     "update vdi_user_refs set raw_ref='Changed literal account'",
                     'delete from vdi_links']
        for sql in mutations:
            with self.subTest(sql=sql):
                preview = self.preview([device('INTRANET\\VDI-NEW')])
                with fixture_connect(self.db) as con:
                    con.execute(sql)
                before = self.snapshot()
                self.assertEqual(self.apply(preview).status_code, 409)
                self.assertEqual(self.snapshot(), before)

    def test_history_write_failure_rolls_back_devices_refs_links_and_allows_retry(self):
        self.saved([device('INTRANET\\VDI-OLD')])
        before = self.snapshot()
        sn_before = self.servicenow()
        preview = self.preview([device('INTRANET\\VDI-NEW')], full=True)
        with fixture_connect(self.db) as con:
            con.execute("create trigger reject_vdi_history before insert on vdi_imports begin select raise(abort,'fictional history failure'); end")
            history_count = con.execute('select count(*) from vdi_imports').fetchone()[0]
        response = self.apply(preview)
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.servicenow(), sn_before)
        with fixture_connect(self.db) as con:
            self.assertEqual(con.execute('select count(*) from vdi_imports').fetchone()[0], history_count)
            con.execute('drop trigger reject_vdi_history')
        self.assertEqual(self.apply(preview).status_code, 200)

    def test_backup_is_vdi_only_and_follows_active_database_without_source_root_patch(self):
        self.saved([device('INTRANET\\VDI-OLD')])
        result = self.saved([device('INTRANET\\VDI-NEW')], full=True)
        backup = self.db.parent / 'backups' / result['backup']
        self.assertTrue(backup.is_file())
        with gzip.open(backup, 'rt', encoding='utf-8') as stream:
            archived = json.load(stream)
        text = json.dumps(archived)
        self.assertIn('VDI-OLD', text)
        self.assertNotIn('PHYSICAL-001', text)
        self.assertNotIn('full_name', text)
        self.assertNotIn('email_norm', text)
        self.assertNotIn('VDI-NEW', text)
        with fixture_connect(self.db) as con:
            path = con.execute('select backup from vdi_imports order by at desc limit 1').fetchone()[0]
        self.assertEqual(Path(path), backup)

    def test_discarded_replaced_and_expired_previews_cannot_apply(self):
        first = self.preview([device()])
        second = self.preview([device('INTRANET\\VDI-2')])
        self.assertEqual(self.apply(first).status_code, 409)
        self.assertEqual(self.client.delete(BASE + '/preview/' + second['id'], headers=TOKEN).status_code, 200)
        self.assertEqual(self.apply(second).status_code, 409)
        third = self.preview([device('INTRANET\\VDI-3')])
        now = time.time()
        with patch.object(api.time, 'time', return_value=now + 3601):
            self.assertEqual(self.apply(third).status_code, 409)
        self.assertEqual(self.snapshot()['vdi_devices'], [])

    def test_raw_source_name_is_sanitized_and_preserved_cells_remain_available(self):
        original = device(**{'Custom Flag': '  <script>literal</script>  '})
        preview = self.preview([original], filename='C%3A%5CExports%5CCitrix%20VDI.csv')
        self.assertEqual(self.apply(preview).status_code, 200)
        with fixture_connect(self.db) as con:
            row = next(iter(data.load(con).values()))
        self.assertEqual(row['source'], 'Citrix VDI.csv')
        self.assertEqual(json.loads(row['source_rows_json'])['rows'][0]['cells'], original)


if __name__ == '__main__':
    unittest.main()
