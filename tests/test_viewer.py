from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest,sqlite3,tempfile,json,hashlib,os
from pathlib import Path
from unittest.mock import patch,Mock
from fastapi.testclient import TestClient
from backend import viewer
import launcher
from contextlib import closing

class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'atlas.db'
        with closing(sqlite3.connect(viewer.DB)) as src,closing(sqlite3.connect(self.db)) as dest:src.backup(dest)
        self.saved=viewer.DB;viewer.DB=self.db
        self.client=TestClient(viewer.app,base_url='http://192.0.2.10:8771',client=('192.0.2.11',12345))
    def tearDown(self):
        self.client.close();viewer.DB=self.saved;self.tmp.cleanup()
    def test_live_maps_search_and_readonly_database(self):
        state=self.client.get('/api/official/state').json();self.assertEqual(len(state['records']),620);self.assertNotIn('token',state)
        with viewer.connect() as con:
            person=con.execute('select id,user_id from users where user_id != "" limit 1').fetchone()
            with self.assertRaises(sqlite3.OperationalError):con.execute("update users set full_name='invalid'")
        result=self.client.get('/api/search',params={'term':'user:'+person['user_id']});self.assertEqual(result.status_code,200)
        self.assertTrue(result.json()['users']);self.assertEqual(self.client.get('/api/user/id:'+str(person['id'])).status_code,200)
        desk=state['records'][0];self.assertEqual(self.client.get('/api/desks/'+desk['id']+'/context').status_code,200)
        desk['notes']='new admin edit'
        with closing(sqlite3.connect(self.db)) as con:
            con.execute('update official_records set body=? where id=?',(json.dumps(desk),desk['id']));con.commit()
        self.assertEqual(self.client.get('/api/official/state').json()['records'][0]['notes'],'new admin edit')
    def test_privileged_reads_and_all_writes_unavailable(self):
        before=hashlib.sha256(self.db.read_bytes()).digest()
        for path in ['/api/performance/PC', '/api/performance/PC?kind=diagnose', '/api/performance/PC/threads/42?created=x&name=app.exe']:
            self.assertEqual(self.client.get(path).status_code,404,path)
        paths=['/api/save','/api/move','/api/vacate','/api/deploy','/api/kill','/api/services','/api/services/stop','/api/services/start','/api/services/restart','/api/reboot','/api/ops/settings','/api/database/apply/x','/api/open-tool/cmd/PC','/api/official/map-occupant','/api/axis/chat','/api/axis/approve','/api/axis/cancel','/api/axis/reset']
        for method in ('POST','PUT','PATCH','DELETE'):
            for path in paths:self.assertEqual(self.client.request(method,path,json={}).status_code,403,(method,path))
        for path in ['/api/processes/PC?kind=gpu','/api/preflight/PC','/api/overview/PC','/api/v28/software/PC','/api/access/PC','/api/backup','/api/package-script','/api/ops/settings','/manage-database','/office_atlas.db','/config.json','/api/docs','/openapi.json','/operations.js','/.git/config','/%2e%2e/config.json']:
            self.assertEqual(self.client.get(path).status_code,404,path)
        self.assertEqual(self.client.get('/api/axis/status').status_code,404)
        self.assertEqual(self.client.get('/assets/axis-chat.js').status_code,404)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).digest())
    def test_full_console_is_visible_but_execution_is_blocked(self):
        import re
        html=self.client.get('/installer?mode=admin').text
        self.assertNotIn('axis-chat',html,'Axis chat stays in the local Admin app')
        self.assertIn('content="viewer"',html)
        self.assertIn('atlas-demo-badge',html)
        self.assertEqual(self.client.get('/assets/desktop.html').status_code, 404, 'The Desktop layout was removed')
        for page in ('workspace','admin','bulk','history','psexec'):
            self.assertIn('data-page="'+page+'"',html)
        for filename in re.findall(r'/assets/([\w.-]+)',html):
            self.assertEqual(self.client.get('/assets/'+filename).status_code,200,filename)
        self.assertEqual(self.client.get('/installer/').status_code,200)
        self.assertEqual(self.client.get('/api/capabilities').json()['elevated_operations'],False)
        for path in ('/api/psexec/runs','/api/overview/PC','/api/machine-health/PC/cpu','/api/catalog','/api/session','/api/app','/api/inbox/arrivals','/api/inbox/control','/atlas-sw.js','/atlas.webmanifest'):
            self.assertEqual(self.client.get(path).status_code,404,path)
        for path in ('/api/psexec/run','/api/psexec/runs/fake/input','/api/bulk/deploy','/api/queue'):
            self.assertEqual(self.client.post(path,json={}).status_code,403,path)
        for path in ('/api/palette/desks','/api/master/status','/api/master/resolve/nobody'):
            self.assertEqual(self.client.get(path).status_code,200,path)

    def test_machine_inspector_uses_stored_relationships_only(self):
        before=hashlib.sha256(self.db.read_bytes()).digest()
        with viewer.connect() as con:
            row=con.execute("select m.machine_name from machines m where exists(select 1 from assignments a where a.machine_id=m.id) limit 1").fetchone()
        response=self.client.get('/api/machine/'+row[0]);self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['machine']['name'],row[0]);self.assertTrue(data['users'])
        self.assertIn('assigned_relationship',data['users'][0]);self.assertIn('logon_relationship',data['users'][0])
        self.assertEqual(self.client.get('/api/machine/NO-SUCH-FIXTURE-MACHINE').status_code,404)
        self.assertEqual(self.client.get('/api/machine/PC;BAD').status_code,400)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).digest())
    def test_assets_and_untrusted_mode_override(self):
        home=self.client.get('/?mode=admin');self.assertIn('content="viewer"',home.text);self.assertNotIn('/assets/machine-health',home.text)
        self.assertNotIn('/assets/axis-chat.js',home.text)
        for path in ['/site-info.js','/viewer.js','/viewer.css','/map-furniture.js','/map-amenities.js','/map-plan-details.js','/official-app.js','/camera-motion.js','/map-cursor.js','/official-data.json','/style.css','/operations.css','/official.css','/studio-floor-2.svg','/assets/atlas-shell.css','/assets/barclays-eagle.svg']:
            self.assertEqual(self.client.get(path).status_code,200,path)
        self.assertEqual(self.client.post('/api/save',headers={'X-Atlas-Token':'anything','X-Forwarded-For':'127.0.0.1'}).status_code,403)

class LauncherTests(unittest.TestCase):
    def test_ports_and_bind_addresses(self):
        with patch.dict(os.environ,{'ATLAS_ADMIN_PORT':'8770','ATLAS_VIEWER_PORT':'8771'}):
            a,v=launcher.servers();self.assertEqual(a['host'],'127.0.0.1');self.assertEqual(v['host'],'0.0.0.0')
        with patch.dict(os.environ,{'ATLAS_ADMIN_PORT':'8770','ATLAS_VIEWER_PORT':'8770'}):
            with self.assertRaises(ValueError):launcher.servers()
    def test_failed_viewer_rolls_back_only_new_admin(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch('runtime_paths.prepare_runtime_database'):
            child=Mock()
            with patch.object(launcher,'start_server',side_effect=[child,RuntimeError('port occupied')]):
                self.assertEqual(launcher.run(False),1);child.terminate.assert_called_once()
            with patch.object(launcher,'start_server',side_effect=[None,RuntimeError('port occupied')]):
                self.assertEqual(launcher.run(False),1)
    def test_both_records_stopped(self):
        with patch.object(launcher,'read_record',return_value={'pid':123}),patch.object(launcher,'stop_record',return_value=0) as stop:
            self.assertEqual(launcher.stop(),0);self.assertEqual([c.args[0] for c in stop.call_args_list],['viewer','admin'])

if __name__=='__main__':unittest.main()
