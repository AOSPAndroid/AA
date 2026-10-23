"""Clipboard history: capture, enrichment from a fictional directory, de-duplication and the API."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import clipboard_history
from clipboard_history import History, candidates, enrich, register
from directory_lookup import prepare_views
from directory_workbook import schema
from identity_links import rebuild_links
from sqlite_fixture import connect


class ClipboardHistory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.db = self.root / 'atlas.db'
        with connect(self.db) as c:
            schema(c)
            for uid, name, email in [(1, 'Alex Morgan', 'alex@example.test'), (2, 'Sam Green', 'sam@example.test'), (3, 'Sam Green', 'sam2@example.test')]:
                c.execute('INSERT INTO users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm,department) VALUES(?,?,?,?,?,?,?,?,?)',
                          (uid, 'person:' + str(uid), 'X0100000' + str(uid), 'x0100000' + str(uid), name, name.lower(), email, email, 'Equities'))
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,assigned_to,model_id,operational_status) VALUES(1,'LAPTOP-0001','laptop-0001','X01000001','Latitude 7450','Operational')")
            c.execute("INSERT INTO machines(id,machine_name,machine_name_norm,model_id) VALUES(2,'SPARE-PC-0042','spare-pc-0042','OptiPlex 7020')")
            rebuild_links(c)
            c.execute('create table official_records(id text primary key, body text)')
            c.execute("insert into official_records values('02R015079', ?)", (json.dumps({'name': 'Alex Morgan', 'team': 'Equities', 'floor': 2, 'occupancy': 'assigned'}),))
        test = self

        class Backend:
            @staticmethod
            def db():
                c = connect(test.db); c.row_factory = sqlite3.Row; prepare_views(c); return c
        self.backend = Backend
        self.path = self.root / 'clipboard-history.json'
        app = FastAPI()

        def check_token(request):
            if request.headers.get('x-atlas-token') != 'token':
                raise HTTPException(403, 'Refresh the page before saving')
        self.history = register(app, Backend, check_token, self.path)
        self.addCleanup(setattr, clipboard_history, 'history', None)
        self.client = TestClient(app); self.addCleanup(self.client.close)

    def post(self, text, source='button', token='token'):
        return self.client.post('/api/clipboard', json={'text': text, 'source': source}, headers={'x-atlas-token': token})

    def test_a_copied_list_is_enriched(self):
        text = ('Machines for the move:\nLAPTOP-0001\nspare-pc-0042\nLAPT0P-OOO1\nGHOST-PC-9999\n'
                'ask alex@example.test or X01000001, Sam Green too\nticket INC0045678, desk 2R015079, printer 10.40.12.7')
        item = self.post(text).json()
        self.assertEqual([m['name'] for m in item['machines']], ['LAPTOP-0001', 'SPARE-PC-0042'])
        self.assertEqual(item['machines'][0]['user']['email'], 'alex@example.test', 'The machine user comes from the directory links')
        self.assertIsNone(item['machines'][1]['user'])
        self.assertEqual(item['unknown_machines'], ['GHOST-PC-9999'], 'Unknown hostnames keep how they were written')
        self.assertEqual([u['email'] for u in item['users']], ['alex@example.test'], 'Shared names (Sam Green) are not guessed')
        self.assertEqual(item['desks'], [{'desk': '02R015079', 'name': 'Alex Morgan', 'team': 'Equities', 'floor': 2, 'occupancy': 'assigned'}])
        self.assertEqual((item['tickets'], item['ips']), (['INC0045678'], ['10.40.12.7']))
        self.assertEqual(self.client.get('/api/clipboard').json()['items'][0]['id'], item['id'])

    def test_copying_again_moves_to_the_top_and_items_can_be_removed(self):
        first = self.post('LAPTOP-0001').json(); second = self.post('SPARE-PC-0042', 'paste').json()
        again = self.post('LAPTOP-0001', 'return').json()
        self.assertEqual((again['id'], again['times'], again['source']), (first['id'], 2, 'return'))
        self.assertEqual([i['id'] for i in self.client.get('/api/clipboard').json()['items']], [first['id'], second['id']])
        with connect(self.db) as c:
            c.execute("update machines set operational_status='Retired' where id=2")
        fresh = self.client.post(f'/api/clipboard/{second["id"]}/refresh', headers={'x-atlas-token': 'token'}).json()
        self.assertEqual(fresh['machines'][0]['operational_status'], 'Retired', 'Refresh re-reads Atlas')
        self.assertEqual(self.client.delete(f'/api/clipboard/{second["id"]}', headers={'x-atlas-token': 'token'}).json(), {'items': 1})
        self.assertEqual(self.client.delete('/api/clipboard', headers={'x-atlas-token': 'token'}).json(), {'items': 0})
        self.assertEqual(json.loads(self.path.read_text())['items'], [])

    def test_guards_and_limit(self):
        self.assertEqual(self.post('LAPTOP-0001', token='wrong').status_code, 403)
        self.assertEqual(self.post('LAPTOP-0001', source='spy').status_code, 422)
        self.assertEqual(self.post('   ').status_code, 422)
        self.assertEqual(self.client.delete('/api/clipboard/missing', headers={'x-atlas-token': 'token'}).status_code, 404)
        with patch.object(clipboard_history, 'LIMIT', 3):
            for n in range(5):
                self.post(f'note {n}')
        self.assertEqual([i['text'] for i in self.client.get('/api/clipboard').json()['items']], ['note 4', 'note 3', 'note 2'])

    def test_live_inbox_reads_land_in_the_history(self):
        import screen_reader
        screen_reader.remember('please look at LAPTOP-0001', 'inbox')
        self.assertEqual(self.history.load()[0]['machines'][0]['name'], 'LAPTOP-0001')

    def test_hostname_candidates(self):
        self.assertEqual(candidates('LAPTOP-0001, user@x.test GBRPWMF20847950 and words'), {'laptop-0001': 'LAPTOP-0001', 'gbrpwmf20847950': 'GBRPWMF20847950'})


if __name__ == '__main__':
    unittest.main()
