"""Directory recovery regressions using small, fictional temporary databases."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database_manager as manager
import refresh_directory
import runtime_paths
from directory_workbook import build
from merge_data import atlas_schema, merge_directory, build as build_shared
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import device_sheets, workbook


class DirectoryTransactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'persistent' / 'office_atlas.db'
        self.db.parent.mkdir()
        self.old_book = self.make_directory('original', 'Original Person', self.db)
        self.new_db = self.root / 'replacement.db'
        self.new_book = self.make_directory('replacement', 'Replacement Person', self.new_db)

    def make_directory(self, name, person, output):
        sheets = device_sheets()
        sheets['users'][1][1] = person
        book = self.root / (name + '.xlsx')
        workbook(book, sheets)
        with contextlib.redirect_stdout(io.StringIO()):
            build(book, output)
        with fixture_connect(output) as con:
            atlas_schema(con)
        return book

    def person(self, path=None):
        with fixture_connect(path or self.db) as con:
            return con.execute("select full_name from users where user_id='u1'").fetchone()[0]

    def client(self):
        app = FastAPI()
        manager.register_database_manager(app, SimpleNamespace(MASTER_DB=self.db, jobs={}, queue_jobs={}), lambda request: None)
        return TestClient(app, raise_server_exceptions=False)

    def stage(self, client):
        with contextlib.redirect_stdout(io.StringIO()):
            response = client.post('/api/database/preview', content=self.new_book.read_bytes(), headers={'x-file-name': 'Replacement.xlsx'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def apply(self, client, stage):
        return client.post('/api/database/apply/' + stage, json={'confirmation': 'APPLY', 'full_snapshot': True})

    def test_api_backups_follow_persistent_database_without_patching_source_root(self):
        with self.client() as client:
            result = self.apply(client, self.stage(client))
            self.assertEqual(result.status_code, 200, result.text)
            backup = self.db.parent / 'backups' / result.json()['backup']
            self.assertEqual(self.person(backup), 'Original Person')
            self.assertEqual(self.person(), 'Replacement Person')
            with fixture_connect(self.db) as con:
                stored = con.execute('select backup from directory_import_history').fetchone()[0]
            self.assertEqual(Path(stored), backup)

    def test_history_write_failure_rolls_back_directory_and_allows_retry(self):
        with self.client() as client:
            stage = self.stage(client)
            before = manager.fingerprint(self.db)
            with fixture_connect(self.db) as con:
                metadata = con.execute('select * from metadata order by key').fetchall()
                con.execute("create trigger reject_history before insert on directory_import_history begin select raise(abort,'fixture history failure'); end")
            self.assertEqual(self.apply(client, stage).status_code, 500)
            self.assertEqual(manager.fingerprint(self.db), before)
            self.assertEqual(self.person(), 'Original Person')
            with fixture_connect(self.db) as con:
                self.assertEqual(con.execute('select * from metadata order by key').fetchall(), metadata)
                self.assertEqual(con.execute('select count(*) from directory_import_history').fetchone()[0], 0)
                con.execute('drop trigger reject_history')
            self.assertEqual(self.apply(client, stage).status_code, 200)
            self.assertEqual(self.person(), 'Replacement Person')

    def test_final_metadata_failure_also_rolls_back_import_history(self):
        with self.client() as client:
            stage = self.stage(client)
            before = manager.fingerprint(self.db)
            with fixture_connect(self.db) as con:
                con.execute("create trigger reject_stamp before insert on metadata when new.key='directory.created_at' and instr(new.value,'+00:00')>0 begin select raise(abort,'fixture stamp failure'); end")
            self.assertEqual(self.apply(client, stage).status_code, 500)
            self.assertEqual(manager.fingerprint(self.db), before)
            self.assertEqual(self.person(), 'Original Person')
            with fixture_connect(self.db) as con:
                self.assertEqual(con.execute('select count(*) from directory_import_history').fetchone()[0], 0)

    def test_change_immediately_before_write_lock_rejects_staged_import(self):
        with self.client() as client:
            stage = self.stage(client)
            original = manager.apply_refresh

            def external_change(*args, **kwargs):
                with fixture_connect(self.db) as con:
                    con.execute("update users set full_name='External Change' where user_id='u1'")
                return original(*args, **kwargs)

            with patch.object(manager, 'apply_refresh', external_change):
                response = self.apply(client, stage)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self.person(), 'External Change')
            self.assertEqual(list((self.db.parent / 'backups').glob('*.db')), [])

    def test_backup_and_replacement_hold_the_same_writer_reservation(self):
        calls = []

        def while_locked(con):
            calls.append(con.execute("select full_name from users where user_id='u1'").fetchone()[0])
            with fixture_connect(self.db, timeout=0) as competing:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    competing.execute("update users set full_name='Competing Writer' where user_id='u1'")

        backup = refresh_directory.apply_refresh(self.db, self.new_db, self.db.parent / 'backups', before_merge=while_locked)
        self.assertEqual(calls, ['Original Person'])
        self.assertEqual(self.person(backup), 'Original Person')
        self.assertEqual(self.person(), 'Replacement Person')

    def test_restore_prefers_current_directory_metadata_once_and_preserves_atlas_state(self):
        with fixture_connect(self.db) as con:
            con.execute("insert into metadata values('atlas.seeded','keep-target')")
        merge_directory(self.db, self.new_db)
        restored_stats = {'machine': {'duplicate_rows': 7}}
        with fixture_connect(self.db) as con:
            con.execute("update metadata set value=? where key='directory.import_resolution'", (json.dumps(restored_stats),))
            con.commit()
            backup = self.root / 'restore.db'
            with fixture_connect(backup) as saved:
                con.backup(saved)
        third = self.root / 'third.db'
        self.make_directory('third', 'Third Person', third)
        merge_directory(self.db, third)
        merge_directory(self.db, backup)
        self.assertEqual(self.person(), 'Replacement Person')
        with fixture_connect(self.db) as con:
            metadata = dict(con.execute('select key,value from metadata'))
        self.assertEqual(metadata['directory.source_file'], 'replacement.xlsx')
        self.assertEqual(json.loads(metadata['directory.import_resolution']), restored_stats)
        self.assertEqual(metadata['atlas.seeded'], 'keep-target')
        from identity_links import MATCHING_VERSION
        self.assertEqual(metadata['directory.matching_version'], MATCHING_VERSION)
        self.assertEqual({k for k in metadata if k.startswith('directory.')}, {'directory.schema_version', 'directory.created_at', 'directory.source_file', 'directory.import_resolution', 'directory.generation', 'directory.matching_version'})

    def test_same_timestamp_refresh_invalidates_cached_names_before_reused_user_ids(self):
        from desk_directory import resolve_person
        from directory_lookup import prepare_views

        previous = self.root / 'previous.db'
        with fixture_connect(self.db) as source, fixture_connect(previous) as target:
            source.backup(target)
        for path in (self.db, previous, self.new_db):
            with fixture_connect(path) as con:
                con.execute("update metadata set value='2026-10-06 12:00:00' where key='created_at'")
        merge_directory(self.db, previous)
        with fixture_connect(self.db) as con:
            con.row_factory = sqlite3.Row
            prepare_views(con)
            desk = {'id': 'custom-cache-fixture', 'occupancy': 'assigned', 'name': 'Original Person'}
            people, _ = resolve_person(con, desk)
            self.assertEqual(people[0]['full_name'], 'Original Person')
            before = con.execute("select value from metadata where key='directory.generation'").fetchone()[0]
            merge_directory(self.db, self.new_db)
            after = con.execute("select value from metadata where key='directory.generation'").fetchone()[0]
            self.assertNotEqual(before, after)
            self.assertEqual(resolve_person(con, desk), ([], 'unmatched'))
            desk['name'] = 'Replacement Person'
            people, method = resolve_person(con, desk)
            self.assertEqual((people[0]['full_name'], method), ('Replacement Person', 'name-match'))

    def test_merge_cli_defaults_to_active_runtime_database_and_leaves_seed_untouched(self):
        root_seed = self.root / 'office_atlas.db'
        with fixture_connect(self.db) as source, fixture_connect(root_seed) as target:
            source.backup(target)
        with patch.dict(os.environ, {'ATLAS_DB_PATH': str(self.db)}), patch.object(sys, 'argv', ['merge_data.py', '--refresh-directory', str(self.new_db)]), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(Path(manager.__file__).parent / 'merge_data.py'), run_name='__main__')
        self.assertEqual(self.person(), 'Replacement Person')
        self.assertEqual(self.person(root_seed), 'Original Person')

    def test_refresh_cli_places_backup_alongside_configured_database(self):
        with patch.object(runtime_paths, 'database_path', return_value=self.db), patch.object(sys, 'argv', ['refresh_directory.py', '--source', str(self.new_book)]), patch('builtins.input', return_value='APPLY'), contextlib.redirect_stdout(io.StringIO()):
            refresh_directory.main()
        backups = list((self.db.parent / 'backups').glob('*.db'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.person(backups[0]), 'Original Person')
        self.assertEqual(self.person(), 'Replacement Person')

    def bootstrap_fixture(self):
        import atlas_store

        assets = self.root / 'fictional-atlas'
        assets.mkdir()
        desk = {'id': 'custom-bootstrap', 'floor': 4, 'x': 0.2, 'y': 0.3, 'angle': 0,
                'kind': 'desk', 'occupancy': 'vacant', 'name': 'Vacant desk'}
        (assets / 'data.json').write_text(json.dumps({'records': [desk]}), encoding='utf-8')
        history = self.root / 'history.db'
        with fixture_connect(history) as con:
            con.execute('create table deployments(id text primary key,state text)')
            con.execute("insert into deployments values('fixture-job','complete')")
        return atlas_store, assets, history

    def test_bootstrap_failure_leaves_no_partial_target_and_valid_retry_restores_store_path(self):
        store, assets, history = self.bootstrap_fixture()
        invalid = self.root / 'invalid-history.db'
        fixture_connect(invalid).close()
        target = self.root / 'bootstrap.db'
        with patch.multiple(store, ROOT=assets, DB=self.db):
            with self.assertRaisesRegex(ValueError, 'no deployments table'):
                build_shared(target, self.db, invalid)
            self.assertFalse(target.exists())
            self.assertEqual(store.DB, self.db)
            build_shared(target, self.db, history)
            self.assertEqual(store.DB, self.db)
        self.assertEqual(list(self.root.glob('.bootstrap.db.*')), [])
        with fixture_connect(target) as con:
            self.assertEqual(con.execute('select * from deployments').fetchall(), [('fixture-job', 'complete')])
            self.assertEqual(con.execute('select id from records').fetchall(), [('custom-bootstrap',)])
            self.assertEqual(con.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_bootstrap_does_not_overwrite_target_created_during_build(self):
        store, assets, history = self.bootstrap_fixture()
        target = self.root / 'bootstrap.db'
        original = store.initialize

        def competing_builder():
            original()
            target.write_bytes(b'KEEP CONCURRENT TARGET')

        with patch.multiple(store, ROOT=assets, DB=self.db), patch.object(store, 'initialize', competing_builder):
            with self.assertRaises(FileExistsError):
                build_shared(target, self.db, history)
            self.assertEqual(store.DB, self.db)
        self.assertEqual(target.read_bytes(), b'KEEP CONCURRENT TARGET')
        self.assertEqual(list(self.root.glob('.bootstrap.db.*')), [])


if __name__ == '__main__':
    unittest.main()
