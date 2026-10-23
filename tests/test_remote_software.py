import json,re,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import remote_software as rs
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
SID='S-1-5-21-1-2-3-1001';GUID='{11111111-2222-3333-4444-555555555555}'
def item(**extra):
 d=dict(Identity='LocalMachine|Registry64|Key',Name='Test App',Version='1',Kind='MSI',Scope='Machine',UserSid='',ProductCode=GUID,UninstallString='',QuietUninstallString='',ModifyPath='',NoRemove=False,NonRemovable=False,Registered=True)
 d.update(extra);return d
class RemoteSoftware(unittest.TestCase):
 def test_msi_uninstall_and_repair(self):
  for action,flag in [('Uninstall','/x'),('Repair','/fomus')]:
   p=rs.make_plan(item(),SID,action=action);self.assertIn(flag+' '+GUID,p['command']);self.assertIn('/qn /norestart',p['command']);self.assertEqual(p['action'],action)
  with self.assertRaises(ValueError):rs.make_plan(item(ProductCode='bad & calc'),SID)
 def test_exe_quiet_and_explicit_silent_arguments(self):
  x=item(Kind='EXE',QuietUninstallString='"C:\\Program Files\\Test\\remove.exe" /silent /norestart')
  p=rs.make_plan(x,SID);self.assertEqual(p['executable'],r'C:\Program Files\Test\remove.exe');self.assertEqual(p['arguments'],'/silent /norestart')
  x=item(Kind='EXE',UninstallString=r'C:\Program Files\Test\remove.exe /remove')
  self.assertEqual(rs.capability(x,SID)[0],'configure')
  with self.assertRaises(ValueError):rs.make_plan(x,SID)
  self.assertEqual(rs.make_plan(x,SID,'/remove /S')['arguments'],'/remove /S')
  x['ModifyPath']=r'"C:\Program Files\Test\setup.exe" /maintenance'
  self.assertEqual(rs.make_plan(x,SID,'/repair /quiet',action='Repair')['arguments'],'/repair /quiet')
 def test_scope_and_unsupported(self):
  for x in [item(NoRemove=True),item(Scope='User',UserSid='S-1-5-21-999'),item(Kind='EXE',UninstallString='rundll32.exe bad'),item(Kind='EXE',UninstallString=r'\\server\share\uninstall.exe /S')]:
   self.assertEqual(rs.capability(x,SID)[0],'blocked')
  self.assertEqual(rs.capability(item(Scope='User',UserSid=SID),SID)[0],'ready')
  self.assertEqual(rs.capability(item(NoRemove=True),SID,'Repair')[0],'ready')
 def test_appx_owner_specific_no_reset(self):
  x=item(Kind='MSIX/Appx',Scope='User',UserSid=SID,PackageFullName='Test_1.0.0.0_x64__abc123')
  p=rs.make_plan(x,SID);self.assertIn('-User '+"'"+SID+"'",p['command']);self.assertNotIn('-AllUsers',p['command'])
  self.assertEqual(rs.capability(x,SID,'Repair')[0],'blocked')
 def test_verification_not_assumed(self):
  result=dict(exit_code=0,verification_complete=True,registration_remaining=False)
  self.assertIn('no longer present',rs.verdict(result,'MSI')[1]);result['registration_remaining']=True
  self.assertIn('still present',rs.verdict(result,'MSI')[1]);self.assertIn('health not verified',rs.verdict(result,'MSI','Repair')[1])
  self.assertEqual(rs.verdict(dict(exit_code=1605),'MSI')[0],'failed');self.assertEqual(rs.verdict(dict(exit_code=3010),'EXE')[0],'failed')
 def test_remote_transport_launches_on_target_and_reads_result(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);calls=[]
   def unc(pc,path):return str(root/path.replace(':','').replace('\\','/'))
   def create(pc,command):
    calls.append((pc,command));out=re.search(r'-OutputPath "([^"]+)"',command)[1];Path(unc(pc,out)).write_text(json.dumps({'ok':True,'software':[]}));return 123
   w=SimpleNamespace(ps=lambda *a,**k:r'C:\Windows',quote=lambda x:"'"+x+"'",unc=unc,wmi_create=create,wmi_running=lambda *a:False)
   result=rs.remote_call(w,'PC1');self.assertEqual(result['pid'],123);self.assertEqual(calls[0][0],'PC1');self.assertIn('-File "C:\\Windows\\Temp\\AtlasSoftware_',calls[0][1]);self.assertNotIn('msiexec',calls[0][1])
 def test_unreadable_or_invalid_post_launch_result_is_unknown(self):
  for contents,unreadable in [('{',False),('[]',False),('{"ok":"true"}',False),('{"ok":true}',True)]:
   with self.subTest(contents=contents,unreadable=unreadable),tempfile.TemporaryDirectory() as td:
    root=Path(td)
    def unc(pc,path):return str(root/path.replace(':','').replace('\\','/'))
    def create(pc,command):
     output=re.search(r'-OutputPath "([^"]+)"',command)[1];Path(unc(pc,output)).write_text(contents);return 123
    w=SimpleNamespace(ps=lambda *a,**k:r'C:\Windows',quote=lambda x:"'"+x+"'",unc=unc,wmi_create=create,wmi_running=lambda *a:False)
    from contextlib import ExitStack
    with ExitStack() as stack:
     if unreadable:stack.enter_context(patch.object(Path,'read_text',side_effect=OSError('SMB connection lost')))
     with self.assertRaises(rs.UnknownOutcome) as error:rs.remote_call(w,'PC1',plan=rs.make_plan(item(),SID))
    self.assertIn('PID 123',str(error.exception));self.assertIn('before retrying',str(error.exception))
 def test_valid_explicit_remote_failure_is_not_unknown(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   def unc(pc,path):return str(root/path.replace(':','').replace('\\','/'))
   def create(pc,command):
    output=re.search(r'-OutputPath "([^"]+)"',command)[1];Path(unc(pc,output)).write_text('{"ok":false,"error":"Registration changed before control"}');return 123
   w=SimpleNamespace(ps=lambda *a,**k:r'C:\Windows',quote=lambda x:"'"+x+"'",unc=unc,wmi_create=create,wmi_running=lambda *a:False)
   with self.assertRaises(RuntimeError) as error:rs.remote_call(w,'PC1',plan=rs.make_plan(item(),SID))
   self.assertNotIsInstance(error.exception,rs.UnknownOutcome);self.assertEqual(str(error.exception),'Registration changed before control')
 def test_post_launch_stat_failures_are_unknown_in_initial_and_grace_poll(self):
  for grace in (False,True):
   with self.subTest(grace=grace),tempfile.TemporaryDirectory() as td:
    root=Path(td)
    w=SimpleNamespace(ps=lambda *a,**k:r'C:\Windows',quote=lambda x:"'"+x+"'",unc=lambda pc,path:str(root/path.replace(':','').replace('\\','/')),wmi_create=lambda *a:123,wmi_running=lambda *a:False)
    failures=[False,OSError('SMB stat failed')] if grace else [OSError('SMB stat failed')]
    with patch.object(Path,'is_file',side_effect=failures),self.assertRaises(rs.UnknownOutcome) as error:
     rs.remote_call(w,'PC1',plan=rs.make_plan(item(),SID))
    self.assertIn('PID 123',str(error.exception));self.assertIn('SMB stat failed',str(error.exception))
 def test_successful_mutation_requires_integer_exit_code(self):
  for ec,valid in [('missing',False),(None,False),(True,False),('0',False),(0,True),(3010,True),(-1,True)]:
   with self.subTest(exit_code=ec),tempfile.TemporaryDirectory() as td:
    root=Path(td);data={'ok':True}
    if ec!='missing':data['exit_code']=ec
    def unc(pc,path):return str(root/path.replace(':','').replace('\\','/'))
    def create(pc,command):
     output=re.search(r'-OutputPath "([^"]+)"',command)[1];Path(unc(pc,output)).write_text(json.dumps(data));return 123
    w=SimpleNamespace(ps=lambda *a,**k:r'C:\Windows',quote=lambda x:"'"+x+"'",unc=unc,wmi_create=create,wmi_running=lambda *a:False)
    if valid:self.assertEqual(rs.remote_call(w,'PC1',plan=rs.make_plan(item(),SID))['exit_code'],ec)
    else:
     with self.assertRaises(rs.UnknownOutcome) as error:rs.remote_call(w,'PC1',plan=rs.make_plan(item(),SID))
     self.assertIn('integer exit code',str(error.exception))
 def test_routes_plan_binding_confirmation_replay_and_locks(self):
  jobs={};lock=threading.Lock();target=threading.Lock();hist=[]
  def validate(pc):
   if not re.fullmatch('[A-Za-z0-9-]+',pc):raise HTTPException(400,'Invalid target')
   return pc.upper()
  def emit(j,msg,state=None,**extra):
   jobs[j]['events'].append(dict(message=msg,**extra))
   if state:jobs[j]['state']=state
  w=SimpleNamespace(validate_pc=validate,target_lock=lambda pc:target,jobs=jobs,lock=lock,CONFIG={},history_create=lambda *a:hist.append(a),history_update=lambda *a,**k:None,emit=emit)
  w.job_service=SimpleNamespace(inventory=threading.BoundedSemaphore(3),target_ready=lambda pc:None,unresolved=set())
  w.start_job=lambda fn,*args:fn(*args)
  app=FastAPI()
  def token(r):
   if r.headers.get('x-atlas-token')!='test':raise HTTPException(403,'Token')
  rs.register_remote_software(app,w,token);c=TestClient(app);headers={'x-atlas-token':'test'}
  def remote(w,pc,plan=None,**kw):
   if plan:return dict(exit_code=0,registration_remaining=False,verification_complete=True,operation_folder='C:\\Windows\\Temp\\test')
   return dict(software=[item()],operator_sid=SID)
  with patch.object(rs,'remote_call',remote):
   self.assertEqual(c.post('/api/software-tools/inventory',json={'computer':'PC1'}).status_code,403)
   scan=c.post('/api/software-tools/inventory',json={'computer':'pc1'},headers=headers).json()['scan']
   p=c.post('/api/software-tools/preview',json={'scan':scan,'row':0},headers=headers).json();self.assertEqual(p['computer'],'PC1')
   self.assertEqual(c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC2'},headers=headers).status_code,400)
   target.acquire()
   self.assertEqual(c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC1'},headers=headers).status_code,409);target.release()
   def ready(pc):
    if pc in w.job_service.unresolved:raise HTTPException(409,'Unknown previous outcome')
   def previous_operation_finished(pc):
    w.job_service.unresolved.add(pc);return target
   with patch.object(w.job_service,'target_ready',ready),patch.object(w,'target_lock',previous_operation_finished):
    self.assertEqual(c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC1'},headers=headers).status_code,409)
    self.assertFalse(target.locked());self.assertEqual(hist,[])
   w.job_service.unresolved.clear()
   r=c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC1'},headers=headers);self.assertEqual(r.status_code,200,r.text)
   for _ in range(100):
    if jobs[r.json()['job']]['state']=='complete':break
    time.sleep(.01)
   self.assertEqual(jobs[r.json()['job']]['state'],'complete');self.assertEqual(hist[0][1],'PC1')
   self.assertEqual(c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC1'},headers=headers).status_code,409)
   p=c.post('/api/software-tools/preview',json={'scan':scan,'row':0,'action':'Repair'},headers=headers).json()
   c.post('/api/software-tools/inventory',json={'computer':'PC1'},headers=headers)
   self.assertEqual(c.post('/api/software-tools/uninstall',json={'plan':p['plan'],'confirmation':'PC1'},headers=headers).status_code,409)
if __name__=='__main__':unittest.main()
