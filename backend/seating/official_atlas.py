"""Official plan register, kept separate from reconstructed seating until reviewed."""
import json
from fastapi import Request,HTTPException
from backend import atlas_store as store

def apply_visual_matches(c):
 """Apply reviewed positional matches once, without overwriting later edits."""
 from datetime import datetime,timezone
 path=store.ROOT/'visual-seating-matches.json'
 if not path.exists():return 0
 applied=0
 for match in json.loads(path.read_text(encoding='utf-8'))['matches']:
  source,target=match['source'],match['target']
  if c.execute('select 1 from official_seating_mappings where legacy_id=? or official_id=?',(source,target)).fetchone():continue
  src=store.get_record(c,source);dst=store.get_record(c,target)
  if not src or not dst:continue
  if any(src.get(k)!=match[v] for k,v in [('revision','sourceRevision'),('name','sourceName'),('x','sourceX'),('y','sourceY')]):continue
  if dst.get('revision',1)!=1 or dst['name']!='Unconfirmed desk':continue
  if c.execute('select 1 from desk_user_links where desk_id=?',(target,)).fetchone():continue
  note='Visually matched from '+source+'. '+match['evidence']+' Position inferred from previous seating plan; current occupancy not independently confirmed.'
  store.save_record(c,dict(dst,name=src['name'],team=src['team'],occupancy=src['occupancy'],verified=False,notes=note),dst,'Visual plan match from '+source)
  at=datetime.now(timezone.utc).isoformat()
  link=c.execute('select user_key,method from desk_user_links where desk_id=?',(source,)).fetchone()
  if link:
   c.execute('insert into desk_user_links values(?,?,?,?)',(target,link[0],link[1],at))
   c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(target,at,'Visual plan match from '+source,None,link[0]))
  c.execute('insert into official_seating_mappings values(?,?,?)',(source,target,at));applied+=1
 return applied

def register_official(app,wmi,check_token):
 with store.connect() as c:
  c.execute('create table if not exists official_records(id text primary key,body text not null)')
  c.execute('create table if not exists official_seating_mappings(legacy_id text primary key,official_id text unique,at text)')
  for r in json.loads((store.ROOT/'official-data.json').read_text())['records']:
   c.execute('insert or ignore into official_records values(?,?)',(r['id'],json.dumps(r)))
  apply_visual_matches(c)
 @app.get('/api/official/state')
 def state():
  from backend.atlas_api import TOKEN
  with store.connect() as c:return {'token':TOKEN,'records':[dict(json.loads(x[0]),layout='official') for x in c.execute('select body from official_records order by id')],'legacy':[json.loads(x[0]) for x in c.execute('select body from records order by id')],'mappings':dict(c.execute('select legacy_id,official_id from official_seating_mappings'))}
 @app.post('/api/official/map-occupant')
 def map_occupant(body:dict,request:Request):
  check_token(request)
  try:
   with store.connect() as c:
    c.execute('begin immediate');src=c.execute('select body from records where id=?',(body.get('source'),)).fetchone();dst=c.execute('select body from official_records where id=?',(body.get('target'),)).fetchone()
    if not src or not dst:raise ValueError('Choose a previous location and an official desk.')
    src,dst=json.loads(src[0]),json.loads(dst[0]);store.check_revision(src,body.get('sourceRevision'));store.check_revision(dst,body.get('targetRevision'))
    if src['occupancy']=='vacant' or src['name'] in ('Vacant desk','Unconfirmed desk'):raise ValueError('Previous location has no recorded person.')
    if dst['occupancy']=='assigned' or dst['name'] not in ('Unconfirmed desk','Vacant desk'):raise ValueError('The official desk already has an occupant. Review it before replacing.')
    if c.execute('select 1 from official_seating_mappings where legacy_id=? or official_id=?',(src['id'],dst['id'])).fetchone():raise ValueError('This seating mapping has already been used.')
    link=c.execute('select user_key,method from desk_user_links where desk_id=?',(src['id'],)).fetchone()
    store.save_record(c,dict(dst,name=src['name'],team=src['team'],occupancy=src['occupancy'],verified=False),dst,'Map occupant from previous desk '+src['id'])
    from datetime import datetime,timezone
    at=datetime.now(timezone.utc).isoformat()
    if link:
     c.execute('insert or replace into desk_user_links values(?,?,?,?)',(dst['id'],link[0],link[1],at))
     c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(dst['id'],at,'Mapped from '+src['id'],None,link[0]))
    c.execute('insert into official_seating_mappings values(?,?,?)',(src['id'],dst['id'],at))
   return {'saved':True}
  except (ValueError,store.Conflict) as e:raise HTTPException(409,str(e))
