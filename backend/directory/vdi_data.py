"""Supplemental Citrix inventory snapshots; imported data never proves a live session."""
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import wraps
from pathlib import Path

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_ROWS = 300000
MAX_COLUMNS = 256
MAX_CELL = 65536
FIELDS = {
    'original_name': ('name', 'machinename', 'dnsname', 'desktopname'),
    'catalog': ('machinecatalog', 'catalog', 'catalogname'),
    'delivery_group': ('deliverygroup', 'desktopgroupname', 'deliverygroupname'),
    'users': ('user', 'users', 'assigneduser', 'assignedusers', 'associatedusername', 'associatedusernames', 'username', 'usernames'),
    'user_display_names': ('userdisplayname', 'userdisplaynames', 'associateduserfullname', 'associateduserfullnames'),
    'maintenance_mode': ('maintenancemode', 'inmaintenancemode'),
    'user_change_persistence': ('userchangepersistence', 'persistence'),
    'power_state': ('powerstate',),
    'registration_state': ('state', 'registrationstate'),
}
DEVICE_FIELDS = ('machine_key', 'target_name', 'name_norm', 'short_name', 'short_norm', 'original_name',
                 'domain', 'catalog', 'delivery_group', 'user_display_names', 'maintenance_mode',
                 'user_change_persistence', 'power_state', 'registration_state', 'matching_issue',
                 'raw_json', 'source_rows_json', 'source', 'imported_at')
TABLES = ('vdi_devices', 'vdi_user_refs', 'vdi_links', 'vdi_imports')
SCHEMA = (
    '''create table if not exists vdi_devices(
      machine_key text primary key, target_name text not null, name_norm text not null,
      short_name text not null, short_norm text not null, original_name text not null,
      domain text not null, catalog text not null, delivery_group text not null,
      user_display_names text not null, maintenance_mode text not null,
      user_change_persistence text not null, power_state text not null,
      registration_state text not null, matching_issue text not null,
      raw_json text not null, source_rows_json text not null, source text not null, imported_at text not null)''',
    '''create table if not exists vdi_user_refs(
      machine_key text not null, ref_norm text not null, raw_ref text not null,
      account text not null, domain text not null, valid integer not null,
      status text not null, candidates_json text not null, primary key(machine_key,ref_norm))''',
    '''create table if not exists vdi_links(
      machine_key text not null, user_key text not null, primary key(machine_key,user_key))''',
    '''create table if not exists vdi_imports(
      id text primary key, at text not null, source text not null, report text not null,
      backup text not null, full_snapshot integer not null)''',
    'create index if not exists ix_vdi_name on vdi_devices(name_norm)',
    'create index if not exists ix_vdi_short on vdi_devices(short_norm)',
    'create index if not exists ix_vdi_original_lower on vdi_devices(lower(original_name))',
    'create index if not exists ix_vdi_users on vdi_links(user_key,machine_key)',
    'create index if not exists ix_vdi_refs_account on vdi_user_refs(ref_norm,machine_key)',
)


def initialize(con):
    # Preserve an import/directory refresh transaction; executescript commits it.
    for statement in SCHEMA:
        con.execute(statement)


def exists(con):
    return con.execute("select 1 from sqlite_master where type='table' and name='vdi_devices'").fetchone() is not None


def _read_snapshot(fn):
    @wraps(fn)
    def wrapped(con, *args, **kwargs):
        con.execute('savepoint vdi_snapshot_read')
        try:
            return fn(con, *args, **kwargs)
        finally:
            con.execute('release vdi_snapshot_read')
    return wrapped


def header_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).strip().casefold())


def _mapping(headers):
    if not headers or len(headers) > MAX_COLUMNS:
        raise ValueError('Citrix export needs a header row with up to 256 columns.')
    if any(len(value) > MAX_CELL or '\x00' in value for value in headers):
        raise ValueError('Citrix export has an invalid or oversized header cell.')
    normalized = [header_key(value) for value in headers]
    mapping = {field: [i for i, value in enumerate(normalized) if value in aliases]
               for field, aliases in FIELDS.items()}
    if not mapping['original_name'] or not mapping['users']:
        raise ValueError('Citrix export needs Name (machine name) and User or Assigned Users headers.')
    return mapping


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def machine_identity(name, headers=None, cells=None):
    """A qualified identity stays qualified; malformed names remain raw metadata."""
    original = str(name or '').strip()
    value = original.rstrip('.').upper()
    label = r'[A-Z0-9](?:[A-Z0-9_-]{0,61}[A-Z0-9_])?'
    domain = ''
    if '\\' in value and value.count('\\') == 1:
        domain, short = value.split('\\')
        if re.fullmatch(label, domain) and re.fullmatch(label, short):
            return {'machine_key': 'netbios:' + value.casefold(), 'target_name': short,
                    'short_name': short, 'domain': domain, 'matching_issue': ''}
    elif re.fullmatch(label + r'(?:\.' + label + r')*', value):
        short, _, domain = value.partition('.')
        if len(value) <= 64:
            return {'machine_key': ('dns:' if domain else 'host:') + value.casefold(),
                    'target_name': value, 'short_name': short, 'domain': domain, 'matching_issue': ''}
    identity = ('literal_name', original.casefold()) if original else ('original_row', headers or [], cells or [])
    return {'machine_key': 'raw:' + _hash(identity), 'target_name': '', 'short_name': '', 'domain': '',
            'matching_issue': 'invalid_machine_name' if original else 'missing_machine_name'}


def user_tokens(values):
    """Read account lists without treating display-name cells as identities."""
    tokens = []
    for raw in values:
        value = str(raw or '').strip()
        if not value:
            continue
        if value.startswith('['):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
                tokens.extend(decoded)
                continue
        value = value.strip('{}[]')
        tokens.extend(re.split(r'[,;|\r\n]+', value))
    refs = {}
    for raw in tokens:
        raw = raw.strip().strip('"\'').strip()
        if not raw or raw.casefold() in ('none', 'n/a', '(empty)', '[]', '{}'):
            continue
        normalized = raw.casefold()
        domain, separator, account = normalized.rpartition('\\')
        if not separator:
            account = normalized
            domain = ''
        valid = bool(re.fullmatch(r'[a-z0-9][a-z0-9_.@-]{0,199}', account) and
                     (not domain or re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,199}', domain)))
        refs.setdefault(normalized, {'raw_ref': raw, 'ref_norm': normalized, 'account': account,
                                     'domain': domain, 'valid': int(valid)})
    return list(refs.values())


def _parse_sheets(sheets):
    rows = {}; sources = {}; row_count = duplicates = 0; ignored_sheets = []; source_columns = []
    for sheet, iterator in sheets:
        first = next(iterator, None)
        if first is None:
            ignored_sheets.append(sheet)
            continue
        _, headers = first
        try:
            mapping = _mapping(headers)
        except ValueError:
            ignored_sheets.append(sheet)
            continue
        source_columns.extend(header for header in headers if header not in source_columns)
        for number, cells in iterator:
            if not any(str(value).strip() for value in cells):
                continue
            row_count += 1
            if row_count > MAX_ROWS:
                raise ValueError('Citrix export exceeds 300,000 nonblank rows.')
            if len(cells) > MAX_COLUMNS or any(len(value) > MAX_CELL or '\x00' in value for value in cells):
                raise ValueError(f'{sheet} row {number}: oversized or invalid cell.')
            # Sparse Excel rows may end before the headers; retain the original cells.
            def values(field):
                return [cells[i].strip() if i < len(cells) else '' for i in mapping[field]]
            row = {field: next((v for v in values(field) if v), '') for field in FIELDS if field != 'users'}
            row.update(machine_identity(row['original_name'], headers, cells))
            row['name_norm'] = row['target_name'].casefold()
            row['short_norm'] = row['short_name'].casefold()
            row['users'] = user_tokens(values('users'))
            row['raw_json'] = json.dumps(dict(zip(headers, cells)), ensure_ascii=False)
            key = row['machine_key']
            duplicates += key in rows
            envelope = sources.setdefault(key, {'sources': [], 'rows': [], 'selection': 'last_row'})
            source = {'sheet': sheet, 'headers': list(headers)}
            if source not in envelope['sources']:
                envelope['sources'].append(source)
            envelope['rows'].append({'sheet': sheet, 'row': number, 'cells': list(cells)})
            envelope.update(selected_sheet=sheet, selected_row=number)
            rows[key] = row
    if not rows:
        raise ValueError('No Citrix rows found. Include Name and User headers and at least one nonblank data row.')
    for key, row in rows.items():
        row['source_rows_json'] = json.dumps(sources[key], ensure_ascii=False, separators=(',', ':'))
    return rows, {'rows': row_count, 'unique': len(rows), 'duplicates': duplicates,
                  'source_columns': source_columns, 'columns': source_columns,
                  'invalid_machines': sum(bool(row['matching_issue']) for row in rows.values()),
                  'ignored_sheets': ignored_sheets}


def parse_csv(content):
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('Choose a Citrix CSV or XLSX up to 50 MB.')
    encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        text = content.decode(encoding)
    except UnicodeDecodeError:
        try:
            text = content.decode('cp1252')
        except UnicodeDecodeError as error:
            raise ValueError('Citrix CSV has an unsupported text encoding.') from error
    offset = 0; delimiter = None
    first_line, separator, remainder = text.partition('\n')
    if re.fullmatch(r'sep=([,;\t|])\r?', first_line, re.IGNORECASE):
        delimiter = first_line[4:5]; text = remainder; offset = 1
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=',;\t').delimiter
        except csv.Error:
            delimiter = ','
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    def rows():
        try:
            for cells in reader:
                yield reader.line_num + offset, cells
        except csv.Error as error:
            raise ValueError(f'CSV row {reader.line_num + offset}: {error}') from error
    return _parse_sheets([('CSV', iter(rows()))])


def parse(content, filename='citrix.csv'):
    suffix = Path(filename).suffix.casefold()
    if suffix == '.csv':
        return parse_csv(content)
    if suffix != '.xlsx':
        raise ValueError('Choose the raw Citrix CSV or XLSX export.')
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('Choose a Citrix CSV or XLSX up to 50 MB.')
    from backend.directory.directory_workbook import workbook_parts, iter_rows, workbook_scope
    with tempfile.TemporaryDirectory(prefix='atlas_vdi_parse_') as temporary:
        path = Path(temporary) / 'citrix.xlsx'; path.write_bytes(content)
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(part.file_size for part in archive.infolist()) > MAX_EXPANDED_BYTES:
                    raise ValueError('Expanded Citrix workbook exceeds 512 MB.')
            @workbook_scope
            def read():
                return _parse_sheets([(sheet, iter(iter_rows(path, part, raw=True))) for sheet, part in workbook_parts(path)])
            return read()
        except (zipfile.BadZipFile, KeyError, IndexError, sqlite3.Error, ET.ParseError) as error:
            raise ValueError('Invalid Citrix XLSX workbook.') from error


@_read_snapshot
def load(con, *, include_source=True):
    if not exists(con):
        return {}
    columns = '*' if include_source else ','.join(column for column in DEVICE_FIELDS if column not in ('raw_json', 'source_rows_json'))
    cursor = con.execute('select ' + columns + ' from vdi_devices order by machine_key')
    names = [item[0] for item in cursor.description]
    rows = {values[0]: dict(zip(names, values)) for values in cursor}
    for row in rows.values():
        row['users'] = []
    for key, ref, raw, account, domain, valid, status, candidates in con.execute('select * from vdi_user_refs order by machine_key,ref_norm'):
        if key in rows:
            rows[key]['users'].append({'ref_norm': ref, 'raw_ref': raw, 'account': account, 'domain': domain,
                                      'valid': valid, 'status': status, 'candidates': json.loads(candidates)})
    return rows


def fingerprint(con):
    digest = hashlib.sha256()
    if con.execute("select 1 from sqlite_master where type='table' and name='metadata'").fetchone():
        for row in con.execute("select key,value from metadata where key in ('directory.generation','generation','directory.created_at','created_at') order by key"):
            digest.update(repr(tuple(row)).encode())
    # User identities can change without a generation bump through maintenance tools.
    if con.execute("select 1 from sqlite_master where type='table' and name='users'").fetchone():
        for row in con.execute('select id,canonical_key,user_id from users order by canonical_key'):
            digest.update(repr(tuple(row)).encode())
    if con.execute("select 1 from sqlite_master where type='table' and name='user_aliases'").fetchone():
        for row in con.execute("select user_id_ref,alias_type,alias_value,alias_norm from user_aliases where alias_type='user_id' order by user_id_ref,alias_norm"):
            digest.update(repr(tuple(row)).encode())
    if exists(con):
        for table in TABLES:
            for row in con.execute('select * from ' + table + ' order by 1,2'):
                digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


def _account_index(con):
    # Use only exported account fields/aliases. Emails and display names never
    # become Citrix account evidence; an explicit UPN remains an exact account.
    from backend.directory.identity_links import build_index
    columns = {row[1] for row in con.execute('pragma table_info(users)')}
    if not {'canonical_key', 'user_id'} <= columns:
        return defaultdict(set), defaultdict(set), {}
    index = build_index(con, canonical=True, include_names=False, accounts_only=True)
    return index.accounts, index.bare, index.domains


def match_refs(con, rows):
    full, bare, domains = _account_index(con)
    result = {'matched_users': 0, 'unmatched_users': 0, 'ambiguous_users': 0,
              'unmatched_examples': [], 'ambiguous_examples': [], 'associations': 0}
    links = set()
    for key, row in rows.items():
        for ref in row['users']:
            ids = set()
            reason = 'unknown_account'
            if not ref['valid']:
                reason = 'invalid_account'
            elif row['matching_issue']:
                reason = 'invalid_machine_name'
            else:
                ids = full.get(ref['ref_norm'], set()) if ref['domain'] else set()
                if not ids:
                    ids = bare.get(ref['account'], set())
                    if ref['domain']:
                        # A known conflicting domain never matches by dropping it.
                        ids = {uid for uid in ids if not domains.get(uid) or ref['domain'] in domains.get(uid, set())}
                        if not ids and bare.get(ref['account']):
                            reason = 'domain_mismatch'
            status = 'matched' if len(ids) == 1 else 'ambiguous' if ids else 'unmatched'
            if status == 'ambiguous':
                reason = 'ambiguous_account'
            ref['status'] = status; ref['candidates'] = sorted(ids)
            result[status + '_users'] += 1
            if status == 'matched':
                links.add((key, next(iter(ids))))
            else:
                examples = result[status + '_examples']
                if len(examples) < 20:
                    example = {'account': ref['raw_ref'], 'machine_name': row['original_name'], 'reason': reason}
                    if ids:
                        example['matches'] = sorted(ids)[:20]
                    examples.append(example)
    result['associations'] = len(links)
    return result, links


def relink(con):
    if not exists(con):
        return {'matched_users': 0, 'unmatched_users': 0, 'ambiguous_users': 0, 'associations': 0,
                'unmatched_examples': [], 'ambiguous_examples': []}
    if not con.in_transaction:
        con.execute('begin immediate')
    rows = load(con, include_source=False)
    summary, links = match_refs(con, rows)
    con.execute('delete from vdi_links')
    con.executemany('insert into vdi_links values(?,?)', sorted(links))
    for key, row in rows.items():
        for ref in row['users']:
            con.execute('update vdi_user_refs set status=?,candidates_json=? where machine_key=? and ref_norm=?',
                        (ref['status'], json.dumps(ref['candidates']), key, ref['ref_norm']))
    return summary


def report(con, incoming, parsed, *, full_snapshot=False):
    existing = load(con)
    matching, _ = match_refs(con, incoming)
    before = set(existing); after = set(incoming) if full_snapshot else before | incoming.keys()
    def comparable(row):
        return {field: row.get(field, '') for field in DEVICE_FIELDS if field not in ('source', 'imported_at')} | {
            'users': [{field: ref[field] for field in ('raw_ref', 'ref_norm', 'account', 'domain', 'valid')} for ref in sorted(row['users'], key=lambda ref: ref['ref_norm'])]}
    changed = sum(comparable(incoming[key]) != comparable(existing[key]) for key in before & incoming.keys())
    collisions = defaultdict(list)
    combined = {**({} if full_snapshot else existing), **incoming}
    for row in combined.values():
        if row['short_norm']:
            collisions[row['short_norm']].append(row['original_name'])
    collision_examples = [{'short_name': name.upper(), 'machines': names[:20]} for name, names in sorted(collisions.items()) if len(names) > 1][:20]
    warnings = []
    if parsed['duplicates']:
        warnings.append(f"{parsed['duplicates']:,} duplicate machine rows: the last complete row wins; all originals are retained.")
    if parsed['invalid_machines']:
        warnings.append(f"{parsed['invalid_machines']:,} machine names are invalid or missing; retained as metadata without remote actions or user links.")
    if collision_examples:
        warnings.append('Some machines share a short hostname across domains. Use an exact qualified machine name; short names are never selected automatically.')
    if matching['unmatched_users'] or matching['ambiguous_users']:
        warnings.append('Unmatched or ambiguous account references are retained and will be checked again after the user directory is updated.')
    if parsed['ignored_sheets']:
        warnings.append('Sheets without Citrix Name/User headers were skipped: ' + ', '.join(parsed['ignored_sheets']))
    return {**parsed, **matching, 'before': len(before), 'after': len(after), 'added': len(incoming.keys() - before),
            'changed': changed, 'removed': len(before - after), 'retained': len(before - incoming.keys()) if not full_snapshot else 0,
            'full_snapshot': full_snapshot, 'warnings': warnings, 'collision_examples': collision_examples,
            'removed_examples': [existing[key]['original_name'] for key in sorted(before - after)[:20]],
            'machine_examples': [{'machine_name': row['original_name'], 'catalog': row['catalog'],
                                  'delivery_group': row['delivery_group'], 'users': [ref['raw_ref'] for ref in row['users']]}
                                 for row in list(incoming.values())[:20]]}


def write_rows(con, rows, source, at, *, full_snapshot=False):
    if full_snapshot:
        for table in ('vdi_links', 'vdi_user_refs', 'vdi_devices'):
            con.execute('delete from ' + table)
    for key, row in rows.items():
        con.execute('delete from vdi_links where machine_key=?', (key,))
        con.execute('delete from vdi_user_refs where machine_key=?', (key,))
        values = {**row, 'source': source, 'imported_at': at}
        con.execute('insert into vdi_devices(' + ','.join(DEVICE_FIELDS) + ') values(' + ','.join('?' for _ in DEVICE_FIELDS) + ') on conflict(machine_key) do update set ' + ','.join(field + '=excluded.' + field for field in DEVICE_FIELDS if field != 'machine_key'), tuple(values[field] for field in DEVICE_FIELDS))
        for ref in row['users']:
            con.execute('insert into vdi_user_refs values(?,?,?,?,?,?,?,?)',
                        (key, ref['ref_norm'], ref['raw_ref'], ref['account'], ref['domain'], ref['valid'], 'unmatched', '[]'))
    return relink(con)


def backup_payload(con, at):
    return {'schema': 1, 'at': at, 'tables': {table: {'columns': [row[1] for row in con.execute('pragma table_info(' + table + ')')],
                                                 'rows': [list(row) for row in con.execute('select * from ' + table + ' order by 1,2')]}
                                           for table in TABLES}}


def _bool(value):
    value = str(value).strip().casefold()
    return True if value in ('true', 'yes', '1', 'on') else False if value in ('false', 'no', '0', 'off') else None


def serialize_device(row):
    row = dict(row); refs = row.get('users', []); name = row['target_name'] or row['original_name'] or 'Unnamed Citrix VDI'
    collision = row.get('short_collisions', 1) > 1 and row['target_name'] == row['short_name']
    return {'id': 'vdi:' + row['machine_key'], 'vdi_key': row['machine_key'], 'name': name, 'machine_name': name,
            'name_norm': row['name_norm'], 'device_kind': 'vdi', 'windows_remote_supported': bool(row['target_name']) and not collision,
            'model_id': '', 'serial_number': '', 'operational_status': row['registration_state'],
            'assigned_to': '', 'last_logon_user': '', 'assigned_relationship': int(bool(refs)), 'logon_relationship': 0,
            'match_type': 'Assigned (Citrix export)', 'link_source': 'Citrix assignment snapshot',
            'relationship_group': 'Assigned to user' if refs else 'Citrix inventory',
            'source_kind': 'citrix', 'inventory_source': 'Citrix export',
            'discovery_source': 'Citrix export',
            'last_discovered': '', 'updated_on': row['imported_at'],
            'inventory_discovered_at': None, 'inventory_updated_at': row['imported_at'],
            'vdi_short_name': row['short_name'], 'vdi_original_name': row['original_name'], 'vdi_domain': row['domain'],
            'vdi_catalog': row['catalog'], 'vdi_delivery_group': row['delivery_group'],
            'vdi_user_display_names': row['user_display_names'], 'vdi_maintenance_mode': row['maintenance_mode'],
            'vdi_maintenance_enabled': _bool(row['maintenance_mode']), 'vdi_user_change_persistence': row['user_change_persistence'],
            'vdi_power_state': row['power_state'], 'vdi_registration_state': row['registration_state'],
            'vdi_assigned_users': [ref['raw_ref'] for ref in refs], 'vdi_assignment_count': len(refs),
            'vdi_shared': len(refs) > 1, 'vdi_imported_at': row['imported_at'], 'vdi_source': row['source'],
            'vdi_matching_issue': row['matching_issue'], 'vdi_short_name_ambiguous': row.get('short_collisions', 1) > 1}


@_read_snapshot
def _read_records(con, sql, parameters):
    cursor = con.execute(sql, parameters); names = [item[0] for item in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor]
    if not rows:
        return []
    indexed = {row['machine_key']: row for row in rows}
    for row in rows:
        row['users'] = []
    # Profile/search pages only read the selected indexed refs, never global users.
    for start in range(0, len(rows), 200):
        keys = [row['machine_key'] for row in rows[start:start+200]]
        for key, ref, raw, account, domain, valid, status, candidates in con.execute('select * from vdi_user_refs where machine_key in (' + ','.join('?' for _ in keys) + ') order by machine_key,ref_norm', keys):
            indexed[key]['users'].append({'ref_norm': ref, 'raw_ref': raw, 'account': account, 'domain': domain,
                                         'valid': valid, 'status': status, 'candidates': json.loads(candidates)})
    return [serialize_device(row) for row in rows]


READ_COLUMNS = ','.join('d.' + column for column in DEVICE_FIELDS if column not in ('raw_json', 'source_rows_json')) + ",(select count(*) from vdi_devices other where other.short_norm=d.short_norm and other.target_name<>'') as short_collisions"


def machines_for_user(con, user_key):
    if not exists(con):
        return []
    return _read_records(con, 'select ' + READ_COLUMNS + ' from vdi_links l join vdi_devices d on d.machine_key=l.machine_key where l.user_key=? order by d.name_norm,d.machine_key', (user_key,))


def machine_records(con, target):
    if not exists(con):
        return []
    value = str(target).strip().rstrip('.').casefold()
    if '.' not in value and '\\' not in value and ':' not in value:
        return _read_records(con, 'select ' + READ_COLUMNS + ' from vdi_devices d where d.short_norm=? order by d.machine_key', (value,))
    # Exact qualified identity first; a short-name collision returns all candidates.
    exact = _read_records(con, 'select ' + READ_COLUMNS + ' from vdi_devices d where d.machine_key=? or d.name_norm=? or lower(d.original_name)=? order by d.machine_key', (value, value, value))
    if exact:
        return exact
    return _read_records(con, 'select ' + READ_COLUMNS + ' from vdi_devices d where d.short_norm=? order by d.machine_key', (value,))


def search_records(con, term, *, exact=False, field=None, limit=100):
    if not exists(con):
        return []
    limit = max(1, min(int(limit), 100))
    if exact:
        return machine_records(con, term)[:limit]
    fields = {'catalog': 'catalog', 'delivery_group': 'delivery_group', 'domain': 'domain', 'state': 'registration_state',
              'operational_status': 'registration_state', 'model_id': 'catalog', 'source_ci': 'original_name',
              'power_state': 'power_state', 'maintenance_mode': 'maintenance_mode', 'name': 'original_name'}
    value = str(term).strip().casefold()
    if not value:
        return []
    like = '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    if field == 'device_kind':
        if value not in 'vdi':
            return []
        condition = '1=1'; parameters = ()
    elif field == 'assigned_to':
        condition = "exists(select 1 from vdi_user_refs r where r.machine_key=d.machine_key and lower(r.raw_ref) like ? escape '\\')"
        parameters = (like,)
    elif field == 'discovery_source':
        if value in 'citrix export':
            condition = '1=1'; parameters = ()
        else:
            condition = "lower(d.source) like ? escape '\\'"; parameters = (like,)
    elif field:
        column = fields.get(field)
        if not column:
            return []
        condition = 'lower(d.' + column + ") like ? escape '\\'"; parameters = (like,)
    else:
        condition = "(d.name_norm like ? escape '\\' or lower(d.original_name) like ? escape '\\' or lower(d.catalog) like ? escape '\\' or lower(d.delivery_group) like ? escape '\\')"
        parameters = (like,)*4
    return _read_records(con, 'select ' + READ_COLUMNS + ' from vdi_devices d where ' + condition + ' order by d.name_norm,d.machine_key limit ?', (*parameters, limit))


def record(con, key, *, include_unmapped=True):
    if not exists(con):
        return None
    cursor = con.execute('select * from vdi_devices where machine_key=?', (key,)); values = cursor.fetchone()
    if values is None:
        return None
    row = dict(zip([item[0] for item in cursor.description], values))
    envelope = json.loads(row['source_rows_json'])
    selected = next((source for source in envelope['rows'] if source['sheet'] == envelope['selected_sheet'] and source['row'] == envelope['selected_row']), None)
    if selected is None:
        return None
    headers = next(source['headers'] for source in envelope['sources'] if source['sheet'] == selected['sheet'])
    mapping = {alias: field for field, aliases in FIELDS.items() for alias in aliases}
    fields = [{'header': header or f'Column {i+1}', 'label': header or f'Column {i+1}',
               'field': mapping.get(header_key(header), ''), 'value': selected['cells'][i] if i < len(selected['cells']) else ''}
              for i, header in enumerate(headers)]
    visible = fields if include_unmapped else [field for field in fields if field['field']]
    result = {'name': row['target_name'] or row['original_name'] or 'Unnamed Citrix VDI', 'source': row['source'],
            'sheet': selected['sheet'], 'row': selected['row'], 'source_rows': len(envelope['rows']),
            'original_cells': True, 'fields': visible, 'restricted_columns': len(fields)-len(visible)}
    if include_unmapped:
        result['raw_rows'] = envelope
    return result
