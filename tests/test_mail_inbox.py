import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlite_fixture import connect, isolate_backend_database
from backend.directory.directory_workbook import schema
from backend.directory.directory_lookup import prepare_views
from backend.directory.identity_links import rebuild_links
from backend.inbox.outlook_watcher import MailQueue, stamp, utcnow
from backend.inbox.mail_inbox import register, watcher_status
from backend.inbox.notification_inbox import notification_status


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.directory = self.base / 'directory.db'
        self.queue = MailQueue(self.base / 'mail', utcnow())
        self.addCleanup(self.queue.close)
        with connect(self.directory) as c:
            schema(c)
            for uid, name, email in [(1, 'Alex Morgan', 'alex@example.test'), (2, 'Alex Morgan', 'other@example.test'), (3, 'Sam Green', 'sam@example.test')]:
                c.execute('INSERT INTO users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) VALUES(?,?,?,?,?,?,?,?)',
                          (uid, 'person:' + str(uid), 'U' + str(uid), 'u' + str(uid), name, name.lower(), email, email))
            c.execute("INSERT INTO user_aliases(user_id_ref,alias_type,alias_value,alias_norm) VALUES(1,'upn','a.morgan@example.test','a.morgan@example.test')")
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,assigned_to,last_logon_user) VALUES(1,'LAPTOP-01','laptop-01','U1','U3')")
            rebuild_links(c)
        def directory_connection():
            c = connect(self.directory)
            c.row_factory = sqlite3.Row
            prepare_views(c)
            return c
        self.app = FastAPI()
        register(self.app, directory_connection, lambda: self.base / 'mail')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def add(self, name='Alex Morgan', address='alex@example.test', subject='Help', body='The application stopped.'):
        eid = str(self.queue.count() + 1)
        self.queue.insert('fixture', {'entry_id': eid, 'received_at': stamp(utcnow()), 'conversation_id': 'thread',
            'sender_name': name, 'sender_address': address, 'subject': subject, 'body': body, 'body_truncated': 0})
        return int(eid)

    def test_detail_includes_request_analysis_from_catalogue_knowledge_and_inventory(self):
        with connect(self.directory) as c:
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm) VALUES(2,'OTHER-PC-0042','other-pc-0042')")
        def directory_connection():
            c = connect(self.directory)
            c.row_factory = sqlite3.Row
            prepare_views(c)
            return c
        app = FastAPI()
        register(app, directory_connection, lambda: self.base / 'mail',
                 packages=lambda: [{'folder': 'Example_App_1.2', 'display_name': 'Example App'}],
                 documents=lambda: [{'id': 'kb1', 'title': 'Example App install guide', 'notes': ''}])
        client = TestClient(app); self.addCleanup(client.close)
        mid = self.add(subject='Software request', body='Please install Example App on OTHER-PC-0042 and LAPTOP-01.')
        analysis = client.get(f'/api/inbox/messages/{mid}').json()['analysis']
        self.assertEqual((analysis['kind'], analysis['action']), ('software', 'Install'))
        self.assertEqual(analysis['packages'][0]['folder'], 'Example_App_1.2')
        self.assertEqual([(m['name'], m['linked']) for m in analysis['machines']], [('LAPTOP-01', True), ('OTHER-PC-0042', False)])
        self.assertEqual(analysis['knowledge'], [{'id': 'kb1', 'title': 'Example App install guide'}])
        self.assertEqual(analysis['warnings'], [])

    def test_unavailable_catalogue_still_opens_the_message(self):
        def broken():
            raise OSError('share offline')
        app = FastAPI()
        def directory_connection():
            c = connect(self.directory)
            c.row_factory = sqlite3.Row
            prepare_views(c)
            return c
        register(app, directory_connection, lambda: self.base / 'mail', packages=broken)
        client = TestClient(app); self.addCleanup(client.close)
        mid = self.add(subject='Install', body='Please install Example App')
        detail = client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['user']['id'], 1)
        self.assertEqual(detail['analysis']['packages'], [])
        self.assertEqual(detail['analysis']['warnings'], ['Package catalogue unavailable: share offline'])

    def test_email_wins_over_ambiguous_name_and_lists_devices(self):
        mid = self.add()
        listing = self.client.get('/api/inbox/messages').json()
        self.assertNotIn('body', listing['items'][0])
        self.assertEqual(listing['items'][0]['match']['kind'], 'email')
        detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['user']['id'], 1)
        self.assertEqual([x['name'] for x in detail['machines']], ['LAPTOP-01'])
        self.assertEqual(detail['machines'][0]['match_type'], 'Assigned')
        self.assertNotIn('entry_id', detail['message'])

    def test_desktop_arrivals_are_count_only_and_respect_cursor(self):
        self.assertEqual(self.client.get('/api/inbox/arrivals').json(), {'newest_id': 0, 'count': 0})
        first, second = self.add(), self.add()
        self.assertEqual(self.client.get(f'/api/inbox/arrivals?after_id={first}').json(), {'newest_id': second, 'count': 1})
        self.assertEqual(self.client.get(f'/api/inbox/arrivals?after_id={second}').json(), {'newest_id': second, 'count': 0})
        self.assertEqual(self.client.get('/api/inbox/arrivals?after_id=99999').json(), {'newest_id': second, 'count': 0})
        self.assertEqual(self.client.get('/api/inbox/arrivals?after_id=-1').status_code, 422)

    def test_upn_alias_and_case_match(self):
        mid = self.add(address=' A.MORGAN@EXAMPLE.TEST ')
        detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['user']['id'], 1)

    def test_name_only_is_unconfirmed_and_inventory_logon_is_labelled(self):
        mid = self.add(' Sam   Green ', 'external@example.test')
        detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['kind'], 'name')
        self.assertEqual(detail['machines'][0]['match_type'], 'Last logged on (inventory)')

    def test_ambiguous_people_never_merge_their_devices(self):
        mid = self.add(address='unknown@example.test')
        result = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(result['match']['kind'], 'ambiguous')
        self.assertIsNone(result['match']['user'])
        self.assertEqual(result['machines'], [])
        chosen = self.client.get(f'/api/inbox/messages/{mid}?user_id=1').json()
        self.assertTrue(chosen['match']['chosen'])
        self.assertEqual(len(chosen['machines']), 1)
        self.assertEqual(self.client.get(f'/api/inbox/messages/{mid}?user_id=3').status_code, 409)

    def test_unknown_or_partial_names_not_guessed(self):
        mid = self.add('Alex', 'nobody@example.test')
        result = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(result['match']['kind'], 'unmatched')
        self.assertEqual(result['machines'], [])

    def test_incremental_and_older_pagination_with_mail_arriving(self):
        for _ in range(5): self.add()
        first = self.client.get('/api/inbox/messages?limit=2').json()
        self.assertEqual([row['id'] for row in first['items']], [5, 4])
        older = self.client.get('/api/inbox/messages?limit=2&before_id=4').json()
        self.assertEqual([row['id'] for row in older['items']], [3, 2])
        for _ in range(4): self.add()
        newer = self.client.get('/api/inbox/messages?limit=2&after_id=5').json()
        self.assertEqual([row['id'] for row in newer['items']], [6, 7])
        self.assertTrue(newer['has_more'])
        tail = self.client.get('/api/inbox/messages?limit=2&after_id=7').json()
        self.assertEqual([row['id'] for row in tail['items']], [8, 9])
        self.assertFalse(tail['has_more'])
        self.assertEqual(self.client.get('/api/inbox/messages?after_id=1&before_id=2').status_code, 400)
        self.assertEqual(self.client.get('/api/inbox/messages?limit=10000').status_code, 422)

    def test_reads_do_not_write_queue_or_directory(self):
        mid = self.add(body='<script>alert(1)</script>')
        paths = [self.directory, self.base / 'mail' / 'inbox.sqlite3']
        before = [p.read_bytes() for p in paths]
        self.client.get('/api/inbox/messages')
        result = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(result['message']['body'], '<script>alert(1)</script>')
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_missing_queue_is_empty_and_no_file_created(self):
        empty = self.base / 'not-created'
        app = FastAPI()
        register(app, lambda: None, lambda: empty)
        with TestClient(app) as client:
            result = client.get('/api/inbox/messages').json()
            self.assertEqual(result['items'], [])
            self.assertEqual(result['watcher']['state'], 'stopped')
            self.assertEqual(client.get('/api/inbox/messages/1').status_code, 404)
        self.assertFalse(empty.exists())

    def test_corrupt_queue_reports_retryable_error(self):
        other = self.base / 'corrupt'
        other.mkdir()
        (other / 'inbox.sqlite3').write_bytes(b'not sqlite')
        app = FastAPI(); register(app, lambda: None, lambda: other)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/inbox/messages').status_code, 503)

    def test_hung_watcher_is_not_reported_as_live(self):
        with patch('backend.inbox.mail_inbox.status', return_value={'running': True, 'state': 'watching', 'updated_at': '2000-01-01T00:00:00+00:00'}):
            self.assertTrue(watcher_status(self.base)['stale'])

    def notification(self, name='Sam Green'):
        self.queue.db.execute("INSERT INTO messages(source,entry_id,received_at,imported_at,conversation_id,sender_name,sender_address,subject,body,body_truncated,channel,content_kind,app_name) VALUES('notification:MSTeams','toast-7',?,?,'',?,'',?,'<script>unsafe()</script>',0,'teams','notification','Microsoft Teams')",
                              (stamp(utcnow()), stamp(utcnow()), name, name))
        self.queue.db.commit()
        return self.queue.db.execute('SELECT max(id) FROM messages').fetchone()[0]

    def test_teams_preview_joins_same_feed_and_links_exact_name(self):
        self.add()
        mid = self.notification()
        listing = self.client.get('/api/inbox/messages?after_id=1').json()
        self.assertEqual(listing['total'], 2)
        self.assertEqual(listing['items'][0]['channel'], 'teams')
        self.assertEqual(listing['items'][0]['content_kind'], 'notification')
        self.assertEqual(listing['items'][0]['preview'], '<script>unsafe()</script>')
        self.assertEqual(self.queue.count(), 1, 'Outlook counters exclude notification previews')
        detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['kind'], 'name')
        self.assertEqual(detail['match']['user']['id'], 3)
        self.assertEqual(detail['message']['body'], '<script>unsafe()</script>')
        self.assertEqual(detail['message']['sender_address'], '')
        self.assertEqual(detail['machines'][0]['name'], 'LAPTOP-01')
        self.assertNotIn('source', detail['message'])

    def test_teams_group_titles_are_not_parsed_into_guessed_people(self):
        mid = self.notification('Sam Green in IT Support')
        detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        self.assertEqual(detail['match']['kind'], 'unmatched')
        self.assertEqual(detail['machines'], [])

    def test_notification_status_detects_stop_stall_permission_and_corruption(self):
        directory = self.base / 'mail'
        path = directory / 'notifications-status.json'
        path.write_text(json.dumps({'state': 'watching', 'updated_at': '2000-01-01T00:00:00+00:00'}))
        self.assertEqual(notification_status(directory)['state'], 'stopped')
        with patch('backend.inbox.notification_inbox.is_running', return_value=True):
            self.assertTrue(notification_status(directory)['stale'])
            path.write_text(json.dumps({'state': 'permission_required', 'updated_at': stamp(utcnow())}))
            current = notification_status(directory)
            self.assertEqual(current['state'], 'permission_required')
            self.assertFalse(current['stale'])
        with patch('backend.inbox.notification_inbox.is_running', side_effect=PermissionError):
            self.assertEqual(notification_status(directory)['state'], 'error')
        path.write_text('[]')
        self.assertEqual(notification_status(directory)['state'], 'error')

    def test_legacy_mail_queue_reads_without_migration_then_preserves_history(self):
        mid = self.add()
        cursor = self.queue.get('cursor')
        for column in ('channel', 'content_kind', 'app_name'):
            self.queue.db.execute(f'ALTER TABLE messages DROP COLUMN {column}')
        self.queue.db.commit()
        path = self.base / 'mail' / 'inbox.sqlite3'
        before = path.read_bytes()
        listing = self.client.get('/api/inbox/messages').json()
        self.assertEqual(listing['items'][0]['content_kind'], 'mail')
        self.assertEqual(self.client.get(f'/api/inbox/messages/{mid}').json()['message']['channel'], 'outlook')
        self.assertEqual(path.read_bytes(), before)
        migrated = MailQueue(self.base / 'mail', utcnow())
        try:
            self.assertEqual(migrated.get('cursor'), cursor)
            self.assertEqual(migrated.count(), 1)
            self.assertEqual(migrated.db.execute('SELECT channel FROM messages WHERE id=?', (mid,)).fetchone()[0], 'outlook')
        finally:
            migrated.close()

    def test_private_routes_not_exposed_to_viewer_or_cross_origin(self):
        isolate_backend_database()
        from backend import main, viewer
        with TestClient(viewer.app, base_url='http://192.0.2.10:8771') as client:
            self.assertEqual(client.get('/api/inbox/messages').status_code, 404)
            self.assertEqual(client.get('/api/inbox/messages/1').status_code, 404)
            self.assertEqual(client.post('/api/inbox/messages', json={}).status_code, 403)
            self.assertEqual(client.get('/api/inbox/control').status_code, 404)
            self.assertEqual(client.post('/api/inbox/control', json={'action': 'start'}).status_code, 403)
        with patch.dict(os.environ, {'ATLAS_MAIL_DIR': str(self.base / 'no-mail')}):
            with TestClient(main.app, base_url='http://127.0.0.1:8770', client=('127.0.0.1', 1234)) as client:
                self.assertEqual(client.get('/api/inbox/messages').status_code, 200)
                self.assertEqual(client.get('/api/inbox/messages', headers={'Origin': 'https://example.test'}).status_code, 403)
                self.assertEqual(client.get('/api/inbox/messages', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
                self.assertEqual(client.post('/api/inbox/control', json={'action': 'start'}, headers={'Origin': 'https://example.test'}).status_code, 403)


    def test_people_named_in_the_message_with_their_machines(self):
        with connect(self.directory) as c:
            for uid, name, email, account in [(4, 'Marie Dupont', 'marie@example.test', 'X01000004'), (5, 'John Smith', 'john@example.test', 'X01000005'),
                                              (6, 'Chloé Martin', 'chloe@example.test', 'X01000006'), (7, 'Riley Operator', 'riley@example.test', 'X01426046'),
                                              (8, 'Lee Wong', 'lee1@example.test', 'X01000008'), (9, 'Lee Wong', 'lee2@example.test', 'X01000009')]:
                c.execute('INSERT INTO users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) VALUES(?,?,?,?,?,?,?,?)',
                          (uid, 'person:' + str(uid), account, account.lower(), name, name.lower(), email, email))
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,assigned_to) VALUES(2,'LAPTOP-04','laptop-04','X01000004')")
            rebuild_links(c)
        body = ("Bonjour Riley Operator,\nPlease install Visio for DUPONT Marie and give her the same access as John Smith's team.\n"
                "Sam Green needs it too, and one of the Lee Wong. Contact chloe@example.test or X01000005.\nThanks\nAlex Morgan\n"
                "From: Old Thread\nSent: Monday\nHi Old Person")
        mid = self.add(subject='Visio for the team', body=body)
        with patch.dict(os.environ, {'USERNAME': 'x01426046_dsk'}):
            detail = self.client.get(f'/api/inbox/messages/{mid}').json()
        people = detail['analysis']['people']
        named = [(p.get('full_name'), p['written'], p['basis']) for p in people if not p.get('ambiguous')]
        # In order of first mention; the operator (Riley, "Hi Riley") and the signature (the sender) are left out.
        self.assertEqual(named, [('Marie Dupont', 'DUPONT Marie', 'name'), ('John Smith', 'John Smith', 'name'),
                                 ('Sam Green', 'Sam Green', 'name'), ('Chloé Martin', 'chloe@example.test', 'email')])
        self.assertEqual([m['name'] for m in people[0]['machines']], ['LAPTOP-04'])
        self.assertEqual(people[0]['desks'], [])
        shared = [p for p in people if p.get('ambiguous')]
        self.assertEqual([(p['written'], sorted(c['email'] for c in p['candidates'])) for p in shared],
                         [('Lee Wong', ['lee1@example.test', 'lee2@example.test'])])
        self.assertEqual(detail['match']['user']['desks'], [])
        person = self.client.get('/api/inbox/person/4').json()
        self.assertEqual((person['user']['full_name'], [m['name'] for m in person['machines']], person['desks']), ('Marie Dupont', ['LAPTOP-04'], []))
        self.assertEqual(self.client.get('/api/inbox/person/999').status_code, 404)

    def test_name_windows_cover_word_orders_and_possessives(self):
        from backend.inbox.mail_inbox import name_candidates
        names = name_candidates("Hi Marie DUPONT, can Dupont, Marie use O'Brien's PC?")
        self.assertEqual(names['marie dupont'], 'Marie DUPONT')
        self.assertEqual(names['dupont marie'], 'Marie DUPONT')
        self.assertIn('hi marie dupont', names)
        self.assertNotIn("o'brien's pc", names)

if __name__ == '__main__': unittest.main()
