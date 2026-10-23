"""Atlas desk register, directory resolution and deployment orchestration."""
import json,re,secrets,sqlite3,tempfile,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from fastapi import HTTPException,Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse,Response,JSONResponse
import atlas_store as store
from merge_data import atlas_schema,import_atlas
from desk_directory import resolve_person,desk_context as shared_context,person_desks
from static_responses import cached_file,prewarm
TOKEN=secrets.token_urlsafe(32)

def now():return datetime.now(timezone.utc).isoformat()


def register_atlas(app):
 from backend import main as wmi
 store.DB=wmi.MASTER_DB;store.initialize()
 with store.connect() as c:atlas_schema(c)

 def check_token(request):
  if not secrets.compare_digest(request.headers.get('x-atlas-token',''),TOKEN):raise HTTPException(403,'Refresh the page before saving')

 def desk(c,desk_id):
  r=store.get_record(c,desk_id)
  if not r:raise HTTPException(404,'Desk not found')
  return r

 resolution=resolve_person
 def context(c,r):
  result=shared_context(c,r)
  result['deployments']=[dict(x) for x in c.execute('select d.*,x.desk_id from desk_deployments x join deployments d on d.id=x.job_id where x.desk_id=? order by d.started desc limit 20',(r['id'],))]
  return result

 @app.get('/api/ops/audit')
 def audit():
  with wmi.db() as c:
   records=store.all_records(c);entries=[];by_user={};by_host={}
   for r in records:
    candidates,method=resolution(c,r);issues=[]
    named=bool(r.get('name','').strip()) and not re.match(r'^(unconfirmed desk|vacant desk|unnamed|unassigned|open|new location)(\b|$)',r['name'],re.I)
    if r['occupancy']!='vacant' and named:
     if r['kind']=='area' and candidates:issues.append('person-as-area')
     if r['kind']=='desk' or candidates:
      if method=='unmatched':issues.append('unmatched')
      if method=='ambiguous':issues.append('ambiguous')
      if method=='missing-linked-user':issues.append('missing-linked-user')
      if method in ('name-match','unconfirmed-name-match'):issues.append('unconfirmed-link')
     if len(candidates)==1:by_user.setdefault(candidates[0]['canonical_key'],[]).append(r['id'])
    hostname=r.get('hostname','').strip().upper()
    if hostname and r['kind']=='desk':by_host.setdefault(hostname,[]).append(r['id'])
    entries.append({'desk':r,'issues':issues,'match_method':method,'candidates':candidates,'related_desks':[]})
   duplicates={}
   for kind,groups in [('duplicate-person',by_user),('duplicate-hostname',by_host)]:
    for ids in groups.values():
     if len(ids)>1:
      for id in ids:duplicates.setdefault(id,[]).append((kind,ids))
   for e in entries:
    for kind,ids in duplicates.get(e['desk']['id'],[]):
     e['issues'].append(kind);e['related_desks']+= [id for id in ids if id!=e['desk']['id']]
    e['related_desks']=sorted(set(e['related_desks']))
   rows=[e for e in entries if e['issues']];counts={}
   for e in rows:
    for issue in e['issues']:counts[issue]=counts.get(issue,0)+1
   return {'rows':rows,'counts':counts,'map_scope':'Paris','directory_scope':'Europe','locations_checked':len(records),'generated_at':now(),'note':'Possible duplicate assignments can be legitimate. Review each location before changing it.'}

 @app.get('/api/catalog')
 def catalog(term:str=''):
  from package_data import load,join_metadata
  source={'available':wmi.REPO.is_dir()};repo=str(wmi.REPO.resolve())
  if not source['available']:source['error']='Repository unavailable. Check Settings and OneDrive sync.'
  with wmi.db() as c:
   metadata={r['folder']:dict(r) for r in c.execute('select * from package_catalog where repository=?',(repo,))}
   imported=load(c,include_source=False)
  # Enumerate once, without recursive scans. Filtering includes saved display names and versions.
  try:names=sorted([p.name for p in wmi.REPO.iterdir() if p.is_dir()],key=str.casefold) if source['available'] else []
  except OSError:names=[];source['error']='Cannot read repository';source['available']=False
  items=[];q=term.strip().casefold();enrichment=join_metadata(names,imported)
  for folder in names:
   m=metadata.get(folder,{})
   info=enrichment[folder] or {}
   item={'folder':folder,'display_name':m.get('display_name') or info.get('display_name') or folder,'version':m.get('version') or '', 'revision':m.get('revision',0),'state':info.get('state',''),'package_id':info.get('package_id','')}
   if not q or any(q in str(item[k]).casefold() for k in ('folder','display_name','version')):items.append(item)
  return {'items':items[:500],'total':len(items),'truncated':len(items)>500,'repository':str(wmi.REPO),'available':source['available'],'error':source.get('error')}

 @app.get('/api/catalog/details')
 def catalog_details(folder:str):
  from package_catalog import inspect_package
  from package_data import load,join_metadata,repository_names
  root=wmi.package_root(folder)
  with wmi.db() as c:
   row=c.execute('select * from package_catalog where repository=? and folder=?',(str(wmi.REPO.resolve()),root.name)).fetchone()
   imported=load(c,include_source=False)
  names,_,_=repository_names(wmi.REPO)
  info=join_metadata(names,imported).get(root.name)
  metadata=dict(row) if row else {'folder':root.name,'display_name':root.name,'version':'','revision':0}
  if info and not row:metadata['display_name']=info['display_name'] or root.name
  return {**metadata,**inspect_package(root),'package_data':{k:v for k,v in info.items() if k!='raw_json'} if info else None}

 @app.post('/api/catalog/metadata')
 def catalog_metadata(body:dict,request:Request):
  check_token(request);root=wmi.package_root(str(body.get('folder','')))
  name=body.get('display_name','');version=body.get('version','');revision=body.get('revision')
  if not isinstance(name,str) or not name.strip() or len(name)>160 or not isinstance(version,str) or len(version)>80 or not isinstance(revision,int):raise HTTPException(400,'Provide a name, version text and current revision')
  with store.connect() as c:
   c.execute('begin immediate');repo=str(wmi.REPO.resolve());row=c.execute('select revision from package_catalog where repository=? and folder=?',(repo,root.name)).fetchone()
   if revision!=(row[0] if row else 0):raise HTTPException(409,'Catalogue changed; reopen the package')
   c.execute('insert into package_catalog values(?,?,?,?,?,?) on conflict(repository,folder) do update set display_name=excluded.display_name,version=excluded.version,revision=excluded.revision,updated_at=excluded.updated_at',(repo,root.name,name.strip(),version.strip(),revision+1,now()))
  return {'saved':True,'revision':revision+1}

 @app.get('/api/palette/person/{uid}')
 def palette_person(uid:str):
  if not (uid.startswith('id:') and uid[3:].isdigit()) and ':' not in uid:raise HTTPException(400,'Select a directory result')
  with wmi.db() as c:
   c.execute('begin')
   person=c.execute('select * from legacy_users where id=?',(int(uid[3:]),)).fetchone() if uid.startswith('id:') and uid[3:].isdigit() else c.execute('select * from legacy_users where canonical_key=?',(uid,)).fetchone()
   if not person:raise HTTPException(404,'Person not found')
   return {'desks':person_desks(c,person)}

 @app.get('/api/session')
 def session():
  return JSONResponse({'token':TOKEN},headers={'Cache-Control':'no-store'})

 @app.get('/api/palette/desks')
 def palette_desks(request:Request):
  import hashlib
  with wmi.db() as c:
   records=[{key:r.get(key,'') for key in ('id','name','team','hostname','floor')} for (body,) in c.execute('select body from official_records order by id') for r in [json.loads(body)]]
  encoded=json.dumps({'records':records},ensure_ascii=False,separators=(',',':')).encode()
  etag='"'+hashlib.sha256(encoded).hexdigest()+'"'
  headers={'ETag':etag,'Cache-Control':'private, no-cache'}
  if request.headers.get('if-none-match')==etag:return Response(status_code=304,headers=headers)
  return Response(encoded,media_type='application/json',headers=headers)

 @app.get('/api/state')
 def state():
  with store.connect() as c:return {'records':store.all_records(c),'token':TOKEN,'storage':'SQLite','database':store.DB.name}

 @app.get('/api/history/{desk_id}')
 def desk_history(desk_id:str):
  with store.connect() as c:
   rows=c.execute('select at,action,before_json,after_json from history where desk_id=? order by seq desc limit 100',(desk_id,)).fetchall()
   links=c.execute('select at,action,before_key,after_key from desk_link_history where desk_id=? order by seq desc limit 100',(desk_id,)).fetchall()
  return {'history':[{'at':r[0],'action':r[1],'before':json.loads(r[2]) if r[2] else None,'after':json.loads(r[3])} for r in rows],'links':[{'at':r[0],'action':r[1],'before':r[2],'after':r[3]} for r in links]}

 @app.get('/api/backup')
 def backup():
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'office-atlas-backup.db'
   with store.connect() as src,sqlite3.connect(path,factory=store.ClosingConnection) as dest:src.backup(dest)
   return Response(path.read_bytes(),media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="office-atlas-backup.db"'})

 @app.post('/api/atlas/import-db')
 async def import_backup(request:Request):
  check_token(request)
  chunks=[];size=0
  async for chunk in request.stream():
   size+=len(chunk)
   if size>100_000_000:raise HTTPException(413,'Backup exceeds 100 MB')
   chunks.append(chunk)
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'atlas.db';path.write_bytes(b''.join(chunks))
   try:result=await run_in_threadpool(import_atlas,store.DB,path)
   except (ValueError,sqlite3.Error,KeyError,TypeError) as e:raise HTTPException(400,'Invalid Atlas backup: '+str(e))
  with store.connect() as c:result['records']=store.all_records(c)
  return result

 def clear_link(c,r,action):
  old=c.execute('select user_key from desk_user_links where desk_id=?',(r['id'],)).fetchone()
  if old:
   c.execute('delete from desk_user_links where desk_id=?',(r['id'],))
   c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(r['id'],now(),action,old[0],None))

 @app.post('/api/save')
 def save(body:dict,request:Request):
  check_token(request);incoming=body.get('records')
  if not isinstance(incoming,list) or not 1<=len(incoming)<=5000:raise HTTPException(400,'Provide 1 to 5000 records')
  try:
   with store.connect() as c:
    c.execute('begin immediate');ids=set()
    for item in incoming:
     r=store.validate(item)
     if r['id'] in ids:raise ValueError('Duplicate desk ID')
     ids.add(r['id']);old=store.get_record(c,r['id']);store.check_revision(old,item.get('revision',0))
     if old and (old['name']!=r['name'] or old['occupancy']!=r['occupancy'] or old['kind']!=r['kind']):clear_link(c,old,'occupant changed')
     store.save_record(c,r,old,'edit' if old else 'create')
    result=store.all_records(c)
   return {'records':result}
  except store.Conflict as e:raise HTTPException(409,str(e))
  except (ValueError,TypeError,KeyError) as e:raise HTTPException(400,str(e))

 @app.post('/api/vacate')
 def vacate(body:dict,request:Request):
  check_token(request)
  try:
   with store.connect() as c:
    c.execute('begin immediate');old=desk(c,body.get('id'))
    if old['kind']!='desk':raise ValueError('Select a desk')
    store.check_revision(old,body.get('revision'));clear_link(c,old,'desk vacated')
    store.save_record(c,dict(old,name='Vacant desk',team='Unassigned',occupancy='vacant',verified=False),old,'leaver / vacate')
    result=store.all_records(c)
   return {'records':result}
  except store.Conflict as e:raise HTTPException(409,str(e))
  except ValueError as e:raise HTTPException(400,str(e))

 @app.post('/api/move')
 def move(body:dict,request:Request):
  check_token(request)
  try:
   with store.connect() as c:
    c.execute('begin immediate');source=desk(c,body.get('source'));target=desk(c,body.get('target'))
    if source['id']==target['id'] or source['kind']!='desk' or target['kind']!='desk' or source['occupancy']!='assigned' or target['occupancy']!='vacant':raise ValueError('Move requires an assigned source and confirmed vacant destination')
    store.check_revision(source,body.get('sourceRevision'));store.check_revision(target,body.get('targetRevision'))
    link=c.execute('select user_key,method from desk_user_links where desk_id=?',(source['id'],)).fetchone()
    clear_link(c,source,'occupant moved');clear_link(c,target,'occupant moved in')
    store.save_record(c,dict(target,name=source['name'],team=source['team'],occupancy='assigned',verified=False),target,'move from '+source['id'])
    store.save_record(c,dict(source,name='Vacant desk',team='Unassigned',occupancy='vacant',verified=False),source,'move to '+target['id'])
    if link:
     c.execute('insert into desk_user_links values(?,?,?,?)',(target['id'],link[0],link[1],now()))
     c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(target['id'],now(),'occupant moved in',None,link[0]))
    result=store.all_records(c)
   return {'records':result}
  except store.Conflict as e:raise HTTPException(409,str(e))
  except ValueError as e:raise HTTPException(400,str(e))

 @app.get('/api/desks/{desk_id}/context')
 def desk_context(desk_id:str):
  with wmi.db() as c:return context(c,desk(c,desk_id))

 @app.post('/api/desks/{desk_id}/link')
 def link_user(desk_id:str,body:dict,request:Request):
  check_token(request)
  try:
   with wmi.db() as read:
    # Read-only master connection for directory evidence; mutation uses shared writable connection below.
    user=read.execute('select * from users where canonical_key=?',(body.get('user_key'),)).fetchone()
    if not user:raise HTTPException(404,'Directory user not found')
   with store.connect() as c:
    c.execute('begin immediate');r=desk(c,desk_id);store.check_revision(r,body.get('revision'))
    if r['kind'] not in ('desk','area'):raise HTTPException(400,'Select a desk or mapped area')
    old=c.execute('select user_key from desk_user_links where desk_id=?',(desk_id,)).fetchone()
    updated=dict(r,kind='desk',name=user['full_name'] or user['user_id'],team=user['department'] or user['business_unit'] or r['team'],occupancy='assigned',verified=False)
    store.save_record(c,updated,r,'link directory user')
    c.execute('insert or replace into desk_user_links values(?,?,?,?)',(desk_id,user['canonical_key'],'confirmed',now()))
    c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(desk_id,now(),'link directory user',old[0] if old else None,user['canonical_key']))
   with wmi.db() as c:return context(c,desk(c,desk_id))
  except store.Conflict as e:raise HTTPException(409,str(e))

 @app.get('/api/package-script')
 def script_preview(package:str,script:str,action:str='Install'):
  if action not in ('Install','Uninstall','Repair'):raise HTTPException(400,'Invalid action')
  p=wmi.Deploy(computer='PREVIEW',folder=package,script=script,action=action)
  wmi.validate_deployment(p);path=Path(p.folder)/p.script
  if path.stat().st_size>1_000_000:raise HTTPException(413,'Script exceeds 1 MB preview limit')
  raw=path.read_bytes();encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
  return {'name':p.script,'content':raw.decode(encoding,errors='replace')}

 @app.post('/api/desks/{desk_id}/deploy')
 def deploy_from_desk(desk_id:str,body:dict,request:Request):
  check_token(request)
  try:
   with wmi.db() as c:
    r=desk(c,desk_id);store.check_revision(r,body.get('revision'));ctx=context(c,r)
    if r['kind']!='desk':raise HTTPException(400,'Select a desk')
    expected=ctx['user']['canonical_key'] if ctx['user'] else None
    if body.get('user_key')!=expected:raise HTTPException(409,'The linked user changed; reload this desk')
    pc=wmi.validate_pc(body.get('computer',''))
    if pc not in {m['name'].upper() for m in ctx['machines']}:raise HTTPException(400,'Select a machine shown for this desk or user')
   p=wmi.Deploy(computer=pc,folder=body.get('folder',''),script=body.get('script',''),action=body.get('action','Install'),mode=body.get('mode','full'))
   wmi.validate_deployment(p);job=uuid.uuid4().hex
   with store.connect() as c:
    c.execute('begin immediate');store.check_revision(desk(c,desk_id),body.get('revision'))
    # Both deployment audit and desk association commit before the worker starts.
    c.execute('insert into deployments(id,started,operator,target,package,action,script,mode,state) values(?,?,?,?,?,?,?,?,?)',(job,now(),wmi.identity(),pc,Path(p.folder).name,p.action,p.script,p.mode,'queued'))
    c.execute('insert into desk_deployments values(?,?,?,?,?,?)',(job,desk_id,expected,pc,r['revision'],now()))
   wmi.jobs[job]={'state':'queued','target':pc,'events':[],'started_at':time.time()};wmi.start_job(wmi.deploy_worker,job,p)
   return {'job':job,'desk_id':desk_id,'computer':pc}
  except store.Conflict as e:raise HTTPException(409,str(e))
  except (ValueError,TypeError) as e:raise HTTPException(400,str(e))

 @app.get('/api/ops/settings')
 def settings():
  import sys,os
  return {'repository':str(wmi.REPO),'available':wmi.REPO.is_dir(),'database':store.DB.name,'python':sys.executable,'environment_override':bool(os.environ.get('WMI_PACKAGE_REPO'))}

 @app.post('/api/ops/settings')
 def save_settings(body:dict,request:Request):
  import os
  check_token(request)
  if os.environ.get('WMI_PACKAGE_REPO'):raise HTTPException(409,'Repository is controlled by WMI_PACKAGE_REPO. Change that environment variable and restart.')
  value=body.get('repository','')
  if not isinstance(value,str) or not value.strip():raise HTTPException(400,'Enter the repository path')
  path=Path(value).expanduser().resolve()
  if not path.is_dir():raise HTTPException(400,'This repository folder is not accessible')
  config=dict(wmi.CONFIG,package_repository=str(path));temporary=wmi.ROOT/('config.'+uuid.uuid4().hex+'.tmp')
  try:temporary.write_text(json.dumps(config,indent=2));os.replace(temporary,wmi.ROOT/'config.json')
  finally:temporary.unlink(missing_ok=True)
  wmi.CONFIG.update(config);wmi.REPO=path
  return {'repository':str(path),'available':True}

 from database_manager import register_database_manager
 register_database_manager(app,wmi,check_token)
 from package_data_api import register as register_package_data
 register_package_data(app,wmi,check_token)
 from vdi_data_api import register as register_vdi_data
 register_vdi_data(app,wmi,check_token)

 from official_atlas import register_official
 register_official(app,wmi,check_token)
 from remote_software import register_remote_software
 register_remote_software(app,wmi,check_token)
 # Reads only the operator's own session; never registered on the LAN viewer.
 from screen_reader import register as register_screen_reader
 register_screen_reader(app,wmi,check_token)
 from clipboard_history import register as register_clipboard
 from runtime_paths import clipboard_path
 register_clipboard(app,wmi,check_token,clipboard_path)
 from backend.axis_api import register as register_axis
 register_axis(app,wmi,check_token)

 @app.get('/legacy-atlas')
 def previous_atlas():
  from fastapi.responses import RedirectResponse
  return RedirectResponse('/')

 prewarm(store.ROOT/'official-data.json',store.ROOT/'studio-floor-2.svg')
 @app.get('/')
 def atlas_home():return FileResponse(store.ROOT/'official-index.html')

 @app.get('/{filename}')
 def atlas_asset(filename:str,request:Request):
  allowed={'service-actions.js','site-info.js','command-registry.js','command-palette.js','command-palette.css','catalogue.js','map-furniture.js','map-amenities.js','map-plan-details.js','official-app.js','camera-motion.js','map-cursor.js','official-data.json','official.css','style.css','data.json','operations.js','operations.css'}
  allowed|={'official-floor-'+str(n)+ext for n in range(-1,9) for ext in ('.jpg','.pdf')}
  allowed|={'studio-floor-'+str(n)+'.svg' for n in range(-1,9)}
  if filename not in allowed:raise HTTPException(404,'Not found')
  return cached_file(request,store.ROOT/filename)
