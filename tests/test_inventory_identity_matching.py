"""Identity regressions exercised through real, synthetic directory workbooks."""
import contextlib
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from device_inventory import device_kind, inventory_identity, supports_windows
from directory_exports import record
from directory_workbook import NS, REL, build


def write_workbook(path, sheets):
    book = ET.Element(NS + 'workbook')
    tabs = ET.SubElement(book, NS + 'sheets')
    relationships = ET.Element('Relationships')
    with zipfile.ZipFile(path, 'w') as archive:
        for index, (name, rows) in enumerate(sheets.items(), 1):
            ET.SubElement(tabs, NS + 'sheet',
                          {'name': name, 'sheetId': str(index), REL + 'id': 'r' + str(index)})
            ET.SubElement(relationships, 'Relationship',
                          {'Id': 'r' + str(index), 'Target': 'worksheets/sheet' + str(index) + '.xml'})
            sheet = ET.Element(NS + 'worksheet')
            data = ET.SubElement(sheet, NS + 'sheetData')
            for number, values in enumerate(rows, 1):
                row = ET.SubElement(data, NS + 'row', r=str(number))
                for column, value in enumerate(values):
                    cell = ET.SubElement(row, NS + 'c', r=chr(65 + column) + str(number), t='inlineStr')
                    ET.SubElement(ET.SubElement(cell, NS + 'is'), NS + 't').text = value
            archive.writestr('xl/worksheets/sheet' + str(index) + '.xml', ET.tostring(sheet))
        archive.writestr('xl/workbook.xml', ET.tostring(book))
        archive.writestr('xl/_rels/workbook.xml.rels', ET.tostring(relationships))


class InventoryIdentityMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.generation = 0
        self.users = [
            ['user_name', 'name', 'email', 'employee_number'],
            ['u1', 'User One', 'one@example.invalid', 'E001'],
            ['u2', 'User Two', 'two@example.invalid', 'E002'],
        ]

    def load(self, devices, users=None):
        self.generation += 1
        source = self.root / ('source' + str(self.generation) + '.xlsx')
        target = self.root / ('candidate' + str(self.generation) + '.db')
        write_workbook(source, {'users': self.users if users is None else users, 'devices': devices})
        with contextlib.redirect_stdout(io.StringIO()):
            build(source, target)
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        return connection

    @staticmethod
    def report(connection):
        return json.loads(connection.execute(
            "select value from metadata where key='import_resolution'").fetchone()[0])

    def test_same_display_name_with_distinct_source_ids_remains_ambiguous(self):
        users = [
            ['user_name', 'name', 'email', 'employee_number', 'sys_id'],
            ['', 'Alex Smith', '', 'E001', 'USER-A'],
            ['', 'Alex Smith', '', 'E002', 'USER-B'],
        ]
        con = self.load([
            ['ci', 'model_category', 'assigned_to'],
            ['PC1', 'Computer', 'Alex Smith'],
            ['PC2', 'Computer', 'E001'],
        ], users)
        self.assertEqual(con.execute('select count(*) from users').fetchone()[0], 2)
        self.assertEqual(con.execute(
            "select count(*) from assignments a join machines m on m.id=a.machine_id where m.machine_name='PC1'"
        ).fetchone()[0], 0)
        self.assertEqual(con.execute(
            "select u.employee_number from assignments a join users u on u.id=a.user_id_ref "
            "join machines m on m.id=a.machine_id where m.machine_name='PC2'"
        ).fetchone()[0], 'E001')
        self.assertEqual(self.report(con)['user']['duplicate_rows'], 0)
        keys = [row[0] for row in con.execute('select canonical_key from users order by id')]
        archived = [record(con, 'user', key) for key in keys]
        self.assertEqual([row['row'] for row in archived], [2, 3])
        self.assertEqual([row['source_rows'] for row in archived], [1, 1])

    def test_employee_ids_distinguish_people_without_source_id_login_or_email(self):
        con = self.load([
            ['ci', 'model_category', 'assigned_to'],
            ['PC1', 'Computer', 'E001'],
            ['PC2', 'Computer', 'E002'],
        ], [
            ['user_name', 'name', 'email', 'employee_number'],
            ['', 'Alex Smith', '', 'E001'],
            ['', 'Alex Smith', '', 'E002'],
        ])
        self.assertEqual(con.execute('select count(*) from users').fetchone()[0], 2)
        self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 2)
        self.assertEqual({row[0] for row in con.execute('select canonical_key from users')},
                         {'employee:e001', 'employee:e002'})

    def test_name_only_rows_are_preserved_separately_and_never_merge_by_name(self):
        users = [
            ['user_name', 'name', 'email', 'location'],
            ['', 'Alex Smith', '', 'Paris'],
            ['', 'Alex Smith', '', 'London'],
        ]
        con = self.load([['ci', 'assigned_to'], ['PC1', 'Alex Smith']], users)
        keys = [row[0] for row in con.execute('select canonical_key from users order by id')]
        self.assertTrue(all(key.startswith('row:') for key in keys))
        self.assertEqual([key.rsplit(':', 1)[-1] for key in keys], ['2', '3'])
        self.assertEqual(len(set(keys)), 2)
        self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 0)
        self.assertEqual([record(con, 'user', key)['row'] for key in keys], [2, 3])
        raw = [json.loads(row[0]) for row in con.execute(
            "select cells from directory_export_rows where sheet='users' order by row_number")]
        self.assertEqual(raw, users[1:])

    def test_authoritative_id_only_person_is_not_discarded(self):
        con = self.load([['ci', 'assigned_to'], ['PC1', 'E001']], [
            ['user_name', 'name', 'email', 'employee_number'],
            ['', '', '', 'E001'],
        ])
        self.assertEqual(con.execute('select canonical_key from users').fetchone()[0], 'employee:e001')
        self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 1)

    def test_placeholder_logins_and_emails_do_not_merge_distinct_source_ids(self):
        placeholders = ('null', 'unassigned', 'not assigned', '-', 'na', 'not supplied')
        users = [['user_name', 'name', 'email', 'sys_id']]
        users.extend([[value, 'User ' + str(index), value, 'USER-' + str(index)]
                      for index, value in enumerate(placeholders)])
        con = self.load([['ci', 'assigned_to'], ['PC1', '']], users)
        self.assertEqual(con.execute('select count(*) from users').fetchone()[0], len(placeholders))
        self.assertEqual({row[0] for row in con.execute('select canonical_key from users')},
                         {'sys:user-' + str(index) for index in range(len(placeholders))})
        self.assertEqual(self.report(con)['user']['duplicate_rows'], 0)

    def test_placeholder_source_ids_do_not_override_distinct_phone_serials(self):
        placeholders = ('null', 'unassigned', 'not assigned', '-', 'na', 'not supplied')
        devices = [['ci', 'model', 'sys_id', 'serial_number', 'assigned_to']]
        devices.extend([['iPhone', 'APPLE iPhone 13', value, 'SER-' + str(index) + '-' + str(ordinal), user]
                        for index, value in enumerate(placeholders)
                        for ordinal, user in enumerate(('u1', 'u2'))])
        con = self.load(devices)
        names = [row[0] for row in con.execute('select machine_name from machines')]
        self.assertEqual(len(names), len(placeholders) * 2)
        self.assertTrue(all(name.startswith('INVENTORY-SERIAL:') for name in names))
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)

    def test_placeholder_domains_do_not_invent_qualified_machine_identities(self):
        placeholders = ('null', 'unassigned', 'not assigned', '-', 'na', 'not supplied')
        devices = [['ci', 'model_category', 'domain', 'assigned_to']]
        devices.extend([['PC' + str(index), 'Computer', value, 'u1']
                        for index, value in enumerate(placeholders)])
        con = self.load(devices)
        machines = [dict(row) for row in con.execute('select * from machines')]
        self.assertEqual({row['machine_name'] for row in machines},
                         {'PC' + str(index) for index in range(len(placeholders))})
        self.assertTrue(all(supports_windows(row) for row in machines))

    def test_unidentified_phone_placeholder_ci_is_not_a_shared_asset_identifier(self):
        con = self.load([
            ['ci', 'model', 'sys_id', 'serial_number', 'asset_tag', 'assigned_to'],
            ['-', 'APPLE iPhone 13', '-', 'null', 'unassigned', 'u1'],
            ['-', 'APPLE iPhone 13', '-', 'null', 'unassigned', 'u2'],
        ])
        names = [row[0] for row in con.execute('select machine_name from machines')]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(name.startswith('INVENTORY-ROW:') for name in names))
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)

    def test_supplied_domains_keep_distinct_bare_hostnames_and_original_source_rows(self):
        devices = [
            ['ci', 'model_category', 'assigned_to', 'serial_number', 'sys_id', 'domain'],
            ['PC1', 'Computer', 'u1', 'PC-A', 'CMDB-A', 'INTRANET'],
            ['PC1', 'Computer', 'u2', 'PC-B', 'CMDB-B', 'CLIENT'],
        ]
        con = self.load(devices)
        machines = [dict(row) for row in con.execute('select * from machines order by id')]
        self.assertEqual([row['machine_name'] for row in machines], ['INTRANET\\PC1', 'CLIENT\\PC1'])
        self.assertEqual([row['serial_number'] for row in machines], ['PC-A', 'PC-B'])
        self.assertTrue(all(not supports_windows(row) for row in machines),
                        'A NetBIOS domain cannot be guessed into a deployable DNS suffix.')
        self.assertEqual([row['source_ci'] for row in machines], ['PC1', 'PC1'])
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)
        for index, machine in enumerate(machines, 1):
            archived = record(con, 'machine', machine['machine_name_norm'])
            self.assertEqual(archived['source_rows'], 1)
            self.assertEqual([field['value'] for field in archived['fields']], devices[index])

    def test_domain_aliases_do_not_change_a_valid_fqdn_or_invent_dns(self):
        for field in ('domain', 'domain_name', 'netbios_domain', 'ad_domain'):
            with self.subTest(field=field):
                qualified, _ = inventory_identity(
                    {'machine_name': ' pc1 ', field: ' client ', 'model_category': 'Computer'}, 2)
                dns, _ = inventory_identity(
                    {'machine_name': 'pc1.example.invalid.', field: 'CLIENT', 'model_category': 'Computer'}, 2)
                self.assertEqual(qualified, 'CLIENT\\PC1')
                self.assertEqual(dns, 'PC1.EXAMPLE.INVALID')
                self.assertFalse(supports_windows({'machine_name': qualified}))
                self.assertTrue(supports_windows({'machine_name': dns}))

    def test_dns_root_dot_variants_are_one_machine_without_losing_domain_or_raw_rows(self):
        devices = [
            ['ci', 'model_category', 'assigned_to', 'serial_number', 'sys_id'],
            ['PC1.example.invalid', 'Computer', 'u1', 'PC-SER', 'CMDB-PC'],
            ['pc1.example.invalid.', 'Computer', 'u2', 'PC-SER', 'CMDB-PC'],
        ]
        con = self.load(devices)
        rows = con.execute('select * from machines').fetchall()
        self.assertEqual(len(rows), 1)
        machine = dict(rows[0])
        self.assertEqual(machine['machine_name'], 'PC1.EXAMPLE.INVALID')
        self.assertEqual(machine['assigned_to'], 'u2')
        self.assertEqual(machine['source_ci'], 'pc1.example.invalid.')
        archived = record(con, 'machine', machine['machine_name_norm'])
        self.assertEqual((archived['source_rows'], archived['row']), (2, 3))
        self.assertEqual([field['value'] for field in archived['fields']], devices[2])
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 1)

    def test_mobile_source_id_survives_phone_to_iphone_classification_change(self):
        devices = [
            ['ci', 'model_category', 'assigned_to', 'serial_number', 'sys_id', 'model'],
            ['Phone', 'Mobile Device - Handheld', 'u1', 'SER-1', 'CMDB-ONE', 'Generic phone'],
            ['iPhone', 'Mobile Device - Handheld', 'u2', 'SER-1', 'CMDB-ONE', 'APPLE iPhone 13'],
        ]
        con = self.load(devices)
        rows = con.execute('select * from machines').fetchall()
        self.assertEqual(len(rows), 1)
        machine = dict(rows[0])
        self.assertEqual((machine['assigned_to'], machine['model_id']), ('u2', 'APPLE iPhone 13'))
        self.assertFalse(supports_windows(machine))
        self.assertFalse(supports_windows({'machine_name': machine['machine_name']}),
                         'Missing classification metadata must never enable Windows operations.')
        self.assertEqual(device_kind(machine['machine_name'], machine['model_category'],
                                     machine['model_id'], machine['sys_class_name']), 'iphone')
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 1)
        self.assertEqual(record(con, 'machine', machine['machine_name_norm'])['source_rows'], 2)

    def test_mobile_literal_and_encoded_identifiers_have_disjoint_namespaces(self):
        unsafe = 'A/B'
        digest = hashlib.sha256(unsafe.encode()).hexdigest()[:24].upper()
        devices = [['ci', 'model_category', 'assigned_to', 'serial_number', 'model']]
        devices.extend([['iPhone', 'Mobile Device - Handheld', 'u1', serial, 'APPLE iPhone 13']
                        for serial in (unsafe, digest, 'HASH-' + digest)])
        con = self.load(devices)
        rows = [dict(row) for row in con.execute('select * from machines')]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row['machine_name'] for row in rows}), 3)
        self.assertTrue(all(len(row['machine_name']) <= 64 and not supports_windows(row) for row in rows))
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)

    def test_generated_mobile_key_cannot_collide_with_valid_physical_hostname(self):
        con = self.load([
            ['ci', 'model_category', 'assigned_to', 'serial_number', 'model'],
            ['iPhone', 'Mobile Device - Handheld', 'u1', 'ABC', 'APPLE iPhone 13'],
            ['INVENTORY-SERIAL-RAW-ABC', 'Computer', 'u2', 'PC-ABC', 'Dell Desktop'],
        ])
        machines = [dict(row) for row in con.execute('select * from machines order by id')]
        self.assertEqual(len(machines), 2)
        self.assertIn(':', machines[0]['machine_name'])
        self.assertFalse(supports_windows(machines[0]))
        self.assertEqual(machines[1]['machine_name'], 'INVENTORY-SERIAL-RAW-ABC')
        self.assertTrue(supports_windows(machines[1]))
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)

    def test_mobile_identifier_sources_remain_distinct_and_unidentified_rows_survive(self):
        common = {'machine_name': 'iphone', 'model_category': 'Mobile Device - Handheld'}
        identities = [inventory_identity(dict(common, **{field: 'SAME-ID'}), 2)[0]
                      for field in ('sys_id', 'serial_number', 'asset_tag')]
        self.assertEqual(len(set(identities)), 3)
        con = self.load([
            ['ci', 'model_category', 'assigned_to', 'model'],
            ['iPhone', 'Mobile Device - Handheld', 'u1', 'APPLE iPhone 13'],
            ['iPhone', 'Mobile Device - Handheld', 'u2', 'APPLE iPhone 13'],
        ])
        self.assertEqual(con.execute('select count(*) from machines').fetchone()[0], 2)
        self.assertEqual(self.report(con)['machine']['duplicate_rows'], 0)

    def test_unidentified_people_and_phones_cannot_reuse_other_occupants_keys_after_reorder(self):
        users = [
            ['user_name', 'name', 'email', 'location'],
            ['', 'Alex Smith', '', 'Paris'],
            ['', 'Casey Smith', '', 'London'],
        ]
        devices = [
            ['ci', 'model_category', 'assigned_to', 'model'],
            ['iPhone', 'Mobile Device - Handheld', 'Alex Smith', 'APPLE iPhone 13'],
            ['iPhone', 'Mobile Device - Handheld', 'Casey Smith', 'APPLE iPhone 13'],
        ]
        original = self.load(devices, users)
        old_users = {row[0] for row in original.execute('select canonical_key from users')}
        old_devices = {row[0] for row in original.execute('select machine_name_norm from machines')}
        reordered = self.load([devices[0], devices[2], devices[1]], [users[0], users[2], users[1]])
        new_users = {row[0] for row in reordered.execute('select canonical_key from users')}
        new_devices = {row[0] for row in reordered.execute('select machine_name_norm from machines')}
        self.assertTrue(old_users.isdisjoint(new_users),
                        'A confirmed reference to an unidentified person must not bind to another row occupant.')
        self.assertTrue(old_devices.isdisjoint(new_devices),
                        'A row identifier must not become the other user\'s phone after a reordered extract.')
        self.assertTrue(all(len(name) <= 64 for name in new_devices))
        for key in new_users:
            self.assertIsNotNone(record(reordered, 'user', key))
        for key in new_devices:
            self.assertIsNotNone(record(reordered, 'machine', key))

    def test_byte_identical_snapshot_under_new_filename_keeps_unidentified_keys(self):
        con = self.load([
            ['ci', 'model_category', 'assigned_to', 'model'],
            ['iPhone', 'Mobile Device - Handheld', 'Alex Smith', 'APPLE iPhone 13'],
        ], [['user_name', 'name', 'email'], ['', 'Alex Smith', '']])
        source = self.root / 'renamed.xlsx'
        source.write_bytes((self.root / 'source1.xlsx').read_bytes())
        target = self.root / 'same_snapshot.db'
        with contextlib.redirect_stdout(io.StringIO()):
            build(source, target)
        other = sqlite3.connect(target)
        self.addCleanup(other.close)
        for table, column in (('users', 'canonical_key'), ('machines', 'machine_name_norm')):
            original = [row[0] for row in con.execute('select ' + column + ' from ' + table)]
            copied = [row[0] for row in other.execute('select ' + column + ' from ' + table)]
            self.assertEqual(original, copied)

    def test_original_laptop_and_iphone_export_still_keep_badges_links_and_raw_cells(self):
        devices = [
            ['assigned_to', 'asset_tag', 'model_category', 'ci', 'model', 'cmp_last_used',
             'install_status', 'serial_number', 'assigned', 'display_name', 'location'],
            ['u1', 'ASSET-PC', 'Laptop', ' gbrplm123 ', 'Dell Latitude 7450',
             '02/10/2026 10:00', 'In Use', 'PC-123', '01/10/2026', ' Laptop asset ', 'Paris'],
            ['u1', 'ASSET-PHONE', 'Mobile Device - Handheld', ' iPhone ', 'APPLE iPhone 13',
             '02/10/2026 11:00', 'In Use', 'PHONE-123', '01/10/2026', ' Phone asset ', 'Paris'],
        ]
        con = self.load(devices)
        machines = [dict(row) for row in con.execute('select * from machines order by id')]
        self.assertEqual(machines[0]['machine_name'], 'GBRPLM123')
        self.assertEqual(device_kind(machines[0]['machine_name'], machines[0]['model_category'],
                                     machines[0]['model_id']), 'laptop')
        self.assertTrue(supports_windows(machines[0]))
        self.assertEqual(device_kind(machines[1]['machine_name'], machines[1]['model_category'],
                                     machines[1]['model_id']), 'iphone')
        self.assertFalse(supports_windows(machines[1]))
        self.assertEqual([row['install_status'] for row in machines], ['In Use', 'In Use'])
        self.assertEqual([row['last_used'] for row in machines], ['02/10/2026 10:00', '02/10/2026 11:00'])
        self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 2)
        for index, machine in enumerate(machines, 1):
            archived = record(con, 'machine', machine['machine_name_norm'])
            self.assertEqual([field['value'] for field in archived['fields']], devices[index])

    def test_fresh_import_has_indexed_alias_and_machine_short_lookups(self):
        from directory_lookup import MACHINE_SHORT_SQL
        con = self.load([
            ['ci', 'model_category', 'domain'],
            ['PC1.example.invalid', 'Computer', ''],
            ['PC1', 'Computer', 'CLIENT'],
        ])
        indexes = {row[0] for row in con.execute("select name from sqlite_master where type='index'")}
        self.assertTrue({'ix_alias_kind_norm', 'ix_alias_user', 'ix_machines_short',
                         'ix_users_employee_lower', 'ix_users_email_lower'} <= indexes)
        short_plan = ' '.join(row[3] for row in con.execute(
            'explain query plan select id from machines where ' + MACHINE_SHORT_SQL + '=?', ('pc1',)))
        self.assertIn('SEARCH machines', short_plan)
        self.assertIn('ix_machines_short', short_plan)
        self.assertEqual(con.execute(
            'select count(*) from machines where ' + MACHINE_SHORT_SQL + '=?', ('pc1',)).fetchone()[0], 2)
        alias_plan = ' '.join(row[3] for row in con.execute(
            'explain query plan select alias_value from user_aliases where user_id_ref=?', (1,)))
        self.assertIn('USING INDEX ix_alias_user', alias_plan)
        for column, value, index in (('employee_number', 'e001', 'ix_users_employee_lower'),
                                     ('email', 'one@example.invalid', 'ix_users_email_lower')):
            plan = ' '.join(row[3] for row in con.execute(
                'explain query plan select id from users where lower(' + column + ')=?', (value,)))
            self.assertIn('SEARCH users', plan)
            self.assertIn(index, plan)


if __name__ == '__main__':
    unittest.main()
