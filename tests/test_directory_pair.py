"""Two separate exports become the usual users/devices workbook; synthetic data only."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import database_manager as dm
from backend.directory.directory_pair import combine
from backend.directory.directory_workbook import build, directory_parts, iter_rows
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import device_sheets, workbook


def csv_text(rows, delimiter=','):
    return '\r\n'.join(delimiter.join('"' + value.replace('"', '""') + '"' for value in row) for row in rows) + '\r\n'


class DirectoryPair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sheets = device_sheets()

    def counts(self, workbook_path):
        db = self.root / (workbook_path.stem + '.db')
        build(workbook_path, db)
        with fixture_connect(db) as c:
            return ({t: c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('users', 'machines', 'assignments')},
                    c.execute('select user_id, full_name, email, employee_number, start_date from users order by user_id').fetchall(),
                    c.execute('select machine_name, model_id, serial_number, assigned_to from machines order by machine_name').fetchall())

    def test_csv_and_xlsx_in_either_order_match_a_combined_workbook(self):
        expected = self.root / 'combined.xlsx'
        workbook(expected, self.sheets)
        users = self.root / 'sys_user.csv'
        users.write_text(csv_text(self.sheets['users']), encoding='utf-8-sig', newline='')
        devices = self.root / 'alm_hardware.xlsx'
        workbook(devices, {'Page 1': self.sheets['devices']})
        out = self.root / 'pair.xlsx'
        result = combine(devices, users, out)
        self.assertEqual(result, {'users_file': 'sys_user.csv', 'devices_file': 'alm_hardware.xlsx', 'rows': {'users': 2, 'devices': 3}})
        self.assertEqual(sorted(directory_parts(out)), ['machine', 'user'])
        self.assertEqual(self.counts(out), self.counts(expected), 'Same directory as the hand-combined workbook')

    def test_semicolon_and_windows_csv(self):
        users = self.root / 'users.csv'
        rows = [row[:] for row in self.sheets['users']]
        rows[1][1] = 'Hélène Exemple'
        users.write_bytes(csv_text(rows, ';').encode('cp1252'))
        devices = self.root / 'devices.csv'
        devices.write_text(csv_text(self.sheets['devices']), encoding='utf-8', newline='')
        out = self.root / 'pair.xlsx'
        combine(users, devices, out)
        names = [row[1] for _, row in iter_rows(out, directory_parts(out)['user'][1])]
        self.assertEqual(names[1], 'Hélène Exemple', 'Excel-saved CSV (Windows-1252, semicolons) is read correctly')

    def test_wrong_pairs_are_refused_with_the_file_name(self):
        users = self.root / 'users.csv'
        users.write_text(csv_text(self.sheets['users']), encoding='utf-8', newline='')
        devices = self.root / 'devices.csv'
        devices.write_text(csv_text(self.sheets['devices']), encoding='utf-8', newline='')
        other = self.root / 'other.csv'
        other.write_text('a,b\r\n1,2\r\n', encoding='utf-8', newline='')
        empty = self.root / 'empty.csv'
        empty.write_text('', encoding='utf-8')
        cases = [((users, users), 'Both files look like users'), ((devices, devices), 'Both files look like devices'),
                 ((users, other), 'other.csv: not a users or devices export'), ((empty, devices), 'empty.csv: the file is empty')]
        for (first, second), text in cases:
            with self.assertRaisesRegex(ValueError, text):
                combine(first, second, self.root / 'out.xlsx')

    def test_preview_pair_endpoint_splits_and_combines(self):
        db = self.root / 'office_atlas.db'
        with fixture_connect(db) as c:
            c.execute('create table users(id integer)')
        w = SimpleNamespace(MASTER_DB=db, jobs={}, queue_jobs={})
        app = FastAPI()

        def token(request):
            if request.headers.get('x-atlas-token') != 'test':
                raise HTTPException(403, 'token')
        dm.register_database_manager(app, w, token)
        client = TestClient(app)
        seen = {}

        def prepare(source, candidate):
            seen['users'] = [row for _, row in iter_rows(source, directory_parts(source)['user'][1])]
            seen['devices'] = [row for _, row in iter_rows(source, directory_parts(source)['machine'][1])]
            with fixture_connect(candidate) as c:
                c.execute('create table users(id integer)')
        users = csv_text(self.sheets['users']).encode('utf-8')
        devices = csv_text(self.sheets['devices']).encode('utf-8')
        headers = {'x-atlas-token': 'test', 'x-first-size': str(len(devices)), 'x-first-name': 'devices.csv', 'x-second-name': 'users.csv'}
        with patch.object(dm, 'prepare', prepare), patch.object(dm, 'compare', lambda target, candidate: {'ok': True}), patch.object(dm, 'fingerprint', lambda path: 'fixture'):
            self.assertEqual(client.post('/api/database/preview-pair', content=devices + users, headers={**headers, 'x-atlas-token': 'no'}).status_code, 403)
            response = client.post('/api/database/preview-pair', content=devices + users, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['source'], 'users.csv + devices.csv')
            self.assertEqual(body['pair']['rows'], {'users': 2, 'devices': 3})
            self.assertEqual(seen['users'][1][:3], ['u1', 'Example Person', 'e@example.invalid'])
            self.assertEqual(seen['devices'][1][3], 'testpc-1')
            missing = client.post('/api/database/preview-pair', content=devices, headers=headers)
            self.assertEqual((missing.status_code, missing.json()['detail']), (400, 'Choose both a users file and a devices file.'))
            w.jobs['x'] = {'state': 'running'}
            self.assertEqual(client.post('/api/database/preview-pair', content=devices + users, headers=headers).status_code, 409)


if __name__ == '__main__':
    unittest.main()
