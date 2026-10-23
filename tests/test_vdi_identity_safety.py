"""Qualified targets and directory-generation races use fictional local fixtures."""
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from directory_lookup import linked_machines, prepare_views
from directory_workbook import schema
from sqlite_fixture import connect as fixture_connect, isolate_backend_database
import vdi_data
import vdi_inventory


def parsed(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Name', 'User', 'Machine Catalog'])
    writer.writerows(rows)
    return vdi_data.parse_csv(stream.getvalue().encode())[0]


class IdentitySafety(unittest.TestCase):
    def memory_directory(self):
        con = fixture_connect(':memory:')
        self.addCleanup(con.close)
        con.row_factory = sqlite3.Row
        schema(con)
        vdi_data.initialize(con)
        con.execute("insert into users(id,canonical_key,user_id,user_id_norm) values(1,'uid:g111','G111','g111')")
        return con

    def test_qualified_netbios_records_remain_distinct_in_shared_machine_lookup(self):
        con = self.memory_directory()
        rows = parsed([('DOMAIN1\\VDI-001', 'G111', 'First catalog'),
                       ('DOMAIN2\\VDI-001', 'G111', 'Second catalog')])
        vdi_data.write_rows(con, rows, 'fictional.csv', '2026-10-07')
        prepare_views(con)
        merged = vdi_inventory.find_machines(con, 'VDI-001')
        self.assertEqual({row['vdi_key'] for row in merged}, set(rows))
        self.assertEqual(len(merged), 2)
        self.assertTrue(all(not row['windows_remote_supported'] for row in merged))
        self.assertTrue(vdi_inventory.machine_context(con, 'VDI-001')['ambiguous'])
        self.assertEqual(len(linked_machines(con, 1)), 2)

    def test_citrix_metadata_cannot_enable_windows_actions_for_servicenow_phone(self):
        con = self.memory_directory()
        con.execute("insert into machines(id,machine_name,machine_name_norm,model_category,model_id) values(1,'PHONE-001','phone-001','Mobile Device - Handheld','Fictional phone model')")
        vdi_data.write_rows(con, parsed([('PHONE-001', 'G111', 'Imported catalog')]), 'fictional.csv', '2026-10-07')
        prepare_views(con)
        result = vdi_inventory.find_machines(con, 'PHONE-001')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['device_kind'], 'phone')
        self.assertFalse(result[0]['windows_remote_supported'])
        self.assertEqual(result[0]['model_id'], 'Fictional phone model')
        self.assertEqual(result[0]['vdi_catalog'], 'Imported catalog')

    def test_unassigned_citrix_record_preserves_servicenow_assignment_evidence(self):
        con = self.memory_directory()
        con.execute("insert into machines(id,machine_name,machine_name_norm,model_id) values(1,'VDI-001.EXAMPLE.TEST','vdi-001.example.test','Fictional hardware model')")
        con.execute("insert into assignments(user_id_ref,machine_id,relationship_type) values(1,1,'assigned_to')")
        vdi_data.write_rows(con, parsed([('VDI-001.EXAMPLE.TEST', '', 'Imported catalog')]), 'fictional.csv', '2026-10-07')
        prepare_views(con)
        physical = dict(con.execute('select * from legacy_machines where id=1').fetchone())
        physical.update(assigned_relationship=1, logon_relationship=0, relationship_group='Assigned to user', match_type='Assigned')
        result = vdi_inventory.merge_records([physical], vdi_data.machine_records(con, 'VDI-001.EXAMPLE.TEST'))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['model_id'], 'Fictional hardware model')
        self.assertEqual(result[0]['assigned_relationship'], 1)
        self.assertEqual(result[0]['relationship_group'], 'Assigned to user')
        self.assertEqual(result[0]['vdi_assignment_count'], 0)


class SnapshotSafety(unittest.TestCase):
    def test_concurrent_directory_refresh_does_not_mix_numeric_id_reuse_into_vdi_links(self):
        class ReplacementDuringIdentityRead(sqlite3.Connection):
            replacement = None

            def execute(self, sql, parameters=()):
                if self.replacement and sql.startswith('select canonical_key from users where id='):
                    replacement, self.replacement = self.replacement, None
                    replacement()
                return super().execute(sql, parameters)

        for caller_transaction in (False, True):
            with self.subTest(caller_transaction=caller_transaction), tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / 'fictional.db'
                with fixture_connect(database) as con:
                    schema(con)
                    vdi_data.initialize(con)
                    con.execute("insert into metadata values('directory.generation','original')")
                    con.execute("insert into users(id,canonical_key,user_id,user_id_norm) values(1,'uid:g111','G111','g111')")
                    con.execute("insert into machines(id,machine_name,machine_name_norm) values(1,'OLD-PHYSICAL','old-physical')")
                    con.execute("insert into assignments(user_id_ref,machine_id,relationship_type) values(1,1,'assigned_to')")
                    vdi_data.write_rows(con, parsed([('VDI-OLD', 'G111', 'Old catalog'),
                                                   ('VDI-NEW', 'G222', 'New catalog')]), 'fictional.csv', '2026-10-07')

                reader = sqlite3.connect(database, factory=ReplacementDuringIdentityRead)
                try:
                    reader.execute('pragma journal_mode=WAL')
                    reader.row_factory = sqlite3.Row
                    prepare_views(reader)
                    if caller_transaction:
                        reader.execute('begin')
                        reader.execute('select canonical_key from users').fetchall()

                    def replace():
                        with fixture_connect(database) as writer:
                            writer.execute('begin immediate')
                            for table in ('assignments', 'user_aliases', 'users', 'machines'):
                                writer.execute('delete from ' + table)
                            writer.execute("update metadata set value='replacement' where key='directory.generation'")
                            writer.execute("insert into users(id,canonical_key,user_id,user_id_norm) values(1,'uid:g222','G222','g222')")
                            writer.execute("insert into machines(id,machine_name,machine_name_norm) values(1,'NEW-PHYSICAL','new-physical')")
                            writer.execute("insert into assignments(user_id_ref,machine_id,relationship_type) values(1,1,'assigned_to')")
                            vdi_data.relink(writer)

                    reader.replacement = replace
                    machines = linked_machines(reader, 1)
                    self.assertEqual({row['name'] for row in machines}, {'OLD-PHYSICAL', 'VDI-OLD'})
                    self.assertIsNone(reader.replacement, 'Concurrent replacement actually occurred')
                    self.assertEqual(reader.in_transaction, caller_transaction, 'Reader must preserve an outer caller transaction')
                    if caller_transaction:
                        self.assertEqual(reader.execute('select canonical_key from users').fetchone()[0], 'uid:g111')
                        reader.rollback()
                    self.assertEqual(reader.execute('select canonical_key from users').fetchone()[0], 'uid:g222')
                finally:
                    reader.close()


class TargetValidationSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Backend startup must use an explicit test path even when run alone.
        isolate_backend_database()
        from backend import main
        cls.backend = main

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'fictional.db'
        with fixture_connect(self.database) as con:
            schema(con)
            vdi_data.initialize(con)
            con.execute("insert into users(id,canonical_key,user_id,user_id_norm) values(1,'uid:g111','G111','g111')")
        self.db_patch = patch.object(self.backend, 'MASTER_DB', self.database)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        # These tests may only validate recorded names, never contact Windows.
        for name in ('run', 'ps', 'wmi_create'):
            forbidden = patch.object(self.backend, name, side_effect=AssertionError('Live transport is forbidden in identity fixtures'))
            forbidden.start()
            self.addCleanup(forbidden.stop)

    def add_inventory(self, physical, virtual):
        with fixture_connect(self.database) as con:
            if physical:
                con.execute('insert into machines(id,machine_name,machine_name_norm) values(1,?,?)', (physical, physical.casefold()))
            vdi_data.write_rows(con, parsed([(virtual, 'G111', 'Fictional catalog')]), 'fictional.csv', '2026-10-07')

    def assert_ambiguous_short_name(self):
        with fixture_connect(self.database) as con:
            con.row_factory = sqlite3.Row
            prepare_views(con)
            result = vdi_inventory.machine_context(con, 'VDI-001')
            self.assertTrue(result['ambiguous'])
            self.assertEqual(len(result['machines']), 2)
        with self.assertRaises(HTTPException) as error:
            self.backend.validate_pc('VDI-001')
        self.assertEqual(error.exception.status_code, 400)

    def test_servicenow_short_host_and_different_citrix_dns_target_require_disambiguation(self):
        self.add_inventory('VDI-001', 'VDI-001.OTHER.EXAMPLE.TEST')
        self.assert_ambiguous_short_name()

    def test_servicenow_dns_target_and_citrix_netbios_short_target_require_disambiguation(self):
        self.add_inventory('VDI-001.OTHER.EXAMPLE.TEST', 'DOMAIN\\VDI-001')
        self.assert_ambiguous_short_name()

    def test_unique_citrix_dns_short_alias_resolves_to_exact_exported_target(self):
        self.add_inventory(None, 'VDI-001.OTHER.EXAMPLE.TEST')
        self.assertEqual(self.backend.validate_pc('vdi-001'), 'VDI-001.OTHER.EXAMPLE.TEST')
        self.assertEqual(self.backend.validate_pc('vdi-001.other.example.test'), 'VDI-001.OTHER.EXAMPLE.TEST')


if __name__ == '__main__':
    unittest.main()
