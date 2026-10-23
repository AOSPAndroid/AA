"""Atlas Companion: its Windows-free logic and the Atlas routes it talks to, end to end.
No Windows API, Outlook or clipboard is used: the Companion client reaches Atlas through TestClient."""
import io
import json
import sqlite3
import struct
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import clipboard_history
import companion_core as core
import companion_server
import mail_inbox
from directory_lookup import prepare_views
from directory_workbook import schema
from identity_links import rebuild_links
from inbox_control import IntegrationError
from outlook_watcher import MailQueue, utcnow
from sqlite_fixture import connect


class Opener:
    """urllib opener for companion_core.Client that answers through a TestClient."""
    def __init__(self, client):
        self.client = client

    def open(self, request, timeout=None):
        path = request.full_url.split('8770', 1)[1]
        response = self.client.post(path, content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, 'error', {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)


def mail(n):
    return {'entry_id': f'E{n}', 'received_at': f'2026-10-20T09:{n:02d}:00+00:00', 'conversation_id': '', 'sender_name': 'Alex Morgan',
            'sender_address': 'alex@example.test', 'subject': f'Fictional request {n}', 'body': 'LAPTOP-0001 is slow', 'body_truncated': 0}


class Companion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        db = root / 'atlas.db'
        with connect(db) as c:
            schema(c)
            c.execute("INSERT INTO users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) VALUES(1,'person:1','X01000001','x01000001','Alex Morgan','alex morgan','alex@example.test','alex@example.test')")
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,assigned_to) VALUES(1,'LAPTOP-0001','laptop-0001','X01000001')")
            rebuild_links(c)
        self.ocr = []

        class Backend:
            @staticmethod
            def db():
                c = connect(db); c.row_factory = sqlite3.Row; prepare_views(c); return c

            @staticmethod
            def ps(script, timeout=120):
                self.ocr.append(script)
                return json.dumps({'text': 'Screenshot: LAPTOP-0001 shows error 0x80070005', 'language': 'en-GB'})

        def check_token(request):
            if request.headers.get('x-atlas-token') != 'admin':
                raise HTTPException(403, 'Refresh the page before saving')
        app = FastAPI()
        clipboard_history.register(app, Backend, check_token, root / 'clipboard-history.json')
        self.server = companion_server.register(app, Backend, check_token, root / 'companion-state.json', root / 'companion-inbox',
                                                folder=root / 'ProgramData', url='http://127.0.0.1:8770')
        for module, name in ((clipboard_history, 'history'), (companion_server, 'companion')):
            self.addCleanup(setattr, module, name, None)
        windows = patch('screen_reader.windows', return_value=True); windows.start(); self.addCleanup(windows.stop)
        self.http = TestClient(app); self.addCleanup(self.http.close)
        url, token = core.read_connection(root / 'ProgramData' / 'connection.json')
        self.client = core.Client(url, token, opener=Opener(self.http))

    def settings(self, **values):
        return self.http.post('/api/companion/settings', json=values, headers={'x-atlas-token': 'admin'})

    def test_connection_file_and_key(self):
        saved = json.loads((self.root / 'ProgramData' / 'connection.json').read_text())
        self.assertEqual(saved['url'], 'http://127.0.0.1:8770')
        self.assertGreaterEqual(len(saved['token']), 32)
        self.assertEqual(self.server.token(), saved['token'], 'The key survives Atlas restarts')
        self.assertEqual(self.http.post('/api/companion/hello', json={}).status_code, 403)
        self.assertEqual(self.http.post('/api/companion/clipboard', json={'text': 'x'}, headers={'x-atlas-companion': 'wrong'}).status_code, 403)
        self.assertEqual(self.settings(mail=True).status_code, 200)
        self.assertEqual(self.http.post('/api/companion/settings', json={'mail': True}, headers={'x-atlas-companion': saved['token']}).status_code, 403,
                         'The Companion key cannot change Atlas settings')
        with self.assertRaisesRegex(core.Offline, 'Start Atlas Admin'):
            core.read_connection(self.root / 'missing.json')
        (self.root / 'remote.json').write_text(json.dumps({'url': 'http://evil.example:80', 'token': 'x'}))
        with self.assertRaisesRegex(core.Offline, 'only connects to Atlas on this PC'):
            core.read_connection(self.root / 'remote.json')

    def test_check_in_clipboard_and_screenshots_reach_the_history(self):
        self.assertFalse(self.http.get('/api/companion').json()['known'])
        settings = core.hello(self.client, 'EXAMPLE\\operator', 'PC-OPS-01', {'state': 'watching', 'captured': 0}, {'state': 'off'})
        self.assertEqual(settings, {'clipboard': True, 'mail': False})
        status = self.http.get('/api/companion').json()
        self.assertEqual((status['online'], status['user'], status['computer']), (True, 'EXAMPLE\\operator', 'PC-OPS-01'))
        forwarder = core.ClipboardForwarder(self.client)
        forwarder.handle({'text': 'please check LAPTOP-0001'})
        forwarder.handle({'text': 'please check LAPTOP-0001'})
        forwarder.handle({'private': True})
        forwarder.handle({'files': [r'C:\Users\operator\Desktop\report.xlsx']})
        forwarder.handle({'image': core.dib_to_bmp(struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0) + b'\0' * 4)})
        items = clipboard_history.history.load()
        self.assertEqual([(i['source'], i['text'][:24]) for i in items],
                         [('screenshot', 'Screenshot: LAPTOP-0001 '), ('companion', 'C:\\Users\\operator\\Deskto'), ('companion', 'please check LAPTOP-0001')])
        self.assertEqual(items[2]['machines'][0]['user']['email'], 'alex@example.test', 'Companion copies are enriched like any other')
        self.assertEqual(forwarder.captured, 3, 'The same copy twice is sent once; private copies are skipped')
        self.assertIn('private', forwarder.report()['detail'])
        self.assertTrue(self.ocr[0].startswith("$Mode='image'"))
        self.settings(clipboard=False)
        with self.assertRaisesRegex(core.Offline, 'Clipboard capture is off'):
            forwarder.handle({'text': 'not wanted now'})
        self.assertEqual(forwarder.report()['state'], 'error')

    def test_outlook_mail_reaches_live_inbox_through_the_companion(self):
        local = MailQueue(self.root / 'companion-local', utcnow())
        for n in range(1, 4):
            local.insert('sourceabc123', mail(n))
        forwarder = core.MailForwarder(local, self.client, batch=2)
        core.hello(self.client, 'EXAMPLE\\operator', 'PC-OPS-01', {}, {'state': 'watching', 'last_success_at': '2026-10-20T09:05:00+00:00'})
        with self.assertRaisesRegex(core.Offline, 'Email watcher is off|Outlook watcher is off'):
            forwarder.forward()
        self.assertEqual(local.get('forwarded'), None, 'Nothing is marked sent when Atlas refuses it')
        self.settings(mail=True)
        self.assertEqual(forwarder.forward(), 3)
        self.assertEqual(forwarder.forward(), 0, 'Only new messages are sent')
        local.insert('sourceabc123', mail(4)); local.db.execute("update watcher_state set value='1' where key='forwarded'"); local.db.commit()
        forwarder.forward()  # Re-sending already delivered messages is harmless: Atlas keeps one copy.
        with sqlite3.connect(self.root / 'companion-inbox' / 'inbox.sqlite3') as c:
            self.assertEqual(c.execute('select count(*) from messages').fetchone()[0], 4)
        local.close()
        self.assertEqual(mail_inbox.mail_directory(), self.root / 'companion-inbox', 'Live Inbox reads the Companion mail')
        watcher = mail_inbox.watcher_status(self.root / 'companion-inbox')
        self.assertEqual((watcher['state'], watcher['running'], watcher['last_success_at']), ('watching', True, '2026-10-20T09:05:00+00:00'))

    def test_live_inbox_switches_control_the_companion(self):
        class Original:
            def status(self): return {'configured': False, 'state': 'not_configured'}
            def command(self, action, **preferences): return 'original'
            def configure(self, *args): return 'configured'
        inbox = companion_server.CompanionInbox(self.server, Original())
        self.assertEqual(inbox.status()['state'], 'not_configured', 'Before any Companion: the original collectors')
        self.assertEqual(inbox.command('start'), 'original')
        core.hello(self.client, 'EXAMPLE\\operator', 'PC-OPS-01', {}, {'state': 'watching'})
        self.assertEqual(inbox.command('start')['desired']['outlook'], True)
        status = inbox.status()
        self.assertEqual((status['configured'], status['companion'], status['mail_user'], status['state']), (True, True, 'EXAMPLE\\operator', 'watching'))
        self.assertFalse(inbox.command('source', outlook=False)['desired']['running'])
        self.assertFalse(self.server.settings()['mail'])
        with self.assertRaisesRegex(IntegrationError, 'Teams notifications'):
            inbox.command('source', notifications=True)
        self.server.state['companion']['seen_epoch'] = 0
        self.assertEqual(inbox.status()['state'], 'stopped')


class CoreHelpers(unittest.TestCase):
    def test_dib_to_bmp_offsets(self):
        for bits, compression, colours, extra in ((24, 0, 0, 0), (8, 0, 0, 1024), (32, 3, 0, 12), (8, 0, 16, 64)):
            dib = struct.pack('<IiiHHIIiiII', 40, 2, 2, 1, bits, compression, 0, 0, 0, colours, 0) + b'\0' * 64
            bmp = core.dib_to_bmp(dib)
            self.assertEqual(bmp[:2], b'BM')
            self.assertEqual(struct.unpack_from('<I', bmp, 2)[0], len(bmp))
            self.assertEqual(struct.unpack_from('<I', bmp, 10)[0], 14 + 40 + extra, (bits, compression, colours))
        with self.assertRaises(ValueError):
            core.dib_to_bmp(b'short')

    def test_private_copies_and_backoff(self):
        self.assertTrue(core.private({'ExcludeClipboardContentFromMonitorProcessing'}))
        self.assertTrue(core.private({'CanIncludeInClipboardHistory'}, 0))
        self.assertFalse(core.private({'CanIncludeInClipboardHistory'}, 1))
        self.assertFalse(core.private({'HTML Format', 'Rich Text Format'}))
        self.assertEqual([core.backoff(n) for n in (1, 2, 3, 5, 9)], [5, 10, 20, 60, 60])

    def test_paused_and_empty_copies_send_nothing(self):
        class Client:
            def post(self, *args): raise AssertionError('Nothing should be sent')
            image = post
        forwarder = core.ClipboardForwarder(Client())
        forwarder.paused = True
        self.assertIsNone(forwarder.handle({'text': 'secret'}))
        self.assertEqual(forwarder.report()['state'], 'paused')
        forwarder.paused = False
        for content in ({}, {'text': '   '}, {'files': []}):
            self.assertIsNone(forwarder.handle(content))


if __name__ == '__main__':
    unittest.main()
