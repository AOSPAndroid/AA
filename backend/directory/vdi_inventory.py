"""Read supplemental Citrix inventory through the shared directory surfaces."""
from backend.directory import vdi_data


def _key(machine):
    if machine.get('vdi_key'):
        return machine['vdi_key']
    name = str(machine.get('name') or machine.get('machine_name') or '').strip().lower().rstrip('.')
    return ('netbios:' if '\\' in name else 'dns:' if '.' in name else 'host:') + name if name else ''


def _merge(physical, virtual):
    """An exact target can keep ServiceNow hardware alongside Citrix evidence."""
    result = dict(physical)
    protected = physical.get('windows_remote_supported') in (False, 0)
    for name, value in virtual.items():
        if name.startswith('vdi_') or name in (
                'device_kind', 'windows_remote_supported', 'source', 'model_category',
                'assigned_relationship', 'relationship_group', 'source_kind', 'inventory_source'):
            if protected and name in ('device_kind', 'windows_remote_supported', 'model_category'):
                continue
            result[name] = value
    result['assigned_relationship'] = int(bool(physical.get('assigned_relationship') or virtual.get('assigned_relationship')))
    if result['assigned_relationship']:
        result['relationship_group'] = 'Assigned to user'
    result['match_type'] = 'Citrix assigned' if virtual.get('assigned_relationship') else result.get('match_type', '')
    return result


def merge_records(primary, supplementary, limit=None):
    """Deduplicate exact identities without guessing a hostname's DNS domain."""
    result = [dict(row) for row in primary]
    positions = {_key(row): index for index, row in enumerate(result) if _key(row)}
    for row in supplementary:
        # Malformed export names remain archived, rather than becoming targets.
        if not _key(row):
            continue
        position = positions.get(_key(row))
        if position is not None:
            result[position] = _merge(result[position], row)
        else:
            positions[_key(row)] = len(result)
            result.append(dict(row))
    return result if limit is None else result[:limit]


def linked_records(con, user_id, physical):
    if not vdi_data.exists(con):
        return physical
    person = con.execute('select canonical_key from users where id=?', (user_id,)).fetchone()
    if person is None:
        return physical
    return merge_records(physical, vdi_data.machines_for_user(con, person[0]))


def find_machines(con, computer):
    """A bare host is an alias across all sources, never an arbitrary first row."""
    from backend.directory.directory_lookup import MACHINE_SHORT_SQL
    normalized = computer.strip().lower().rstrip('.')
    condition='name_norm in (?,?)';parameters=(normalized,normalized+'.')
    if '.' not in normalized and '\\' not in normalized and ':' not in normalized:
        condition+=' or '+MACHINE_SHORT_SQL+'=?';parameters+=(normalized,)
    known={r[1] for r in con.execute('pragma table_info(machines)')}
    if 'source_ci' in known:
        condition+=' or lower(source_ci)=?';parameters+=(normalized,)
    primary = [dict(row) for row in con.execute(
        'select * from legacy_machines where '+condition+' order by id', parameters)]
    supplemental = vdi_data.machine_records(con, computer) if vdi_data.exists(con) else []
    return merge_records(primary, supplemental)


def assigned_users(con, machine):
    users = []
    machine_id = machine.get('id')
    if isinstance(machine_id, int):
        users = [dict(row) for row in con.execute("""select u.*,
            max(a.relationship_type='assigned_to') as assigned_relationship,
            max(a.relationship_type='last_logon_user') as logon_relationship
            from assignments a join legacy_users u on u.id=a.user_id_ref
            where a.machine_id=? group by u.id order by u.full_name,u.id""", (machine_id,))]
    if machine.get('vdi_key') and vdi_data.exists(con):
        virtual_users = [dict(row) for row in con.execute("""select u.*,
            1 as assigned_relationship, 0 as logon_relationship
            from vdi_links l join legacy_users u on u.canonical_key=l.user_key
            where l.machine_key=? order by u.full_name,u.id""", (machine['vdi_key'],))]
        by_id = {row['id']: row for row in users}
        for row in virtual_users:
            if row['id'] in by_id:
                by_id[row['id']]['assigned_relationship'] = 1
            else:
                users.append(row)
                by_id[row['id']] = row
    return users


def machine_context(con, computer):
    rows = find_machines(con, computer)
    if not rows:
        return None
    if len(rows) != 1:
        return {'ambiguous': True, 'machines': rows}
    machine = rows[0]
    return {'machine': machine, 'users': assigned_users(con, machine)}


def count(con):
    return con.execute('select count(*) from vdi_devices').fetchone()[0] if vdi_data.exists(con) else 0


def search_records(con, text, *, field=None, exact=False, limit=100):
    if not vdi_data.exists(con):
        return []
    return vdi_data.search_records(con, text, field=field, exact=exact, limit=limit)
