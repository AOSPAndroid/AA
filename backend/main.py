from __future__ import annotations
from datetime import datetime
import base64, hashlib, json, logging, os, re, secrets, shutil, sqlite3, subprocess, sys, threading, time, uuid, zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from backend import __version__
from directory_lookup import exact_users, linked_machines, search_directory, prepare_views
from reboot_monitor import has_echo_reply

ROOT=Path(__file__).resolve().parent.parent
WEB=ROOT/'frontend'
LOGS=ROOT/'logs'
DATA=ROOT/'data'
from runtime_paths import database_path
MASTER_DB=database_path()
DB=MASTER_DB
HISTORY_DB=MASTER_DB
LOGS.mkdir(parents=True,exist_ok=True)
DATA.mkdir(parents=True,exist_ok=True)

CONFIG=json.loads((ROOT/'config.json').read_text(encoding='utf-8')) if (ROOT/'config.json').exists() else {}
from package_paths import package_repository
REPO=package_repository(CONFIG,ROOT)
REMOTE_ROOT=r'C:\Temp\Packages'; NW=0x08000000 if os.name=='nt' else 0
# Axis stages under its own root; one cleanup clears both. Axis job logs beside it are kept.
STAGING_ROOTS=(REMOTE_ROOT,r'C:\Temp\LocalAgent\Packages')
def staging_linked(root):
 """A link anywhere on the staging path could redirect deletion; C:\\Temp is writable by standard users."""
 from axis.it_tools import linked
 return any(item.exists() and linked(item) for item in [root,*root.parents])
logging.basicConfig(filename=LOGS/'application.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
app=FastAPI(title='Office Atlas',version=__version__,docs_url='/api/docs',redoc_url=None)
from response_compression import compress_responses
compress_responses(app)
from job_service import JobService, TERMINAL
from shared_operations import TargetLock, axis_ready
from axis.it_tools import describe_install_activity, install_activity_finish, install_activity_setup, install_unconfirmed, read_install_activity
job_service=JobService(lambda:HISTORY_DB,guard=axis_ready)
jobs=job_service.jobs;lock=job_service.lock
@app.on_event('startup')
def recover_operations():job_service.recover()
NAME_RE=re.compile(r'^[A-Za-z0-9_.-]{1,64}$')

def validate_pc(pc):
 from device_inventory import canonical_machine_name,supports_windows
 pc=canonical_machine_name(pc)
 if pc.startswith('INVENTORY-') and ':' in pc:raise HTTPException(400,'This device is inventory only. Windows deployment and remote tools require a PC.')
 if not NAME_RE.fullmatch(pc) or pc.startswith(('-', '.')) or '..' in pc:raise HTTPException(400,'Invalid computer name')
 if Path(MASTER_DB).exists():
  with sqlite3.connect(Path(MASTER_DB).resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
   c.row_factory=sqlite3.Row;c.execute('begin')
   if c.execute("select 1 from sqlite_master where type='table' and name='machines'").fetchone():
    prepare_views(c)
    from vdi_inventory import find_machines
    matches=find_machines(c,pc)
    if len(matches)>1:raise HTTPException(400,'Ambiguous inventory hostname; select its fully qualified name.')
    if matches:
     record=matches[0]
     if not supports_windows(record) or record.get('windows_remote_supported') in (False,0):raise HTTPException(400,'This device is inventory only. Windows deployment and remote tools require a unique PC target.')
     target=canonical_machine_name(record.get('name') or record.get('machine_name'))
     if not NAME_RE.fullmatch(target) or target.startswith(('-', '.')) or '..' in target:raise HTTPException(400,'This inventory record has no valid Windows target.')
     pc=target
 # Unknown but valid hostnames remain usable for an explicitly chosen PC.
 if not supports_windows({'machine_name':pc}):raise HTTPException(400,'This device is inventory only. Windows deployment and remote tools require a PC.')
 return pc

def quote(v):return "'"+str(v).replace("'","''")+"'"
def unc(pc,p='C:'):return rf'\\{validate_pc(pc)}\{p.replace(":","$",1).lstrip(chr(92))}'
def run(args,check=True,timeout=120,env=None):
 p=subprocess.run(args,text=True,capture_output=True,timeout=timeout,creationflags=NW,env=dict(os.environ,**env) if env else None)
 if check and p.returncode:raise RuntimeError((p.stderr or p.stdout or f'Exit code {p.returncode}').strip())
 return p
def ps(script,timeout=120,env=None):
 encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
 return run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',encoded],timeout=timeout,env=env).stdout.strip()
def hist_db():
 c=sqlite3.connect(HISTORY_DB,timeout=20,factory=ClosingConnection);c.row_factory=sqlite3.Row
 c.execute('''create table if not exists deployments(id text primary key,started text,finished text,operator text,target text,package text,action text,script text,mode text,state text,robocopy_code text,pid text,exit_code text,details text)''')
 # The full request (folder, fresh copy, threads) so a failed deployment can be retried or queued as it was.
 if 'payload' not in {row[1] for row in c.execute('pragma table_info(deployments)')}:c.execute('alter table deployments add column payload text')
 c.commit();return c
def history_create(j,target,package,action,script,mode,payload=None):
 if j in jobs:jobs[j].update(target=target,package=package,action=action,script=script,action_title=action+' · '+package,started_at=time.time(),payload=payload);job_service.save(j)
 with hist_db() as c:c.execute('insert into deployments(id,started,operator,target,package,action,script,mode,state,payload) values(?,datetime("now","localtime"),?,?,?,?,?,?,?,?)',(j,identity(),target,package,action,script,mode,'queued',json.dumps(payload) if payload else None));c.commit()
def saved_payload(j):
 """The deployment request behind a job or history row, rebuilt from its columns for older rows."""
 job=jobs.get(j) or {}
 if job.get('payload'):return dict(job['payload'])
 with hist_db() as c:row=c.execute('select target,package,action,script,mode,payload from deployments where id=?',(j,)).fetchone()
 if not row:raise HTTPException(404,'Deployment not found in history')
 if row['payload']:return json.loads(row['payload'])
 return {'computer':row['target'],'folder':row['package'],'script':row['script'],'action':row['action'] or 'Install','mode':row['mode'] or 'full'}
def history_update(j,**fields):
 if not fields:return
 with hist_db() as c:c.execute('update deployments set '+','.join(f'{k}=?' for k in fields)+' where id=?',(*fields.values(),j));c.commit()
def identity():return run(['whoami.exe']).stdout.strip()
def emit(j,message,state=None,**extra):
 with lock:
  job=jobs[j];job['events'].append({'time':time.strftime('%H:%M:%S'),'message':message,**extra})
  if state:job['state']=state
  job_service.save(j)

def copy_pkg(src,dst,fresh=False,threads=8):
 if fresh and os.path.exists(dst):shutil.rmtree(dst)
 os.makedirs(dst,exist_ok=True)
 p=run(['robocopy.exe',src,dst,'/E',f'/MT:{threads}','/R:1','/W:1','/Z','/FFT','/COPY:DAT','/DCOPY:DAT','/NFL','/NDL','/NP','/NJH','/NJS'],False,timeout=int(CONFIG.get('deployment_timeout_seconds',3600)))
 if p.returncode>7:raise RuntimeError(f'Robocopy failed: {p.returncode}\n{p.stderr or p.stdout}')
 return p.returncode
def wmi_create(pc,cmd):
 # The remote command travels in an environment variable: encoding it into this command line again could pass Windows' 32K limit.
 out=ps(f'$r=Invoke-WmiMethod -ComputerName {quote(pc)} -Class Win32_Process -Name Create -ArgumentList $env:ATLAS_REMOTE_COMMAND -EA Stop;if($r.ReturnValue-ne 0){{throw "WMI start failed: $($r.ReturnValue)"}};$r.ProcessId',env={'ATLAS_REMOTE_COMMAND':cmd})
 return int(out.splitlines()[-1])
def wmi_running(pc,pid):
 return ps(f'[bool](Get-WmiObject -ComputerName {quote(pc)} Win32_Process -Filter {quote("ProcessId="+str(int(pid)))} -EA Stop)',timeout=30).lower()=='true'
def install_files(ex):
 """The target's waiting status and installer-activity record for a launch's exit-code file."""
 base=ex.rsplit('.',1)[0];return base+'.status',base+'.activity.json'
def remote_command(payload):
 # Compressed so the command line stays well inside Windows' 32K limit; it still never touches the target's disk.
 packed=base64.b64encode(zlib.compress(payload.encode('utf-8'),9)[2:-4]).decode('ascii')
 bootstrap=("$s=New-Object IO.Compression.DeflateStream((New-Object IO.MemoryStream(,[Convert]::FromBase64String('"+packed+"'))),"
            "[IO.Compression.CompressionMode]::Decompress);& ([scriptblock]::Create((New-Object IO.StreamReader($s,[Text.Encoding]::UTF8)).ReadToEnd()))")
 return 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand '+base64.b64encode(bootstrap.encode('utf-16le')).decode('ascii')
def launch(pc,remote,pkg):
 token=uuid.uuid4().hex
 safe=re.sub(r'[^A-Za-z0-9_.-]','_',pkg)[:60]
 log=rf'C:\Temp\{safe}_{token}.log';ex=rf'C:\Temp\{safe}_{token}.exitcode';status,activity=install_files(ex)
 # The target stops waiting for installer activity early enough to report before monitoring ends.
 limit=max(60,int(CONFIG.get('deployment_timeout_seconds',3600))-120)
 invoke=f'& {quote(remote)} *>&1 | Out-File -LiteralPath {quote(log)} -Encoding utf8' if remote.lower().endswith('.ps1') else f'& cscript.exe //B //NoLogo {quote(remote)} *>&1 | Out-File -LiteralPath {quote(log)} -Encoding utf8'
 # EncodedCommand avoids nested cmd/PowerShell quoting. Each attempt owns its result files.
 payload=f"""$ErrorActionPreference='Stop'
$ec=1
{install_activity_setup(limit)}
try {{
 Set-Location -LiteralPath (Split-Path -LiteralPath {quote(remote)})
 Get-ChildItem -LiteralPath (Split-Path -LiteralPath {quote(remote)}) -Recurse -File -Filter *.ps1 | Unblock-File
 $global:LASTEXITCODE=0
 {invoke}
 $ec=$LASTEXITCODE
}} catch {{
 $_ | Out-File -LiteralPath {quote(log)} -Append -Encoding utf8
 $ec=1
}} finally {{
 {install_activity_finish('$ec',status,activity,log)}
 [string]$ec | Out-File -LiteralPath {quote(ex)} -Encoding ascii
}}
exit $ec
"""
 return wmi_create(pc,remote_command(payload)),log,ex
def monitor(pc,pid,log,ex,progress=None,activity=None):
 # progress receives what the target is still waiting for; activity is filled with its installer-activity record.
 deadline=time.monotonic()+int(CONFIG.get('deployment_timeout_seconds',3600))
 status_path,activity_path=(Path(unc(pc,path)) for path in install_files(ex));shown=None
 while wmi_running(pc,pid):
  if time.monotonic()>deadline:raise RuntimeError('Monitoring timed out; remote installation may still be running. Inspect target before retrying.')
  try:status=status_path.read_text(encoding='utf-8-sig',errors='replace').strip()[:300]
  except OSError:status=None
  if progress and status and status!=shown:progress(status);shown=status
  time.sleep(2)
 eu,lu=Path(unc(pc,ex)),Path(unc(pc,log))
 # Brief grace period for SMB visibility; absence is never success.
 for _ in range(5):
  if eu.is_file():break
  time.sleep(1)
 values=eu.read_text(encoding='utf-8-sig',errors='replace').splitlines() if eu.is_file() else []
 ec=values[0].strip() if values else 'not written'
 lines=lu.read_text(encoding='utf-8-sig',errors='replace').splitlines()[-100:] if lu.is_file() else []
 if activity is not None:activity.update(read_install_activity(activity_path) or {})
 return ec,lines

class Deploy(BaseModel):computer:str;folder:str;script:str;action:Literal['Install','Uninstall','Repair']='Install';fresh:bool=False;threads:int=Field(8,ge=1,le=128);mode:Literal['full','copy','execute']='full';sha256:str|None=Field(None,pattern=r'^[a-f0-9]{64}$')
class Bulk(BaseModel):computers:list[str]=Field(min_length=1,max_length=200);folder:str;script:str;action:Literal['Install','Uninstall','Repair']='Install';fresh:bool=False;threads:int=Field(8,ge=1,le=128);concurrency:int=Field(5,ge=1,le=10)
class Kill(BaseModel):computer:str;value:str;created:str|None=None;name:str|None=None;match:Literal['exact','contains']='exact'
class Machine(BaseModel):computer:str
class ServiceControl(Machine):
 name:str=Field(min_length=1,max_length=256)
 expected_identity:str=Field(pattern=r'^[a-f0-9]{64}$')
class QueueItem(BaseModel):
 computer:str;folder:str;script:str;action:Literal['Install','Uninstall','Repair']='Install';fresh:bool=False;threads:int=Field(8,ge=1,le=128);mode:Literal['full','copy','execute']='full'
class QueueRequest(BaseModel):
 items:list[QueueItem]

import weakref
target_locks=weakref.WeakValueDictionary()
def start_job(fn,j,*args):
 try:
  job_service.save(j);return job_service.submit(fn,j,*args)
 except Exception as error:
  emit(j,str(error),'failed');history_update(j,state='failed',details=str(error));raise

def target_lock(pc):
 with lock:return target_locks.setdefault(pc,TargetLock(pc))

def outcome(ec):
 # Deployment status confirms launch, never installation success.
 return 'launched','Launched'


def file_sha256(path):
 h=hashlib.sha256()
 with open(path,'rb') as source:
  for block in iter(lambda:source.read(1<<20),b''):h.update(block)
 return h.hexdigest()

def deploy_worker(j,p):
 with job_service.execution:
  return _deploy_worker(j,p)

def _deploy_worker(j,p):
 acquired=False;guard=None;launched=False
 try:
  validate_deployment(p);pc=p.computer;job_service.target_ready(pc);jobs[j]['target']=pc;pkg=Path(p.folder).name
  guard=target_lock(pc);acquired=guard.acquire(blocking=False)
  if not acquired:raise RuntimeError('Another deployment or cleanup is active on this target')
  job_service.target_ready(pc)
  remote=rf'{REMOTE_ROOT}\{pkg}\{p.script}'
  emit(j,'Validating target access','running');history_update(j,state='running')
  if not os.path.isdir(unc(pc)):raise RuntimeError('Target administrative share is unavailable')
  # An approved request (Axis) names the script's digest: run exactly that script or nothing. Queue items have none.
  approved=getattr(p,'sha256',None)
  if approved and file_sha256(Path(p.folder)/p.script)!=approved:raise RuntimeError('Installer changed after approval; nothing was copied or launched')
  if p.mode!='execute':
   emit(j,'Copying package...');rc=copy_pkg(p.folder,unc(pc,rf'{REMOTE_ROOT}\{pkg}'),p.fresh,p.threads)
   emit(j,f'Copy complete. Robocopy: {rc}');history_update(j,robocopy_code=str(rc))
  if approved and file_sha256(unc(pc,remote))!=approved:raise RuntimeError('The installer on the target differs from the approved script; it was not launched')
  if p.mode=='copy':
   emit(j,'Copy-only completed','complete');history_update(j,state='complete',finished=time.strftime('%Y-%m-%d %H:%M:%S'));return
  pid,log,ex=launch(pc,remote,pkg);launched=True;emit(j,'Launched',pid=pid);history_update(j,pid=str(pid))
  activity={};ec,lines=monitor(pc,pid,log,ex,lambda status:emit(j,status),activity);state,message=outcome(ec)
  if not re.fullmatch(r'-?\d+',str(ec).strip()):
   # No exit record is no outcome: hold the PC until someone inspects it and acknowledges, as after a lost monitor.
   job_service.unresolved.add(pc);message='Launched; the installer left no exit code. Inspect the target, then acknowledge it in Operation recovery.'
   with lock:jobs[j]['recovery_required']=True
  elif install_unconfirmed(activity):
   # The script returned, but nothing confirms the installers it started have finished: the same open outcome.
   job_service.unresolved.add(pc);message=f'Launched; {install_unconfirmed(activity)}. Inspect the target, then acknowledge it in Operation recovery.'
   with lock:jobs[j]['recovery_required']=True
  elif describe_install_activity(activity):message+='; '+describe_install_activity(activity)
  emit(j,message,state,log=lines,exit_code=ec,**({'install':activity} if activity else {}))
  history_update(j,state=state,exit_code=str(ec),finished=time.strftime('%Y-%m-%d %H:%M:%S'),details=message+'\n'+'\n'.join(lines[-20:]))
 except Exception as e:
  state='launched' if launched else 'failed'
  if launched:job_service.unresolved.add(pc)
  if launched:jobs[j]['recovery_required']=True
  emit(j,'Launched' if launched else str(e),state,log=[str(e)] if launched else [])
  try:history_update(j,state=state,finished=time.strftime('%Y-%m-%d %H:%M:%S'),details=str(e))
  except Exception:logging.exception('Could not persist failed deployment')
  logging.exception('deployment failed')
 finally:
  if acquired:guard.release()

def bulk_worker(j,p):
 jobs[j].update(package=Path(p.folder).name,action=p.action,script=p.script,targets=list(p.computers))
 rows=[{'machine':pc,'copy':'Waiting','launch':'Waiting','pid':'','completion':'','exit_code':'','details':''} for pc in p.computers]
 jobs[j].update(state='running',phase='deploy',results=rows)
 def work(row):
  child=uuid.uuid4().hex;jobs[child]={'state':'queued','events':[],'started_at':time.time()}
  item=Deploy(computer=row['machine'],folder=p.folder,script=p.script,action=p.action,fresh=p.fresh,threads=p.threads)
  row.update(copy='Running',completion='Running',job=child)
  try:
   history_create(child,item.computer,Path(item.folder).name,item.action,item.script,item.mode,item.model_dump())
   deploy_worker(child,item)
   events=jobs[child]['events'];end=events[-1] if events else {}
   row.update(copy='Complete' if any('Copy complete' in e['message'] for e in events) else 'Failed',launch='Started' if any('pid' in e for e in events) else 'Not started',pid=next((e['pid'] for e in events if 'pid' in e),''),completion='Launched' if jobs[child]['state']=='launched' else ('Complete' if jobs[child]['state']=='complete' else 'Failed'),exit_code=end.get('exit_code',''),details=end.get('message',''))
  except Exception as exc:row.update(copy='Failed',launch='Not started',completion='Failed',details=str(exc));jobs[child]['state']='failed'
 try:
  with ThreadPoolExecutor(max_workers=p.concurrency) as pool:list(pool.map(work,rows))
 finally:
  jobs[j].update(state='complete',phase='complete');job_service.save(j)

class ClosingConnection(sqlite3.Connection):
 def __exit__(self,*args):
  try:return super().__exit__(*args)
  finally:self.close()

def master_db():
 if not MASTER_DB.is_file():raise RuntimeError(f'MasterDB missing: {MASTER_DB}')
 c=sqlite3.connect(MASTER_DB.resolve().as_uri()+'?mode=ro',uri=True,timeout=20,factory=ClosingConnection)
 c.row_factory=sqlite3.Row
 return c

def db():
 c=master_db()
 prepare_views(c)
 return c

@app.middleware('http')
async def local_only(request:Request,call_next):
 if request.client and request.client.host not in ('127.0.0.1','::1'):
  return JSONResponse({'detail':'Local access only'},status_code=403)
 if request.url.hostname not in ('127.0.0.1','localhost','::1'):
  return JSONResponse({'detail':'Invalid host'},status_code=403)
 if request.url.path.startswith('/api/') and request.headers.get('sec-fetch-site')=='cross-site':
  return JSONResponse({'detail':'Cross-site API requests are not allowed'},status_code=403)
 origin=request.headers.get('origin')
 if origin and origin != str(request.base_url).rstrip('/'):
  return JSONResponse({'detail':'Cross-origin requests are not allowed'},status_code=403)
 response=await call_next(request)
 # Assets keep conditional caching, but every navigation must check for updates.
 # Otherwise a new shared card can run alongside an older cached console script.
 response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
 response.headers['Content-Security-Policy']="frame-ancestors 'self'"
 response.headers['X-Frame-Options']='SAMEORIGIN'
 response.headers['X-Content-Type-Options']='nosniff'
 return response
@app.get('/api/health')
def health():
 u=m=v=0
 if DB.exists():
  with db() as c:
   from vdi_inventory import count
   u=c.execute('select count(*) from users').fetchone()[0];m=c.execute('select count(*) from machines').fetchone()[0];v=count(c)
 return {'identity':identity(),'users':u,'machines':m,'vdi_machines':v,'database':DB.exists(),'repository':REPO.is_dir(),'application':'Office Atlas','mode':'admin','version':__version__,'instance_id':os.environ.get('ATLAS_INSTANCE_ID'),'instance_root':str(ROOT)}



@app.get('/api/search')
def search(term:str,palette:bool=False):
 with db() as c:
  c.execute('begin')
  result=search_directory(c,term)
  if palette:
   from desk_directory import palette_search
   return palette_search(c,result)
  return result
@app.get('/api/user/{uid}')
def user(uid:str):
 with db() as c:
  c.execute('begin')
  rows=c.execute('select * from legacy_users where id=?',(int(uid[3:]),)).fetchall() if uid.startswith('id:') and uid[3:].isdigit() else exact_users(c,uid)
  if not rows:raise HTTPException(404,'User not found')
  if len(rows)!=1:raise HTTPException(409,'Ambiguous identity; select a user from search results')
  u=dict(rows[0]);return {'user':u,'machines':linked_machines(c,u['id'])}
def package_root(folder):
 base=REPO.resolve();raw=Path(folder);root=(raw if raw.is_absolute() else base/raw).resolve()
 if root.parent!=base or not root.is_dir():raise HTTPException(400,'Select an available package within the configured repository')
 return root

INSTALLER_SUFFIX={'Install':('_i','_install','_installs'),'Uninstall':('_u','_uninstall','_uninstalls'),'Repair':('_r','_repair','_repairs')}
def installer(folder,script,action):
 """The package folder, once its script is a .ps1/.vbs inside it named for the action."""
 root=package_root(folder);path=Path(script)
 if not script or path.is_absolute() or '..' in path.parts or ':' in script:
  raise HTTPException(400,'Invalid installer path')
 target=(root/path).resolve()
 if root not in target.parents or not target.is_file() or target.suffix.lower() not in ('.ps1','.vbs') or not target.stem.lower().endswith(INSTALLER_SUFFIX[action]):
  raise HTTPException(400,'Installer does not match the selected package and action')
 return root

def validate_deployment(p):
 p.computer=validate_pc(p.computer)
 p.folder=str(installer(p.folder,p.script,p.action));return p

@app.get('/api/packages')
def packages(term:str=''):
 try:
  if not REPO.is_dir():
   return {'packages':[], 'repository':str(REPO), 'available':False, 'error':'Repository folder is unavailable. Check Settings and OneDrive sync.'}
  names=sorted([x.name for x in REPO.iterdir() if x.is_dir() and term.lower() in x.name.lower()],key=str.lower)
  return {'packages':names[:500], 'repository':str(REPO), 'available':True, 'total':len(names), 'truncated':len(names)>500}
 except OSError:
  return {'packages':[], 'repository':str(REPO), 'available':False, 'error':'Cannot read the repository. Check folder access and OneDrive sync.'}
@app.get('/api/scripts')
def scripts(package:str,action:str='Install'):
 if action not in ('Install','Uninstall','Repair'):raise HTTPException(400,'Invalid action')
 root=package_root(package);suffix=INSTALLER_SUFFIX[action]
 return {'scripts':sorted(str(x.relative_to(root)) for x in root.rglob('*') if x.is_file() and root in x.resolve().parents and x.suffix.lower() in ('.ps1','.vbs') and x.stem.lower().endswith(suffix))}
@app.get('/api/preflight/{pc}')
def preflight(pc:str):
 pc=validate_pc(pc);checks={'ping':has_echo_reply(run(['ping.exe','-4','-n','1','-w','1200',pc],False,timeout=5)),'c_share':os.path.isdir(unc(pc))}
 try:checks['wmi']=ps(f'[bool](Get-WmiObject -ComputerName {quote(pc)} Win32_OperatingSystem -EA Stop)').lower()=='true'
 except:checks['wmi']=False
 return checks
@app.post('/api/deploy')
def deploy(p:Deploy):
 validate_deployment(p);job_service.target_ready(p.computer)
 j=uuid.uuid4().hex;jobs[j]={'state':'queued','events':[]};history_create(j,p.computer,Path(p.folder).name,p.action,p.script,p.mode,p.model_dump());start_job(deploy_worker,j,p);return {'job':j}
@app.get('/api/deploy/{j}/payload')
def deployment_payload(j:str):
 """What a past deployment asked for, to add it to the queue again."""
 return Deploy(**saved_payload(j)).model_dump(exclude={'sha256'})
@app.post('/api/deploy/{j}/retry')
def retry_deployment(j:str):
 """Run a past deployment again with the same machine, package, script and options."""
 # The operator approves the retry here, for the script as it is now; an earlier approval's digest does not apply.
 payload=Deploy(**{k:v for k,v in saved_payload(j).items() if k!='sha256'})
 return {**deploy(payload),'target':payload.computer,'package':Path(payload.folder).name,'action':payload.action}
@app.get('/api/job/{j}')
def job(j:str):
 if j not in jobs:raise HTTPException(404,'Job not found')
 return job_service.snapshot(jobs,j)
@app.post('/api/bulk/deploy')
def bulk_deploy(p:Bulk):
 targets=list(dict.fromkeys(validate_pc(x) for x in p.computers))
 for pc in targets:validate_deployment(Deploy(computer=pc,folder=p.folder,script=p.script,action=p.action,fresh=p.fresh,threads=p.threads))
 p.computers=targets
 j=uuid.uuid4().hex;jobs[j]={'state':'queued','phase':'queued','results':[],'events':[],'started_at':time.time()}
 start_job(bulk_worker,j,p);return {'job':j}
@app.get('/api/bulk/job/{j}')
def bulk_job(j:str):
 if j not in jobs:raise HTTPException(404,'Job not found')
 return job_service.snapshot(jobs,j)
@app.get('/api/history')
def history(limit:int=100,today:bool=False):
 with hist_db() as c:
  where = ' where date(started)=date("now","localtime")' if today else ''
  rows=[dict(x) for x in c.execute('select * from deployments'+where+' order by started desc limit ?', (max(1,min(limit,500)),))]
 for row in rows:row.pop('payload',None)
 return rows
@app.get('/api/ping/{pc}')
def ping(pc:str):return {'online':has_echo_reply(run(['ping.exe','-4','-n','1','-w','1200',validate_pc(pc)],False,timeout=5))}
@app.get('/api/access/{pc}')
def access(pc:str):return {'available':os.path.isdir(unc(pc))}
@app.get('/api/overview/{pc}')
def overview(pc:str):
 pc=validate_pc(pc);out=ps(f"$o=Get-WmiObject -ComputerName {quote(pc)} Win32_OperatingSystem;$c=Get-WmiObject -ComputerName {quote(pc)} Win32_ComputerSystem;[pscustomobject]@{{Computer=$o.CSName;OS=$o.Caption;LastBoot=$o.ConvertToDateTime($o.LastBootUpTime);LoggedOn=$c.UserName;MemoryGB=[math]::Round($c.TotalPhysicalMemory/1GB,1)}}|ConvertTo-Json -Compress");return json.loads(out)
@app.get('/api/disk/{pc}')
def disk(pc:str):
 out=ps(f"Get-WmiObject -ComputerName {quote(validate_pc(pc))} Win32_LogicalDisk -Filter 'DriveType=3'|select DeviceID,@{{n='FreeGB';e={{[math]::Round($_.FreeSpace/1GB,1)}}}},@{{n='SizeGB';e={{[math]::Round($_.Size/1GB,1)}}}}|ConvertTo-Json -Compress");d=json.loads(out) if out else [];return d if isinstance(d,list) else [d]
@app.get('/api/processes/{pc}')
def processes(pc:str,kind:str='cpu'):
 import remote_processes,sys
 return remote_processes.list_processes(sys.modules[__name__],pc,kind)
@app.get('/api/performance/{pc}/threads/{pid}')
def performance_threads(pc:str,pid:int,created:str,name:str):
 import performance,sys
 return performance.collect(sys.modules[__name__],pc,'threads',pid=pid,created=created,name=name)
@app.get('/api/performance/{pc}')
def performance_snapshot(pc:str,kind:str='cpu'):
 import performance,sys
 return performance.collect(sys.modules[__name__],pc,kind)
@app.post('/api/kill')
def kill(p:Kill):
 import remote_processes,sys
 return remote_processes.terminate(sys.modules[__name__],p)
@app.post('/api/remote-registry/enable')
def enable_remote_registry(p:Machine):
 import service_actions,sys
 result=service_actions.enable_remote_registry(sys.modules[__name__],p.computer)
 logging.info('Enabled RemoteRegistry target=%s operator=%s previous_state=%s startup=%s',result['computer'],identity(),result['previous_state'],result['start_mode'])
 return result

@app.post('/api/services')
def list_services(p:Machine):
 import service_actions,sys
 return service_actions.list_services(sys.modules[__name__],p.computer)

@app.post('/api/services/stop')
def stop_service(p:ServiceControl):
 import service_actions,sys
 return service_actions.stop_service(sys.modules[__name__],p)

@app.post('/api/services/start')
def start_service(p:ServiceControl):
 import service_actions,sys
 return service_actions.start_service(sys.modules[__name__],p)

@app.post('/api/services/restart')
def restart_service(p:ServiceControl):
 import service_actions,sys
 return service_actions.restart_service(sys.modules[__name__],p)

@app.post('/api/reboot')
def reboot(p:Machine):
 pc=validate_pc(p.computer)
 job_service.target_ready(pc)
 return reboot_monitor.start(pc)

def request_reboot(pc):
 result=ps(f'$ErrorActionPreference="Stop";$o=Get-WmiObject -ComputerName {quote(pc)} Win32_OperatingSystem -EnableAllPrivileges -EA Stop;$o.Reboot().ReturnValue',timeout=30)
 if result.strip()!='0':raise RuntimeError('Windows rejected the reboot request (return '+result.strip()+')')

from reboot_monitor import RebootMonitor
reboot_monitor=RebootMonitor(request_reboot)

@app.get('/api/reboots')
def reboots():return reboot_monitor.snapshot()

@app.post('/api/reboots/{job_id}/stop')
def stop_reboot_monitor(job_id:str):return reboot_monitor.stop(job_id)

@app.on_event('shutdown')
def stop_reboot_monitors():reboot_monitor.shutdown()


def _start_local(args):
    subprocess.Popen(args, creationflags=NW)

def _start_msc(arguments):
    subprocess.Popen(['mmc.exe'] + arguments, creationflags=NW)

@app.post('/api/open-tool/{tool}/{pc}')
def open_target_tool(tool:str,pc:str):
    pc=validate_pc(pc)
    allowed={'msra','rdp','compmgmt','eventvwr','cshare','temp','packages','quickassist','remotehelp'}
    if tool not in allowed: raise HTTPException(400,'Unsupported tool')
    if tool=='msra': _start_local([r'C:\Windows\System32\msra.exe','/offerra',pc])
    elif tool=='rdp': _start_local([r'C:\Windows\System32\mstsc.exe','/v:'+pc])
    elif tool=='compmgmt': _start_msc(['compmgmt.msc','/computer='+pc])
    elif tool=='eventvwr': _start_msc(['eventvwr.msc','/computer='+pc])
    elif tool=='cshare': _start_local(['explorer.exe',unc(pc)])
    elif tool=='temp': _start_local(['explorer.exe',unc(pc,r'C:\Temp')])
    elif tool=='packages': _start_local(['explorer.exe',unc(pc,REMOTE_ROOT)])
    elif tool=='quickassist':
        candidates=[r'C:\Windows\System32\quickassist.exe',r'C:\Windows\System32\QuickAssist.exe']
        exe=next((x for x in candidates if Path(x).exists()),None)
        if exe:_start_local([exe])
        else:
            app_id=ps("$a=Get-StartApps|Where-Object {$_.Name -match '^Quick Assist$'}|Select-Object -First 1 -ExpandProperty AppID;if($a){$a}")
            if not app_id:raise RuntimeError('Quick Assist is not installed or not discoverable')
            _start_local(['explorer.exe','shell:AppsFolder\\'+app_id])
    elif tool=='remotehelp':
        app_id=ps("$a=Get-StartApps|Where-Object {$_.Name -match '^Remote Help$'}|Select-Object -First 1 -ExpandProperty AppID;if($a){$a}")
        if not app_id:raise RuntimeError('Microsoft Remote Help is not installed or not discoverable')
        _start_local(['explorer.exe','shell:AppsFolder\\'+app_id])
    logging.info('Opened tool=%s target=%s operator=%s',tool,pc,identity())
    return {'launched':True,'tool':tool,'computer':pc}

@app.get('/api/package-folder/{pc}')
def package_folder_info(pc:str):
    pc=validate_pc(pc);folders=files=size=0;locations=[]
    for staging in STAGING_ROOTS:
        root=Path(unc(pc,staging))
        if not root.exists() or staging_linked(root):continue
        locations.append(staging)
        for item in root.rglob('*'):
            try:
                if item.is_dir():folders+=1
                elif item.is_file():files+=1;size+=item.stat().st_size
            except OSError:pass
    return {'exists':bool(locations),'folders':folders,'files':files,'bytes':size,'locations':locations}

@app.post('/api/cleanup-packages/{pc}')
def cleanup_package_folder(pc:str):
    pc=validate_pc(pc);job_service.target_ready(pc);guard=target_lock(pc)
    if not guard.acquire(blocking=False):raise HTTPException(409,"A deployment is active on this target")
    try:
        job_service.target_ready(pc)
        return _cleanup_package_folder(pc)
    finally:guard.release()

def _cleanup_package_folder(pc:str):
    pc=validate_pc(pc);deleted=[];failed=[]
    roots=[(staging,Path(unc(pc,staging))) for staging in STAGING_ROOTS]
    if not any(root.exists() for _,root in roots):return {'deleted':0,'failed':0,'items':[],'message':'Package folder does not exist'}
    # Hard safety boundary: only children of the fixed staging roots are removed, never through a link.
    for staging,root in roots:
        label='' if staging==REMOTE_ROOT else 'Axis: '
        if staging_linked(root):
            failed.append({'item':staging,'error':'Staging path contains a link; not followed'});continue
        for item in list(root.iterdir()) if root.is_dir() else ():
            try:
                if item.is_dir():shutil.rmtree(item)
                else:item.unlink()
                deleted.append(label+item.name)
            except Exception as exc:failed.append({'item':label+item.name,'error':str(exc)})
    logging.warning('Package cleanup target=%s deleted=%s failed=%s operator=%s',pc,len(deleted),len(failed),identity())
    return {'deleted':len(deleted),'failed':len(failed),'items':deleted,'errors':failed}



queue_jobs=job_service.queues

def _queue_worker(queue_id,items):
 q=queue_jobs[queue_id];q['state']='running';job_service.save(queue_id,queue=True)
 try:
  for index,item in enumerate(items):
   # Claim the next item atomically with Pause/Cancel waiting. Once claimed it is current.
   with lock:
    row=q['items'][index]
    if row['state'] in TERMINAL:continue
    if q.get('cancel_requested'):
     q['state']='cancelled';return
    if q.get('pause_requested'):
     q['state']='paused';return
    row['state']='running';child=uuid.uuid4().hex
    jobs[child]={'state':'queued','target':item.computer,'events':[],'started_at':time.time()};row['job']=child;job_service.save(queue_id,queue=True)
   try:
    history_create(child,item.computer,Path(item.folder).name,item.action,item.script,item.mode,item.model_dump())
    deploy_worker(child,item)
    row.update(state=jobs[child]['state'],events=jobs[child].get('events',[]))
   except Exception as exc:
    jobs[child]['state']='failed';row.update(state='failed',events=[{'message':str(exc)}])
   job_service.save(child);job_service.save(queue_id,queue=True)
  q['state']='cancelled' if q.get('cancel_requested') else 'complete'
 except Exception as exc:q.update(state='failed',error=str(exc))
 finally:
  if q['state']=='cancelled':
   for row in q['items']:
    if row['state']=='waiting':row['state']='cancelled'
  job_service.save(queue_id,queue=True)

def queue_items(items,**details):
 """Check every item first, then run them one after another; nothing starts if any is refused."""
 if not items or len(items)>200:raise HTTPException(400,'Queue must contain 1 to 200 items')
 for item in items:
  validate_deployment(item);job_service.target_ready(item.computer)
 queue_id=uuid.uuid4().hex
 queue_jobs[queue_id]={'id':queue_id,'state':'queued','pause_requested':False,'started_at':time.time(),**details,'items':[{'target':x.computer,'package':Path(x.folder).name,'action':x.action,'mode':x.mode,'state':'waiting','events':[],'payload':x.model_dump()} for x in items]}
 job_service.save(queue_id,queue=True)
 try:job_service.submit(_queue_worker,queue_id,items)
 except Exception:
  queue_jobs[queue_id]['state']='cancelled';job_service.save(queue_id,queue=True);raise
 return {'queue':queue_id}

@app.post('/api/queue')
def start_queue(request:QueueRequest):return queue_items(request.items)

@app.get('/api/queue/{queue_id}')
def get_queue(queue_id:str):return job_service.snapshot(queue_jobs,queue_id)

@app.post('/api/queue/{queue_id}/pause')
def pause_queue(queue_id:str):
 with lock:
  q=queue_jobs.get(queue_id)
  if not q:raise HTTPException(404,'Queue not found')
  if q['state'] not in ('queued','running'):raise HTTPException(409,'Only a running queue can be paused')
  q['pause_requested']=True;job_service.save(queue_id,queue=True)
 return {'pause_requested':True}

@app.post('/api/queue/{queue_id}/resume')
def resume_queue(queue_id:str):
 with lock:
  q=queue_jobs.get(queue_id)
  if not q:raise HTTPException(404,'Queue not found')
  if q['state']!='paused':raise HTTPException(409,'Only a paused queue can be resumed')
  items=[QueueItem(**row['payload']) for row in q['items']]
  for item,row in zip(items,q['items']):
   if row['state']=='waiting':validate_deployment(item);job_service.target_ready(item.computer)
  q.update(state='queued',pause_requested=False);job_service.save(queue_id,queue=True)
  try:job_service.submit(_queue_worker,queue_id,items)
  except Exception:
   q['state']='paused';job_service.save(queue_id,queue=True);raise
 return {'queue':queue_id}

@app.post('/api/queue/{queue_id}/cancel')
def cancel_queue(queue_id:str):
 with lock:
  q=queue_jobs.get(queue_id)
  if not q:raise HTTPException(404,'Queue not found')
  q['cancel_requested']=True
  if q['state']=='paused':
   q['state']='cancelled'
   for row in q['items']:
    if row['state']=='waiting':row['state']='cancelled'
  job_service.save(queue_id,queue=True)
 return {'queue':queue_id,'state':q['state']}

@app.get('/api/operations/recovery')
def operation_recovery():return {'targets':sorted(job_service.unresolved)}

@app.post('/api/operations/recovery/{pc}')
def acknowledge_recovery(pc:str,body:dict):
 pc=validate_pc(pc)
 if body.get('confirmation')!=pc:raise HTTPException(400,'Type the exact hostname after inspecting the target')
 with lock:
  job_service.acknowledge(pc)
  for key,data in list(jobs.items()):
   if data.get('state') in ('unknown','interrupted') or data.get('recovery_required'):
    if data.get('target')==pc:data['recovery_acknowledged']=True
    data.setdefault('acknowledged_targets',[]).append(pc);job_service.save(key)
  for key,data in list(queue_jobs.items()):
   if data.get('state')=='interrupted':
    data.setdefault('acknowledged_targets',[]).append(pc);job_service.save(key,queue=True)
 return {'acknowledged':pc}

@app.get('/api/database-freshness')
def database_freshness():
    excel=ROOT/'templates'/'database040926.xlsx'
    db=DB
    return {'database_exists':db.exists(),'excel_exists':excel.exists(),'database_modified':datetime.fromtimestamp(db.stat().st_mtime).isoformat(sep=' ',timespec='seconds') if db.exists() else '', 'excel_modified':datetime.fromtimestamp(excel.stat().st_mtime).isoformat(sep=' ',timespec='seconds') if excel.exists() else '', 'excel_newer':bool(excel.exists() and db.exists() and excel.stat().st_mtime>db.stat().st_mtime), 'database_size':db.stat().st_size if db.exists() else 0}

def deployment_details(job_id,job):
    targets=job.get('targets') or [r.get('machine','') for r in job.get('results',[]) if r.get('machine')]
    details={'target':job.get('target',''),'package':job.get('package',''),'action':job.get('action',''),'script':job.get('script',''),'retry':not targets,'requested_by':job.get('requested_by','')}
    if targets:details['target']=', '.join(targets)
    # Older persisted jobs retain their original selection in deployment history.
    if not details['package']:
        with hist_db() as c:
            row=c.execute('select target,package,action,script from deployments where id=?',(job_id,)).fetchone()
            if row:details.update(dict(row))
    return details

def newest_first(pool):
    # Latest deployment first so it is visible without scrolling. Older saved jobs
    # without a start time keep their relative order below the timed ones.
    items=[(k,job_service.snapshot(pool,k)) for k in list(pool)]
    order={k:i for i,(k,_) in enumerate(items)}
    return sorted(items,key=lambda kv:(kv[1].get('started_at') or 0,order[kv[0]]),reverse=True)

@app.get('/api/deployments/active')
def active_deployments():
    active_states={'queued','running','monitoring','paused'}
    deployments=[]
    for job_id,job_data in newest_first(jobs):
        state=job_data.get('state','unknown')
        if state not in active_states:continue
        events=job_data.get('events',[])
        deployments.append({
            'id':job_id,
            **deployment_details(job_id,job_data),
            'kind':'single',
            'state':state,
            'started_at':job_data.get('started_at'),
            'events':events[-200:],
            'last_message':events[-1].get('message','') if events else '',
        })
    for queue_id,queue_data in newest_first(queue_jobs):
        state=queue_data.get('state','unknown')
        if state not in active_states:continue
        items=[]
        for item in queue_data.get('items',[]):
            items.append({
                'target':item.get('target',''),
                'package':item.get('package',''),
                'action':item.get('action',''),
                'state':item.get('state','waiting'),
                'events':item.get('events',[])[-100:],
            })
        deployments.append({'id':queue_id,'kind':'queue','state':state,'started_at':queue_data.get('started_at'),'persona':queue_data.get('persona'),'items':items})
    # Interleave single jobs and queues by start time; sorted() keeps ties stable.
    deployments.sort(key=lambda d:d.get('started_at') or 0,reverse=True)
    return {'count':len(deployments),'deployments':deployments}

@app.get('/api/deployments/recent')
def recent_deployments():
    result=[]
    for job_id,job_data in newest_first(jobs)[:20]:
        events=job_data.get('events',[])
        result.append({
            'id':job_id,'kind':'single','state':job_data.get('state','unknown'),
            **deployment_details(job_id,job_data),
            'events':events[-200:],
            'last_message':events[-1].get('message','') if events else ''
        })
    return {'deployments':result}



@app.get('/api/master/status')
def master_status():
    result={'available':MASTER_DB.exists(),'path':str(MASTER_DB),'users':0,'machines':0,'assignments':0}
    if not MASTER_DB.exists():return result
    try:
        with master_db() as c:
            result['users']=c.execute('select count(*) from users').fetchone()[0]
            result['machines']=c.execute('select count(*) from machines').fetchone()[0]
            from vdi_inventory import count
            result['vdi_machines']=count(c)
            result['assignments']=c.execute('select count(*) from assignments').fetchone()[0]
            row=c.execute("select value from metadata where key='created_at'").fetchone();result['created_at']=row[0] if row else ''
    except Exception as exc:result.update(available=False,error=str(exc))
    return result

@app.get('/api/master/resolve/{value}')
def master_resolve(value:str):
 from directory_lookup import resolve_directory
 with db() as c:
  c.execute('begin')
  return resolve_directory(c,value)

@app.get('/api/machine/{computer}')
def machine_record(computer:str):
 if not NAME_RE.fullmatch(computer) or computer.startswith(('-', '.')) or '..' in computer:raise HTTPException(400,'Invalid computer name')
 from desk_directory import machine_context
 with db() as c:
  result=machine_context(c,computer)
  if result is None:raise HTTPException(404,'Machine not found in directory')
  if result.get('ambiguous'):raise HTTPException(409,'Ambiguous VDI hostname; select its fully qualified name.')
  return result

app.mount('/assets',StaticFiles(directory=WEB/'assets'),name='assets')
@app.get('/installer')
def index():
 html=(WEB/'index.html').read_text(encoding='utf-8')
 # A changed asset gets a new URL, including when an older response was cached
 # before revalidation headers were introduced. Keep the static project simple.
 def version(match):
  stamp=(WEB/'assets'/match[2]).stat().st_mtime_ns
  return f'{match[1]}{match[2]}?v={stamp}{match[3]}'
 html=re.sub(r'((?:src|href)="/assets/)([^"?]+\.(?:js|css))(")',version,html)
 return HTMLResponse(html)

# Register the app files before Atlas's single-segment static fallback.
from pwa import register as register_pwa
register_pwa(app)
from atlas_api import register_atlas
register_atlas(app)
from psexec_runner import register as register_psexec
register_psexec(app,validate_pc)
from local_terminal import register as register_terminal
register_terminal(app)
# Scripts: built-in and saved PowerShell scripts run against a list of machines.
from script_library import register as register_scripts
from runtime_paths import scripts_path
register_scripts(app, scripts_path())
# Personas: saved software bundles, each installed on a machine as one deployment queue,
# with each desk's new joiner requests from the requests workbook; New joiners tracks both steps.
from personas import register as register_personas
from persona_access import Store as PersonaAccess
from joiners import register as register_joiners
from runtime_paths import personas_path, persona_access_path, joiners_path
persona_access_store=PersonaAccess(persona_access_path())
persona_store=register_personas(app, personas_path(), sys.modules[__name__], persona_access_store)
joiner_store=register_joiners(app, joiners_path(), sys.modules[__name__], persona_store, persona_access_store)

# Independent live health results; retains the application's local-only middleware.
from machine_health import register_machine_health
import sys as _health_sys
machine_health_checks=register_machine_health(app,_health_sys.modules[__name__])

# Queue reads existing activity; it never initiates remote scans.
from action_activity import register as register_activity
import sys
register_activity(app,sys.modules[__name__])

# Knowledge documents stay in the local Admin runtime, never in published assets.
from knowledge_base import register as register_knowledge
from runtime_paths import knowledge_path
# Articles first: "/api/knowledge/articles" must not be read as a diagram ID.
from knowledge_articles import register as register_articles
register_articles(app, knowledge_path())
register_knowledge(app, knowledge_path())

# Private local Outlook queue: intentionally absent from backend.viewer.
from mail_inbox import register as register_inbox
_inbox_catalogue={'at':0.0,'repo':None,'items':[]}
def inbox_packages():
 # Cached briefly: listing a OneDrive-synced share on every message click would be slow.
 now=time.monotonic();cache=_inbox_catalogue
 if cache['repo']==str(REPO) and now-cache['at']<120:return cache['items']
 from package_data import load,join_metadata
 names=sorted((p.name for p in REPO.iterdir() if p.is_dir()),key=str.casefold) if REPO.is_dir() else []
 with db() as c:
  saved={r['folder']:r['display_name'] for r in c.execute('select folder,display_name from package_catalog where repository=?',(str(REPO.resolve()),))}
  info=join_metadata(names,load(c,include_source=False))
 items=[{'folder':n,'display_name':saved.get(n) or (info.get(n) or {}).get('display_name') or n} for n in names]
 cache.update(at=now,repo=str(REPO),items=items)
 return items
def knowledge_diagrams():
 path=knowledge_path()
 if not path.is_file():return []
 c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5,factory=ClosingConnection)
 with c:
  rows=c.execute('select id,title,body from documents').fetchall()
 documents=[]
 for doc_id,title,body in rows:
  try:notes=json.loads(body).get('notes','')
  except (ValueError,AttributeError):notes=''
  documents.append({'id':doc_id,'title':title,'notes':str(notes)[:20000]})
 return documents
def inbox_documents():
 # Diagrams and articles; articles carry their tags and linked issue categories.
 from knowledge_articles import all_articles
 articles=[{'id':'article:'+a['id'],'title':a['title'],'notes':a['markdown'][:20000]+'\n'+' '.join(a['tags']),'categories':a['categories']}
           for a in all_articles(knowledge_path())]
 return knowledge_diagrams()+articles
register_inbox(app, db, packages=inbox_packages, documents=inbox_documents)
from package_matching import prewarm as prewarm_package_aliases
prewarm_package_aliases()

# Search everything (Admin only): articles, diagrams, Live Inbox requests and deployments.
import hashlib
from search_index import SearchIndex, register as register_search
def _signature(rows):
 return hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
def search_articles():
 from knowledge_articles import all_articles,plain_text
 from inbox_analysis import CATEGORIES
 labels={key:label for key,label,*_ in CATEGORIES}
 articles=all_articles(knowledge_path())
 rows=[{'ref':a['id'],'title':a['title'],'at':a['updated'],'extra':{'tags':a['tags'],'categories':a['categories']},
        'body':plain_text(a['markdown'])+'\n'+' '.join(a['tags'])+' '+' '.join(labels.get(c,c) for c in a['categories'])} for a in articles]
 return _signature([(a['id'],a['revision']) for a in articles]),rows
def search_diagrams():
 documents=knowledge_diagrams()
 return _signature([(d['id'],d['title'],d['notes']) for d in documents]),[{'ref':d['id'],'title':d['title'],'body':d['notes']} for d in documents]
def search_deployments():
 with hist_db() as c:
  rows=[dict(r) for r in c.execute('select id,started,finished,operator,target,package,action,state,details from deployments order by started desc limit 3000')]
 return _signature([(r['id'],r['state'],r['finished']) for r in rows]),[{'ref':r['id'],'title':f"{r['action'] or 'Deploy'} {r['package'] or ''} on {r['target'] or ''}",
   'body':' '.join(str(r[k] or '') for k in ('state','details','operator','package','target')),'at':r['started'] or '',
   'extra':{k:r[k] for k in ('target','package','action','state','finished')}} for r in rows]
def search_inbox(after):
 from mail_inbox import mail_directory,queue_reader
 with queue_reader(mail_directory()) as queue:
  if queue is None:return 0,[]
  newest=queue.execute('select coalesce(max(id),0) from messages').fetchone()[0]
  rows=queue.execute('select * from messages where id>? order by id limit 5000',(after,)).fetchall()
 return newest,[{'ref':r['id'],'title':r['subject'] or (r['body'] or '')[:80] or '(No subject)','at':r['received_at'],
   'body':f"{r['sender_name'] or ''} {r['sender_address'] or ''}\n{(r['body'] or '')[:20000]}",
   'extra':{'sender':r['sender_name'] or r['sender_address'] or ''}} for r in rows]
def search_message(message_id):
 from mail_inbox import mail_directory,queue_reader
 with queue_reader(mail_directory()) as queue:
  row=queue.execute('select subject,body from messages where id=?',(message_id,)).fetchone() if queue else None
 if row is None:raise HTTPException(404,'Message not found in the local inbox.')
 return dict(row)
search_index=SearchIndex(knowledge_path().parent/'search-index.sqlite3',
 {'article':search_articles,'diagram':search_diagrams,'deployment':search_deployments,'inbox':search_inbox})
register_search(app,search_index,search_message)
# The Atlas Companion runs in the operator's normal Windows session (clipboard, Outlook) and
# reports here; Live Inbox's collector switches control it once it has connected.
from inbox_control import register as register_inbox_control, InboxIntegration
from companion_server import register as register_companion, CompanionInbox
from runtime_paths import companion_state_path, companion_inbox_path
def _admin_token(request):
 from atlas_api import TOKEN
 if not secrets.compare_digest(request.headers.get('x-atlas-token',''),TOKEN):raise HTTPException(403,'Refresh the page before saving')
_companion=register_companion(app,sys.modules[__name__],_admin_token,companion_state_path,companion_inbox_path)
register_inbox_control(app,CompanionInbox(_companion,InboxIntegration()))

# Bundled open-source Draw.io static editor (no server-side editor endpoints).
app.mount('/drawio', StaticFiles(directory=ROOT/'frontend/drawio', html=True), name='drawio')

from active_directory import register as register_active_directory
register_active_directory(app, ps)
