"""Existing directory/search/remote guards consume fictional supplemental VDI data."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlite_fixture import connect as fixture_connect, isolate_backend_database
isolate_backend_database()

from backend import main, viewer
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.directory.desk_directory import machine_context
from backend.directory.directory_lookup import exact_users, linked_machines, prepare_views, search_directory
from backend.directory.directory_workbook import schema as directory_schema
from backend.directory.merge_data import merge_directory, atlas_schema
from test_vdi_data import csv_bytes, device, directory, store, user
from backend.directory import vdi_data


class VdiLookup(unittest.TestCase):
    def test_viewer_reads_shared_vdi_and_known_fields_without_writing_or_importing(self):
        with self.connect() as con:
            atlas_schema(con)
            con.execute('create table official_seating_mappings(legacy_id text primary key,official_id text)')
            user(con, 2, 'X7654321', name='Second Fictional User')
            incoming = self.import_rows(con, [device('VDI-SHARED.example.test', 'X0123456;X7654321')])
            key = next(iter(incoming))
        before = self.db.read_bytes()
        with patch.object(viewer, 'DB', self.db), TestClient(viewer.app) as client:
            for account in ('uid:g0123456', 'uid:x7654321'):
                result = client.get('/api/user/' + account)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual([row['vdi_key'] for row in self.virtual(result.json()['machines'])], [key])
            self.assertEqual(client.get('/api/machine/VDI-SHARED.example.test').status_code, 200)
            original = client.get('/api/vdi-data/record/' + key)
            self.assertEqual(original.status_code, 200, original.text)
            self.assertGreater(original.json()['restricted_columns'], 0)
            self.assertNotIn('raw_rows', original.json())
            self.assertNotIn('Custom Flag', [field['header'] for field in original.json()['fields']])
            self.assertEqual(client.post('/api/vdi-data/import/preview', content=b'fictional').status_code, 403)
        self.assertEqual(self.db.read_bytes(), before)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'fictional.db'
        with fixture_connect(self.db) as con:
            directory(con)
            con.execute('create table official_records(id text primary key,body text not null)')

    def connect(self):
        con = fixture_connect(self.db)
        con.row_factory = sqlite3.Row
        prepare_views(con)
        return con

    def import_rows(self, con, rows):
        incoming, _ = vdi_data.parse_csv(csv_bytes(rows))
        store(con, incoming)
        return incoming

    @staticmethod
    def virtual(rows):
        return [row for row in rows if row.get('vdi_key')]

    def test_user_lookup_keeps_physical_devices_and_every_assigned_vdi_user(self):
        with self.connect() as con:
            user(con, 2, 'X7654321', name='Second Fictional User', email='second@example.invalid')
            incoming = self.import_rows(con, [device('INTRANET\\VDI-MULTI', 'INTRANET\\X0123456;INTRANET\\X7654321')])
            key = next(iter(incoming))
            first = linked_machines(con, 1)
            second = linked_machines(con, 2)
            self.assertIn('PHYSICAL-001', [row['name'] for row in first])
            self.assertEqual([row['vdi_key'] for row in self.virtual(first)], [key])
            self.assertEqual([row['vdi_key'] for row in self.virtual(second)], [key])
            self.assertTrue(all(row['assigned_relationship'] for row in self.virtual(first + second)))
            self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 1)
            context = machine_context(con, 'VDI-MULTI')
            self.assertEqual({row['id'] for row in context['users']}, {1, 2})
            self.assertTrue(all(row['assigned_relationship'] for row in context['users']))

    def test_g_export_and_x_windows_aliases_return_the_same_vdi_associations(self):
        with self.connect() as con:
            incoming = self.import_rows(con, [device('VDI-ALIAS', 'INTRANET\\X0123456')])
            key = next(iter(incoming))
            for alias in ('G0123456', 'X0123456', 'INTRANET\\X0123456'):
                with self.subTest(alias=alias):
                    people = exact_users(con, alias)
                    self.assertEqual([row['id'] for row in people], [1])
                    self.assertEqual([row['vdi_key'] for row in self.virtual(linked_machines(con, people[0]['id']))], [key])
        with patch.multiple(main, MASTER_DB=self.db, DB=self.db, HISTORY_DB=self.db), patch.object(main, 'run') as run, patch.object(main, 'ps') as ps:
            with TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
                for alias in ('G0123456', 'X0123456'):
                    response = client.get('/api/user/' + alias)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['user']['id'], 1)
                    self.assertEqual([row['vdi_key'] for row in self.virtual(response.json()['machines'])], [key])
            run.assert_not_called()
            ps.assert_not_called()

    def test_type_vdi_and_exact_dns_search_keep_qualified_remote_targets(self):
        with self.connect() as con:
            incoming = self.import_rows(con, [device('VDI-DNS.one.example.test'), device('VDI-DNS.two.example.test'), device('VDI-OTHER')])
            result = search_directory(con, 'type:vdi')
            self.assertEqual({row['vdi_key'] for row in result['machines']}, set(incoming))
            self.assertEqual(result['users'], [])
            for query in ('VDI-DNS.one.example.test', 'machine:vdi-dns.one.example.test', 'machine:VDI-DNS.ONE.EXAMPLE.TEST.'):
                with self.subTest(query=query):
                    result = search_directory(con, query)
                    self.assertEqual(len(result['machines']), 1)
                    self.assertEqual(result['machines'][0]['name'], 'VDI-DNS.ONE.EXAMPLE.TEST')
                    self.assertTrue(result['machines'][0]['windows_remote_supported'])
            # Shared short DNS labels never discard their safe fully qualified identities.
            short = search_directory(con, 'machine:VDI-DNS')
            self.assertEqual({row['name'] for row in short['machines']}, {'VDI-DNS.ONE.EXAMPLE.TEST', 'VDI-DNS.TWO.EXAMPLE.TEST'})

    def test_netbios_domains_stay_distinct_and_bare_host_context_is_ambiguous(self):
        with self.connect() as con:
            user(con, 2, 'INTRANET\\x55', name='Intranet Fictional User')
            user(con, 3, 'CLIENT\\x55', name='Client Fictional User')
            incoming = self.import_rows(con, [device('DOMAIN1\\VDI-SHARED', 'INTRANET\\x55'), device('DOMAIN2\\VDI-SHARED', 'CLIENT\\x55')])
            self.assertEqual(len(incoming), 2)
            result = search_directory(con, 'machine:VDI-SHARED')
            self.assertEqual({row['vdi_key'] for row in result['machines']}, set(incoming))
            self.assertTrue(all(not row['windows_remote_supported'] for row in result['machines']))
            context = machine_context(con, 'VDI-SHARED')
            self.assertTrue(context['ambiguous'])
            self.assertEqual({row['vdi_key'] for row in context['machines']}, set(incoming))
            self.assertNotIn('machine', context, 'Ambiguous aliases cannot silently select a machine')
            for hostname, uid in [('DOMAIN1\\VDI-SHARED', 2), ('DOMAIN2\\VDI-SHARED', 3)]:
                with self.subTest(hostname=hostname):
                    context = machine_context(con, hostname)
                    self.assertEqual([row['id'] for row in context['users']], [uid])
                    self.assertEqual(len(self.virtual(linked_machines(con, uid))), 1)
            # One user can also legitimately be associated with both distinct domains.
            changed, _ = vdi_data.parse_csv(csv_bytes([device('DOMAIN2\\VDI-SHARED', 'INTRANET\\x55')]))
            vdi_data.write_rows(con, changed, 'fictional-updated.csv', '2026-10-07T13:00:00+00:00')
            self.assertEqual({row['vdi_key'] for row in self.virtual(linked_machines(con, 2))}, set(incoming))

    def test_unknown_and_cross_domain_accounts_do_not_link_by_short_name_or_display_name(self):
        with self.connect() as con:
            user(con, 2, 'INTRANET\\x77', name='Same Display Name')
            user(con, 3, 'CLIENT\\x55', name='Same Display Name')
            self.import_rows(con, [device('VDI-WRONG-DOMAIN', 'CLIENT\\x77'), device('VDI-NAME-ONLY', 'Same Display Name'), device('VDI-UNKNOWN', 'EXTERNAL\\unknown')])
            self.assertEqual(self.virtual(linked_machines(con, 2)), [])
            self.assertEqual(self.virtual(linked_machines(con, 3)), [])
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
            self.assertEqual(con.execute('select count(*) from vdi_user_refs').fetchone()[0], 3)
            self.assertEqual(machine_context(con, 'VDI-WRONG-DOMAIN')['users'], [])

    def replacement_directory(self, path, *, keep_original=True):
        with fixture_connect(path) as con:
            directory_schema(con)
            con.execute("insert into metadata values('generation','fictional-directory-replacement')")
            # Reused row 1 belongs to a different canonical account after refresh.
            user(con, 1, 'G0765432', name='Replacement Person')
            if keep_original:
                user(con, 17, 'G0123456', name='Updated Original Person')
                con.execute("insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(17,'user_id','X0123456','x0123456')")

    def test_directory_merge_relinks_canonical_accounts_without_reusing_old_row_ids(self):
        with self.connect() as con:
            incoming = self.import_rows(con, [device('VDI-REFRESH')])
            key = next(iter(incoming))
        replacement = self.root / 'replacement.db'
        self.replacement_directory(replacement)
        merge_directory(self.db, replacement)
        with self.connect() as con:
            self.assertEqual(self.virtual(linked_machines(con, 1)), [])
            self.assertEqual([row['vdi_key'] for row in self.virtual(linked_machines(con, 17))], [key])
            self.assertEqual(machine_context(con, 'VDI-REFRESH')['users'][0]['full_name'], 'Updated Original Person')
            self.assertEqual(con.execute('select user_key from vdi_links').fetchone()[0], 'uid:g0123456')
        missing = self.root / 'missing.db'
        self.replacement_directory(missing, keep_original=False)
        merge_directory(self.db, missing)
        with self.connect() as con:
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
            self.assertEqual(con.execute('select count(*) from vdi_devices').fetchone()[0], 1)
            self.assertEqual(con.execute('select count(*) from vdi_user_refs').fetchone()[0], 1)
            self.assertEqual(machine_context(con, 'VDI-REFRESH')['users'], [])
        # A later global users refresh restores the link from the retained raw account.
        merge_directory(self.db, replacement)
        with self.connect() as con:
            self.assertEqual([row['vdi_key'] for row in self.virtual(linked_machines(con, 17))], [key])

    def test_servicenow_phone_cannot_gain_windows_support_from_a_same_name_vdi(self):
        with self.connect() as con:
            con.execute("insert into machines(id,machine_name,machine_name_norm,assigned_to,model_category,model_id) values(2,'SHARED-DEVICE','shared-device','G0123456','Mobile Device - Handheld','Apple iPhone 15')")
            con.execute("insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(1,2,'assigned_to','G0123456')")
            self.import_rows(con, [device('SHARED-DEVICE')])
            matches = [row for row in linked_machines(con, 1) if row['name'] == 'SHARED-DEVICE']
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]['device_kind'], 'iphone')
            self.assertFalse(matches[0]['windows_remote_supported'])
            context = machine_context(con, 'SHARED-DEVICE')
            self.assertFalse(context['machine']['windows_remote_supported'])
            self.assertEqual(context['machine']['device_kind'], 'iphone')
        with patch.multiple(main, MASTER_DB=self.db, DB=self.db), patch.object(main, 'run') as run, patch.object(main, 'ps') as ps:
            with self.assertRaises(HTTPException) as error:
                main.validate_pc('SHARED-DEVICE')
            self.assertEqual(error.exception.status_code, 400)
            run.assert_not_called()
            ps.assert_not_called()


if __name__ == '__main__':
    unittest.main()
