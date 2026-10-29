from sqlite_fixture import connect as fixture_connect
import unittest,tempfile,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from backend import atlas_store as store
from backend.seating.official_atlas import register_official
class OfficialAtlas(unittest.TestCase):
 def test_register_and_explicit_mapping_preserve_previous(self):
  before_db=store.DB
  with tempfile.TemporaryDirectory() as tmp:
   db=Path(tmp)/'test.db'
   with fixture_connect(before_db) as a,fixture_connect(db) as b:a.backup(b)
   store.DB=db
   try:
    app=FastAPI()
    def token(r):
     if r.headers.get('x-atlas-token')!='test':raise HTTPException(403,'token')
    register_official(app,SimpleNamespace(),token);c=TestClient(app)
    with fixture_connect(db) as con:
     old=store.get_record(con,'L4-089');target=store.get_record(con,'04R021071');self.assertEqual(con.execute('select count(*) from official_records').fetchone()[0],620)
    body={'source':old['id'],'target':target['id'],'sourceRevision':old['revision'],'targetRevision':target['revision']}
    self.assertEqual(c.post('/api/official/map-occupant',json=body).status_code,403)
    r=c.post('/api/official/map-occupant',json=body,headers={'x-atlas-token':'test'});self.assertEqual(r.status_code,200,r.text)
    with fixture_connect(db) as con:
     self.assertEqual(store.get_record(con,old['id']),old);new=store.get_record(con,target['id']);self.assertEqual(new['name'],old['name']);self.assertEqual(new['x'],target['x']);self.assertFalse(new['verified'])
    self.assertEqual(c.post('/api/official/map-occupant',json=body,headers={'x-atlas-token':'test'}).status_code,409)
   finally:store.DB=before_db
if __name__=='__main__':unittest.main()
