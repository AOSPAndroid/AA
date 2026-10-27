from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest
from fastapi.testclient import TestClient
from backend import main,viewer

class PaletteTests(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(main.app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
 def tearDown(self):self.client.close()
 def test_confirmed_person_resolves_official_desks(self):
  with main.db() as c:
   person=c.execute('select id from legacy_users where canonical_key in (select user_key from desk_user_links where desk_id="04R024065")').fetchone()
  self.assertIsNotNone(person)
  response=self.client.get('/api/palette/person/id:'+str(person[0]));self.assertEqual(response.status_code,200)
  rows=response.json()['desks'];self.assertIn('04R024065',[r['id'] for r in rows]);self.assertTrue(all(not r['id'].startswith('L') for r in rows))
  self.assertTrue(all(r['match']=='confirmed account link' for r in rows))
 def test_bad_or_missing_person(self):
  self.assertEqual(self.client.get('/api/palette/person/id:999999999').status_code,404)
  self.assertEqual(self.client.get('/api/palette/person/not-an-id').status_code,400)
 def test_removed_assistant_has_no_registered_or_accessible_routes(self):
  for app in (main.app,viewer.app):
   self.assertFalse(any(getattr(route,'path','').startswith('/api/assistant/') for route in app.routes))
  self.assertEqual(self.client.get('/api/assistant/status').status_code,404)
  self.assertEqual(self.client.post('/api/assistant/ask',json={'question':'Hello'}).status_code,404)
  with TestClient(viewer.app) as client:
   self.assertEqual(client.get('/api/assistant/status').status_code,404)
   # The viewer rejects all POSTs before routing, including nonexistent paths.
   self.assertEqual(client.post('/api/assistant/ask',json={'question':'Hello'}).status_code,403)
 def test_admin_assets_and_remote_boundary(self):
  for path in ('/command-palette.js','/command-palette.css','/command-registry.js','/catalogue.js'):
   self.assertEqual(self.client.get(path).status_code,200)
  with TestClient(main.app,base_url='http://127.0.0.1',client=('192.0.2.10',12345)) as remote:
   self.assertEqual(remote.get('/api/palette/person/id:1').status_code,403)
 def test_viewer_shares_palette_reads_without_admin_routes(self):
  with TestClient(viewer.app) as client:
   for path in ('/command-palette.js','/command-palette.css','/command-registry.js'):
    self.assertEqual(client.get(path).status_code,200)
   with main.db() as c:
    person=c.execute('select id from legacy_users where canonical_key in (select user_key from desk_user_links where desk_id="04R024065")').fetchone()
   path='/api/palette/person/id:'+str(person[0])
   self.assertEqual(client.get(path).json(),self.client.get(path).json())
   self.assertEqual(client.get('/api/palette/person/not-an-id').status_code,400)
   self.assertEqual(client.get('/api/palette/person/id:999999999').status_code,404)
   # Demo serves Admin's map code (operations.js) but none of its routes.
   for path in ('/api/session','/viewer.js','/api/preflight/PC1','/api/desks/04R024065/deploy','/api/ops/settings'):
    self.assertEqual(client.get(path).status_code,404)

if __name__=='__main__':unittest.main()
