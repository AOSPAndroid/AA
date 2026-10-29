"""Shared database-only directory queries for admin and viewer."""
from backend.directory.directory_exports import field_map
from backend.directory.device_inventory import ASSET_COLUMNS, device_kind
import re

MACHINE_SHORT_SQL = "lower(case when instr(machine_name,'\\')>0 then substr(machine_name,instr(machine_name,'\\')+1) when instr(machine_name,'.')>0 then substr(machine_name,1,instr(machine_name,'.')-1) else machine_name end)"


def windows_login(value):
    """The confirmed login convention is G-number export ID -> X-number login."""
    domain, separator, account = str(value or '').strip().rpartition('\\')
    if re.fullmatch(r'g[0-9]+', account, re.IGNORECASE):
        account = 'x' + account[1:]
    return domain + separator + account

# Only these explicit column names ever enter SQL. Values remain parameters.
SEARCH_FIELDS = {alias: (kind, column) for kind in ('user', 'machine')
                 for alias, (column, _) in field_map(kind).items() if alias not in ('name', 'user_name', 'email')}
SEARCH_FIELDS.update({
 'serial': ('machine', 'serial_number'), 'asset': ('machine', 'correlation_id'),
 'model': ('machine', 'model_id'), 'status': ('machine', 'operational_status'),
 'class': ('machine', 'sys_class_name'), 'source': ('machine', 'discovery_source'),
 'infrastructure': ('machine', 'infrastructure_itsi'), 'assigned': ('machine', 'assigned_to'),
 'type': ('machine', 'device_kind'), 'asset_state': ('machine', 'install_status'),
 'device_location': ('machine', 'device_location'),
 'source_ci': ('machine', 'source_ci'),
 'last_user': ('machine', 'last_logon_user'), 'description': ('machine', 'short_description'),
 'team': ('user', 'department'), 'business': ('user', 'business_unit'),
 'organisation': ('user', 'organisational_unit'), 'office': ('user', 'location'),
 'location': ('user', 'location'),
 'title': ('user', 'job_role'), 'worker': ('user', 'job_type'),
})

def _alias_users(c, values, types, condition='', parameters=()):
 placeholders=','.join('?' for _ in values);kinds=','.join('?' for _ in types)
 sql="select distinct u.* from legacy_users u where "+(condition+' or ' if condition else '')+"u.id in (select user_id_ref from user_aliases where alias_norm in ("+placeholders+") and alias_type in ("+kinds+")) order by u.name,u.id limit 100"
 return c.execute(sql,(*parameters,*values,*types)).fetchall()


def _account_users(c, value):
 from backend.directory.identity_links import MATCHING_VERSION,key
 q=key(value);account=q.rsplit('\\',1)[-1]
 variants={account}
 if re.fullmatch(r'x[0-9]+',account):variants.add('g'+account[1:])
 types=('user_id','login','windows_login','account','matching_account')
 qualified='\\' in q
 full={q} if qualified else variants
 if qualified:
  domain=q.rsplit('\\',1)[0]
  full.update(domain+'\\'+alias for alias in variants)
 rows=_alias_users(c,tuple(full),types,'u.user_name_norm in ('+','.join('?' for _ in full)+')',tuple(full))
 if qualified and rows:return rows
 # Derived aliases are installed during import/admin migration. The fallback
 # keeps old read-only exports usable without writing to a reader connection.
 rows=_alias_users(c,tuple(variants),types,'u.user_name_norm in ('+','.join('?' for _ in variants)+')',tuple(variants))
 marker=c.execute("select value from metadata where key='matching_accounts_version'").fetchone() if c.execute("select 1 from sqlite_master where name='metadata' and type='table'").fetchone() else None
 if not marker or marker[0]!=MATCHING_VERSION:
  conditions=[];parameters=[]
  for alias in variants:
   conditions.append("u.user_name_norm like ? escape '\\'")
   parameters.append('%'+chr(92)+chr(92)+alias.replace('%',chr(92)+'%').replace('_',chr(92)+'_'))
  legacy=c.execute('select u.* from legacy_users u where '+' or '.join(conditions)+' order by u.name,u.id limit 100',parameters).fetchall()
  rows=list({r['id']:r for r in [*rows,*legacy]}.values())
 if not qualified:return rows
 ids=[r['id'] for r in rows]
 if not ids:return []
 domains={uid:set() for uid in ids}
 for row in rows:
  login=key(row['user_id'])
  if '\\' in login:domains[row['id']].add(login.rsplit('\\',1)[0])
 unknown_primary={row['id'] for row in rows if not key(row['user_id'])}
 for uid,alias in c.execute("select user_id_ref,alias_value from user_aliases where user_id_ref in ("+','.join('?' for _ in ids)+") and alias_type in ('user_id','login','windows_login','account')",ids):
  text=key(alias)
  if uid in unknown_primary and '\\' in text:domains[uid].add(text.rsplit('\\',1)[0])
 return [row for row in rows if not domains[row['id']] or domain in domains[row['id']]]


def exact_users(c,value,*,field=None):
 from backend.directory.identity_links import EMPTY_IDENTITIES,key
 q=key(value)
 if q in EMPTY_IDENTITIES:return []
 if field=='name':
  return c.execute('select * from legacy_users where name_norm=? order by name,id limit 100',(' '.join(value.strip().split()).lower(),)).fetchall()
 if field=='email':
  return _alias_users(c,(q,value.strip().lower()),('email','upn','user_principal_name','matching_email'), 'u.email_norm=?',(value.strip().lower(),))
 if field=='brid':
  return _alias_users(c,(q,value.strip().lower()),('employee_number','employee_id','brid','matching_employee'),'lower(u.brid)=?',(value.strip().lower(),))
 canonical=c.execute('select * from legacy_users where canonical_key in (?,?)',(value.strip(),value.strip().lower())).fetchall()
 if canonical:return canonical
 # Authoritative identifiers win before display names; preserve collisions
 # between independently exported accounts and G/X aliases.
 accounts=_account_users(c,value)
 identities=[] if '\\' in q else _alias_users(c,(q,value.strip().lower()),('email','upn','user_principal_name','employee_number','employee_id','brid','canonical_key','matching_identity'), 'u.email_norm=? or lower(u.brid)=?',(value.strip().lower(),value.strip().lower()))
 rows=list({r['id']:r for r in [*accounts,*identities]}.values())
 if rows or '\\' in q or '@' in q:return rows
 return exact_users(c,value,field='name')

def linked_machines(c,uid):
 c.execute('savepoint directory_linked_read')
 try:return _linked_machines(c,uid)
 finally:c.execute('release directory_linked_read')

def _linked_machines(c,uid):
 physical=[dict(r) for r in c.execute("""select m.*,max(a.relationship_type='assigned_to') as assigned_relationship,max(a.relationship_type='last_logon_user') as logon_relationship,case when count(distinct a.relationship_type)>1 then 'Assigned + last logged on (inventory)' when max(a.relationship_type)='assigned_to' then 'Assigned' else 'Last logged on (inventory)' end as match_type from assignments a join legacy_machines m on m.id=a.machine_id where a.user_id_ref=? group by m.id order by assigned_relationship desc,case when lower(m.operational_status)='operational' then 0 else 1 end,m.last_discovered desc,m.name""",(uid,))]
 from backend.directory.vdi_inventory import linked_records
 return linked_records(c,uid,physical)


def resolve_directory(c,value):
 from backend.directory.vdi_inventory import machine_context
 raw=value.strip();context=machine_context(c,raw)
 if context and context.get('ambiguous'):
  return {'matched':False,'ambiguous':True,'query':raw,'machine':None,'machines':context['machines'],'users':[]}
 machine=context['machine'] if context else None
 rows=context['users'] if context else exact_users(c,raw)
 users=[dict(row) for row in rows]
 if len(users)!=1:
  return {'matched':False,'ambiguous':len(users)>1,'query':raw,'machine':machine,'users':users}
 user=users[0]
 return {'matched':True,'resolved_by':'machine' if machine else 'identity','user':user,'users':users,'machine':machine,
         'search_value':user['user_name'] or user['email'] or user['full_name'],'user_key':user['canonical_key'],
         'requested_machine':machine['machine_name'] if machine else '',
         'machines':[row['name'] for row in linked_machines(c,user['id'])]}

def search_directory(c,term:str):
 text=' '.join(term.strip().split());prefix=''
 if ':' in text and text.split(':',1)[0].lower() in SEARCH_FIELDS:
  prefix,text=text.split(':',1);kind,column=SEARCH_FIELDS[prefix.lower()];value=text.strip().lower()
  if not value:return {'users':[],'machines':[]}
  like='%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
  table='legacy_users' if kind=='user' else 'legacy_machines'
  condition='lower("'+column+'") like ? escape \'\\\''
  parameters=(like,)
  if prefix.lower()=='asset':
   condition='('+condition+' or lower(asset_tag) like ? escape \'\\\')';parameters=(like,like)
  rows=c.execute('select * from '+table+' where '+condition+' order by name,id limit 100',parameters).fetchall()
  machines=[dict(r) for r in rows] if kind=='machine' else []
  if kind=='machine':
   from backend.directory.vdi_inventory import merge_records,search_records
   machines=merge_records(machines,search_records(c,text,field=column),limit=100)
  return {'users':[dict(r) for r in rows] if kind=='user' else [],'machines':machines}
 if ':' in text and text.split(':',1)[0].lower() in ('machine','user','email','name','brid'):
  prefix,text=text.split(':',1);prefix=prefix.lower();text=text.strip()
 if not text:return {'users':[],'machines':[]}
 q=text.lower();like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
 users=[] if prefix=='machine' else exact_users(c,text,field=prefix if prefix in ('email','name','brid') else None)
 machines=[]
 if prefix not in ('user','email','name','brid'):
  # A synthetic empty asset column in old snapshots must not turn this indexed lookup into a full scan.
  asset_column=c.execute("select 1 from pragma_table_info('machines') where name='asset_tag'").fetchone()
  condition='name_norm=? or lower(serial_number)=? or lower(correlation_id)=?'
  parameters=(q.rstrip('.'),q,q)
  if asset_column:condition+=' or lower(asset_tag)=?';parameters+=(q,)
  source_ci=c.execute("select 1 from pragma_table_info('machines') where name='source_ci'").fetchone()
  if source_ci:condition+=' or lower(source_ci)=?';parameters+=(q,)
  inventory=c.execute('select * from legacy_machines where '+condition+' order by name limit 100',parameters).fetchall()
  from backend.directory.vdi_inventory import find_machines,merge_records,search_records
  machines=merge_records(inventory,find_machines(c,text),limit=100)
 if not users and not machines:
  if prefix!='machine':
   columns={'email':('email_norm',),'name':('name_norm',),'brid':('lower(brid)',)}.get(prefix,('user_name_norm','name_norm','email_norm','lower(brid)'))
   condition=' or '.join(column+" like ? escape '\\'" for column in columns)
   users=c.execute('select * from legacy_users where '+condition+' order by name,id limit 100',(like,)*len(columns)).fetchall()
  if prefix not in ('user','email','name','brid'):
   condition="name_norm like ? escape '\\'";parameters=(like,)
   if source_ci:condition+=" or lower(source_ci) like ? escape '\\'";parameters+=(like,)
   machines=c.execute('select * from legacy_machines where '+condition+' order by name limit 100',parameters).fetchall()
   machines=merge_records(machines,search_records(c,text),limit=100)
 return {'users':[dict(x) for x in users],'machines':[dict(x) for x in machines]}


def prepare_views(c):
    c.create_function('atlas_windows_login', 1, windows_login, deterministic=True)
    c.create_function('atlas_device_kind', 4, device_kind, deterministic=True)
    from backend.directory.device_inventory import supports_windows
    c.create_function('atlas_supports_windows', 4, lambda name, category, model, cls:
        int(supports_windows({'machine_name':name,'model_category':category,'model_id':model,'sys_class_name':cls})), deterministic=True)
    known = {r[1] for r in c.execute('pragma table_info(machines)')}
    optional = ''.join(",'' as " + column for column in ASSET_COLUMNS if column not in known)
    kind = "atlas_device_kind(machine_name,model_category,model_id,sys_class_name)"
    c.execute("create temp view legacy_users as select *,user_id as user_name,user_id_norm as user_name_norm,atlas_windows_login(user_id) as login_id,lower(atlas_windows_login(user_id)) as login_norm,full_name as name,full_name_norm as name_norm,employee_number as employee_id,employee_number as brid,job_role as job_title,job_type as worker_type,organisational_unit as organisation,'' as active,'' as country from main.users")
    supported = "atlas_supports_windows(machine_name,model_category,model_id,sys_class_name)"
    c.execute("create temp view legacy_machines as select *," + kind + " as device_kind," + supported + " as windows_remote_supported,machine_name as name,machine_name_norm as name_norm,last_logon_user as u_last_logon_user,assigned_to as assigned_user,last_logon_user as last_logged_on_user,last_logon_user as most_frequent_user,infrastructure_itsi as u_infrastructure_itsi,sys_class_name as class,short_description as description,updated_on as updated,'' as operating_system,'' as support_group from (select *" + optional + " from main.machines)")
