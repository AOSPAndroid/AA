"""Database-only desk identity evidence shared by admin, viewer and palette."""
import json
import re
import threading
import unicodedata
from functools import wraps
from backend.directory.directory_lookup import linked_machines


def name_key(value):
    return ' '.join(sorted(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', str(value)).casefold())))


_indexes = {}
_lock = threading.Lock()


def read_snapshot(fn):
    """Keep names, IDs and relationship evidence on one directory generation."""
    @wraps(fn)
    def wrapped(c, *args, **kwargs):
        c.execute('savepoint desk_directory_read')
        try:
            return fn(c, *args, **kwargs)
        finally:
            c.execute('release desk_directory_read')
    return wrapped


@read_snapshot
def resolve_person(c, desk):
    if desk['occupancy'] == 'vacant':
        return [], 'unassigned'
    explicit = c.execute('select user_key from desk_user_links where desk_id=?', (desk['id'],)).fetchone()
    if explicit:
        person = c.execute('select * from legacy_users where canonical_key=?', (explicit[0],)).fetchone()
        return ([dict(person)] if person else []), ('confirmed' if person else 'missing-linked-user')
    key = name_key(desk['name'])
    if len(key.split()) < 2:
        return [], 'unmatched'
    path = c.execute('pragma database_list').fetchone()[2]
    stamp = tuple(c.execute("select key,value from metadata where key in ('directory.generation','generation','directory.created_at','created_at') order by key").fetchall())
    cache_key = (path or id(c), tuple(tuple(row) for row in stamp))
    with _lock:
        index = _indexes.get(cache_key)
        if index is None:
            index = {}
            for uid, name in c.execute('select id,full_name from legacy_users'):
                index.setdefault(name_key(name), []).append(uid)
            if len(_indexes) >= 8:
                _indexes.pop(next(iter(_indexes)))
            _indexes[cache_key] = index
    ids = index.get(key, [])
    people = [dict(row) for row in c.execute('select * from legacy_users where id in ('+','.join('?' for _ in ids)+') order by id', ids)] if ids else []
    method = ('unconfirmed-name-match' if desk['occupancy']=='unconfirmed' else 'name-match') if len(people)==1 else 'ambiguous' if people else 'unmatched'
    return people, method


@read_snapshot
def desk_context(c, desk):
    candidates, method = resolve_person(c, desk)
    person = candidates[0] if len(candidates)==1 else None
    machines = linked_machines(c, person['id']) if person else []
    for machine in machines:
        machine['link_source'] = 'User directory'
    hostname = desk.get('hostname','').strip().upper() if desk['kind']=='desk' else ''
    if hostname:
        existing = next((m for m in machines if m['name'].upper()==hostname), None)
        if existing:
            existing['desk_equipment'] = True
        else:
            from backend.directory.vdi_inventory import find_machines
            matches = find_machines(c, hostname)
            machine = matches[0] if len(matches) == 1 else {'name':hostname,'operational_status':'Ambiguous machine' if matches else 'Not in directory','model_id':'','serial_number':'','windows_remote_supported':not bool(matches)}
            machine.update(link_source='Desk equipment record',match_type='Recorded at this desk',desk_equipment=True,assigned_relationship=0,logon_relationship=0)
            machines.insert(0, machine)
    for machine in machines:
        machine['relationship_group'] = 'Assigned to user' if machine.get('assigned_relationship') else 'Desk equipment' if machine.get('desk_equipment') else 'Last logged on (inventory)'
        machine['inventory_discovered_at'] = machine.get('last_discovered') or None
        machine['inventory_updated_at'] = machine.get('updated_on') or None
    order = {'Assigned to user':0,'Desk equipment':1,'Last logged on (inventory)':2}
    machines.sort(key=lambda m:(order[m['relationship_group']], m['name']))
    return {'desk':desk,'user':person,'candidates':candidates,'match_method':method,'machines':machines}


@read_snapshot
def people_desks(c, people, suggestions=True):
    """Resolve a batch against one directory snapshot without per-person queries.

    Names are suggestions only when unique across the full directory. Any direct
    or mapped legacy account link prevents name inference for that desk.
    """
    result = {person['canonical_key']: [] for person in people}
    if not result:
        return result
    desks = {row[0]: json.loads(row[1]) for row in c.execute('select id,body from official_records order by id')}
    links = {}
    for desk_id, user_key in c.execute('''select coalesce(m.official_id,l.desk_id),l.user_key
        from desk_user_links l left join official_seating_mappings m on m.legacy_id=l.desk_id'''):
        links.setdefault(desk_id, set()).add(user_key)
    for desk_id, accounts in links.items():
        # Conflicting explicit links must be reviewed rather than merged.
        if desk_id in desks and len(accounts) == 1:
            account = next(iter(accounts))
            if account in result:
                result[account].append({'id': desk_id, 'floor': desks[desk_id]['floor'], 'match': 'confirmed account link'})
    if not suggestions:
        return result
    pending = {person['canonical_key']: name_key(person['full_name']) for person in people
               if not result[person['canonical_key']]}
    named_desks = {}
    for desk_id, desk in desks.items():
        if desk_id not in links and desk.get('occupancy') != 'vacant':
            key = name_key(desk.get('name', ''))
            named_desks.setdefault(key, []).append({'id': desk_id, 'floor': desk['floor'], 'match': 'matching name; account not confirmed'})
    counts = {key: 0 for key in pending.values() if key and key in named_desks}
    if not counts:
        return result
    for (full_name,) in c.execute('select full_name from users'):
        key = name_key(full_name)
        if key in counts:
            counts[key] += 1
    for account, key in pending.items():
        if counts.get(key) == 1:
            result[account] = named_desks.get(key, [])
    return result


def person_desks(c, person, suggestions=True):
    return people_desks(c, [person], suggestions)[person['canonical_key']]


def palette_search(c, result):
    """Add optional desk evidence to displayed people, leaving search data intact."""
    people = result['users'][:10]
    matches = people_desks(c, people)
    users = [dict(person, palette_desks=matches[person['canonical_key']]) if index < 10 else dict(person)
             for index, person in enumerate(result['users'])]
    return {**result, 'users': users}


@read_snapshot
def machine_context(c, computer):
    """Stored inventory and identity evidence only; never contacts a machine."""
    from backend.directory.vdi_inventory import machine_context as inventory_context
    result = inventory_context(c, computer)
    if result is None:
        return None
    if result.get('ambiguous'):
        return result
    machine = result['machine']
    desks = [{'id':r['id'], 'floor':r['floor'], 'match':'recorded at this desk'}
             for (body,) in c.execute('select body from official_records')
             for r in [json.loads(body)] if r.get('hostname','').casefold().rstrip('.') == machine['name'].casefold().rstrip('.')]
    return {**result, 'desks':desks}
