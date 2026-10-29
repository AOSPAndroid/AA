import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlite_fixture import connect
from backend.directory.directory_workbook import schema
from backend.directory.directory_lookup import prepare_views
from backend.directory.identity_links import rebuild_links
from backend.inbox import screen_reader
from backend.inbox.screen_reader import register, title_names

TEAMS = 'Chat | Alex Morgan | Microsoft Teams'


class ScreenReader(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name) / 'directory.db'
        with connect(self.directory) as c:
            schema(c)
            for uid, name, email in [(1, 'Alex Morgan', 'alex@example.test'), (2, 'Sam Green', 'sam@example.test'), (3, 'Sam Green', 'sam2@example.test')]:
                c.execute('INSERT INTO users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) VALUES(?,?,?,?,?,?,?,?)',
                          (uid, 'person:' + str(uid), 'U' + str(uid), 'u' + str(uid), name, name.lower(), email, email))
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,assigned_to) VALUES(1,'LAPTOP-0001','laptop-0001','U1')")
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm) VALUES(2,'SPARE-PC-0042','spare-pc-0042')")
            rebuild_links(c)
        self.scripts, self.capture = [], {'title': TEAMS, 'process': 'ms-teams', 'text': 'Hi, my PC is very slow\nalex@example.test', 'lines': 2}
        test = self

        class Backend:
            @staticmethod
            def ps(script, timeout=120):
                test.scripts.append(script)
                return json.dumps(test.capture)

            @staticmethod
            def db():
                c = connect(test.directory); c.row_factory = sqlite3.Row; prepare_views(c); return c

            @staticmethod
            def inbox_packages():
                return [{'folder': 'Example_App', 'display_name': 'Example App'}]

        def check_token(request):
            if request.headers.get('x-atlas-token') != 'token':
                raise HTTPException(403, 'Refresh the page before saving')
        self.backend = Backend
        app = FastAPI(); register(app, Backend, check_token)
        self.client = TestClient(app); self.addCleanup(self.client.close)
        windows = patch.object(screen_reader, 'windows', return_value=True); windows.start(); self.addCleanup(windows.stop)

    def post(self, url, body, token='token'):
        return self.client.post(url, json=body, headers={'x-atlas-token': token})

    def test_window_capture_is_analysed_like_an_email(self):
        result = self.post('/api/screen/read', {'source': 'window', 'delay': 2}).json()
        self.assertTrue(self.scripts[0].startswith("$Mode='window'; $Delay=2\n"))
        self.assertEqual(result['match']['kind'], 'email')
        self.assertEqual(result['match']['user']['id'], 1)
        self.assertEqual([m['name'] for m in result['machines']], ['LAPTOP-0001'])
        self.assertEqual(result['analysis']['kind'], 'issue')
        self.assertEqual(result['analysis']['packages'], [], 'The email domain does not match "Example App"')
        self.assertEqual((result['title'], result['process']), (TEAMS, 'ms-teams'))

    def test_clipboard_hostname_and_install_request(self):
        self.capture = {'title': 'Notepad', 'process': 'notepad', 'text': 'please install Example App on SPARE-PC-0042'}
        result = self.post('/api/screen/read', {'source': 'clipboard'}).json()
        self.assertIn("$Mode='clipboard'; $Delay=3", self.scripts[0])
        self.assertEqual(result['match']['kind'], 'unmatched')
        self.assertEqual((result['analysis']['kind'], result['analysis']['action']), ('software', 'Install'))
        self.assertEqual(result['analysis']['packages'][0]['folder'], 'Example_App')
        self.assertEqual([(m['name'], m['linked']) for m in result['analysis']['machines']], [('SPARE-PC-0042', False)])

    def test_ocr_lookalike_characters_still_find_the_machine(self):
        # Windows OCR read 0 as O and 1 as I/l in hostnames.
        self.capture = {'title': 'Notepad', 'process': 'notepad', 'text': 'SPARE-PC-OO42 is slow, so is LAPTOP-OOOl'}
        machines = self.post('/api/screen/read', {'source': 'window'}).json()['analysis']['machines']
        self.assertEqual(sorted((m['name'], m.get('written_as')) for m in machines),
                         [('LAPTOP-0001', 'LAPTOP-OOOL'), ('SPARE-PC-0042', 'SPARE-PC-OO42')])

    def test_exact_name_wins_and_unknown_lookalikes_find_nothing(self):
        with connect(self.directory) as c:
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm) VALUES(3,'SPARE-PC-OO42','spare-pc-oo42')")
        self.capture = {'title': 'Notepad', 'process': 'notepad', 'text': 'SPARE-PC-OO42 and NOWHERE-PC-9999 are slow'}
        machines = self.post('/api/screen/read', {'source': 'window'}).json()['analysis']['machines']
        self.assertEqual([(m['name'], m.get('written_as')) for m in machines], [('SPARE-PC-OO42', None)])

    def test_title_name_and_ambiguous_people(self):
        self.capture = {'title': 'Chat | Sam Green | Microsoft Teams', 'process': 'ms-teams', 'text': 'printer is broken'}
        result = self.post('/api/screen/read', {'source': 'window', 'delay': 0}).json()
        self.assertEqual(result['match']['kind'], 'ambiguous')
        self.assertEqual(sorted(c['id'] for c in result['match']['candidates']), [2, 3])
        chosen = self.post('/api/screen/analyse', {'title': result['title'], 'text': result['text'], 'user_id': 3}).json()
        self.assertEqual((chosen['match']['user']['id'], chosen['match']['chosen']), (3, True))
        self.assertEqual(self.post('/api/screen/analyse', {'title': 'Notepad', 'text': 'x', 'user_id': 3}).status_code, 409)

    def test_edited_text_is_reanalysed_without_capturing(self):
        result = self.post('/api/screen/analyse', {'title': '', 'text': 'Can I have Example App? alex@example.test'}).json()
        self.assertEqual(self.scripts, [])
        self.assertEqual(result['analysis']['packages'][0]['folder'], 'Example_App')
        self.assertEqual(result['match']['user']['id'], 1)

    def test_guards(self):
        self.assertEqual(self.post('/api/screen/read', {'source': 'window'}, token='wrong').status_code, 403)
        self.assertEqual(self.post('/api/screen/read', {'source': 'files'}).status_code, 422)
        self.assertEqual(self.post('/api/screen/read', {'source': 'window', 'delay': 11}).status_code, 422)
        self.assertEqual(self.scripts, [], 'Invalid requests never run PowerShell')
        self.capture = {'title': 'Atlas · IT Console - Work - Microsoft Edge', 'process': 'msedge', 'text': 'Atlas'}
        self.assertEqual(self.post('/api/screen/read', {'source': 'window'}).status_code, 409)
        self.capture = {'title': 'Blank', 'process': 'mspaint', 'text': '  '}
        self.assertEqual(self.post('/api/screen/read', {'source': 'screen'}).status_code, 422)
        with patch.object(screen_reader, 'windows', return_value=False):
            self.assertEqual(self.post('/api/screen/read', {'source': 'window'}).status_code, 501)

    def test_a_pasted_screenshot_is_read_with_ocr(self):
        self.capture = {'title': 'ignored', 'process': '', 'text': 'Hi IT, please install Example App on SPARE-PC-0042\nalex@example.test', 'language': 'en-GB'}
        seen = []
        def ps(script, timeout=120):
            path = script.split("$ImagePath='", 1)[1].split("'\n", 1)[0]
            seen.append(Path(path).read_bytes())
            self.scripts.append(script)
            return json.dumps(self.capture)
        png = b'\x89PNG\r\n\x1a\n' + b'fictional image bytes'
        with patch.object(self.backend, 'ps', ps):
            response = self.client.post('/api/screen/image', content=png, headers={'x-atlas-token': 'token', 'content-type': 'image/png'})
        result = response.json()
        self.assertEqual(response.status_code, 200, result)
        self.assertTrue(self.scripts[0].startswith("$Mode='image'; $Delay=0; $ImagePath='"))
        self.assertEqual(seen, [png], 'PowerShell reads exactly the uploaded image')
        self.assertFalse(Path(self.scripts[0].split("$ImagePath='", 1)[1].split("'", 1)[0]).exists(), 'The temporary image is deleted')
        self.assertEqual((result['source'], result['title']), ('image', 'Pasted screenshot'))
        self.assertEqual(result['match']['user']['id'], 1)
        self.assertEqual(result['analysis']['packages'][0]['folder'], 'Example_App')

    def test_screenshot_guards(self):
        post = lambda body, token='token': self.client.post('/api/screen/image', content=body, headers={'x-atlas-token': token})
        self.assertEqual(post(b'\x89PNG\r\n\x1a\n', token='wrong').status_code, 403)
        self.assertEqual(post(b'<script>not an image</script>').status_code, 415)
        self.assertEqual(post(b'\x89PNG\r\n\x1a\n' + b'0' * (15 * 1024 * 1024)).status_code, 413)
        self.assertEqual(self.scripts, [], 'Rejected uploads never run PowerShell')
        self.capture = {'text': '   '}
        self.assertEqual(post(b'\xff\xd8\xff' + b'jpeg').status_code, 422)

    def test_title_names(self):
        self.assertEqual(title_names('Chat | Alex Morgan | Microsoft Teams'), ['Alex Morgan'])
        self.assertEqual(title_names('RE: Laptop issue - Message (HTML) - Outlook'), [])
        self.assertEqual(title_names('INC0012345 - Sam Green - ServiceNow'), ['Sam Green'])
        self.assertEqual(title_names("Chat | Jean-Luc O'Neil | Microsoft Teams"), ["Jean-Luc O'Neil"])
        self.assertEqual(title_names('Chat | Hélène van Dijk | Microsoft Teams'), ['Hélène van Dijk'])

    def test_viewer_never_registers_screen_routes(self):
        from backend import viewer
        self.assertFalse([r.path for r in viewer.app.routes if '/api/screen' in getattr(r, 'path', '')])


if __name__ == '__main__':
    unittest.main()
