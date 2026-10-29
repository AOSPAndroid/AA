"""Windows logins are derived without changing imported identity records."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.directory.directory_workbook import schema
from backend.directory.directory_lookup import prepare_views, search_directory, windows_login


def add_user(c, uid, login, name='Example Person'):
    c.execute('''insert into users
        (id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,
         email,email_norm,employee_number)
        values(?,?,?,?,?,?,?,?,?)''',
        (uid, 'uid:' + login.lower(), login, login.lower(), name, name.lower(),
         f'person{uid}@example.test', f'person{uid}@example.test', login))


class DomainAccountsTests(unittest.TestCase):
    def test_confirmed_number_convention_only(self):
        for source, expected in [
            ('G00123456', 'x00123456'), ('g123', 'x123'),
            ('INTRANET\\G00123456', 'INTRANET\\x00123456'),
            ('x00123456', 'x00123456'), ('george', 'george'),
            ('G123A', 'G123A'), ('g123@example.test', 'g123@example.test'),
            ('', ''), (None, ''),
        ]:
            with self.subTest(source=source):
                self.assertEqual(windows_login(source), expected)

    def test_search_aliases_and_original_identity_preserved(self):
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.row_factory = sqlite3.Row
        schema(c)
        add_user(c, 1, 'G00123456')
        before = tuple(c.execute('select * from users').fetchone())
        prepare_views(c)
        for term in ['G00123456', 'x00123456', 'X00123456',
                     'INTRANET\\x00123456', 'user:x00123456',
                     'user:INTRANET\\X00123456', 'person1@example.test']:
            with self.subTest(term=term):
                rows = search_directory(c, term)['users']
                self.assertEqual([r['id'] for r in rows], [1])
                self.assertEqual(rows[0]['login_id'], 'x00123456')
                self.assertEqual(rows[0]['login_norm'], 'x00123456')
                self.assertEqual(rows[0]['user_name'], 'G00123456')
                self.assertEqual(rows[0]['employee_number'], 'G00123456')
                self.assertEqual(rows[0]['canonical_key'], 'uid:g00123456')
        self.assertEqual(tuple(c.execute('select * from users').fetchone()), before)
        plan = str([tuple(r) for r in c.execute('explain query plan select * from legacy_users where user_name_norm in (?,?,?,?)', ('x00123456', '', 'g00123456', ''))])
        self.assertIn('ix_users_login', plan)

    def test_admin_and_demo_share_login_and_handle_conflicts(self):
        from backend import main, viewer
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'directory.db'
            c = sqlite3.connect(path)
            schema(c)
            c.executescript('''
                create table desk_user_links(desk_id text, user_key text);
                create table official_seating_mappings(legacy_id text, official_id text);
                create table official_records(id text, body text);
            ''')
            add_user(c, 1, 'G00123456')
            c.commit()
            c.close()
            with patch.object(main, 'MASTER_DB', path), patch.object(viewer, 'DB', path), patch.object(main.job_service, 'recover'):
                for app, host in [(main.app, 'http://127.0.0.1'), (viewer.app, 'http://192.0.2.10')]:
                    with TestClient(app, base_url=host, client=('127.0.0.1', 12345)) as client:
                        for term in ['G00123456', 'x00123456', 'INTRANET\\x00123456']:
                            response = client.get('/api/search', params={'term': term})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.json()['users'][0]['login_id'], 'x00123456')
                        response = client.get('/api/user/x00123456')
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()['user']['user_name'], 'G00123456')
                # Separate exported identities must remain ambiguous, never silently combined.
                c = sqlite3.connect(path)
                add_user(c, 2, 'x00123456', 'Different Person')
                c.commit()
                c.close()
                for app in (main.app, viewer.app):
                    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
                        result = client.get('/api/search', params={'term': 'x00123456'}).json()
                        self.assertEqual({u['id'] for u in result['users']}, {1, 2})
                        self.assertEqual(client.get('/api/user/x00123456').status_code, 409)
                        self.assertEqual(client.get('/api/user/id:1').status_code, 200)


if __name__ == '__main__':
    unittest.main()
