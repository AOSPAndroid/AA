"""No remote Windows commands are executed by this suite."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import base64,json,re,sqlite3,sys,tempfile,unittest,uuid,zlib
from pathlib import Path
from install_fixture import finished
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import main as app
import install_watch
from fastapi.testclient import TestClient
from identity_links import build_index,candidates

class Regression(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)
  cls.original_history=app.HISTORY_DB;cls.original_repo=app.REPO
  app.HISTORY_DB=cls.base/'history.db';app.REPO=cls.base/'repo';app.REPO.mkdir()
  cls.pkg=app.REPO/'Example';cls.pkg.mkdir();(cls.pkg/'setup_i.ps1').write_text('exit 0')
  cls.identity=patch.object(app,'identity',return_value='TEST OPERATOR');cls.identity.start()
  cls.client=TestClient(app.app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
  with app.master_db() as c:
   cls.user=dict(c.execute("select * from users where user_id<>'' and email<>'' and id in (select user_id_ref from assignments) limit 1").fetchone())
   cls.machine=c.execute('select machine_name from machines where id in (select machine_id from assignments) limit 1').fetchone()[0]
 @classmethod
 def tearDownClass(cls):
  cls.client.close();cls.identity.stop();app.HISTORY_DB=cls.original_history;app.REPO=cls.original_repo;cls.tmp.cleanup()
 def test_repository_listing_and_unavailable(self):
  response=self.client.get('/api/packages',params={'term':'example'}).json()
  self.assertEqual(response['packages'],['Example']);self.assertTrue(response['available'])
  for name,action in [('remove_u.vbs','Uninstall'),('fix_r.ps1','Repair')]:
   path=self.pkg/name;path.write_text('test')
   try:self.assertIn(name,self.client.get('/api/scripts',params={'package':'Example','action':action}).json()['scripts'])
   finally:path.unlink()
  with patch.object(app,'REPO',self.base/'missing'):
   response=self.client.get('/api/packages').json();self.assertFalse(response['available']);self.assertIn('error',response)
  with patch.object(Path,'iterdir',side_effect=PermissionError('denied')):
   response=self.client.get('/api/packages').json();self.assertFalse(response['available']);self.assertEqual(response['packages'],[])
 def test_lookup_id_email_name_employee_domain(self):
  for term in [self.user['user_id'],self.user['email'],self.user['full_name'],self.user['employee_number'],'TEST\\'+self.user['user_id']]:
   with self.subTest(kind='identity'):
    r=self.client.get('/api/search',params={'term':term});self.assertEqual(r.status_code,200)
    self.assertIn(self.user['id'],[u['id'] for u in r.json()['users']])
 def test_user_machine_links(self):
  r=self.client.get('/api/user/id:'+str(self.user['id']));self.assertEqual(r.status_code,200);self.assertTrue(r.json()['machines'])
 def test_partial_and_literal_search(self):
  self.assertTrue(self.client.get('/api/search',params={'term':self.user['full_name'][:4]}).json()['users'])
  for q in ['','%','not-present-unique-938291']:
   r=self.client.get('/api/search',params={'term':q});self.assertEqual(r.status_code,200);self.assertFalse(r.json()['users'])
 def test_current_directory_and_master_routes(self):
  from urllib.parse import quote
  paths=['/api/health','/api/master/status','/api/database-freshness','/api/master/resolve/'+quote(self.user['user_id']),'/api/master/resolve/'+quote(self.machine)]
  for path in paths:
   r=self.client.get(path);self.assertEqual(r.status_code,200);self.assertNotIn('error',r.json())
  person=self.client.get('/api/user/id:'+str(self.user['id'])).json()
  self.assertEqual(person['user']['canonical_key'],self.user['canonical_key'])
  self.assertEqual(person['user']['full_name'],self.user['full_name'])
  self.assertTrue(person['machines']);self.assertIn('match_type',person['machines'][0])
  machine=self.client.get('/api/search',params={'term':'machine:'+self.machine}).json()['machines'][0]
  self.assertEqual(machine['machine_name'],self.machine)
  for field in ('model_id','serial_number','operational_status'):self.assertIn(field,machine)
 def test_retired_duplicate_directory_routes_are_unregistered(self):
  self.assertFalse(any(getattr(route,'path','').startswith(('/api/daas/','/api/v2814/')) for route in app.app.routes))
  with patch.object(app,'db') as db,patch.object(app,'ps') as powershell:
   for path in ('/api/daas/status','/api/daas/user/example','/api/daas/machine/TESTPC','/api/v2814/reverse/TESTPC'):
    self.assertEqual(self.client.get(path).status_code,404)
   self.assertEqual(self.client.post('/api/daas/machines',json={'computers':['TESTPC']}).status_code,404)
   db.assert_not_called();powershell.assert_not_called()
 def test_previous_map_bookmark_redirects_without_retired_image_routes(self):
  response=self.client.get('/legacy-atlas',follow_redirects=False)
  self.assertEqual(response.status_code,307);self.assertEqual(response.headers['location'],'/')
  self.assertEqual(self.client.get('/legacy-atlas').status_code,200)
  for floor in range(2,8):self.assertEqual(self.client.get('/floor-'+str(floor)+'.jpg').status_code,404)
 def test_identity_ambiguity_never_guessed(self):
  c=sqlite3.connect(':memory:')
  c.executescript('create table users(id,user_id,email,employee_number,full_name);create table user_aliases(user_id_ref,alias_norm,alias_type);')
  c.executemany('insert into users values(?,?,?,?,?)',[(1,'one','one@test','E1','Same Name'),(2,'two','two@test','E2','Same Name')])
  index=build_index(c);self.assertEqual(candidates(index,'Same Name'),{1,2});self.assertEqual(candidates(index,'DOMAIN\\one'),{1});self.assertEqual(candidates(index,'one@test'),{1});self.assertFalse(candidates(index,'one@other'))
  c.close()
 def test_history_round_trip(self):
  j=uuid.uuid4().hex;app.history_create(j,'TESTPC','Example','Install','setup_i.ps1','full');app.history_update(j,state='failed',exit_code='1603')
  rows=app.history();self.assertTrue(any(x['id']==j and x['exit_code']=='1603' for x in rows))
 def test_deployment_validation(self):
  for folder,script in [('../outside','setup_i.ps1'),('Example','../setup_i.ps1'),('Example','setup_u.ps1'),('Example','missing_i.ps1')]:
   r=self.client.post('/api/deploy',json={'computer':'TESTPC','folder':folder,'script':script});self.assertEqual(r.status_code,400)
  self.assertEqual(self.client.post('/api/bulk/deploy',json={'computers':[],'folder':'Example','script':'setup_i.ps1'}).status_code,422)
  self.assertEqual(self.client.get('/api/job/not-found').status_code,404)
 def test_local_origin_boundaries(self):
  self.assertEqual(self.client.post('/api/deploy',headers={'Origin':'https://other.example'},json={}).status_code,403)
  self.assertEqual(self.client.get('/api/history',headers={'Host':'other.example'}).status_code,403)
 def test_performance_routes_and_validation(self):
  sample={'ok':True,'items':[],'summary':{'memory_percent':50}}
  with patch.object(app,'run',return_value=type('Result',(),{'stdout':json.dumps(sample)})()) as remote:
   response=self.client.get('/api/performance/TESTPC?kind=memory')
   self.assertEqual(response.status_code,200);self.assertEqual(response.json()['summary']['memory_percent'],50)
   response=self.client.get('/api/performance/TESTPC?kind=diagnose')
   self.assertEqual(response.status_code,200);self.assertEqual(remote.call_args.args[0][-1],'diagnose')
   response=self.client.get('/api/performance/TESTPC/threads/42',params={'created':'20260910100000.000000+000','name':'example.exe'})
   self.assertEqual(response.status_code,200);self.assertIn('-ProcessId',remote.call_args.args[0])
   remote.reset_mock()
   self.assertEqual(self.client.get('/api/performance/PC;BAD').status_code,400)
   self.assertEqual(self.client.get('/api/performance/TESTPC?kind=other').status_code,400)
   self.assertEqual(self.client.get('/api/performance/TESTPC/threads/42',params={'created':'bad','name':'example.exe'}).status_code,400)
   self.assertEqual(self.client.get('/api/performance/TESTPC',headers={'Origin':'https://other.example'}).status_code,403)
   remote.assert_not_called()
 def test_browser_revalidates_pages_and_scripts(self):
  for path in ['/installer','/','/assets/console-directory.js','/assets/shared-ui.js','/assets/ui-tokens.css','/command-palette.js','/map-cursor.js']:
   with self.subTest(path=path):
    response=self.client.get(path);self.assertEqual(response.status_code,200)
    self.assertEqual(response.headers.get('cache-control'),'no-cache')
  script=self.client.get('/assets/console-directory.js')
  cached=self.client.get('/assets/console-directory.js',headers={'If-None-Match':script.headers['etag']})
  self.assertEqual(cached.status_code,304);self.assertEqual(cached.headers.get('cache-control'),'no-cache')
  self.assertNotIn('renderDaaSUser',script.text)
  response=self.client.get('/api/user/id:'+str(self.user['id']))
  self.assertEqual(response.status_code,200);self.assertEqual(response.headers.get('cache-control'),'no-store')
  # A new URL escapes previously cached scripts; an unchanged file keeps its URL.
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'assets').mkdir();script=root/'assets'/'test.js';script.write_text('old script')
   (root/'index.html').write_text('<script src="/assets/test.js"></script>')
   with patch.object(app,'WEB',root):
    old=self.client.get('/installer').text
    self.assertIn('/assets/test.js?v=',old);self.assertEqual(self.client.get('/installer').text,old)
    script.write_text('new script');stat=script.stat()
    app.os.utime(script,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
    self.assertNotEqual(self.client.get('/installer').text,old)
 def test_outcomes_and_remote_failure(self):
  for code,expected in [(code,'launched') for code in ('0','3010','1641','1','1603','not written')]:
   j=uuid.uuid4().hex;app.jobs[j]={'state':'queued','events':[]};app.history_create(j,'TESTPC','Example','Install','setup_i.ps1','full')
   p=app.Deploy(computer='TESTPC',folder='Example',script='setup_i.ps1')
   with patch.object(app.os.path,'isdir',return_value=True),patch.object(app,'copy_pkg',return_value=1),patch.object(app,'watch_for',lambda pc:install_watch.Watch(lambda script:'{}',pc)),patch.object(app,'launch',return_value=(123,'log','exit')),patch.object(app,'monitor',side_effect=finished(code)):
    app.deploy_worker(j,p)
   self.assertEqual(app.jobs[j]['state'],expected)
   # No exit record is no outcome: the PC stays held until someone inspects it and acknowledges.
   self.assertEqual(bool(app.jobs[j].get('recovery_required')),code=='not written')
   self.assertEqual('TESTPC' in app.job_service.unresolved,code=='not written')
   app.job_service.unresolved.discard('TESTPC')
 def test_launch_status_survives_log_failure_but_not_start_failure(self):
  for started in (True,False):
   j=uuid.uuid4().hex;app.jobs[j]={'state':'queued','events':[]};app.history_create(j,'TESTPC','Example','Install','setup_i.ps1','full')
   p=app.Deploy(computer='TESTPC',folder='Example',script='setup_i.ps1')
   def collect(*args):
    self.assertEqual(app.jobs[j]['events'][-1]['message'],'Launched')
    self.assertEqual(app.jobs[j]['events'][-1]['pid'],123)
    raise RuntimeError('Log unavailable')
   with patch.object(app.os.path,'isdir',return_value=True),patch.object(app,'copy_pkg',return_value=1),patch.object(app,'watch_for',lambda pc:install_watch.Watch(lambda script:'{}',pc)),patch.object(app,'launch',side_effect=None if started else RuntimeError('Cannot start'),return_value=(123,'log','exit')),patch.object(app,'monitor',side_effect=collect):
    app.deploy_worker(j,p)
   self.assertEqual(app.jobs[j]['state'],'launched' if started else 'failed')
   app.job_service.unresolved.discard('TESTPC')
 def test_wmi_error_not_process_exit(self):
  with patch.object(app,'ps',side_effect=RuntimeError('WMI unreachable')):
   with self.assertRaises(RuntimeError):app.wmi_running('TESTPC',123)
 def test_reboot_routes_are_monitored_and_validate_target(self):
  with patch.object(app.reboot_monitor,'start',return_value={'job':'test-watch','target':'TESTPC'}) as start:
   response=self.client.post('/api/reboot',json={'computer':'testpc'})
   self.assertEqual(response.status_code,200);self.assertEqual(response.json()['job'],'test-watch')
   start.assert_called_once_with('TESTPC')
   self.assertEqual(self.client.post('/api/reboot',json={'computer':'bad;name'}).status_code,400)
  with patch.object(app,'ps',return_value='5'):
   with self.assertRaisesRegex(RuntimeError,'rejected'):app.request_reboot('TESTPC')
  with patch.object(app,'ps',return_value='0') as command:
   app.request_reboot('TESTPC');self.assertEqual(command.call_args.kwargs['timeout'],30)
  with patch.object(app.reboot_monitor,'stop',return_value={'ok':True}) as stop:
   self.assertEqual(self.client.post('/api/reboots/test-watch/stop').status_code,200)
   stop.assert_called_once_with('test-watch')
 def test_remote_process_routes_validate_and_report_windows_outcomes(self):
  item={'PID':42,'Process':'sample.exe','CreatedAt':'20260910100000.000000+000','CanTerminate':True,'GPU':40}
  with patch.object(app,'ps',return_value=json.dumps({'ok':True,'items':[item]})) as remote:
   response=self.client.get('/api/processes/TESTPC?kind=gpu');self.assertEqual(response.status_code,200);self.assertEqual(response.json(),[item])
   self.assertIn("-Kind 'gpu'",remote.call_args.args[0]);remote.reset_mock()
   self.assertEqual(self.client.get('/api/processes/TESTPC?kind=invalid').status_code,400);remote.assert_not_called()
  payload={'computer':'TESTPC','value':'42','created':item['CreatedAt'],'name':item['Process']}
  outcome={'ok':True,'count':0,'failed':1,'results':[{'PID':42,'Process':'sample.exe','state':'failed','message':'Access denied'}]}
  with patch.object(app,'ps',return_value=json.dumps(outcome)) as remote:
   response=self.client.post('/api/kill',json=payload);self.assertEqual(response.status_code,200);self.assertEqual(response.json()['count'],0);self.assertEqual(response.json()['failed'],1)
   response=self.client.post('/api/kill',json={'computer':'TESTPC','value':'a180','match':'contains'})
   self.assertEqual(response.status_code,200);self.assertIn("-Match 'contains'",remote.call_args.args[0]);self.assertIn("-Value 'a180'",remote.call_args.args[0])
  with patch.object(app,'ps',side_effect=RuntimeError('WMI unreachable')):
   self.assertEqual(self.client.get('/api/processes/TESTPC?kind=cpu').status_code,502)
  with patch.object(app,'ps') as remote:
   self.assertEqual(self.client.post('/api/kill',json=dict(payload,value='4')).status_code,400)
   self.assertEqual(self.client.post('/api/kill',json={'computer':'TESTPC','value':'a180','match':'regex'}).status_code,422)
   self.assertEqual(self.client.post('/api/kill',json={'computer':'TESTPC','value':'*','match':'contains'}).status_code,400)
   self.assertEqual(self.client.post('/api/kill',headers={'Origin':'https://other.example'},json=payload).status_code,403)
   remote.assert_not_called()
 def test_service_routes_require_target_identity_and_report_verified_outcomes(self):
  inventory={'ok':True,'computer':'TESTPC','items':[]}
  payload={'computer':'TESTPC','name':'TestService','expected_identity':'a'*64}
  with patch.object(app,'ps',return_value=json.dumps(inventory)) as remote:
   response=self.client.post('/api/services',json={'computer':'TESTPC'});self.assertEqual(response.status_code,200);self.assertEqual(response.json(),inventory)
   remote.reset_mock()
   self.assertEqual(self.client.post('/api/services',json={'computer':'bad;name'}).status_code,400)
   self.assertEqual(self.client.post('/api/services/stop',json=dict(payload,expected_identity='bad')).status_code,422)
   self.assertEqual(self.client.post('/api/services/stop',json={'computer':'TESTPC','name':'TestService'}).status_code,422)
   self.assertEqual(self.client.post('/api/services/stop',headers={'Origin':'https://other.example'},json=payload).status_code,403)
   remote.assert_not_called()
  item={'name':'TestService','display_name':'Test Service','identity':'a'*64,'state':'Stopped','start_mode':'Auto','pid':0,'can_start':True,'start_reason':'','can_stop':False,'stop_reason':'Service is not running','can_restart':False,'restart_reason':'Service is not running'}
  with patch.object(app,'ps',return_value=json.dumps({'ok':True,'computer':'TESTPC','name':'TestService','outcome':'stopped','state':'Stopped','item':item})) as remote:
   response=self.client.post('/api/services/stop',json=payload);self.assertEqual(response.status_code,200);self.assertEqual(response.json()['state'],'Stopped')
   self.assertIn("-Action 'stop'",remote.call_args.args[0])
  with patch.object(app,'ps',side_effect=RuntimeError('WMI unreachable')):
   self.assertEqual(self.client.post('/api/services',json={'computer':'TESTPC'}).status_code,502)
   response=self.client.post('/api/services/stop',json=payload);self.assertEqual(response.status_code,502);self.assertIn('outcome may be unknown',response.json()['detail'])
 def test_unique_readable_remote_commands(self):
  commands=[]
  with patch.object(app,'wmi_create',side_effect=lambda pc,cmd:commands.append(cmd) or 12):
   a=app.launch('TESTPC',r'C:\Temp\Packages\Example\setup_i.ps1','Example');b=app.launch('TESTPC',r'C:\Temp\Packages\Example\setup_i.ps1','Example')
  self.assertNotEqual(a[1:],b[1:])
  # Each attempt owns its result files; the command is plain text naming the package's own script.
  self.assertNotEqual(commands[0],commands[1])
  self.assertIn("& 'C:\\Temp\\Packages\\Example\\setup_i.ps1'",commands[0]);self.assertIn('finally',commands[0]);self.assertIn('$LASTEXITCODE',commands[0])
  self.assertNotIn('EncodedCommand',commands[0]);self.assertLess(len(commands[0]),1000)
 def test_busy_target_blocks_deployment(self):
  guard=app.target_lock('TESTPC');guard.acquire();j=uuid.uuid4().hex;app.jobs[j]={'state':'queued','events':[]}
  try:
   with patch.object(app,'copy_pkg') as copy:app.deploy_worker(j,app.Deploy(computer='TESTPC',folder='Example',script='setup_i.ps1'));copy.assert_not_called()
   self.assertEqual(app.jobs[j]['state'],'failed')
  finally:guard.release()
 def test_bulk_and_queue_terminal_states(self):
  with patch.object(app.os.path,'isdir',return_value=True),patch.object(app,'copy_pkg',return_value=1),patch.object(app,'watch_for',lambda pc:install_watch.Watch(lambda script:'{}',pc)),patch.object(app,'launch',return_value=(123,'log','exit')),patch.object(app,'monitor',side_effect=finished('1603')):
   j=uuid.uuid4().hex;app.jobs[j]={'state':'queued','events':[]};app.bulk_worker(j,app.Bulk(computers=['TESTPC'],folder='Example',script='setup_i.ps1'))
   self.assertEqual(app.jobs[j]['state'],'complete');self.assertEqual(app.jobs[j]['results'][0]['completion'],'Launched')
   q=uuid.uuid4().hex;app.queue_jobs[q]={'items':[{'state':'waiting'}]};app._queue_worker(q,[app.QueueItem(computer='TESTPC',folder='Example',script='setup_i.ps1')]);self.assertEqual(app.queue_jobs[q]['state'],'complete');self.assertEqual(app.queue_jobs[q]['items'][0]['state'],'launched')
 def test_databases_integrity(self):
  for path in [app.MASTER_DB,self.original_history]:
   c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
   try:self.assertEqual(c.execute('pragma integrity_check').fetchall(),[('ok',)])
   finally:c.close()

if __name__=='__main__':unittest.main()
