"""ServiceNow package enrichment. CSV data never supplies executable packages."""
import csv
import hashlib
import io
import json
import os
from collections import Counter
from datetime import datetime, timezone

FIELDS = {
    'short_name': ('name', 'short package name', 'short_package_name'),
    'display_name': ('u_display_name', 'display name', 'display_name'),
    'package_id': ('u_barclays_correlation_id', 'package id', 'package_id'),
    'state': ('u_package_sub_state', 'package state', 'state'),
    'requester': ('u_requester', 'requester'),
    'packager': ('assigned_to', 'packager (assigned to)', 'packager', 'assigned to'),
    'domain': ('u_domain', 'domain'),
    'build': ('u_build', 'build'),
    'created': ('sys_created_on', 'created', 'created on'),
}
SOURCE_FIELDS = ('raw_json', 'source_rows_json')
UPDATED_HEADERS = ('sys_updated_on', 'updated_on', 'updated', 'updated on')
RAW_PREFIX = '/atlas-raw/'
SCHEMA = '''
create table if not exists package_data(
 name_key text primary key, short_name text not null, display_name text not null,
 package_id text not null, state text not null, requester text not null,
 packager text not null, domain text not null, build text not null, created text not null,
 raw_json text not null, source text not null, imported_at text not null,
 source_rows_json text not null default '{}');
create table if not exists package_data_imports(
 id text primary key, at text not null, source text not null, report text not null, backup text not null);
'''


def name_key(value):
    # Deliberately no punctuation, version or prefix normalization.
    return value.strip().casefold()


def matching_issue(short):
    if not short:
        return 'missing_short_name'
    if len(short) > 200 or short in ('.', '..') or any(c in '/\\<>:"|?*' or ord(c) < 32 for c in short):
        return 'non_folder_name'
    return ''


def record_key(row, headers, cells):
    """Separate raw metadata identity from a real SharePoint folder name."""
    short = row['short_name']
    if not matching_issue(short):
        return name_key(short)
    if short:
        identity = ('literal_name', name_key(short))
    else:
        sys_id = next((cells[i].strip() for i, h in enumerate(headers)
                       if h.strip().casefold() == 'sys_id' and cells[i].strip()), '')
        if sys_id:
            identity = ('sys_id', sys_id.casefold())
        elif row['package_id']:
            identity = ('package_id', row['package_id'].casefold())
        else:
            identity = ('original_row', dict(zip((h.strip().casefold() for h in headers), cells)))
    # '/' cannot occur in a directory entry name, so raw keys cannot match a source folder.
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return RAW_PREFIX + digest


def initialize(con):
    con.executescript(SCHEMA)
    columns = {row[1] for row in con.execute('pragma table_info(package_data)')}
    if 'source_rows_json' not in columns:
        con.execute("alter table package_data add column source_rows_json text not null default '{}'")


def load(con, *, include_source=True):
    if not con.execute("select 1 from sqlite_master where type='table' and name='package_data'").fetchone():
        return {}
    columns = '*' if include_source else ','.join(['name_key', *FIELDS, 'source', 'imported_at'])
    cursor = con.execute(f'select {columns} from package_data order by name_key')
    columns = [c[0] for c in cursor.description]
    return {row[0]: dict(zip(columns, row)) for row in cursor}


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def updated_rank(value):
    """Only an explicit update time can outrank CSV order; creation is not an update."""
    value = value.strip()
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        date = None
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
            try:
                date = datetime.strptime(value, fmt)
                break
            except ValueError:
                pass
        if date is None:
            return None
    return (date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date).timestamp()


def parse_csv(data):
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError('Choose a package CSV up to 10 MB.')
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        text = data.decode('cp1252')
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=''), dialect=dialect, strict=True, skipinitialspace=False)
    try:
        headers = next(reader)
        if not headers or len(headers) > 100:
            raise ValueError('CSV must have a header row with up to 100 columns.')
        normalized = [h.strip().casefold() for h in headers]
        if len(set(normalized)) != len(headers) or '' in normalized:
            raise ValueError('CSV headers must be unique and non-empty.')
        mapping = {}
        for field, aliases in FIELDS.items():
            matches = [i for i, h in enumerate(normalized) if h in aliases]
            if len(matches) > 1:
                raise ValueError(f'Multiple columns map to {field}. Keep one column for each field.')
            if matches:
                mapping[field] = matches[0]
        if not {'short_name', 'state'} <= mapping.keys():
            raise ValueError('CSV needs name (Short Package Name) and u_package_sub_state (Package State) headers.')
        updated_columns = [i for i, h in enumerate(normalized) if h in UPDATED_HEADERS]
        rows = {}; sources = {}; ranks = {}; signatures = {}
        duplicates = 0; identical_duplicates = 0; row_count = 0
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            row_count += 1
            if row_count > 20000:
                raise ValueError('Package CSV exceeds 20,000 rows.')
            if len(cells) != len(headers):
                raise ValueError(f'CSV row {reader.line_num} has {len(cells)} cells; expected {len(headers)}. Quote values containing commas.')
            if any(len(c) > 4096 or '\x00' in c for c in cells):
                raise ValueError(f'CSV row {reader.line_num} has an invalid or oversized cell.')
            row = {field: cells[mapping[field]].strip() if field in mapping else '' for field in FIELDS}
            key = record_key(row, headers, cells)
            row['name_key'] = key
            row['raw_json'] = json.dumps(dict(zip(headers, cells)), ensure_ascii=False)
            rank = next((rank for i in updated_columns if (rank := updated_rank(cells[i])) is not None), None)
            signature_cells = list(cells)
            signature_cells[mapping['short_name']] = key
            signature = hashlib.sha256(json.dumps(signature_cells, ensure_ascii=False).encode()).digest()
            if key in rows:
                duplicates += 1
                identical_duplicates += signature in signatures[key]
            else:
                sources[key] = {'headers': headers, 'rows': []}
                if key.startswith(RAW_PREFIX):
                    sources[key]['matching_issue'] = matching_issue(row['short_name'])
                signatures[key] = set()
            signatures[key].add(signature)
            sources[key]['rows'].append({'row': reader.line_num, 'cells': cells})
            old_rank = ranks.get(key)
            if key not in rows or old_rank is None or (rank is not None and rank >= old_rank):
                # Select a whole record, including blanks; never mix states or owners across rows.
                rows[key] = row
                ranks[key] = rank
                sources[key].update(selected_row=reader.line_num,
                                    selection='latest_updated' if rank is not None else 'last_row')
        if not rows:
            raise ValueError('CSV contains no package rows.')
        duplicate_examples = []
        duplicate_names = 0
        unmatched_examples = []
        unmatched_rows = 0; unmatched_records = 0
        for key, row in rows.items():
            source = sources[key]
            row['source_rows_json'] = json.dumps(source, ensure_ascii=False, separators=(',', ':'))
            if key.startswith(RAW_PREFIX):
                unmatched_rows += len(source['rows']); unmatched_records += 1
                if len(unmatched_examples) < 20:
                    unmatched_examples.append({'row': source['selected_row'], 'short_name': row['short_name'],
                                               'package_id': row['package_id'], 'reason': source['matching_issue']})
            if len(source['rows']) > 1:
                duplicate_names += 1
                if len(duplicate_examples) < 20:
                    duplicate_examples.append({'short_name': row['short_name'], 'rows': len(source['rows']),
                                               'selected_row': source['selected_row'], 'selection': source['selection']})
        return rows, {'rows': row_count, 'unique': len(rows), 'duplicates': duplicates,
                      'identical_duplicates': identical_duplicates, 'conflicting_duplicates': duplicates - identical_duplicates,
                      'duplicate_names': duplicate_names, 'duplicate_examples': duplicate_examples,
                      'unmatched_rows': unmatched_rows, 'unmatched_records': unmatched_records,
                      'unmatched_examples': unmatched_examples,
                      'columns': headers, 'extra_columns': [h for i, h in enumerate(headers) if i not in mapping.values()]}
    except (csv.Error, StopIteration) as error:
        raise ValueError('Invalid or empty package CSV: ' + str(error)) from error


def repository_names(repo):
    if repo is None:
        return [], False, 'SharePoint package files are available in Atlas Admin. This view shows stored package data.'
    try:
        with os.scandir(repo) as entries:
            # Read folder names only; do not hydrate or recursively inspect package files.
            return sorted([e.name for e in entries if e.is_dir(follow_symlinks=False) and not e.is_symlink()], key=str.casefold), True, ''
    except OSError:
        return [], False, 'Package source unavailable. Check Settings and OneDrive sync; stored package data is still shown.'


def join_metadata(folders, metadata):
    counts = Counter(name_key(folder) for folder in folders)
    return {folder: metadata.get(name_key(folder)) if counts[name_key(folder)] == 1 else None for folder in folders}


def browse(con, repo=None, *, term='', state='', coverage='', offset=0, limit=100):
    # Browsing needs operational fields, not every preserved CSV row.
    metadata = load(con, include_source=False)
    folders, available, note = repository_names(repo)
    counts = Counter(name_key(f) for f in folders)
    manual = {}
    if repo is not None and con.execute("select 1 from sqlite_master where name='package_catalog'").fetchone():
        manual = {f: {'display_name': n, 'version': v} for f, n, v in con.execute(
            'select folder,display_name,version from package_catalog where repository=?', (str(repo.resolve()),))}
    items = []; matched = set()
    for folder in folders:
        key = name_key(folder); ambiguous = counts[key] > 1
        data = metadata.get(key) if not ambiguous else None
        if data:
            matched.add(key)
        custom = manual.get(folder, {})
        items.append({**(data or {}), 'id': 'repo:' + folder, 'short_name': folder,
                      'folder': folder, 'display_name': custom.get('display_name') or (data or {}).get('display_name') or folder,
                      'version': custom.get('version', ''), 'state': (data or {}).get('state', ''),
                      'coverage': 'matched' if data else 'ambiguous' if ambiguous else 'source-only',
                      'source_present': True, 'metadata_present': bool(data), 'ambiguous': ambiguous})
    for key, data in metadata.items():
        if key not in matched:
            items.append({**data, 'id': 'data:' + key, 'folder': '', 'version': '',
                          'display_name': data['display_name'] or data['short_name'] or data['package_id'] or 'Unnamed package',
                          'coverage': 'metadata-only', 'source_present': False, 'metadata_present': True,
                          'ambiguous': counts[key] > 1})
            if key.startswith(RAW_PREFIX):
                items[-1]['metadata_note'] = ('Short name not supplied; original record preserved.' if not data['short_name']
                                             else 'Original short name preserved; no source folder match.')
    stats = {'source_packages': len(folders), 'metadata_packages': len(metadata), 'matched': len(matched),
             'source_only': sum(i['coverage'] == 'source-only' for i in items),
             'metadata_only': len(metadata) - len(matched),
             'ambiguous': sum(i['coverage'] == 'ambiguous' for i in items)}
    states = sorted({data['state'] for data in metadata.values() if data['state']}, key=str.casefold)
    query = term.strip().casefold()
    items = [i for i in items if (not state or i['state'].casefold() == state.casefold())
             and (not coverage or i['coverage'] == coverage)
             and (not query or any(query in str(i.get(f, '')).casefold() for f in
                  ('short_name', 'display_name', 'package_id', 'state', 'requester', 'packager', 'domain', 'build')))]
    items.sort(key=lambda i: ((i['short_name'] or i['display_name']).casefold(), i['id']))
    total = len(items)
    for item in items:
        item.pop('raw_json', None)
    return {'items': items[offset:offset + limit], 'total': total, 'offset': offset, 'limit': limit,
            'stats': stats, 'states': states, 'source_available': available, 'note': note}


def report(incoming, existing, repo, parsed):
    folders, available, note = repository_names(repo)
    counts = Counter(name_key(f) for f in folders)
    added = sum(key not in existing for key in incoming)
    changed = sum(key in existing and any(incoming[key][f] != existing[key][f] for f in FIELDS) for key in incoming)
    return {**parsed, 'before': len(existing), 'after': len(existing.keys() | incoming.keys()),
            'added': added, 'changed': changed, 'unchanged': len(incoming) - added - changed,
            'retained': len(existing.keys() - incoming.keys()),
            'matched': sum(counts[key] == 1 for key in incoming),
            'metadata_only': sum(counts[key] == 0 for key in incoming),
            'ambiguous': sum(counts[key] > 1 for key in incoming),
            'source_packages': len(folders), 'source_available': available, 'note': note,
            'examples': [{f: r[f] for f in FIELDS} for r in list(incoming.values())[:12]]}
