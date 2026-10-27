"""Local GUI for staged directory refreshes. Never edits deployment workers."""
import asyncio,json,re,sqlite3,tempfile,time,uuid,hashlib,zipfile,shutil
from pathlib import Path
from fastapi import Request,HTTPException
from fastapi.responses import FileResponse,StreamingResponse
from starlette.concurrency import run_in_threadpool
from refresh_directory import prepare,apply_refresh,counts
from atlas_store import ClosingConnection
import directory_exports

def fingerprint(path):
 with sqlite3.connect(path,factory=ClosingConnection) as c:
  return fingerprint_connection(c)

def fingerprint_connection(c):
 h=hashlib.sha256()
 for t in ('users','machines','assignments','desk_user_links'):
  for row in c.execute('select * from '+t+' order by 1'):h.update(repr(tuple(row)).encode())
 if directory_exports.exists(c):
  for t in directory_exports.TABLES:
   for row in c.execute('select * from '+t+' order by 1,2'):h.update(repr(tuple(row)).encode())
 return h.hexdigest()

def compare_rows(before, after, *, key=lambda row: row):
 """Merge ordered unique keys, retaining at most 20 examples per side."""
 result={'before':0,'after':0,'added':0,'removed':0,'changed':0,'added_examples':[],'removed_examples':[]}
 old=next(before,None);new=next(after,None)
 while old is not None or new is not None:
  if new is None or (old is not None and key(old)<key(new)):
   result['before']+=1;result['removed']+=1
   if len(result['removed_examples'])<20:result['removed_examples'].append(key(old))
   old=next(before,None)
  elif old is None or key(new)<key(old):
   result['after']+=1;result['added']+=1
   if len(result['added_examples'])<20:result['added_examples'].append(key(new))
   new=next(after,None)
  else:
   result['before']+=1;result['after']+=1;result['changed']+=old!=new
   old=next(before,None);new=next(after,None)
 return result

def compare(target,candidate):
 with sqlite3.connect(target,factory=ClosingConnection) as a,sqlite3.connect(candidate,factory=ClosingConnection) as b:
  result={}
  for table,key in [('users','canonical_key'),('machines','machine_name_norm')]:
   def read(c):
    cols=[x[1] for x in c.execute('pragma table_info('+table+')')];ki=cols.index(key)
    keep=[i for i,column in enumerate(cols) if column!='id']
    return ((r[ki],tuple(r[i] for i in keep)) for r in c.execute('select * from '+table+' order by '+key))
   result[table]=compare_rows(read(a),read(b),key=lambda row:row[0])
  def links(c):return iter(c.execute('select distinct u.canonical_key,m.machine_name_norm,a.relationship_type from assignments a join users u on u.id=a.user_id_ref join machines m on m.id=a.machine_id order by 1,2,3'))
  relationship_changes=compare_rows(links(a),links(b))
  result['relationships']={key:relationship_changes[key] for key in ('before','after','added','removed')}
  result['missing_desk_accounts']=[{'desk':d,'account':k} for d,k in a.execute('select desk_id,user_key from desk_user_links') if not b.execute('select 1 from users where canonical_key=?',(k,)).fetchone()]
  result['warnings']=[f'{t}: more than 10% of existing records disappear.' for t in ('users','machines') if result[t]['removed']>result[t]['before']*.1]
  result['unlinked_machine_references']=b.execute("select count(*) from machines m where (trim(coalesce(assigned_to,''))<>'' or trim(coalesce(last_logon_user,''))<>'') and not exists(select 1 from assignments a where a.machine_id=m.id)").fetchone()[0]
  result['coverage']=directory_exports.coverage(b)
  resolution=b.execute("select value from metadata where key in ('import_resolution','directory.import_resolution') order by case key when 'directory.import_resolution' then 0 else 1 end limit 1").fetchone()
  result['import_resolution']=json.loads(resolution[0]) if resolution else {}
  for kind,label in (('user','Users'),('machine','Devices')):
   summary=result['import_resolution'].get(kind,{})
   if summary.get('conflicting_rows'):
    result['warnings'].append(f"{label}: {summary['conflicting_rows']:,} duplicate rows had different values; the newest record-updated date wins, otherwise the last row wins. All original rows are retained.")
  if result['import_resolution'].get('mobile_without_identifiers'):
   result['warnings'].append(f"{result['import_resolution']['mobile_without_identifiers']:,} mobile rows have no unique CI, serial or asset tag; kept as separate inventory records using source row IDs.")
  result['devices_without_hostnames']=sum(s['rows']-s['linked'] for s in result['coverage']['sheets'] if s['kind']=='machine')
  if result['devices_without_hostnames']:
   result['warnings'].append(f"{result['devices_without_hostnames']:,} device rows have no ci/name hostname; retained in the export archive, excluded from searchable machines.")
  def columns(coverage):
   return {(s['kind'] or s['sheet'].strip().casefold(),col['field'] or 'header:'+col['header'].strip().casefold()):s['sheet']+'.'+col['header'] for s in coverage['sheets'] for col in s['columns']}
  old_columns=columns(directory_exports.coverage(a));new_columns=columns(result['coverage'])
  missing=sorted(old_columns[k] for k in old_columns.keys()-new_columns.keys())
  if missing:result['warnings'].append('Columns absent from this snapshot: '+', '.join(missing))
  if directory_exports.exists(a) and not result['coverage']['original_cells']:
   result['warnings'].append('This older backup has no original export archive. Restoring it removes the current archive; stored directory fields remain.')
  return result

HISTORY_SCHEMA='create table if not exists directory_import_history(id text primary key,at text,source text,backup text,report text)'

def apply_directory(db,candidate,source,report,expected,busy=None):
 """Back up, then merge a prepared candidate; refused when the directory changed since `expected`.
 `busy` is checked again inside the write, for callers outside the HTTP mutation gate."""
 from datetime import datetime,timezone
 at=datetime.now(timezone.utc).isoformat()
 def validate_current(c):
  if fingerprint_connection(c)!=expected:raise HTTPException(409,'Directory or account links changed. Prepare a fresh preview.')
  if busy and busy():raise HTTPException(409,'Active jobs or queues must finish first.')
 def record_import(c,backup):
  c.execute(HISTORY_SCHEMA)
  c.execute('insert into directory_import_history values(?,?,?,?,?)',(uuid.uuid4().hex,at,source,str(backup),json.dumps(report)))
  c.execute('insert or replace into metadata values(?,?)',('directory.created_at',at))
 return apply_refresh(db,candidate,Path(db).parent/'backups',before_merge=validate_current,after_merge=record_import)

def register_database_manager(app,wmi,check_token):
 from urllib.parse import unquote
 root=Path(__file__).parent;staged={};gate=asyncio.Lock()
 with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:c.execute(HISTORY_SCHEMA)
 def busy():
  from shared_operations import axis_busy
  return any(j.get('state') not in ('complete','failed','cancelled','interrupted','unknown') for pool in (wmi.jobs,wmi.queue_jobs) for j in list(pool.values())) or axis_busy()
 def clean():
  for id,s in list(staged.items()):
   if time.time()-s['created']>3600:shutil.rmtree(s['folder'],ignore_errors=True);del staged[id]
 # Serialize mutations with imports so a new deployment cannot start between the job check and commit.
 @app.middleware('http')
 async def directory_mutation_gate(request,call_next):
  # Inventory runs against immutable scan data; directory reads do not mutate.
  independent=request.url.path in ('/api/software-tools/inventory','/api/software-tools/preview','/api/kill','/api/reboot') or request.url.path.startswith(('/api/open-tool/','/api/cleanup-packages/'))
  if request.method in ('POST','PUT','PATCH','DELETE') and not independent:
   async with gate:return await call_next(request)
  return await call_next(request)
 def stage(folder,source,candidate):
  clean()
  for s in staged.values():shutil.rmtree(s['folder'],ignore_errors=True)
  staged.clear();report=compare(wmi.MASTER_DB,candidate);id=uuid.uuid4().hex
  staged[id]={'folder':str(folder),'candidate':str(candidate),'source':source,'report':report,'fingerprint':fingerprint(wmi.MASTER_DB),'created':time.time()}
  return {'id':id,'source':source,'report':report,'expires_minutes':60}
 @app.get('/api/excel-templates/{kind}')
 def excel_template(kind:str):
  files={'seating-official':'users-and-desks-official-template.xlsx',
         'seating-previous':'users-and-desks-previous-template.xlsx',
         'directory':'users-and-computers-template.xlsx'}
  if kind not in files:raise HTTPException(404,'Choose a listed Excel template.')
  return FileResponse(root/'templates'/files[kind],filename=files[kind],media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
 @app.get('/manage-database')
 def manager_page():return FileResponse(root/'frontend/database.html')
 @app.get('/api/database/status')
 def status():
  with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:
   c.row_factory=sqlite3.Row;history=[dict(r) for r in c.execute('select id,at,source,report from directory_import_history order by at desc limit 30')]
   coverage=directory_exports.coverage(c)
  return {'counts':counts(wmi.MASTER_DB),'busy':busy(),'history':history,'coverage':coverage}
 @app.get('/api/directory/record')
 def export_record(kind:str,key:str):
  with sqlite3.connect(wmi.MASTER_DB.resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
   c.row_factory=sqlite3.Row
   try:result=directory_exports.record(c,kind,key)
   except ValueError as e:raise HTTPException(400,str(e))
  if result is None:raise HTTPException(404,'Directory record not found')
  return result
 @app.get('/api/database/export-archive')
 def export_archive():
  def lines():
   with sqlite3.connect(wmi.MASTER_DB.resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
    c.execute('begin')
    coverage=directory_exports.coverage(c)
    yield json.dumps({'type':'coverage',**coverage},ensure_ascii=False)+'\n'
    if coverage['original_cells']:
     for sheet,number,key,cells in c.execute('select sheet,row_number,entity_key,cells from directory_export_rows order by sheet,row_number'):
      yield json.dumps({'type':'row','sheet':sheet,'row':number,'key':key,'cells':json.loads(cells)},ensure_ascii=False)+'\n'
    else:
     c.row_factory=sqlite3.Row
     for kind,table in (('user','users'),('machine','machines')):
      for row in c.execute('select * from '+table+' order by id'):
       yield json.dumps({'type':'stored_record','kind':kind,'fields':{column:row[column] for _,column,_ in directory_exports.FIELDS[kind]}},ensure_ascii=False)+'\n'
  return StreamingResponse(lines(),media_type='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="atlas-directory-export.ndjson"'})
 @app.post('/api/database/preview')
 async def preview(request:Request):
  check_token(request)
  if busy():raise HTTPException(409,'Finish active jobs and queues before preparing an import.')
  folder=Path(tempfile.mkdtemp(prefix='atlas_directory_'));source=folder/'extract.xlsx';size=0
  try:
   with source.open('wb') as f:
    async for chunk in request.stream():
     size+=len(chunk)
     if size>50*1024*1024:raise ValueError('Excel file exceeds 50 MB.')
     f.write(chunk)
   with zipfile.ZipFile(source) as z:
    if sum(x.file_size for x in z.infolist())>512*1024*1024:raise ValueError('Expanded workbook exceeds 512 MB.')
   candidate=folder/'candidate.db'
   await run_in_threadpool(prepare,source,candidate)
   filename=Path(unquote(request.headers.get('x-file-name','extract.xlsx'))).name[:200]
   with sqlite3.connect(candidate,factory=ClosingConnection) as c:
    if directory_exports.exists(c):c.execute('update directory_export_sheets set source_file=?',(filename,))
   return await run_in_threadpool(stage,folder,filename,candidate)
  except Exception as e:
   shutil.rmtree(folder,ignore_errors=True)
   if isinstance(e,HTTPException):raise
   raise HTTPException(400,str(e) or 'Invalid workbook')
 # Two separate ServiceNow exports (users and devices, .xlsx or .csv, either order) in one request:
 # the first file's bytes, then the second's; x-first-size marks the split. Atlas combines them
 # into the usual users/devices workbook and previews it exactly like an uploaded workbook.
 @app.post('/api/database/preview-pair')
 async def preview_pair(request:Request):
  check_token(request)
  if busy():raise HTTPException(409,'Finish active jobs and queues before preparing an import.')
  try:first_size=int(request.headers.get('x-first-size',''))
  except ValueError:raise HTTPException(400,'Choose a users file and a devices file.')
  names=[Path(unquote(request.headers.get(h,default))).name[:120] for h,default in (('x-first-name','first'),('x-second-name','second'))]
  folder=Path(tempfile.mkdtemp(prefix='atlas_directory_'));paths=[folder/'first.bin',folder/'second.bin'];size=0
  try:
   if first_size<=0 or first_size>50*1024*1024:raise ValueError('Each export must be under 50 MB.')
   handles=[paths[0].open('wb'),paths[1].open('wb')]
   try:
    async for chunk in request.stream():
     while chunk:
      if size<first_size:
       take=chunk[:first_size-size];handles[0].write(take)
      else:
       take=chunk;handles[1].write(take)
       if size-first_size+len(take)>50*1024*1024:raise ValueError('Each export must be under 50 MB.')
      size+=len(take);chunk=chunk[len(take):]
   finally:
    for handle in handles:handle.close()
   if size<=first_size:raise ValueError('Choose both a users file and a devices file.')
   source=folder/'extract.xlsx'
   from directory_pair import combine
   # Keep the original names (one folder each) so messages say which file is wrong.
   for index,name in enumerate(names):
    (folder/str(index)).mkdir()
    paths[index]=paths[index].rename(folder/str(index)/(re.sub(r'[^\w.\- ()+]+','_',name).strip(' .') or 'export'))
   pair=await run_in_threadpool(combine,paths[0],paths[1],source)
   candidate=folder/'candidate.db'
   await run_in_threadpool(prepare,source,candidate)
   filename=(pair['users_file']+' + '+pair['devices_file'])[:200]
   with sqlite3.connect(candidate,factory=ClosingConnection) as c:
    if directory_exports.exists(c):c.execute('update directory_export_sheets set source_file=?',(filename,))
   staged_preview=await run_in_threadpool(stage,folder,filename,candidate)
   return {**staged_preview,'pair':pair}
  except Exception as e:
   shutil.rmtree(folder,ignore_errors=True)
   if isinstance(e,HTTPException):raise
   raise HTTPException(400,str(e) or 'Invalid export')
 @app.post('/api/database/restore-preview/{import_id}')
 def restore_preview(import_id:str,request:Request):
  check_token(request)
  if busy():raise HTTPException(409,'Finish active jobs and queues first.')
  with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:r=c.execute('select backup from directory_import_history where id=?',(import_id,)).fetchone()
  if not r or not Path(r[0]).is_file():raise HTTPException(404,'Backup unavailable')
  folder=Path(tempfile.mkdtemp(prefix='atlas_restore_'));candidate=folder/'candidate.db'
  with sqlite3.connect(r[0],factory=ClosingConnection) as a,sqlite3.connect(candidate,factory=ClosingConnection) as b:a.backup(b)
  return stage(folder,'Restore directory from '+Path(r[0]).name,candidate)
 @app.delete('/api/database/preview/{stage_id}')
 def discard(stage_id:str,request:Request):
  check_token(request);s=staged.pop(stage_id,None)
  if s:shutil.rmtree(s['folder'],ignore_errors=True)
  return {'ok':True}
 @app.post('/api/database/apply/{stage_id}')
 def apply(stage_id:str,body:dict,request:Request):
  check_token(request);clean();s=staged.get(stage_id)
  if not s:raise HTTPException(409,'Preview expired or was replaced. Validate the file again.')
  if body.get('confirmation')!='APPLY' or body.get('full_snapshot') is not True:raise HTTPException(400,'Confirm the complete intended directory snapshot and type APPLY.')
  if busy():raise HTTPException(409,'Active jobs or queues must finish first.')
  backup=apply_directory(wmi.MASTER_DB,s['candidate'],s['source'],s['report'],s['fingerprint'])
  del staged[stage_id];shutil.rmtree(s['folder'],ignore_errors=True)
  return {'ok':True,'backup':backup.name,'counts':counts(wmi.MASTER_DB)}

 from desk_moves import register_desk_moves
 register_desk_moves(app,wmi,check_token,busy)

 from seating_excel import register_seating_excel
 register_seating_excel(app,wmi,check_token,busy)
 # Live floor plan: the assistants' desk-plan Excel keeps official seating current.
 from seating_sync import register as register_seating_sync
 register_seating_sync(app,wmi,check_token,busy,Path(wmi.MASTER_DB).resolve().parent/'seating-sync.json')
 # Import folder: exports saved in one folder (C:\AtlasXL by default) update the database by themselves.
 from import_folder import register as register_import_folder
 register_import_folder(app,wmi,check_token,busy,Path(wmi.MASTER_DB).resolve().parent/'import-folder.json')
