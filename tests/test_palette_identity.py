"""Palette merging uses verified desk identities, never names from a result page."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.directory.directory_workbook import schema
from backend.directory.desk_directory import palette_search, people_desks, person_desks
from backend.directory.directory_lookup import prepare_views, search_directory


class PaletteIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'identity.db'
        c = sqlite3.connect(self.path)
        try:
            schema(c)
            c.executescript('''
                create table official_records(id text primary key,body text);
                create table official_seating_mappings(legacy_id text primary key,official_id text);
                create table desk_user_links(desk_id text primary key,user_key text);
            ''')
            names = ['Unique Person', 'Confirmed Person', 'Duplicate Person', 'Duplicate Person',
                     'Conflict Person', 'Different Person', 'Legacy Conflict', 'No Desk', 'Élodie Martin']
            names += ['Result Person '+str(number) for number in range(12)]
            c.executemany('''insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm)
                values(?,?,?,?,?,?)''', [(index, 'uid:g'+str(index), 'G'+str(index), 'g'+str(index), name, name.casefold())
                                       for index, name in enumerate(names, 1)])
            desks = [('UNIQUE', 'PERSON UNIQUE'), ('CONFIRMED', 'Different desk label'),
                     ('DUPLICATE', 'Duplicate Person'), ('CONFLICT', 'Conflict Person'),
                     ('LEGACY-CONFLICT', 'Legacy Conflict'), ('UNICODE', 'MARTIN ÉLODIE'),
                     ('VACANT', 'No Desk')]
            c.executemany('insert into official_records values(?,?)',
                          [(key, json.dumps({'id': key, 'floor': 4, 'name': name,
                                             'occupancy': 'vacant' if key == 'VACANT' else 'assigned'}))
                           for key, name in desks])
            c.executemany('insert into official_seating_mappings values(?,?)',
                          [('OLD-CONFIRMED', 'CONFIRMED'), ('OLD-CONFLICT', 'LEGACY-CONFLICT')])
            c.executemany('insert into desk_user_links values(?,?)',
                          [('OLD-CONFIRMED', 'uid:g2'), ('CONFLICT', 'uid:g6'), ('OLD-CONFLICT', 'uid:g6')])
            c.commit()
        finally:
            c.close()
        self.c = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        self.addCleanup(self.c.close)
        self.c.row_factory = sqlite3.Row
        prepare_views(self.c)
        self.c.execute('pragma query_only=on')

    def person(self, uid):
        return self.c.execute('select * from legacy_users where id=?', (uid,)).fetchone()

    def test_confirmed_and_globally_unique_names_keep_their_provenance(self):
        self.assertEqual(person_desks(self.c, self.person(1)),
                         [{'id': 'UNIQUE', 'floor': 4, 'match': 'matching name; account not confirmed'}])
        self.assertEqual(person_desks(self.c, self.person(2)),
                         [{'id': 'CONFIRMED', 'floor': 4, 'match': 'confirmed account link'}])
        self.assertEqual(person_desks(self.c, self.person(9))[0]['id'], 'UNICODE')
        self.assertEqual(person_desks(self.c, self.person(1), suggestions=False), [])

    def test_ambiguous_names_and_other_account_links_cannot_be_merged(self):
        # Both duplicate accounts must remain distinct even when only one is searched.
        for uid in (3, 4, 5, 7, 8):
            with self.subTest(uid=uid):
                self.assertEqual(person_desks(self.c, self.person(uid)), [])
                enriched = palette_search(self.c, search_directory(self.c, 'user:G'+str(uid)))
                self.assertEqual(enriched['users'][0]['palette_desks'], [])
        self.assertEqual({desk['id'] for desk in person_desks(self.c, self.person(6))},
                         {'CONFLICT', 'LEGACY-CONFLICT'})

    def test_conflicting_explicit_legacy_and_official_links_are_not_inferred(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('insert into desk_user_links values(?,?)', ('CONFIRMED', 'uid:g1'))
            c.commit()
        matches = people_desks(self.c, [self.person(1), self.person(2)])
        self.assertNotIn('CONFIRMED', [desk['id'] for desks in matches.values() for desk in desks])

    def test_enrichment_is_bounded_and_does_not_mutate_cached_search_results(self):
        original = search_directory(self.c, 'Result Person')
        before = copy.deepcopy(original)
        statements = []
        self.c.set_trace_callback(statements.append)
        enriched = palette_search(self.c, original)
        self.c.set_trace_callback(None)
        self.assertEqual(original, before)
        self.assertEqual(len(enriched['users']), 12)
        self.assertTrue(all(user['palette_desks'] == [] for user in enriched['users'][:10]))
        self.assertTrue(all('palette_desks' not in user for user in enriched['users'][10:]))
        reads = [statement for statement in statements if statement.lstrip().lower().startswith('select')]
        self.assertLessEqual(len(reads), 3, 'enrichment must batch directory and desk reads')
        self.assertTrue(all(new is not old for new, old in zip(enriched['users'], original['users'])))

    def test_global_user_without_a_candidate_desk_skips_directory_name_scan(self):
        person = self.person(10)
        statements = []
        self.c.set_trace_callback(statements.append)
        self.assertEqual(person_desks(self.c, person), [])
        self.c.set_trace_callback(None)
        self.assertFalse(any('select full_name from users' in statement.lower() for statement in statements))

    def test_optional_admin_and_demo_enrichment_and_fresh_resolution_agree(self):
        from backend import main, viewer
        before = self.path.read_bytes()
        responses = []
        with patch.object(main, 'MASTER_DB', self.path), patch.object(viewer, 'DB', self.path), \
                patch.object(main.job_service, 'recover'):
            for app in (main.app, viewer.app):
                with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)) as client:
                    plain = client.get('/api/search', params={'term': 'Unique Person'})
                    self.assertEqual(plain.status_code, 200)
                    self.assertEqual(plain.headers['cache-control'], 'no-store')
                    self.assertNotIn('palette_desks', plain.json()['users'][0])
                    enriched = client.get('/api/search', params={'term': 'Unique Person', 'palette': 'true'})
                    self.assertEqual(enriched.status_code, 200)
                    self.assertEqual(enriched.headers['cache-control'], 'no-store')
                    response = enriched.json()
                    self.assertEqual(response['users'][0]['palette_desks'],
                                     client.get('/api/palette/person/id:1').json()['desks'])
                    self.assertEqual(client.get('/api/palette/person/id:3').json()['desks'], [])
                    self.assertEqual(client.get('/api/palette/person/id:7').json()['desks'], [])
                    self.assertEqual(client.get('/api/search', params={'term': 'Unique Person'}).json(), plain.json())
                    responses.append(response)
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
