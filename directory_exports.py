"""Export field definitions, lossless cell storage and read-only inspection.

Raw rows are separate from operational tables. Adding an export column never
changes the identity/assignment schema or enables an administrative operation.
"""
import json

USER_FIELDS = (
    ('user_name', 'user_id', 'Account'), ('name', 'full_name', 'Name'),
    ('email', 'email', 'Email'),
    ('u_organisational_unit', 'organisational_unit', 'Organisation'),
    ('u_business_unit', 'business_unit', 'Business unit'),
    ('u_start_date', 'start_date', 'Start date'), ('manager', 'manager', 'Manager'),
    ('location', 'location', 'Office'), ('last_login', 'last_login', 'Last login date'),
    ('last_login_time', 'last_login_time', 'Last login time'),
    ('title', 'job_role', 'Job title'), ('u_job_type', 'job_type', 'Worker type'),
    ('employee_number', 'employee_number', 'Employee ID'), ('department', 'department', 'Department'),
)
MACHINE_FIELDS = (
    ('name', 'machine_name', 'Hostname'),
    ('u_infrastructure_itsi', 'infrastructure_itsi', 'Infrastructure'),
    ('sys_class_name', 'sys_class_name', 'Record class'),
    ('operational_status', 'operational_status', 'Inventory status'),
    ('u_barclays_correlation_id', 'correlation_id', 'Correlation ID'),
    ('serial_number', 'serial_number', 'Serial number'),
    ('manufacturer', 'manufacturer', 'Manufacturer'), ('model_id', 'model_id', 'Model'),
    ('short_description', 'short_description', 'Description'),
    ('sys_updated_on', 'updated_on', 'Record updated'),
    ('last_discovered', 'last_discovered', 'Last discovered'),
    ('discovery_source', 'discovery_source', 'Discovery source'),
    ('assigned_to', 'assigned_to', 'Assigned to'),
    ('u_last_logon_user', 'last_logon_user', 'Last logged-on user'),
    ('asset_tag', 'asset_tag', 'Asset tag'),
    ('model_category', 'model_category', 'Device category'),
    ('cmp_last_used', 'last_used', 'Last used'),
    ('install_status', 'install_status', 'Asset state'),
    ('assigned', 'assigned_at', 'Assignment date'),
    ('display_name', 'display_name', 'Asset display name'),
    ('location', 'device_location', 'Device location'),
)
FIELDS = {'user': USER_FIELDS, 'machine': MACHINE_FIELDS}
TABLES = ('directory_export_sheets', 'directory_export_rows')


def sheet_kind(name):
    return {'users': 'user', 'devices': 'machine', 'computers': 'machine'}.get(str(name).strip().casefold(), '')


def field_map(kind):
    mapping = {alias: (column, label) for source, column, label in FIELDS.get(kind, ())
               for alias in (source, column)}
    if kind == 'machine':
        mapping.update(ci=mapping['name'], model=mapping['model_id'])
    return mapping


def exists(con):
    return con.execute("select 1 from sqlite_master where name='directory_export_sheets' and type='table'").fetchone() is not None


def schema(con):
    # Individual statements preserve the caller's transaction (no executescript).
    con.execute('create table if not exists directory_export_sheets(sheet text primary key,kind text not null,source_file text not null,headers text not null,populated text not null,row_count integer not null,linked_count integer not null)')
    con.execute('create table if not exists directory_export_rows(sheet text not null,row_number integer not null,entity_key text not null,cells text not null,primary key(sheet,row_number))')
    if 'selected' not in {r[1] for r in con.execute('pragma table_info(directory_export_rows)')}:
        con.execute('alter table directory_export_rows add column selected integer not null default 0')
    con.execute('create index if not exists ix_export_entity on directory_export_rows(entity_key,sheet)')


def copy_archive(source, target):
    schema(target)
    for table in reversed(TABLES):
        target.execute('delete from '+table)
    if exists(source):
        target.executemany('insert into directory_export_sheets values (?,?,?,?,?,?,?)',
                           (tuple(row) for row in source.execute('select * from directory_export_sheets')))
        selected='selected' if 'selected' in {r[1] for r in source.execute('pragma table_info(directory_export_rows)')} else '0'
        target.executemany('insert into directory_export_rows(sheet,row_number,entity_key,cells,selected) values (?,?,?,?,?)',
                           (tuple(row) for row in source.execute('select sheet,row_number,entity_key,cells,'+selected+' from directory_export_rows')))


def capture(con, path, *, selection_table=None, snapshot_id=None):
    from directory_workbook import workbook_parts, iter_rows, directory_columns, directory_data, user_identity, snapshot_identity, norm
    from device_inventory import inventory_identity
    if selection_table not in (None,'directory_import_sources'):raise ValueError('Unknown import selection table')
    if snapshot_id is None:snapshot_id=snapshot_identity(path)
    schema(con)
    for sheet, part in workbook_parts(path):
        kind = sheet_kind(sheet)
        rows = iter_rows(path, part, raw=True)
        first = next(rows, None)
        if first is None:
            con.execute('insert into directory_export_sheets values(?,?,?,?,?,?,?)',
                        (sheet, kind, path.name, '[]', '[]', 0, 0))
            continue
        _, headers = first
        columns=directory_columns(kind,headers)
        populated = [0] * len(headers)
        row_count = linked_count = 0
        for number, row in rows:
            if not any(value != '' for value in row):
                continue
            if len(row) > len(headers):
                headers.extend('' for _ in range(len(row)-len(headers)))
                populated.extend(0 for _ in range(len(headers)-len(populated)))
            cells = list(row)  # Positional arrays preserve duplicate/blank headers.
            d = directory_data(columns,row)
            key = ''
            if kind == 'user':
                key = user_identity(d,number,snapshot_id=snapshot_id)
            elif kind == 'machine':
                name,_=inventory_identity(d,number,snapshot_id=snapshot_id)
                if name:key='machine:'+norm(name)
            values=(sheet,number,key,json.dumps(cells,ensure_ascii=False,separators=(',',':')))
            if selection_table:
                con.execute('insert into directory_export_rows(sheet,row_number,entity_key,cells,selected) values(?,?,?,?,coalesce((select row_number=? from directory_import_sources where kind=? and entity_key=?),0))',values+(number,kind,key))
            else:
                con.execute('insert into directory_export_rows(sheet,row_number,entity_key,cells) values(?,?,?,?)',values)
            row_count += 1
            linked_count += bool(key)
            for i, value in enumerate(cells):
                populated[i] += value != ''
        con.execute('insert into directory_export_sheets values(?,?,?,?,?,?,?)',
                    (sheet, kind, path.name, json.dumps(headers, ensure_ascii=False),
                     json.dumps(populated), row_count, linked_count))


def column_info(kind, headers, populated):
    from directory_workbook import canonical_header
    mapping = field_map(kind)
    result = []
    for i, header in enumerate(headers):
        field, label = mapping.get(canonical_header(header), ('', ''))
        result.append({'column': i+1, 'header': header or f'Column {i+1}',
                       'field': field, 'label': label or header or f'Column {i+1}',
                       'populated': populated[i],
                       'use': 'Profile, search and export details' if field else 'Retained in export archive (admin)'})
    return result


def coverage(con):
    if exists(con) and con.execute('select 1 from directory_export_sheets limit 1').fetchone():
        sheets = []
        for sheet, kind, source, headers, populated, rows, linked in con.execute('select * from directory_export_sheets order by sheet'):
            sheets.append({'sheet': sheet, 'kind': kind, 'source': source, 'rows': rows, 'linked': linked,
                           'columns': column_info(kind, json.loads(headers), json.loads(populated))})
        return {'original_cells': True, 'sheets': sheets}
    sheets = []
    for kind, table, name in (('user', 'users', 'Users'), ('machine', 'machines', 'computers')):
        fields = FIELDS[kind]
        known = {r[1] for r in con.execute('pragma table_info('+table+')')}
        query = ','.join('sum(case when trim(coalesce('+('"'+column+'"' if column in known else 'NULL')+',\'\'))<>\'\' then 1 else 0 end)' for _, column, _ in fields)
        row = con.execute('select count(*),'+query+' from '+table).fetchone()
        sheets.append({'sheet': name, 'kind': kind, 'source': 'Stored directory', 'rows': row[0], 'linked': row[0],
                       'columns': column_info(kind, [f[0] for f in fields], [v or 0 for v in row[1:]])})
    return {'original_cells': False, 'sheets': sheets}


def record(con, kind, key, *, include_unmapped=True):
    # A refresh must not mix a person from one snapshot with another's cells.
    con.execute('savepoint directory_record_read')
    try:
        return _record(con, kind, key, include_unmapped=include_unmapped)
    finally:
        con.execute('release directory_record_read')


def _record(con, kind, key, *, include_unmapped):
    if kind not in FIELDS:
        raise ValueError('Choose a person or machine')
    table, identity = ('users', 'canonical_key') if kind == 'user' else ('machines', 'machine_name_norm')
    row = con.execute('select * from '+table+' where '+identity+'=?', (key,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    name = data['full_name' if kind == 'user' else 'machine_name']
    if exists(con):
        selected='r.selected desc,' if 'selected' in {r[1] for r in con.execute('pragma table_info(directory_export_rows)')} else ''
        archived = con.execute('select s.sheet,s.source_file,s.headers,r.row_number,r.cells from directory_export_rows r join directory_export_sheets s on s.sheet=r.sheet where r.entity_key=? and s.kind=? order by '+selected+'r.row_number limit 1',
                               (key if kind == 'user' else 'machine:'+key, kind)).fetchone()
        if archived:
            sheet, source, headers, number, cells = archived
            headers, cells = json.loads(headers), json.loads(cells)
            fields = column_info(kind, headers, [0]*len(headers))
            for i, field in enumerate(fields):
                field['value'] = cells[i] if i < len(cells) else ''
                field['stored_value'] = data.get(field['field']) if field['field'] else None
            visible = [field for field in fields if include_unmapped or field['field']]
            row_count=con.execute('select count(*) from directory_export_rows where sheet=? and entity_key=?',(sheet,key if kind=='user' else 'machine:'+key)).fetchone()[0]
            return {'name': name, 'source': source, 'sheet': sheet, 'row': number, 'source_rows':row_count,
                    'original_cells': True, 'fields': visible, 'restricted_columns': len(fields)-len(visible)}
    return {'name': name, 'source': 'Stored directory', 'original_cells': False,
            'fields': [{'header': source, 'label': label, 'field': column, 'value': data.get(column, '')}
                       for source, column, label in FIELDS[kind]], 'restricted_columns': 0}
