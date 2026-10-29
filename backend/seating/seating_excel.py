"""Compare an Excel seating snapshot with live desks before an atomic import."""
import hashlib, io, json, sqlite3, tempfile, time, uuid, zipfile
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from fastapi import Request, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from backend import atlas_store as store
from backend.seating.desk_moves import snapshot
from backend.directory.directory_workbook import workbook_parts, iter_rows, canonical_header
from backend.directory.identity_links import key, build_index, candidates
from backend.atlas_store import ClosingConnection

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
HEADERS = ['Desk ID', 'Name', 'Team', 'Account', 'Status']
ALIASES = {'desk_id':'desk', 'desk':'desk', 'desk_number':'desk', 'desk_code':'desk',
           'name':'name', 'full_name':'name', 'user_name':'name', 'occupant':'name',
           'team':'team', 'department':'team', 'account':'account', 'login':'account',
           'username':'account', 'user_id':'account', 'email':'account', 'brid':'account',
           'status':'status', 'occupancy':'status'}

def layout_records(c, layout):
    if layout not in ('official', 'previous'):
        raise ValueError('Choose official or previous seating.')
    records, links = snapshot(c)
    return {d:r for d,r in records.items() if r['kind']=='desk' and r.get('layout','previous') == layout}, links

def stamp(c, layout):
    records, links = layout_records(c, layout)
    users = c.execute('select canonical_key,user_id,email,employee_number,full_name from users order by canonical_key').fetchall()
    aliases = list(c.execute('select user_id_ref,alias_type,alias_value,alias_norm from user_aliases order by user_id_ref,alias_type,alias_norm')) if c.execute("select 1 from sqlite_master where name='user_aliases' and type='table'").fetchone() else []
    return hashlib.sha256(json.dumps([records, sorted(links.items()), users, aliases],sort_keys=True).encode()).hexdigest()

def read_sheet(path):
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 2000 or sum(x.file_size for x in z.infolist()) > 50*1024*1024:
            raise ValueError('Expanded workbook exceeds seating import limits.')
        parts = workbook_parts(path)
        choices = [(n,p) for n,p in parts if canonical_header(n) in ('users_and_desks','seating')]
        if not choices and len(parts)==1: choices=parts
        if len(choices)!=1: raise ValueError('Name the seating worksheet Users and desks or Seating.')
        xml = ET.fromstring(z.read(choices[0][1]))
        if xml.find('.//'+NS+'f') is not None: raise ValueError('Use plain values, not formulas, in the seating worksheet.')
        if any(c.get('t')=='e' for c in xml.iter(NS+'c')): raise ValueError('Correct Excel error cells before importing.')
    with closing(iter_rows(path,choices[0][1])) as it:
        _, header=next(it)
        mapped=[ALIASES.get(canonical_header(h)) for h in header]
        known=[h for h in mapped if h]
        if len(known)!=len(set(known)): raise ValueError('Two columns map to the same field. Keep one Desk ID, Name, Team, Account and Status column.')
        if not {'desk','name'} <= set(known): raise ValueError('The sheet needs Desk ID and Name columns. Team, Account and Status are optional.')
        rows=[]
        for number, values in it:
            if len(rows)>=5000: raise ValueError('At most 5,000 seating rows are supported.')
            if not any(values): continue
            row={h:(values[i].strip() if i<len(values) else '') for i,h in enumerate(mapped) if h}
            row['_row']=number; rows.append(row)
        if not rows: raise ValueError('Empty sheet refused. Use explicit vacant rows to clear desks.')
        return rows

def account_index(c):
    index=build_index(c,canonical=True,include_names=False); users={}
    for canonical,login,email,employee,name in c.execute('select canonical_key,user_id,email,employee_number,full_name from users'):
        users[canonical]={'account':login or email or canonical,'name':name}
    return index, users

def occupied(r):
    return r['occupancy']!='vacant' and key(r['name']) not in ('','vacant desk','unconfirmed desk','unassigned','unnamed desk')

def plan_sheet(c, rows, layout='official', complete=False, labels=frozenset(), lenient=False):
    """labels: names of team/room labels ("Credit Sales") that are not people, so repeats are not duplicates.
    lenient: the plan is the authority (the live floor plan). Nothing blocks the update: rows Atlas cannot
    use are skipped, names it cannot link to one account are kept as written, a person placed twice is
    placed twice, and every such case is listed in report['notes']."""
    records, links=layout_records(c,layout); index, users=account_index(c)
    notes=[]
    def problem(message): (notes if lenient else errors).append(message)
    def occupant(r): return occupied(r) and not (r['occupancy']=='unconfirmed' and key(r['name']) in labels)
    name_links=defaultdict(set)
    for d,r in records.items():
        if occupant(r) and links.get(d): name_links[key(r['name'])].add(links[d])
    desired={}; warnings=[]; errors=[]
    for row in rows:
        d=row.get('desk','').strip(); prefix=f"Row {row.get('_row','?')}"
        if d not in records: problem(f'{prefix}: unknown desk in {layout} layout: {d or "(blank)"}.'); continue
        if d in desired: problem(f'{prefix}: duplicate desk {d}.'); continue
        old=records[d]; name=row.get('name','').strip(); account=row.get('account','').strip()
        status=key(row.get('status')) or ('assigned' if name or account else 'vacant')
        if status not in ('assigned','vacant','unconfirmed'): problem(f'{prefix}: Status must be assigned, vacant or unconfirmed.'); continue
        if status=='vacant' and (name or account): problem(f'{prefix}: a vacant desk must have blank Name and Account.'); continue
        link=None
        if account:
            found=candidates(index,account,allow_names=False)
            # Keep an existing unavailable canonical link when round-tripping an export.
            if not found and account==links.get(d): link=account; warnings.append(f'{d}: linked account is no longer in the directory.')
            elif len(found)!=1:
                if not lenient: errors.append(f'{prefix}: account {account} is unknown or ambiguous. Refresh the directory or correct Account.'); continue
                notes.append(f'{d}: {name or account} kept as written; account {account} is unknown or ambiguous.')
            else: link=next(iter(found))
            if not name: name=users.get(link,{}).get('name') or account
        elif name and status!='vacant':
            if key(name)==key(old['name']) and occupant(old): link=links.get(d)
            elif len(name_links[key(name)])==1: link=next(iter(name_links[key(name)]))
            elif len(name_links[key(name)])>1:
                if not lenient: errors.append(f'{prefix}: this name has multiple existing accounts. Fill Account.'); continue
                notes.append(f'{d}: {name} kept as written; several accounts have this name.')
            else: warnings.append(f'{d}: {name} has no confirmed account link; machine lookup remains unconfirmed. Fill Account to link explicitly.')
        if status=='assigned' and not name: problem(f'{prefix}: assigned desk needs a name or account.'); continue
        team=row.get('team',old['team']).strip() or 'Unassigned'
        label=name or (old['name'] if status==old['occupancy'] and not occupant(old) else ('Vacant desk' if status=='vacant' else 'Unconfirmed desk'))
        r=dict(old,name=label,team=team,occupancy=status)
        try: store.validate(r)
        except ValueError as e: problem(f'{prefix}: {e}'); continue
        desired[d]={'record':r,'link':link}
    # An identifiable person moving to a new desk also leaves their old desk.
    current_people=defaultdict(list)
    for d,r in records.items():
        if occupant(r): current_people[('account',links[d]) if links.get(d) else ('name',key(r['name']))].append(d)
    auto_vacated=[]
    for d,item in list(desired.items()):
        if not occupant(item['record']): continue
        person=('account',item['link']) if item['link'] else ('name',key(item['record']['name']))
        origins=current_people.get(person,[])
        # The sheet says where this person sits now (the Excel wins): every other desk it does not
        # mention is freed, including a desk still holding only their name with no account link.
        if item['link']: origins=list(dict.fromkeys(origins+current_people.get(('name',key(item['record']['name'])),[])))
        leaving=[o for o in origins if o!=d and o not in desired]
        for source in leaving:
            old=records[source]
            desired[source]={'record':dict(old,name='Vacant desk',team='Unassigned',occupancy='vacant'),'link':None}
            auto_vacated.append(source)
    if complete:
        for d,old in records.items():
            if d not in desired: desired[d]={'record':dict(old,name='Vacant desk',team='Unassigned',occupancy='vacant'),'link':None}
    final={d:desired.get(d,{'record':r,'link':links.get(d)}) for d,r in records.items()}
    # Only reject duplicates involving a supplied/cleared desk; unrelated historic issues stay untouched.
    seen=defaultdict(list)
    for d,item in final.items():
        if occupant(item['record']): seen[('account',item['link']) if item['link'] else ('name',key(item['record']['name']))].append(d)
    for identity, desks in seen.items():
        if len(desks)>1 and any(d in desired for d in desks):
            # Duplicates follow the Excel: whoever it places twice is placed twice, and it is listed.
            note='Same person on '+', '.join(sorted(desks))+' in the Excel: placed on each, as written.'
            notes.append(note)
            if not lenient: warnings.append(note)
    def identity(r,link): return ('account',link) if link else ('name',key(r['name']))
    before=defaultdict(list)
    for d,r in records.items():
        if occupant(r): before[identity(r,links.get(d))].append(d)
    changes=[]; updates={}
    for d,item in desired.items():
        old=records[d]; new=item['record']; link=item['link']
        fields=[k for k in ('name','team','occupancy') if old[k]!=new[k]]
        if links.get(d)!=link: fields.append('account')
        if not fields: continue
        new=dict(new,verified=False); updates[d]={'record':new,'link':link}
        origin=before.get(identity(new,link),[]) if occupant(new) else []
        kind='vacated' if new['occupancy']=='vacant' else ('moved' if len(origin)==1 and origin[0]!=d else ('assigned' if not occupant(old) or identity(old,links.get(d))!=identity(new,link) else 'updated'))
        def display(r,k): return {'name':r['name'],'team':r['team'],'status':r['occupancy'],'account':users.get(k,{}).get('account',k or '')}
        changes.append({'desk':d,'kind':kind,'from_desk':origin[0] if kind=='moved' else None,'fields':fields,'before':display(old,links.get(d)),'after':display(new,link)})
    report={'changes':changes,'errors':sorted(set(errors)),'warnings':sorted(set(warnings)),'notes':list(dict.fromkeys(notes)), 'unchanged':len(desired)-len(updates),'omitted':len(records)-len({r.get('desk') for r in rows}&set(records)), 'auto_vacated':auto_vacated,'complete':complete,'layout':layout,'rows':len(rows)}
    return {'fingerprint':stamp(c,layout),'layout':layout,'updates':updates,'report':report}

def apply_sheet(db, plan, folder, source):
    if plan['report']['errors']: raise ValueError('Resolve workbook conflicts before applying.')
    if not plan['updates']: raise ValueError('No changes to apply.')
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    backup=folder/('office_atlas_before_seating_'+uuid.uuid4().hex+'.db')
    with sqlite3.connect(db,timeout=15,factory=ClosingConnection) as c:
        c.execute('begin immediate')
        if stamp(c,plan['layout'])!=plan['fingerprint']: raise store.Conflict('Seating or directory changed after preview. Upload again to compare the latest data.')
        # A separate read connection snapshots committed state while this write lock prevents other writers.
        with sqlite3.connect(db,factory=ClosingConnection) as reader, sqlite3.connect(backup,factory=ClosingConnection) as dest: reader.backup(dest)
        batch=uuid.uuid4().hex; at=datetime.now(timezone.utc).isoformat(); action='Excel seating import '+batch
        for d,item in plan['updates'].items():
            old=store.get_record(c,d); prior=c.execute('select user_key from desk_user_links where desk_id=?',(d,)).fetchone()
            store.save_record(c,item['record'],old,action)
            if (prior[0] if prior else None)!=item['link']:
                c.execute('delete from desk_user_links where desk_id=?',(d,))
                if item['link']: c.execute('insert into desk_user_links values(?,?,?,?)',(d,item['link'],'confirmed',at))
                c.execute('insert into desk_link_history(desk_id,at,action,before_key,after_key) values(?,?,?,?,?)',(d,at,action,prior[0] if prior else None,item['link']))
        c.execute('create table if not exists seating_import_history(id text primary key,at text,source text,backup text,report text)')
        c.execute('insert into seating_import_history values(?,?,?,?,?)',(batch,at,source,str(backup),json.dumps(plan['report'])))
    return backup.name

def workbook_bytes(rows):
    # Small native XLSX with inline text cells: no formulas, external links or new runtime dependency.
    sheet=ET.Element('worksheet',xmlns=NS[1:-1]); views=ET.SubElement(sheet,'sheetViews'); view=ET.SubElement(views,'sheetView',workbookViewId='0'); ET.SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
    cols=ET.SubElement(sheet,'cols')
    for i,width in enumerate((22,32,28,28,18),1): ET.SubElement(cols,'col',min=str(i),max=str(i),width=str(width),customWidth='1')
    data=ET.SubElement(sheet,'sheetData')
    for i,values in enumerate([HEADERS]+rows,1):
        row=ET.SubElement(data,'row',r=str(i))
        for j,value in enumerate(values):
            cell=ET.SubElement(row,'c',r=chr(65+j)+str(i),t='inlineStr'); ET.SubElement(ET.SubElement(cell,'is'),'t').text=str(value or '')
    ET.SubElement(sheet,'autoFilter',ref='A1:E'+str(len(rows)+1))
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Users and desks" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',ET.tostring(sheet,encoding='utf-8',xml_declaration=True))
    return out.getvalue()

def export_sheet(db,layout):
    with sqlite3.connect(db,factory=ClosingConnection) as c:
        records,links=layout_records(c,layout); _,users=account_index(c)
    return workbook_bytes([[d,r['name'] if occupied(r) else '',r['team'],users.get(links.get(d),{}).get('account',links.get(d,'')) if occupied(r) else '',r['occupancy']] for d,r in sorted(records.items())])

def register_seating_excel(app,wmi,check_token,busy):
    staged={}; root=Path(wmi.MASTER_DB).resolve().parent
    @app.get('/api/seating-excel/export')
    def export(layout:str='official'):
        try: data=export_sheet(wmi.MASTER_DB,layout)
        except ValueError as e: raise HTTPException(400,str(e))
        return Response(data,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="Users-and-desks-{layout}.xlsx"'})
    @app.get('/api/seating-excel/history')
    def history():
        with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:
            if not c.execute("select 1 from sqlite_master where name='seating_import_history'").fetchone():return []
            return [{'at':a,'source':s,'changes':len(json.loads(r)['changes'])} for a,s,r in c.execute('select at,source,report from seating_import_history order by at desc limit 30')]
    @app.post('/api/seating-excel/preview')
    async def preview(request:Request,layout:str='official',complete:bool=False):
        check_token(request)
        if busy(): raise HTTPException(409,'Finish active jobs and queues first.')
        staged.clear(); raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>10*1024*1024: raise HTTPException(413,'Seating workbook exceeds 10 MB.')
        def prepare():
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/'seating.xlsx'; p.write_bytes(raw); rows=read_sheet(p)
            with sqlite3.connect(wmi.MASTER_DB,factory=ClosingConnection) as c:
                c.execute('begin'); return plan_sheet(c,rows,layout,complete)
        try: plan=await run_in_threadpool(prepare)
        except (ValueError,KeyError,StopIteration,zipfile.BadZipFile,ET.ParseError,IndexError) as e: raise HTTPException(400,str(e) or 'Invalid seating workbook.')
        id=uuid.uuid4().hex;source=Path(unquote(request.headers.get('x-file-name','Users-and-desks.xlsx'))).name[:200]
        if not plan['report']['errors'] and plan['updates']: staged[id]=(time.time(),plan,source)
        return {'id':id if id in staged else None,'report':plan['report']}
    @app.post('/api/seating-excel/apply/{id}')
    def apply(id:str,body:dict,request:Request):
        check_token(request)
        if busy(): raise HTTPException(409,'Finish active jobs and queues first.')
        item=staged.get(id)
        if not item or time.time()-item[0]>3600: raise HTTPException(409,'Preview expired. Upload again.')
        if body.get('confirmation')!='APPLY': raise HTTPException(400,'Type APPLY to confirm the reviewed seating changes.')
        try: backup=apply_sheet(wmi.MASTER_DB,item[1],root/'backups',item[2])
        except store.Conflict as e: raise HTTPException(409,str(e))
        except ValueError as e: raise HTTPException(400,str(e))
        del staged[id]
        return {'ok':True,'changes':len(item[1]['updates']),'backup':backup}
