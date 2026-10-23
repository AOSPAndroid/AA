"""Bulk occupant moves between existing desks, including swaps and cycles."""
import io,json,sqlite3,tempfile,time,uuid,zipfile
from pathlib import Path
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from fastapi import Request,HTTPException
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response
import atlas_store as store
from directory_workbook import workbook_parts,iter_rows
from atlas_store import ClosingConnection
HEADERS=['Desk ID','Floor','Current name','Team','Account','Occupancy','Type','X','Y','Angle','Revision','Move to desk']
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def snapshot(c):
 records={r['id']:r for r in store.all_records(c)}
 if c.execute("select 1 from sqlite_master where name='official_records'").fetchone():records.update({id:dict(json.loads(b),layout='official') for id,b in c.execute('select id,body from official_records')})
 links={r[0]:r[1] for r in c.execute('select desk_id,user_key from desk_user_links')}
 return records,links

def plan_moves(c,rows):
 records,links=snapshot(c);seen={};moves={}
 for row in rows:
  row=list(row)+['']*(12-len(row));id=str(row[0]).strip()
  if not id:continue
  if id in seen:raise ValueError('Duplicate source row: '+id)
  if id not in records:raise ValueError('Unknown desk: '+id)
  seen[id]=row;dest=str(row[11]).strip()
  if dest and dest!=id:moves[id]=dest
 if not moves:raise ValueError('No moves entered. Fill the Move to desk column.')
 if len(set(moves.values()))!=len(moves):raise ValueError('Two occupants cannot move to the same destination.')
 affected=set(moves)|set(moves.values())
 for id in affected:
  if id not in records or id not in seen:raise ValueError('Keep the destination row in the workbook: '+id)
  r=records[id];row=seen[id]
  if r['kind']!='desk':raise ValueError(id+' is an area, not a desk.')
  try:revision=int(str(row[10]))
  except ValueError:raise ValueError('Invalid revision for '+id)
  if revision!=r['revision']:raise ValueError(id+' changed after export. Export again.')
  if str(row[2])!=r['name'] or str(row[3])!=r['team']:raise ValueError('Edit Move to desk only. Name or team changed at '+id)
 for src,dest in moves.items():
  if records[src].get('layout')!=records[dest].get('layout'):raise ValueError('Use Carry over previous seating to map between layouts.')
  if records[src]['occupancy']=='vacant' or records[src]['name'] in ('Unconfirmed desk','Vacant desk','Unassigned','Unnamed desk'):raise ValueError(src+' has no recorded occupant to move.')
  if records[dest]['occupancy']!='vacant' and dest not in moves:raise ValueError(dest+' is occupied or unconfirmed. Move its occupant out in this batch, or vacate it first in Atlas.')
 return {'moves':moves,'records':{id:records[id] for id in affected},'links':{id:links.get(id) for id in affected},'summary':[{'person':records[src]['name'],'from':src,'to':dest} for src,dest in moves.items()]}

def apply_moves(db,plan,backup_folder):
 # Caller serializes API mutations and blocks active jobs; transaction rechecks all affected records.
 folder=Path(backup_folder);folder.mkdir(parents=True,exist_ok=True)
 backup=folder/('office_atlas_before_moves_'+uuid.uuid4().hex+'.db')
 with sqlite3.connect(db,factory=ClosingConnection) as a,sqlite3.connect(backup,factory=ClosingConnection) as b:a.backup(b)
 with sqlite3.connect(db,factory=ClosingConnection) as c:
  c.execute('begin immediate');records,links=snapshot(c)
  for id,old in plan['records'].items():
   if records.get(id)!=old or links.get(id)!=plan['links'][id]:raise ValueError(id+' changed after preview. Export and preview again.')
  batch=uuid.uuid4().hex;action='bulk desk move '+batch;at=datetime.now(timezone.utc).isoformat();updates={}
  for id in plan['records']:updates[id]=dict(records[id])
  for src in plan['moves']:updates[src].update(name='Vacant desk',team='Unassigned',occupancy='vacant',verified=False)
  newlinks={id:None for id in plan['records']}
  for src,dest in plan['moves'].items():
   old=records[src];updates[dest].update(name=old['name'],team=old['team'],occupancy=old['occupancy'],verified=False);newlinks[dest]=plan['links'][src]
  for id,r in updates.items():
   store.save_record(c,r,records[id],action);c.execute('delete from desk_user_links where desk_id=?',(id,))
   if newlinks[id]:c.execute('insert into desk_user_links values(?,?,?,?)',(id,newlinks[id],'confirmed',at))
   c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(id,at,action,plan['links'][id],newlinks[id]))
 return backup.name

def export_workbook(db,layout="previous"):
 # Populate the pre-authored Excel template using OpenXML; no extra Windows dependency.
 with sqlite3.connect(db,factory=ClosingConnection) as c:
  records,links=snapshot(c);users=dict(c.execute('select canonical_key,user_id from users'))
 records={id:r for id,r in records.items() if r.get('layout','previous')==layout}
 rows=[[r['id'],r['floor'],r['name'],r['team'],users.get(links.get(r['id']),''),r['occupancy'],r['kind'],r['x'],r['y'],r['angle'],r['revision'],''] for r in sorted(records.values(),key=lambda r:r['id'])]
 template=Path(__file__).parent/'desk_moves_template.xlsx';out=io.BytesIO()
 with zipfile.ZipFile(template) as z,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as target:
  sheet=dict(workbook_parts(template))['Desk moves'];xml=ET.fromstring(z.read(sheet));data=xml.find(NS+'sheetData');styles={x.attrib['r'].rstrip('0123456789'):x.attrib.get('s') for x in data[1]}
  for row in list(data)[1:]:data.remove(row)
  for i,values in enumerate(rows,2):
   row=ET.SubElement(data,NS+'row',{'r':str(i),'ht':'30','customHeight':'1'})
   for j,v in enumerate(values):
    col=chr(65+j);attrs={'r':col+str(i)}
    if styles.get(col):attrs['s']=styles[col]
    cell=ET.SubElement(row,NS+'c',attrs)
    if isinstance(v,(int,float)):ET.SubElement(cell,NS+'v').text=str(v)
    else:cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,NS+'is'),NS+'t').text=str(v)
  dim=xml.find(NS+'dimension')
  if dim is not None:dim.set('ref','A1:L'+str(len(rows)+1))
  for name in z.namelist():target.writestr(name,ET.tostring(xml,encoding='utf-8',xml_declaration=True) if name==sheet else z.read(name).replace(b'524 saved locations',str(len(rows)).encode()+b' saved locations'))
 return out.getvalue()

def register_desk_moves(app,wmi,check_token,busy):
 staged={};root=Path(wmi.MASTER_DB).resolve().parent
 @app.get('/api/desk-moves/export')
 def export(layout:str="previous"):
  if layout not in ("previous","official"):raise HTTPException(400,"Choose official or previous layout")
  return Response(export_workbook(wmi.MASTER_DB,layout),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="Paris-Desk-Moves.xlsx"'})
 @app.post('/api/desk-moves/preview')
 async def preview(request:Request):
  check_token(request)
  if busy():raise HTTPException(409,'Finish active jobs and queues first.')
  raw=bytearray()
  async for chunk in request.stream():
   raw.extend(chunk)
   if len(raw)>10*1024*1024:raise HTTPException(413,'Desk workbook exceeds 10 MB')
  def prepare():
   with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'moves.xlsx';path.write_bytes(raw)
    with zipfile.ZipFile(path) as z:
     if sum(x.file_size for x in z.infolist())>50*1024*1024:raise ValueError('Expanded workbook exceeds 50 MB')
     part=dict(workbook_parts(path))['Desk moves']
     if ET.fromstring(z.read(part)).find('.//'+NS+'f') is not None:raise ValueError('Use plain values, not formulas, in Desk moves.')
    it=iter_rows(path,part);_,headers=next(it)
    if headers[:12]!=HEADERS:raise ValueError('Use the exported Desk moves workbook without changing headers.')
    rows=[r for _,r in it]
    if len(rows)>5000:raise ValueError('Too many desk rows')
    with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:plan=plan_moves(c,rows)
   return plan
  try:
   plan=await run_in_threadpool(prepare)
   staged.clear();id=uuid.uuid4().hex;staged[id]=(time.time(),plan)
   return {'id':id,'moves':plan['summary']}
  except (ValueError,KeyError,StopIteration,zipfile.BadZipFile,ET.ParseError) as e:raise HTTPException(400,str(e) or 'Invalid desk workbook')
 @app.post('/api/desk-moves/apply/{id}')
 def apply(id:str,body:dict,request:Request):
  check_token(request)
  if busy():raise HTTPException(409,'Finish active jobs and queues first.')
  item=staged.get(id)
  if not item or time.time()-item[0]>3600:raise HTTPException(409,'Preview expired. Upload again.')
  if body.get('confirmation')!='MOVE':raise HTTPException(400,'Type MOVE to apply this batch.')
  try:backup=apply_moves(wmi.MASTER_DB,item[1],root/'backups')
  except ValueError as e:raise HTTPException(409,str(e))
  del staged[id];return {'ok':True,'moves':len(item[1]['moves']),'backup':backup}
