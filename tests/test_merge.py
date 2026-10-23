"""Shared database tests. All deployment workers are stubbed; no remote actions run."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import main as m
import atlas_store
from merge_data import import_atlas,merge_directory
from fastapi.testclient import TestClient

class MergedAtlas(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.original=m.MASTER_DB;cls.original_repo=m.REPO
  cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)
  cls.db=cls.base/'shared.db';src=sqlite3.connect(cls.original);dst=sqlite3.connect(cls.db);src.backup(dst);src.close();dst.close()
  m.MASTER_DB=m.DB=m.HISTORY_DB=atlas_store.DB=cls.db
  m.REPO=cls.base/'packages';m.REPO.mkdir();pkg=m.REPO/'Example';pkg.mkdir();(pkg/'app_i.ps1').write_text('exit 0')
  cls.client=TestClient(m.app,base_url='http://127.0.0.1',client=('127.0.0.1',42000))
  cls.token=cls.client.get('/api/state').json()['token'];cls.headers={'X-Atlas-Token':cls.token}
  cls.operator=patch.object(m,'identity',return_value='TEST OPERATOR');cls.operator.start()
 @classmethod
 def tearDownClass(cls):
  cls.client.close();cls.operator.stop();m.MASTER_DB=m.DB=m.HISTORY_DB=atlas_store.DB=cls.original;m.REPO=cls.original_repo;cls.tmp.cleanup()
 def post(self,path,data):return self.client.post(path,headers=self.headers,json=data)
 def create_desk(self,slug,occupancy='assigned',name='Fixture Person',hostname=''):
  item={'id':'custom-'+slug,'floor':3,'x':0.5,'y':0.5,'angle':90,'kind':'desk','occupancy':occupancy,'name':name,'team':'Fixture','hostname':hostname,'revision':0}
  r=self.post('/api/save',{'records':[item]});self.assertEqual(r.status_code,200,r.text)
  return next(x for x in r.json()['records'] if x['id']==item['id'])
 def pick_user(self):
  with m.db() as c:return dict(c.execute('select * from legacy_users where id in (select user_id_ref from assignments) limit 1').fetchone())
 def test_01_counts_and_routes(self):
  r=self.client.get('/api/state');self.assertEqual(len(r.json()['records']),524)
  with m.db() as c:
   for t,n in [('users',18739),('machines',69289),('assignments',31557),('deployments',22)]:self.assertEqual(c.execute('select count(*) from '+t).fetchone()[0],n)
  for url in ['/','/official-app.js','/map-plan-details.js','/camera-motion.js','/operations.js','/operations.css','/installer','/assets/atlas-theme.css','/api/history','/api/ops/settings']:
   self.assertEqual(self.client.get(url).status_code,200)
  self.assertEqual(self.client.get('/office_atlas.db').status_code,404)
 def test_02_all_assigned_desks_resolve(self):
  counts={}
  for r in self.client.get('/api/state').json()['records']:
   if r['kind']=='desk' and r['occupancy']=='assigned':
    response=self.client.get('/api/desks/'+r['id']+'/context');self.assertEqual(response.status_code,200)
    x=response.json();counts[x['match_method']]=counts.get(x['match_method'],0)+1
    if x['match_method']=='ambiguous':self.assertIsNone(x['user'])
  self.assertEqual(counts,{'name-match':189,'unmatched':46,'ambiguous':2,'confirmed':6})
 def test_unconfirmed_sabri_matches_console_and_keeps_seating_status(self):
  ctx=self.client.get('/api/desks/L3-093/context').json()
  self.assertEqual(ctx['desk']['occupancy'],'unconfirmed')
  self.assertEqual(ctx['match_method'],'unconfirmed-name-match')
  self.assertEqual(ctx['user']['canonical_key'],'uid:eljailas')
  console=self.client.get('/api/user/id:'+str(ctx['user']['id'])).json()
  self.assertEqual({x['name'] for x in ctx['machines']},{x['name'] for x in console['machines']})
  self.assertEqual(len(ctx['machines']),8)
  vacant=self.create_desk('vacant-sabri','vacant','Sabri El Jailani')
  result=self.client.get('/api/desks/'+vacant['id']+'/context').json()
  self.assertIsNone(result['user']);self.assertEqual(result['machines'],[])
 def test_unconfirmed_ambiguous_is_not_selected(self):
  assigned=next(r for r in self.client.get('/api/state').json()['records'] if r['kind']=='desk' and r['occupancy']=='assigned' and self.client.get('/api/desks/'+r['id']+'/context').json()['match_method']=='ambiguous')
  fixture=self.create_desk('ambiguous-unconfirmed','unconfirmed',assigned['name'])
  ctx=self.client.get('/api/desks/'+fixture['id']+'/context').json()
  self.assertEqual(ctx['match_method'],'ambiguous');self.assertIsNone(ctx['user']);self.assertEqual(ctx['machines'],[])
 def test_03_link_move_vacate_and_revision(self):
  u=self.pick_user();a=self.create_desk('move-source',hostname='SOURCEPC');b=self.create_desk('move-target','vacant',hostname='TARGETPC')
  r=self.post('/api/desks/'+a['id']+'/link',{'user_key':u['canonical_key'],'revision':a['revision']});self.assertEqual(r.status_code,200);a=r.json()['desk']
  bad=self.post('/api/move',{'source':a['id'],'target':b['id'],'sourceRevision':0,'targetRevision':b['revision']});self.assertEqual(bad.status_code,409)
  r=self.post('/api/move',{'source':a['id'],'target':b['id'],'sourceRevision':a['revision'],'targetRevision':b['revision']});self.assertEqual(r.status_code,200)
  ctx=self.client.get('/api/desks/'+b['id']+'/context').json();self.assertEqual(ctx['user']['canonical_key'],u['canonical_key']);self.assertEqual(ctx['desk']['hostname'],'TARGETPC');self.assertEqual(ctx['match_method'],'confirmed')
  self.assertIsNone(self.client.get('/api/desks/'+a['id']+'/context').json()['user'])
  r=self.post('/api/vacate',{'id':b['id'],'revision':ctx['desk']['revision']});self.assertEqual(r.status_code,200)
  self.assertIsNone(self.client.get('/api/desks/'+b['id']+'/context').json()['user'])
 def test_04_deployment_snapshot_and_target_validation(self):
  u=self.pick_user();a=self.create_desk('deploy');linked=self.post('/api/desks/'+a['id']+'/link',{'user_key':u['canonical_key'],'revision':a['revision']}).json();pc=linked['machines'][0]['name']
  body={'revision':linked['desk']['revision'],'user_key':u['canonical_key'],'computer':pc,'folder':'Example','script':'app_i.ps1','action':'Install','mode':'full'}
  with patch.object(m.threading,'Thread') as thread:
   r=self.post('/api/desks/'+a['id']+'/deploy',{**body,'computer':'UNRELATEDPC'});self.assertEqual(r.status_code,400);thread.assert_not_called()
   r=self.post('/api/desks/'+a['id']+'/deploy',{**body,'revision':0});self.assertEqual(r.status_code,409);thread.assert_not_called()
   r=self.post('/api/desks/'+a['id']+'/deploy',{**body,'user_key':'wrong'});self.assertEqual(r.status_code,409);thread.assert_not_called()
   r=self.post('/api/desks/'+a['id']+'/deploy',body);self.assertEqual(r.status_code,200,r.text);thread.return_value.start.assert_called_once();job=r.json()['job']
  with m.db() as c:
   row=c.execute('select * from desk_deployments where job_id=?',(job,)).fetchone();self.assertEqual(row['desk_id'],a['id']);self.assertEqual(row['user_key'],u['canonical_key'])
  self.assertTrue(self.client.get('/api/desks/'+a['id']+'/context').json()['deployments'])
 def test_05_preview_and_token(self):
  r=self.client.get('/api/package-script',params={'package':'Example','script':'app_i.ps1'});self.assertEqual(r.json()['content'],'exit 0')
  self.assertEqual(self.client.get('/api/package-script',params={'package':'Example','script':'../bad.ps1'}).status_code,400)
  self.assertEqual(self.client.post('/api/save',json={'records':[]}).status_code,403)
 def test_06_backup_is_unified(self):
  r=self.client.get('/api/backup');self.assertEqual(r.status_code,200);file=self.base/'backup.db';file.write_bytes(r.content)
  c=sqlite3.connect(file)
  try:
   tables={x[0] for x in c.execute("select name from sqlite_master where type='table'")};self.assertTrue({'users','machines','assignments','records','history','deployments','desk_user_links','desk_deployments'}<=tables);self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')
  finally:c.close()
 def test_07_refresh_preserves_seating_history_links(self):
  with m.db() as c:
   before={t:c.execute('select count(*) from '+t).fetchone()[0] for t in ('records','history','deployments','desk_user_links')}
  merge_directory(self.db,self.original)
  with m.db() as c:
   for t,n in before.items():self.assertEqual(c.execute('select count(*) from '+t).fetchone()[0],n)
 def test_08_import_old_atlas_backup(self):
  source=self.base/'old-atlas.db';c=sqlite3.connect(source);c.executescript('create table records(id text primary key,body text);create table history(seq integer primary key,desk_id text,at text,action text,before_json text,after_json text);')
  r={'id':'custom-imported','floor':4,'x':0.2,'y':0.4,'angle':180,'kind':'desk','occupancy':'assigned','name':'Imported Person','team':'Example','revision':4}
  c.execute('insert into records values(?,?)',(r['id'],json.dumps(r)));c.execute('insert into history(desk_id,at,action,before_json,after_json) values(?,?,?,?,?)',(r['id'],'2026-01-01','old edit',None,json.dumps(r)));c.commit();c.close()
  n=import_atlas(self.db,source);self.assertEqual(n['imported'],1);self.assertTrue(import_atlas(self.db,source)['already_imported'])
  ctx=self.client.get('/api/desks/'+r['id']+'/context').json();self.assertEqual(ctx['desk']['name'],'Imported Person')
  with m.db() as c:self.assertEqual(c.execute('select count(*) from users').fetchone()[0],18739)


 def test_09_review_queue_is_read_only_and_finds_duplicates(self):
  a=self.create_desk('audit-one',name='Sabri El Jailani',hostname='DUPLICATEPC')
  b=self.create_desk('audit-two',name='Sabri El Jailani',hostname='DUPLICATEPC')
  with m.db() as c:before=[tuple(r) for r in c.execute('select id,body from records order by id')]
  response=self.client.get('/api/ops/audit');self.assertEqual(response.status_code,200)
  rows={e['desk']['id']:e for e in response.json()['rows']}
  self.assertIn('person-as-area',rows['L3-093']['issues'])
  for r in [a,b]:
   self.assertIn('duplicate-person',rows[r['id']]['issues']);self.assertIn('duplicate-hostname',rows[r['id']]['issues'])
  with m.db() as c:self.assertEqual(before,[tuple(r) for r in c.execute('select id,body from records order by id')])
 def test_10_machine_groups_retain_all_relationships(self):
  ctx=self.client.get('/api/desks/L3-093/context').json();self.assertEqual(len(ctx['machines']),8)
  self.assertTrue(any(m['assigned_relationship'] for m in ctx['machines']))
  self.assertTrue(any(m['logon_relationship'] for m in ctx['machines']))
  assigned=[bool(row['assigned_relationship']) for row in ctx['machines']]
  self.assertEqual(assigned,sorted(assigned,reverse=True))
  user_machines=self.client.get('/api/user/id:'+str(ctx['user']['id'])).json()['machines']
  assigned=[bool(row['assigned_relationship']) for row in user_machines]
  self.assertEqual(assigned,sorted(assigned,reverse=True))
  pc=ctx['machines'][0]['name'];fixture=self.create_desk('group-overlap',name='Sabri El Jailani',hostname=pc)
  merged=self.client.get('/api/desks/'+fixture['id']+'/context').json()['machines']
  self.assertEqual(len(merged),8)
  match=next(m for m in merged if m['name']==pc)
  self.assertTrue(match['desk_equipment']);self.assertEqual(match['relationship_group'],'Assigned to user' if match['assigned_relationship'] else 'Desk equipment')
  self.assertIn('inventory_discovered_at',match)
 def test_11_catalog_metadata_scripts_and_revision(self):
  pkg=m.REPO/'Example';(pkg/'remove_u.vbs').write_text('test')
  result=self.client.get('/api/catalog/details',params={'folder':'Example'}).json()
  self.assertIn('app_i.ps1',result['scripts']['Install']);self.assertIn('remove_u.vbs',result['scripts']['Uninstall']);self.assertEqual(result['revision'],0)
  body={'folder':'Example','display_name':'Example Friendly App','version':'2.0','revision':0}
  self.assertEqual(self.client.post('/api/catalog/metadata',json=body).status_code,403)
  self.assertEqual(self.post('/api/catalog/metadata',body).status_code,200)
  self.assertEqual(self.post('/api/catalog/metadata',body).status_code,409)
  found=self.client.get('/api/catalog',params={'term':'Friendly'}).json()['items'];self.assertEqual(found[0]['folder'],'Example');self.assertEqual(found[0]['version'],'2.0')
  self.assertEqual(self.client.get('/api/catalog/details',params={'folder':'../outside'}).status_code,400)
  from package_catalog import inspect_package
  self.assertFalse(inspect_package(pkg,limit=1)['complete'])

 def test_11a_catalog_enrichment_excludes_raw_records_and_source_payloads(self):
  import package_data as data
  rows,_=data.parse_csv(b'name,state,custom_note\nExample,Live,Original one\nExample,Live,Original two\n../Example,Work in Progress,Keep literal path\n')
  columns=['name_key',*data.FIELDS,*data.SOURCE_FIELDS,'source','imported_at']
  with atlas_store.connect() as c:
   data.initialize(c)
   for row in rows.values():
    item={**row,'source':'fictional.csv','imported_at':'2026-10-05'}
    c.execute(f"insert or replace into package_data({','.join(columns)}) values({','.join('?' for _ in columns)})",tuple(item[column] for column in columns))
  response=self.client.get('/api/catalog/details',params={'folder':'Example'})
  self.assertEqual(response.status_code,200,response.text)
  info=response.json()['package_data'];self.assertEqual(info['state'],'Live')
  for field in data.SOURCE_FIELDS:self.assertNotIn(field,info)
  catalog=self.client.get('/api/catalog').json()['items']
  self.assertEqual([row['folder'] for row in catalog],['Example'])
  self.assertEqual(catalog[0]['state'],'Live')
  raw=self.client.get('/api/package-data',params={'term':'../Example'}).json()['items']
  self.assertEqual(len(raw),1);self.assertEqual(raw[0]['folder'],'');self.assertFalse(raw[0]['source_present'])
  self.assertEqual(self.client.get('/api/catalog/details',params={'folder':'../Example'}).status_code,400)

 def test_12_refresh_backup_preserves_catalogue_and_paris(self):
  from refresh_directory import apply_refresh
  with m.db() as c:
   before={t:[tuple(r) for r in c.execute('select * from '+t)] for t in ('records','history','desk_user_links','deployments','package_catalog')}
  backup=apply_refresh(self.db,self.original,self.base/'backups')
  self.assertTrue(backup.is_file())
  with m.db() as c:
   for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in c.execute('select * from '+t)])
  with sqlite3.connect(backup) as c:
   self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')
   self.assertEqual(c.execute('select version from package_catalog where folder="Example"').fetchone()[0],'2.0')

if __name__=='__main__':unittest.main()
