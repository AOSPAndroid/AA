"""Raw VDI exports and conservative identity matching; fictional temporary data only."""
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import vdi_data as data
from directory_workbook import schema as directory_schema
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import workbook


HEADERS = ['Name', 'User', 'Machine Catalog', 'Delivery Group', 'Maintenance Mode',
           'User Change Persistence', 'Power State', 'State', 'User Display Names', 'Custom Flag']


def csv_bytes(rows, *, headers=HEADERS, delimiter=',', encoding='utf-8', sep=False):
    stream = io.StringIO(newline='')
    if sep:
        stream.write('sep=' + delimiter + '\r\n')
    writer = csv.writer(stream, delimiter=delimiter, lineterminator='\r\n')
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


def device(name='INTRANET\\VDI-001', users='INTRANET\\X0123456', **changes):
    fields = dict(zip(HEADERS, [name, users, 'Markets Desktop', 'Trading EMEA', 'Off',
                               'Discard', 'On', 'Registered', 'Alex Example', '  keep spaces  ']))
    fields.update(changes)
    return [fields[h] for h in HEADERS]


def user(con, uid, account, *, name='Alex Example', email='alex@example.invalid'):
    canonical = 'uid:' + account.casefold()
    con.execute('insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) values(?,?,?,?,?,?,?,?)',
                (uid, canonical, account, account.casefold(), name, name.casefold(), email, email.casefold()))
    return canonical


def directory(con):
    directory_schema(con)
    con.execute("insert into metadata values('generation','fictional-directory-1')")
    user(con, 1, 'G0123456')
    con.execute("insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(1,'user_id','X0123456','x0123456')")
    con.execute("insert into machines(id,machine_name,machine_name_norm,assigned_to) values(1,'PHYSICAL-001','physical-001','G0123456')")
    con.execute("insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(1,1,'assigned_to','G0123456')")
    data.initialize(con)


def store(con, rows, *, source='fictional.csv'):
    columns = [r[1] for r in con.execute('pragma table_info(vdi_devices)')]
    for row in rows.values():
        item = {**row, 'source': source, 'imported_at': '2026-10-07T12:00:00+00:00'}
        con.execute('insert into vdi_devices(' + ','.join(columns) + ') values(' + ','.join('?' for _ in columns) + ')',
                    tuple(item.get(column, '') for column in columns))
        # Ref provenance is stored separately from device metadata.
        for ref in row['users']:
            con.execute('insert into vdi_user_refs(machine_key,ref_norm,raw_ref,account,domain,valid,status,candidates_json) values(?,?,?,?,?,?,?,?)',
                        (row['machine_key'], ref['ref_norm'], ref['raw_ref'], ref['account'], ref['domain'],
                         ref['valid'], 'unmatched' if ref['valid'] else 'invalid', '[]'))
    data.relink(con)


class VdiData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'fictional.db'

    def connect(self):
        con = fixture_connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def test_duplicate_last_whole_record_wins_without_carrying_old_assignment(self):
        first = device('INTRANET\\VDI-001', 'INTRANET\\X0123456')
        last = device(' intranet\\vdi-001 ', '', **{'Machine Catalog': '', 'Custom Flag': '  last value  '})
        rows, report = data.parse(csv_bytes([first, last]), 'Citrix.csv')
        self.assertEqual(list(rows), ['netbios:intranet\\vdi-001'])
        row = next(iter(rows.values()))
        self.assertEqual(row['catalog'], '')
        self.assertEqual(row['users'], [])
        raw = json.loads(row['source_rows_json'])
        self.assertEqual(raw['sources'][0]['headers'], HEADERS)
        self.assertEqual([r['cells'] for r in raw['rows']], [first, last])
        self.assertEqual(raw['selected_row'], 3)
        self.assertEqual(raw['selection'], 'last_row')
        self.assertEqual(json.loads(row['raw_json'])['Custom Flag'], '  last value  ')

    def test_csv_bom_utf16_cp1252_and_excel_separator_keep_original_cells(self):
        original = device(**{'Custom Flag': '  Éléonore café  '})
        cases = [('utf-8-sig', ',', False), ('utf-16', ',', False), ('cp1252', ';', True)]
        for encoding, delimiter, sep in cases:
            with self.subTest(encoding=encoding):
                rows, _ = data.parse(csv_bytes([original], encoding=encoding, delimiter=delimiter, sep=sep), 'export.csv')
                row = next(iter(rows.values()))
                raw = json.loads(row['source_rows_json'])
                self.assertEqual(raw['sources'][0]['headers'], HEADERS)
                self.assertEqual(raw['rows'][0]['cells'], original)
                self.assertEqual(raw['rows'][0]['row'], 3 if sep else 2)

    def test_duplicate_and_blank_headers_are_retained_positionally(self):
        headers = HEADERS + ['Custom Flag', '']
        original = device() + ['duplicate column', '  unnamed cell  ']
        rows, _ = data.parse_csv(csv_bytes([original], headers=headers))
        raw = json.loads(next(iter(rows.values()))['source_rows_json'])
        self.assertEqual(raw['sources'][0]['headers'], headers)
        self.assertEqual(raw['rows'][0]['cells'], original)

    def test_known_field_record_view_never_leaks_hidden_cells_or_raw_rows(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device(**{'Custom Flag': 'PRIVATE ORIGINAL VALUE'})]))
            store(con, rows)
            key = next(iter(rows))
            admin = data.record(con, key)
            self.assertIn('PRIVATE ORIGINAL VALUE', json.dumps(admin))
            self.assertIn('raw_rows', admin)
            readonly = data.record(con, key, include_unmapped=False)
            self.assertEqual(readonly['restricted_columns'], 1)
            self.assertNotIn('raw_rows', readonly)
            self.assertNotIn('PRIVATE ORIGINAL VALUE', json.dumps(readonly))
            self.assertNotIn('Custom Flag', json.dumps(readonly))
            self.assertEqual({f['header'] for f in readonly['fields']}, set(HEADERS) - {'Custom Flag'})
            loaded = next(iter(data.load(con, include_source=False).values()))
            self.assertNotIn('raw_json', loaded)
            self.assertNotIn('source_rows_json', loaded)

    def test_xlsx_retains_unknown_columns_and_original_sheet_name(self):
        path = self.root / 'Citrix.xlsx'
        original = device()
        workbook(path, {'Citrix machine export': [HEADERS, original]})
        rows, _ = data.parse(path.read_bytes(), path.name)
        raw = json.loads(next(iter(rows.values()))['source_rows_json'])
        self.assertEqual(raw['sources'], [{'sheet': 'Citrix machine export', 'headers': HEADERS}])
        self.assertEqual(raw['rows'], [{'sheet': 'Citrix machine export', 'row': 2, 'cells': original}])

    def test_machine_names_have_separate_dns_netbios_and_short_namespaces(self):
        rows, _ = data.parse_csv(csv_bytes([
            device('VDI-001', ''), device('DOMAIN\\VDI-001', ''),
            device('VDI-001.one.example.test', ''), device('VDI-001.two.example.test', ''),
            device('../VDI-001', ''), device('', ''),
        ]))
        self.assertEqual(len(rows), 6)
        self.assertIn('host:vdi-001', rows)
        self.assertIn('netbios:domain\\vdi-001', rows)
        self.assertIn('dns:vdi-001.one.example.test', rows)
        self.assertIn('dns:vdi-001.two.example.test', rows)
        raw = [row for key, row in rows.items() if key.startswith('raw:')]
        self.assertEqual(len(raw), 2)
        self.assertTrue(all(not row['target_name'] for row in raw))

    def test_malformed_machine_names_keep_user_refs_without_links_or_remote_actions(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device('../VDI-001'), device('')]))
            store(con, rows)
            self.assertEqual(len(data.load(con)), 2)
            self.assertEqual(con.execute('select count(*) from vdi_user_refs').fetchone()[0], 2)
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
            self.assertEqual(data.machines_for_user(con, 'uid:g0123456'), [])
            self.assertTrue(all(not row['target_name'] for row in data.load(con).values()))

    def test_multiple_accounts_in_separators_braces_and_json_lists(self):
        values = ['INTRANET\\X0123456;CLIENT\\x88|missing',
                  '{INTRANET\\X0123456, CLIENT\\x88, missing}',
                  'INTRANET\\X0123456\nCLIENT\\x88\nmissing',
                  json.dumps(['INTRANET\\X0123456', 'CLIENT\\x88', 'missing'])]
        for value in values:
            with self.subTest(value=value):
                rows, _ = data.parse_csv(csv_bytes([device(users=value)]))
                refs = next(iter(rows.values()))['users']
                self.assertEqual({ref['ref_norm'] for ref in refs}, {'intranet\\x0123456', 'client\\x88', 'missing'})
                self.assertTrue(all(ref['valid'] for ref in refs))

    def test_required_headers_and_invalid_workbooks_fail_before_storage(self):
        for content in (csv_bytes([['VDI-001']], headers=['Name']), csv_bytes([['x1']], headers=['User']), b''):
            with self.subTest(content=content), self.assertRaises(ValueError):
                data.parse_csv(content)
        with self.assertRaises(ValueError):
            data.parse(b'not an Excel ZIP', 'bad.xlsx')

    def test_file_row_column_cell_and_expanded_zip_bounds_are_enforced(self):
        content = csv_bytes([device()])
        with patch.object(data, 'MAX_FILE_BYTES', len(content) - 1), self.assertRaises(ValueError):
            data.parse_csv(content)
        with patch.object(data, 'MAX_ROWS', 2), self.assertRaises(ValueError):
            data.parse_csv(csv_bytes([device('VDI-1'), device('VDI-2'), device('VDI-3')]))
        with patch.object(data, 'MAX_COLUMNS', len(HEADERS) - 1), self.assertRaises(ValueError):
            data.parse_csv(content)
        with patch.object(data, 'MAX_CELL', 8), self.assertRaises(ValueError):
            data.parse_csv(content)
        path = self.root / 'expanded.xlsx'
        workbook(path, {'VDI': [HEADERS, device()]})
        with patch.object(data, 'MAX_EXPANDED_BYTES', 32), self.assertRaises(ValueError):
            data.parse(path.read_bytes(), path.name)

    def test_malformed_xlsx_column_and_row_references_are_rejected(self):
        original = self.root / 'original.xlsx'
        workbook(original, {'VDI': [HEADERS, device()]})
        for before, after in [(b'r="A1"', b'r="ZZZZZZ1"'), (b'r="1"', b'r="1048577"')]:
            with self.subTest(reference=after):
                damaged = io.BytesIO()
                with zipfile.ZipFile(original) as source, zipfile.ZipFile(damaged, 'w') as target:
                    for item in source.infolist():
                        payload = source.read(item.filename)
                        if item.filename == 'xl/worksheets/sheet1.xml':
                            payload = payload.replace(before, after, 1)
                        target.writestr(item.filename, payload)
                with self.assertRaises(ValueError):
                    data.parse(damaged.getvalue(), 'damaged.xlsx')

    def test_matching_uses_account_aliases_but_never_display_names_or_email(self):
        with self.connect() as con:
            directory(con)
            content = csv_bytes([device('DOMAIN\\VDI-1', 'INTRANET\\X0123456'),
                                 device('DOMAIN\\VDI-2', 'Alex Example'),
                                 device('DOMAIN\\VDI-3', 'alex@example.invalid')])
            rows, _ = data.parse_csv(content)
            store(con, rows)
            linked = data.machines_for_user(con, 'uid:g0123456')
            self.assertEqual(len(linked), 1)
            self.assertEqual(linked[0]['name'], 'VDI-1')
            self.assertEqual(con.execute('select count(*) from assignments').fetchone()[0], 1)

    def test_qualified_accounts_never_fall_back_to_a_different_domain(self):
        with self.connect() as con:
            directory(con)
            user(con, 2, 'INTRANET\\x55', name='Intranet User')
            user(con, 3, 'CLIENT\\x55', name='Client User')
            user(con, 4, 'INTRANET\\x77', name='Another User')
            rows, _ = data.parse_csv(csv_bytes([device('DOMAIN\\VDI-A', 'INTRANET\\x55'),
                                               device('DOMAIN\\VDI-B', 'x55'),
                                               device('DOMAIN\\VDI-C', 'CLIENT\\x77')]))
            store(con, rows)
            self.assertEqual(len(data.machines_for_user(con, 'uid:intranet\\x55')), 1)
            self.assertEqual(data.machines_for_user(con, 'uid:client\\x55'), [])
            self.assertEqual(data.machines_for_user(con, 'uid:intranet\\x77'), [])
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 1)

    def test_bare_user_id_alias_cannot_erase_the_primary_account_domain(self):
        with self.connect() as con:
            directory(con)
            user(con, 2, 'INTRANET\\x55', name='Intranet User')
            con.execute("insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(2,'user_id','x55','x55')")
            rows, _ = data.parse_csv(csv_bytes([device('DOMAIN\\VDI-A', 'CLIENT\\x55')]))
            store(con, rows)
            self.assertEqual(data.machines_for_user(con, 'uid:intranet\\x55'), [])
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)

    def test_profile_target_and_search_reads_do_not_fetch_bulk_original_rows(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device()]))
            store(con, rows)

            def authorize(action, table, column, database, source):
                if action == sqlite3.SQLITE_READ and table == 'vdi_devices' and column in ('raw_json', 'source_rows_json'):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            con.set_authorizer(authorize)
            try:
                self.assertEqual(len(data.machines_for_user(con, 'uid:g0123456')), 1)
                self.assertEqual(len(data.machine_records(con, 'VDI-001')), 1)
                self.assertEqual(len(data.search_records(con, 'Markets', field='catalog')), 1)
            finally:
                con.set_authorizer(None)

    def test_display_name_alias_and_ambiguous_derived_login_do_not_create_links(self):
        with self.connect() as con:
            directory(con)
            user(con, 2, 'X0123456', name='Separate Exported Identity')
            con.execute("insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(1,'name','anotherlogin','anotherlogin')")
            con.execute("insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(1,'email','email-alias@example.invalid','email-alias@example.invalid')")
            rows, _ = data.parse_csv(csv_bytes([device('DOMAIN\\VDI-A', 'X0123456'),
                                               device('DOMAIN\\VDI-B', 'anotherlogin')]))
            store(con, rows)
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)

    def test_duplicate_short_hosts_are_separate_and_cannot_select_a_short_remote_target(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device('DOMAIN1\\VDI-001'), device('DOMAIN2\\VDI-001')]))
            store(con, rows)
            records = data.machine_records(con, 'VDI-001')
            self.assertEqual(len(records), 2)
            self.assertTrue(all(not row['windows_remote_supported'] for row in records))
            self.assertEqual(len(data.machines_for_user(con, 'uid:g0123456')), 2)

    def test_duplicate_dns_short_hosts_keep_safe_fully_qualified_targets(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device('VDI-001.one.example.test'), device('VDI-001.two.example.test')]))
            store(con, rows)
            records = data.machine_records(con, 'VDI-001')
            self.assertEqual(len(records), 2)
            self.assertEqual({row['name'] for row in records}, {'VDI-001.ONE.EXAMPLE.TEST', 'VDI-001.TWO.EXAMPLE.TEST'})
            self.assertTrue(all(row['windows_remote_supported'] for row in records))

    def test_directory_refresh_relinks_against_current_accounts_and_removes_stale_links(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device()]))
            store(con, rows)
            self.assertEqual(len(data.machines_for_user(con, 'uid:g0123456')), 1)
            con.execute('delete from user_aliases')
            con.execute("update users set canonical_key='uid:g7654321',user_id='G7654321',user_id_norm='g7654321' where id=1")
            data.relink(con)
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
            self.assertEqual(data.machines_for_user(con, 'uid:g7654321'), [])
            con.execute("update users set canonical_key='uid:g0123456',user_id='G0123456',user_id_norm='g0123456' where id=1")
            data.relink(con)
            self.assertEqual(len(data.machines_for_user(con, 'uid:g0123456')), 1)

    def test_relink_preserves_callers_transaction_and_rolls_back_with_directory_failure(self):
        with self.connect() as con:
            directory(con)
            rows, _ = data.parse_csv(csv_bytes([device()]))
            store(con, rows)
            con.commit()
            con.execute('begin immediate')
            con.execute('delete from user_aliases')
            con.execute("update users set canonical_key='uid:g7654321',user_id='G7654321',user_id_norm='g7654321' where id=1")
            data.relink(con)
            self.assertTrue(con.in_transaction)
            self.assertEqual(con.execute('select count(*) from vdi_links').fetchone()[0], 0)
            con.rollback()
            self.assertEqual(len(data.machines_for_user(con, 'uid:g0123456')), 1)
            self.assertEqual(con.execute("select user_id from users where id=1").fetchone()[0], 'G0123456')


if __name__ == '__main__':
    unittest.main()
