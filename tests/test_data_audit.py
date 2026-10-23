"""Import bounds, identity consistency and durable backups; fictional data only."""
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import desk_moves
import package_data_api
from directory_lookup import linked_machines, prepare_views, search_directory
from directory_workbook import NS, col_idx, iter_rows, norm, schema
from identity_links import rebuild_links
from seating_excel import account_index
from sqlite_fixture import FixtureConnection, connect as fixture_connect


class WorkbookBounds(unittest.TestCase):
    def rows(self, content):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'fictional.xlsx'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('xl/worksheets/sheet1.xml',
                f'<worksheet xmlns="{NS[1:-1]}"><sheetData>{content}</sheetData></worksheet>')
        return list(iter_rows(path, 'xl/worksheets/sheet1.xml', raw=True))

    def test_excel_boundaries_sparse_cells_and_original_value(self):
        self.assertEqual(col_idx('XFD1048576'), 16383)
        rows = self.rows('<row r="1048576"><c r="XFD1048576" t="inlineStr"><is><t> unchanged </t></is></c></row>')
        self.assertEqual(rows[0][0], 1048576)
        self.assertEqual(len(rows[0][1]), 16384)
        self.assertEqual(rows[0][1][-1], ' unchanged ')
        rows = self.rows('<row r="4"><c r="C4" t="inlineStr"><is><t>C</t></is></c><c t="inlineStr"><is><t>D</t></is></c></row>')
        self.assertEqual(rows, [(4, ['', '', 'C', 'D'])])

    def test_optional_cell_and_row_references_infer_positions(self):
        rows = self.rows('<row><c t="inlineStr"><is><t>A</t></is></c><c t="inlineStr"><is><t>B</t></is></c></row><row><c t="inlineStr"><is><t>C</t></is></c></row>')
        self.assertEqual(rows, [(1, ['A', 'B']), (2, ['C'])])

    def test_malicious_or_invalid_reference_rejected_before_row_allocation(self):
        for reference in ('XFE1', 'ZZZZ1', 'ZZZZZZZZZZZZZZ1', 'A1048577', 'A0', 'A-1', 'A1junk', 'A999999999999999999999', ''):
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError):
                    self.rows(f'<row r="1"><c r="{reference}"><v>1</v></c></row>')
        for reference in ('0', '1048577', '999999999999999999', '-1', 'A', ''):
            with self.subTest(row_reference=reference):
                with self.assertRaises(ValueError):
                    self.rows(f'<row r="{reference}"><c><v>1</v></c></row>')


class IdentityConsistency(unittest.TestCase):
    def connection(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.row_factory = sqlite3.Row
        schema(c)
        c.execute('''insert into users(canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm)
            values(?,?,?,?,?,?,?)''', ('uid:g123', 'G123', 'g123', 'Anna Groß', norm('Anna Groß'), 'anna@example.invalid', 'anna@example.invalid'))
        c.execute('''insert into machines(machine_name,machine_name_norm,assigned_to,last_logon_user)
            values(?,?,?,?)''', ('PC-1', 'pc-1', 'INTRANET\\x123', 'x123'))
        return c

    def test_windows_login_links_and_seating_use_same_export_identity(self):
        c = self.connection()
        self.assertEqual(rebuild_links(c), {'linked': 2, 'ambiguous': 0, 'unmatched': 0})
        prepare_views(c)
        self.assertEqual(search_directory(c, 'x123')['users'][0]['canonical_key'], 'uid:g123')
        machine = linked_machines(c, 1)[0]
        self.assertEqual((machine['assigned_relationship'], machine['logon_relationship']), (1, 1))
        index, users = account_index(c)
        self.assertEqual(index['x123'], {'uid:g123'})
        self.assertEqual(users['uid:g123']['account'], 'G123')
        self.assertEqual(c.execute('select user_id from users').fetchone()[0], 'G123')

    def test_separate_g_and_x_exports_remain_ambiguous(self):
        c = self.connection()
        c.execute('''insert into users(canonical_key,user_id,user_id_norm,full_name,full_name_norm)
            values(?,?,?,?,?)''', ('uid:x123', 'x123', 'x123', 'Other Person', 'other person'))
        self.assertEqual(rebuild_links(c), {'linked': 0, 'ambiguous': 2, 'unmatched': 0})
        self.assertEqual(c.execute('select count(*) from assignments').fetchone()[0], 0)
        self.assertEqual(account_index(c)[0]['x123'], {'uid:g123', 'uid:x123'})

    def test_unicode_search_matches_existing_import_normalization(self):
        c = self.connection(); prepare_views(c)
        for term in ('Anna Groß', 'ANNA GROẞ', 'Groß', 'name:Anna Groß'):
            with self.subTest(term=term):
                self.assertEqual([r['canonical_key'] for r in search_directory(c, term)['users']], ['uid:g123'])


class RuntimeBackups(unittest.TestCase):
    def test_package_api_uses_database_directory_not_source_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / 'persistent'; runtime.mkdir()
            install = root / 'install'; install.mkdir()
            database = runtime / 'directory.db'
            app = FastAPI()
            with patch.object(package_data_api, '__file__', str(install / 'package_data_api.py')):
                package_data_api.register(app, SimpleNamespace(MASTER_DB=database, REPO=None), lambda request: None)
                with TestClient(app) as client:
                    preview = client.post('/api/package-data/import/preview', content=b'name,state\nixExample,Live\n', headers={'x-file-name': 'packages.csv'})
                    self.assertEqual(preview.status_code, 200, preview.text)
                    applied = client.post('/api/package-data/import/apply/' + preview.json()['id'])
                    self.assertEqual(applied.status_code, 200, applied.text)
            self.assertTrue((runtime / 'backups' / applied.json()['backup']).is_file())
            self.assertFalse((install / 'backups').exists())


    def test_desk_moves_api_uses_database_directory_not_source_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / 'persistent'; runtime.mkdir()
            install = root / 'install'; install.mkdir()
            database = runtime / 'directory.db'; app = FastAPI()
            with fixture_connect(database) as c:
                c.executescript('''
                    create table records(id text primary key,body text);
                    create table official_records(id text primary key,body text);
                    create table history(seq integer primary key,desk_id text,at text,action text,before_json text,after_json text);
                    create table desk_user_links(desk_id text primary key,user_key text,method text,updated_at text);
                    create table desk_link_history(seq integer primary key,desk_id text,at text,action text,before_key text,after_key text);
                ''')
                for index, name in enumerate(('Alice Fictional', 'Bob Fictional'), 1):
                    record = dict(id=f'02A{index:06}', floor=2, name=name, team='IT', occupancy='assigned',
                                  kind='desk', x=.1, y=.2, angle=0, hostname='PC'+str(index))
                    desk_moves.store.save_record(c, record, None, 'fixture')
            from test_directory_exports import workbook
            path = root / 'moves.xlsx'
            workbook(path, {'Desk moves': [desk_moves.HEADERS,
                ['02A000001', '2', 'Alice Fictional', 'IT', '', 'assigned', 'desk', '.1', '.2', '0', '1', '02A000002'],
                ['02A000002', '2', 'Bob Fictional', 'IT', '', 'assigned', 'desk', '.1', '.2', '0', '1', '02A000001']]})
            with patch.object(desk_moves, '__file__', str(install / 'desk_moves.py')):
                desk_moves.register_desk_moves(app, SimpleNamespace(MASTER_DB=database), lambda request: None, lambda: False)
            with TestClient(app) as client:
                preview = client.post('/api/desk-moves/preview', content=path.read_bytes())
                self.assertEqual(preview.status_code, 200, preview.text)
                result = client.post('/api/desk-moves/apply/' + preview.json()['id'], json={'confirmation': 'MOVE'})
                self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue((runtime / 'backups' / result.json()['backup']).is_file())
            self.assertFalse((install / 'backups').exists())


class DeskSnapshotConsistency(unittest.TestCase):
    def test_concurrent_refresh_does_not_replace_cached_person_inside_one_lookup(self):
        from desk_directory import resolve_person
        from merge_data import atlas_schema

        class RefreshDuringLookup(FixtureConnection):
            replacement = None

            def execute(self, sql, parameters=()):
                if self.replacement and sql.startswith('select * from legacy_users where id in'):
                    replacement, self.replacement = self.replacement, None
                    replacement()
                return super().execute(sql, parameters)

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'concurrent.db'
            with fixture_connect(database) as c:
                schema(c); atlas_schema(c)
                c.execute('insert into metadata values(?,?)', ('directory.generation', 'original'))
                c.execute('''insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm)
                    values(1,'uid:original','G1','g1','Original Person','original person')''')
            with fixture_connect(database, factory=RefreshDuringLookup) as c:
                c.execute('pragma journal_mode=wal'); c.row_factory = sqlite3.Row; prepare_views(c)

                def replace():
                    with fixture_connect(database) as writer:
                        writer.execute('delete from users')
                        writer.execute('''insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm)
                            values(1,'uid:replacement','G2','g2','Replacement Person','replacement person')''')
                        writer.execute("update metadata set value='replacement' where key='directory.generation'")

                c.replacement = replace
                desk = {'id': '02A000001', 'occupancy': 'assigned', 'name': 'Original Person'}
                people, method = resolve_person(c, desk)
                self.assertEqual(method, 'name-match')
                self.assertEqual([p['canonical_key'] for p in people], ['uid:original'])
                self.assertEqual(resolve_person(c, desk), ([], 'unmatched'))



if __name__ == '__main__':
    unittest.main()
