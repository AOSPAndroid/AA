#!/usr/bin/env python3
"""Read directory workbooks and build validated import candidates."""
import argparse, hashlib, json, os, re, shutil, sqlite3, zipfile, uuid
from identity_links import rebuild_links
from device_inventory import EMPTY_IDENTIFIERS, row_identity
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MAX_COLUMNS=16384
MAX_ROWS=1048576
from contextvars import ContextVar
from functools import wraps
_STRINGS=ContextVar('atlas_workbook_strings',default=None)
def workbook_scope(fn):
    @wraps(fn)
    def scoped(*args,**kwargs):
        if _STRINGS.get() is not None:return fn(*args,**kwargs)
        token=_STRINGS.set({})
        try:return fn(*args,**kwargs)
        finally:_STRINGS.reset(token)
    return scoped

def clean(v): return str(v or '').strip()
def norm(v): return re.sub(r'\s+',' ',clean(v)).lower()
def excel_date(v):
    try:
        d=datetime(1899,12,30)+timedelta(days=float(v));return d.isoformat(sep=' ',timespec='seconds')
    except:return clean(v)
def col_idx(ref):
    match=re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})',ref if ref is not None else 'A1')
    if not match or int(match[2])>MAX_ROWS:
        raise ValueError('Invalid Excel cell reference; use A1 through XFD1048576.')
    n=0
    for ch in match[1]:n=n*26+ord(ch)-64
    if n>MAX_COLUMNS:raise ValueError('Excel cells cannot extend beyond column XFD.')
    return n-1

def workbook_parts(path):
    with zipfile.ZipFile(path) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'));rr=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'));rels={x.attrib['Id']:x.attrib['Target'] for x in rr}
        return [(s.attrib['name'],('xl/'+rels[s.attrib[REL+'id']].lstrip('/').removeprefix('xl/'))) for s in wb.find(NS+'sheets')]

def shared_strings(z,path_key=''):
    cache=_STRINGS.get()
    if cache is not None and path_key in cache:return cache[path_key]
    out=[]
    if 'xl/sharedStrings.xml' not in z.namelist():return out
    with z.open('xl/sharedStrings.xml') as f:
        parser=ET.iterparse(f,events=('start','end'));_,root=next(parser)
        for event,e in parser:
            if event=='end' and e.tag==NS+'si':
                out.append(''.join(t.text or '' for t in e.iter(NS+'t')))
                root.remove(e)
    if cache is not None:cache[path_key]=out
    return out

def iter_rows(path,target,raw=False):
    with zipfile.ZipFile(path) as z:
        ss=shared_strings(z,str(path))
        with z.open(target) as f:
            sheet_data=None;previous_row=0
            for event,e in ET.iterparse(f,events=('start','end')):
                if event=='start' and e.tag==NS+'sheetData':sheet_data=e
                if event!='end' or e.tag!=NS+'row':continue
                row_ref=e.attrib.get('r')
                if row_ref is None:number=previous_row+1
                elif not re.fullmatch(r'[1-9][0-9]{0,6}',row_ref):
                    raise ValueError('Invalid Excel row reference.')
                else:number=int(row_ref)
                if not 1<=number<=MAX_ROWS:raise ValueError('Excel rows cannot extend beyond 1048576.')
                previous_row=number;cells={};previous_column=-1
                for c in e.findall(NS+'c'):
                    ref=c.attrib.get('r')
                    i=col_idx(ref) if ref is not None else previous_column+1
                    if i>=MAX_COLUMNS:raise ValueError('Excel cells cannot extend beyond column XFD.')
                    previous_column=i;k=c.attrib.get('t');v=c.find(NS+'v');val=''
                    if k=='inlineStr':val=''.join(t.text or '' for t in c.iter(NS+'t'))
                    elif v is not None and v.text is not None:val=ss[int(v.text)] if k=='s' else v.text
                    cells[i]=val if raw else clean(val)
                if cells:
                    row=['']*(max(cells)+1)
                    for i,v in cells.items():row[i]=v
                    yield number,row
                if sheet_data is not None:sheet_data.remove(e)

def canonical_header(v):return re.sub(r'[^a-z0-9]+','_',norm(v)).strip('_')

def directory_parts(path):
    from directory_exports import sheet_kind
    parts={}
    for name,part in workbook_parts(path):
        kind=sheet_kind(name)
        if not kind:continue
        if kind in parts:raise ValueError(f'Multiple {kind} worksheets: {parts[kind][0]} and {name}. Keep one users tab and one devices/computers tab.')
        parts[kind]=(name,part)
    if not {'user','machine'}<=parts.keys():raise ValueError('Include users and devices worksheets (Users and computers are also supported).')
    return parts

def directory_columns(kind, headers):
    from directory_exports import field_map
    mapping=field_map(kind)
    columns=[(i,canonical_header(h),mapping.get(canonical_header(h),(canonical_header(h),''))[0]) for i,h in enumerate(headers)]
    # A devices export may include both its CI and its asset display name.
    # Prefer CI, then coalesce nonempty aliases without changing the original cells.
    return sorted(columns,key=lambda x:({'machine_name':0,'ci':1,'name':2}.get(x[1],3) if x[2]=='machine_name' else 0,x[0]))

def directory_data(columns, row):
    data={}
    for index,header,field in columns:
        value=clean(row[index]) if index<len(row) else ''
        if not data.get(field):data[field]=value
    return data

def snapshot_identity(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def user_identity(data, row_number, *, snapshot_id=None):
    """Names are searchable aliases, never a unique person identifier."""
    for prefix,field in (('uid:','user_id'),('email:','email'),
                         ('sys:','sys_id'),('employee:','employee_number')):
        value=norm(data.get(field))
        if value not in EMPTY_IDENTIFIERS:return prefix+value
    if clean(data.get('full_name')):
        return 'row:'+row_identity(data,row_number,snapshot_id=snapshot_id)
    return ''

def directory_rows(path,kind,sheet,part):
    rows=iter_rows(path,part);first=next(rows,None)
    if first is None:raise ValueError(f'{sheet}: worksheet is empty.')
    columns=directory_columns(kind,first[1]);headers={field for _,_,field in columns}
    required={'user_id','full_name','email'} if kind=='user' else {'machine_name'}
    if not required<=headers:
        expected='user_name, name and email' if kind=='user' else 'ci or name (machine hostname)'
        raise ValueError(f'{sheet}: missing identity columns; include {expected}.')
    for number,row in rows:
        yield number,directory_data(columns,row)

def updated_rank(data):
    value=clean(data.get('updated_on') or data.get('sys_updated_on'))
    if not value:return None
    value=excel_date(value)
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        date=None
        for fmt in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M','%d/%m/%Y'):
            try:date=datetime.strptime(value,fmt);break
            except ValueError:pass
        if date is None:return None
    return date.replace(tzinfo=timezone.utc).timestamp() if date.tzinfo is None else date.timestamp()

def select_import_row(con,kind,key,number,data,values,stats):
    """Use the newest dated row, then the last source row; never combine assignments."""
    rank=updated_rank(data)
    digest=hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    previous=con.execute('select row_number,updated,signature from directory_import_sources where kind=? and entity_key=?',(kind,key)).fetchone()
    if previous:
        stats['duplicate_rows']+=1
        if digest!=previous[2]:
            stats['conflicting_rows']+=1
            if len(stats['examples'])<20:stats['examples'].append({'identity':key,'rows':[previous[0],number]})
        old_rank=previous[1]
        if old_rank is not None and (rank is None or old_rank>rank):return False
    con.execute('insert or replace into directory_import_sources values(?,?,?,?,?)',(kind,key,number,rank,digest))
    return True

def schema(c):
    c.executescript('''
    pragma journal_mode=delete;pragma synchronous=normal;pragma temp_store=memory;
    create table metadata(key text primary key,value text);
    create table users(id integer primary key,canonical_key text unique,user_id text,user_id_norm text,full_name text,full_name_norm text,email text,email_norm text,organisational_unit text,business_unit text,start_date text,manager text,location text,last_login text,job_role text,job_type text,employee_number text,department text,last_login_time text);
    create table user_aliases(id integer primary key,user_id_ref integer,alias_type text,alias_value text,alias_norm text,unique(alias_type,alias_norm,user_id_ref));
    create table machines(id integer primary key,machine_name text,machine_name_norm text unique,infrastructure_itsi text,sys_class_name text,operational_status text,correlation_id text,serial_number text,manufacturer text,model_id text,short_description text,updated_on text,last_discovered text,discovery_source text,assigned_to text,last_logon_user text);
    create table assignments(id integer primary key,user_id_ref integer,machine_id integer,relationship_type text,source_value text,unique(user_id_ref,machine_id,relationship_type));
    create index ix_users_name on users(full_name_norm);create index ix_users_login on users(user_id_norm);create index ix_users_email on users(email_norm);create index ix_alias on user_aliases(alias_norm);create index ix_machine on machines(machine_name_norm);create index ix_assign_user on assignments(user_id_ref);create index ix_assign_machine on assignments(machine_id);
    create view user_machine_links as select u.canonical_key,u.user_id as login_id,u.employee_number as brid,u.email,u.full_name,m.machine_name,a.relationship_type from assignments a join users u on u.id=a.user_id_ref join machines m on m.id=a.machine_id;
    ''')
    from device_inventory import ensure_asset_columns
    ensure_asset_columns(c)
    c.execute('create index ix_alias_kind_norm on user_aliases(alias_type,alias_norm)')
    c.execute('create index ix_alias_user on user_aliases(user_id_ref)')
    c.execute('create index ix_users_employee_lower on users(lower(employee_number))')
    c.execute('create index ix_users_email_lower on users(lower(email))')
    from directory_lookup import MACHINE_SHORT_SQL
    c.execute('create index ix_machines_short on machines('+MACHINE_SHORT_SQL+')')

def normalise_vendor(v):
    x=clean(v);low=x.lower()
    if low.startswith('dell'):return 'Dell Inc.'
    if low.startswith('vmware'):return 'VMware, Inc.'
    if low.startswith('hewlett') or low=='hp':return 'HP'
    if low.startswith('apple'):return 'Apple'
    return x

@workbook_scope
def build(src,out):
    src=Path(src);out=Path(out);candidate=out.with_name(out.stem+'_'+uuid.uuid4().hex+'_new.db')
    snapshot_id=snapshot_identity(src)
    if candidate.exists():candidate.unlink()
    c=sqlite3.connect(candidate)
    try:
        schema(c)
        c.execute('create temp table directory_import_sources(kind text,entity_key text,row_number integer,updated real,signature text,primary key(kind,entity_key)) without rowid')
        stats={kind:{'duplicate_rows':0,'conflicting_rows':0,'examples':[]} for kind in ('user','machine')}
        stats['mobile_identity_rows']=0;stats['mobile_without_identifiers']=0
        parts=directory_parts(src)
        # Users
        from directory_exports import capture
        user_count=0
        for number,d in directory_rows(src,'user',*parts['user']):
            uid=clean(d.get('user_id'));email=clean(d.get('email'));name=clean(d.get('full_name'))
            key=user_identity(d,number,snapshot_id=snapshot_id)
            if not key:continue
            vals=(key,uid,norm(uid),name,norm(name),email,norm(email),d.get('organisational_unit',''),d.get('business_unit',''),excel_date(d.get('start_date','')),d.get('manager',''),d.get('location',''),excel_date(d.get('last_login','')),d.get('job_role',''),d.get('job_type',''),d.get('employee_number',''),d.get('department',''),d.get('last_login_time',''))
            if select_import_row(c,'user',key,number,d,vals,stats['user']):
                c.execute('insert into users(canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm,organisational_unit,business_unit,start_date,manager,location,last_login,job_role,job_type,employee_number,department,last_login_time) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(canonical_key) do update set user_id=excluded.user_id,user_id_norm=excluded.user_id_norm,full_name=excluded.full_name,full_name_norm=excluded.full_name_norm,email=excluded.email,email_norm=excluded.email_norm,organisational_unit=excluded.organisational_unit,business_unit=excluded.business_unit,start_date=excluded.start_date,manager=excluded.manager,location=excluded.location,last_login=excluded.last_login,job_role=excluded.job_role,job_type=excluded.job_type,employee_number=excluded.employee_number,department=excluded.department,last_login_time=excluded.last_login_time',vals)
            user_count+=1
            if user_count%5000==0:c.commit()
        c.commit()
        # Rebuild aliases only from final records; keep duplicate names as ambiguous.
        c.execute('delete from user_aliases')
        for ref,uid,email,name,employee in c.execute('select id,user_id,email,full_name,employee_number from users'):
            for typ,val in [('user_id',uid),('email',email),('name',name),('employee_number',employee)]:
                if clean(val):c.execute('insert or ignore into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(?,?,?,?)',(ref,typ,val,norm(val)))
        # Machines
        from device_inventory import ASSET_COLUMNS,inventory_identity
        machine_columns = 'machine_name,machine_name_norm,infrastructure_itsi,sys_class_name,operational_status,correlation_id,serial_number,manufacturer,model_id,short_description,updated_on,last_discovered,discovery_source,assigned_to,last_logon_user,' + ','.join(ASSET_COLUMNS)
        machine_sql = 'insert into machines('+machine_columns+') values('+','.join('?' for _ in range(15+len(ASSET_COLUMNS)))+') on conflict(machine_name_norm) do update set '+','.join(column+'=excluded.'+column for column in machine_columns.split(',') if column!='machine_name_norm')
        machine_count=0
        for number,d in directory_rows(src,'machine',*parts['machine']):
            name,identity_source=inventory_identity(d,number,snapshot_id=snapshot_id)
            if not name:continue
            if identity_source!='hostname':stats['mobile_identity_rows']+=1
            if identity_source=='row':stats['mobile_without_identifiers']+=1
            values=(name,norm(name),d.get('infrastructure_itsi',''),d.get('sys_class_name',''),d.get('operational_status',''),d.get('correlation_id','').upper(),re.sub(r'\s+',' ',d.get('serial_number','')).strip(),normalise_vendor(d.get('manufacturer','')),re.sub(r'\s+',' ',d.get('model_id','')).strip(),d.get('short_description',''),excel_date(d.get('updated_on','')),excel_date(d.get('last_discovered','')),d.get('discovery_source',''),d.get('assigned_to',''),d.get('last_logon_user',''))
            values += tuple(clean(d.get('machine_name')) if column=='source_ci' else excel_date(d.get(column,'')) if column in ('last_used','assigned_at') else d.get(column,'') for column in ASSET_COLUMNS)
            if select_import_row(c,'machine','machine:'+norm(name),number,d,values,stats['machine']):
                c.execute(machine_sql,values)
            machine_count+=1
            if machine_count%5000==0:c.commit()
        if not user_count or not machine_count:raise ValueError('Empty user or device extract refused. The existing directory was not changed.')
        links=rebuild_links(c)
        capture(c,src,selection_table='directory_import_sources',snapshot_id=snapshot_id)
        print('Relationship matching:',links)
        c.executemany('insert into metadata(key,value) values(?,?)',[('schema_version','3'),('created_at',datetime.now().isoformat(sep=' ',timespec='seconds')),('generation',uuid.uuid4().hex),('source_file',src.name),('import_resolution',json.dumps(stats))])
        c.commit();check=c.execute('pragma integrity_check').fetchone()[0]
        counts={t:c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('users','machines','assignments','user_aliases')};c.close()
        if check!='ok':raise RuntimeError(check)
        if out.exists():shutil.copy2(out,out.with_name(out.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.backup.db'))
        os.replace(candidate,out)
        print('SUCCESS',out)
        for k,v in counts.items():print(f'{k}: {v:,}')
    finally:
        c.close()
        candidate.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',default='templates/database040926.xlsx');p.add_argument('--db',default='wmi_packager_master.db');a=p.parse_args();build(a.source,a.db)
if __name__=='__main__':main()
