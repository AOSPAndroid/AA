from sqlite_fixture import connect as fixture_connect
"""Excel seating import: real workbook bytes and isolated SQLite data."""
import tempfile, unittest, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.seating import seating_excel as sx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

class SeatingExcel(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'test.db'
  with fixture_connect(self.db) as c:
   c.executescript('''create table records(id text primary key,body text);create table official_records(id text primary key,body text);create table history(seq integer primary key,desk_id text,at text,action text,before_json text,after_json text);create table desk_user_links(desk_id text primary key,user_key text,method text,updated_at text);create table desk_link_history(id integer primary key,desk_id text,at text,action text,before_key text,after_key text);create table users(canonical_key text,user_id text,email text,employee_number text,full_name text);''')
   for i,name in enumerate(('Alice','Bob',''),1):
    d=f'02A{i:06}';r=dict(id=d,floor=2,name=name,team='Rates',occupancy='assigned' if name else 'vacant',kind='desk',x=.1*i,y=.2,angle=180,hostname=f'PC{i}',asset='monitor',notes='physical note',verified=True)
    sx.store.save_record(c,r,None,'fixture')
   for i,name in enumerate(('Alice','Bob','Carol'),1):c.execute('insert into users values(?,?,?,?,?)',(f'key{i}',f'u{i}',f'u{i}@test',str(i),name))
   for i in (1,2):c.execute('insert into desk_user_links values(?,?,?,?)',(f'02A{i:06}',f'key{i}','confirmed','test'))
  self.ids=[f'02A{i:06}' for i in (1,2,3)]
 def tearDown(self):self.temp.cleanup()
 def rows(self,values):
  p=self.root/(str(len(list(self.root.iterdir())))+'.xlsx');p.write_bytes(sx.workbook_bytes(values));return sx.read_sheet(p)
 def plan(self,values,complete=False):
  with fixture_connect(self.db) as c:return sx.plan_sheet(c,self.rows(values),'official',complete)
 def state(self):
  with fixture_connect(self.db) as c:return sx.snapshot(c)
 def test_swap_rename_backup_and_repeat(self):
  a,b,d=self.ids;values=[[a,'Bob','Credit','u2','assigned'],[b,'Alice Renamed','Rates','u1','assigned'],[d,'','','','vacant']]
  before,links=self.state();p=self.plan(values);self.assertFalse(p['report']['errors']);self.assertEqual({x['kind'] for x in p['report']['changes'] if x['desk'] in (a,b)},{'moved'})
  backup=sx.apply_sheet(self.db,p,self.root/'backups','test.xlsx');self.assertTrue((self.root/'backups'/backup).exists())
  now,links=self.state();self.assertEqual(links[a],'key2');self.assertEqual(now[b]['name'],'Alice Renamed')
  for desk in (a,b):
   for field in ('hostname','asset','x','y','angle','notes'):self.assertEqual(now[desk][field],before[desk][field])
   self.assertFalse(now[desk]['verified'])
  self.assertFalse(self.plan(values)['updates'])
  with fixture_connect(self.root/'backups'/backup) as c:self.assertEqual(sx.snapshot(c)[0],before)
 def test_partial_move_auto_vacates_source_and_preserves_other(self):
  a,b,d=self.ids;p=self.plan([[d,'Alice','Rates','u1','assigned']]);self.assertFalse(p['report']['errors']);self.assertEqual(p['report']['auto_vacated'],[a]);self.assertEqual(set(p['updates']),{a,d})
  sx.apply_sheet(self.db,p,self.root/'backups','move.xlsx');r,l=self.state();self.assertEqual(r[a]['occupancy'],'vacant');self.assertEqual(l[d],'key1');self.assertEqual(l[b],'key2')
 def test_omitted_users_partial_vs_complete_and_new_name(self):
  a,b,d=self.ids;values=[[d,'New Joiner','Team','','assigned']];p=self.plan(values);self.assertNotIn(a,p['updates']);self.assertTrue(p['report']['warnings']);self.assertFalse(p['report']['errors'])
  p=self.plan(values,True);self.assertEqual(p['updates'][a]['record']['occupancy'],'vacant');self.assertEqual(p['updates'][b]['record']['occupancy'],'vacant')
 def test_conflicts(self):
  a,b,d=self.ids
  for values in ([[a,'A','','u1','assigned'],[a,'B','','u2','assigned']],[['BAD','A','','','assigned']],[[a,'Unknown','','missing','assigned']],[[a,'Alice','','u1','vacant']]):
   self.assertTrue(self.plan(values)['report']['errors'],values)
 def test_duplicates_follow_the_excel(self):
  # The same person on two desks in the sheet is placed on both, with a warning, not a blocking error.
  a,b,d=self.ids;p=self.plan([[a,'Alice','','u1','assigned'],[d,'Alice','','u1','assigned']])
  self.assertFalse(p['report']['errors']);self.assertEqual(p['updates'][d]['link'],'key1');self.assertEqual((p['updates'][a]['record']['name'],p['updates'][a]['record']['occupancy']),('Alice','assigned'),'Alice keeps her first desk too')
  self.assertTrue(any('Same person on' in w and 'placed on each' in w for w in p['report']['warnings']))
 def test_stale_preview_and_atomic_rollback(self):
  a,b,d=self.ids;p=self.plan([[d,'Alice','Rates','u1','assigned']]);before=self.state()
  original=sx.store.save_record;calls=[]
  def fail(*args):
   calls.append(1)
   if len(calls)==2:raise RuntimeError('write failed')
   return original(*args)
  with patch.object(sx.store,'save_record',fail):
   with self.assertRaises(RuntimeError):sx.apply_sheet(self.db,p,self.root/'backups','test.xlsx')
  self.assertEqual(self.state(),before)
  with fixture_connect(self.db) as c:c.execute("update users set full_name='new' where canonical_key='key1'")
  with self.assertRaises(sx.store.Conflict):sx.apply_sheet(self.db,p,self.root/'backups','test.xlsx')
 def test_roundtrip_and_formula_rejection(self):
  with fixture_connect(self.db) as c:
   r=sx.store.get_record(c,self.ids[2]);sx.store.save_record(c,dict(r,team='Unassigned'),r,'fixture')
  path=self.root/'roundtrip.xlsx';path.write_bytes(sx.export_sheet(self.db,'official'))
  with fixture_connect(self.db) as c:p=sx.plan_sheet(c,sx.read_sheet(path));self.assertFalse(p['updates']);self.assertFalse(p['report']['errors'])
  import io,zipfile
  out=io.BytesIO()
  with zipfile.ZipFile(path) as source,zipfile.ZipFile(out,'w') as target:
   for name in source.namelist():target.writestr(name,source.read(name).replace(b'</sheetData>',b'<row r="5"><c r="A5"><f>1+1</f><v>2</v></c></row></sheetData>') if name.endswith('sheet1.xml') else source.read(name))
  path.write_bytes(out.getvalue())
  with self.assertRaises(ValueError):sx.read_sheet(path)
 def test_api_guards_preview_apply_history(self):
  app=FastAPI();w=SimpleNamespace(MASTER_DB=self.db,jobs={},queue_jobs={})
  def token(r):
   if r.headers.get('x-atlas-token')!='test':raise HTTPException(403,'token')
  sx.register_seating_excel(app,w,token,lambda:bool(w.jobs));cli=TestClient(app);headers={'x-atlas-token':'test'};data=sx.workbook_bytes([[self.ids[2],'Carol','Rates','u3','assigned']])
  self.assertEqual(cli.post('/api/seating-excel/preview',content=data).status_code,403)
  w.jobs['test']={};self.assertEqual(cli.post('/api/seating-excel/preview',content=data,headers=headers).status_code,409);w.jobs.clear()
  r=cli.post('/api/seating-excel/preview',content=data,headers=headers);self.assertEqual(r.status_code,200,r.text);id=r.json()['id']
  self.assertEqual(cli.post('/api/seating-excel/apply/'+id,json={},headers=headers).status_code,400)
  r=cli.post('/api/seating-excel/apply/'+id,json={'confirmation':'APPLY'},headers=headers);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(len(cli.get('/api/seating-excel/history').json()),1)
  self.assertEqual(cli.post('/api/seating-excel/apply/'+id,json={'confirmation':'APPLY'},headers=headers).status_code,409)
  r=cli.post('/api/seating-excel/preview',content=data,headers=headers);self.assertIsNone(r.json()['id'])
if __name__=='__main__':unittest.main()
