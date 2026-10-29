from sqlite_fixture import connect as fixture_connect
"""Temporary database only; no deployment or remote calls."""
import unittest,tempfile,sys,io,zipfile,os,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from backend import database_manager as dm
from backend import shared_operations
from axis import it_tools
class DatabaseManager(unittest.TestCase):
 def test_preview_apply_restore_and_busy_guards(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);db=root/'office_atlas.db'
   with fixture_connect(Path(dm.__file__).resolve().parents[1]/'office_atlas.db') as a,fixture_connect(db) as b:a.backup(b)
   w=SimpleNamespace(MASTER_DB=db,jobs={},queue_jobs={});app=FastAPI()
   def token(r):
    if r.headers.get('x-atlas-token')!='test':raise HTTPException(403,'token')
   with patch.object(dm,'__file__',str(root/'backend'/'database_manager.py')):dm.register_database_manager(app,w,token)
   cli=TestClient(app);headers={'x-atlas-token':'test','x-file-name':'Friday.xlsx'}
   def prepare(source,out):
    with fixture_connect(db) as a,fixture_connect(out) as b:a.backup(b)
    with fixture_connect(out) as b:b.execute("update users set department='TEST UPDATE' where id=(select min(id) from users)")
   data=io.BytesIO()
   with zipfile.ZipFile(data,'w') as z:z.writestr('test','fixture')
   body=data.getvalue()
   with patch.object(dm,'prepare',prepare):
    self.assertEqual(cli.post('/api/database/preview',content=body).status_code,403)
    w.jobs['x']={'state':'running'};self.assertEqual(cli.post('/api/database/preview',content=body,headers=headers).status_code,409);w.jobs.clear()
    # A running Axis deployment also holds imports, as an Atlas job does.
    job=root/'axis'/'jobs'/('a'*32+'.json')
    it_tools.write_json(job,{'id':'a'*32,'state':'running','computers':['PC1'],'created_epoch':time.time(),'worker_pid':os.getpid()})
    with patch.object(shared_operations,'AXIS_STATE',root/'axis'):
     self.assertEqual(cli.post('/api/database/preview',content=body,headers=headers).status_code,409)
     it_tools.write_json(job,{'id':'a'*32,'state':'complete','computers':['PC1'],'created_epoch':0})
     self.assertFalse(cli.get('/api/database/status').json()['busy'])
    r=cli.post('/api/database/preview',content=body,headers=headers);self.assertEqual(r.status_code,200,r.text);stage=r.json()['id'];self.assertEqual(r.json()['report']['users']['changed'],1)
    payload={'confirmation':'APPLY','full_snapshot':True}
    self.assertEqual(cli.post('/api/database/apply/'+stage,json={},headers=headers).status_code,400)
    w.queue_jobs['q']={'state':'paused'};self.assertEqual(cli.post('/api/database/apply/'+stage,json=payload,headers=headers).status_code,409);w.queue_jobs.clear()
    with fixture_connect(db) as c:before=c.execute('select body from records order by id').fetchall()
    r=cli.post('/api/database/apply/'+stage,json=payload,headers=headers);self.assertEqual(r.status_code,200,r.text)
    with fixture_connect(db) as c:
     self.assertEqual(before,c.execute('select body from records order by id').fetchall());self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')
    self.assertTrue((root/'backups'/r.json()['backup']).is_file())
    self.assertEqual(cli.post('/api/database/apply/'+stage,json=payload,headers=headers).status_code,409)
    history=cli.get('/api/database/status').json()['history'];self.assertEqual(len(history),1)
    r=cli.post('/api/database/restore-preview/'+history[0]['id'],headers=headers);self.assertEqual(r.status_code,200,r.text)
    r=cli.post('/api/database/apply/'+r.json()['id'],json=payload,headers=headers);self.assertEqual(r.status_code,200,r.text)
    with fixture_connect(db) as c:self.assertNotEqual(c.execute('select department from users order by id limit 1').fetchone()[0],'TEST UPDATE')
if __name__=='__main__':unittest.main()
