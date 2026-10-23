"""Optional asset fields and conservative device classification for directory records."""
import hashlib
import json
import re
from identity_links import EMPTY_IDENTITIES

ASSET_COLUMNS = ('asset_tag', 'model_category', 'last_used', 'install_status',
                 'assigned_at', 'display_name', 'device_location', 'source_ci')
NON_WINDOWS_KINDS = frozenset(('iphone', 'phone', 'tablet', 'mac', 'inventory'))
EMPTY_IDENTIFIERS = EMPTY_IDENTITIES | {'na', 'not supplied'}
_DNS_NAME = re.compile(r'[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)*')
_INVENTORY_NAME = re.compile(r'^INVENTORY-(?:CMDB|SERIAL|ASSET|CI|ROW):')


def canonical_machine_name(value):
    """Normalize DNS case/root-dot without dropping the host's domain."""
    value = str(value or '').strip().upper()
    if value.endswith('.') and _DNS_NAME.fullmatch(value[:-1]):
        return value[:-1]
    return value


def _inventory_token(value):
    # A literal hexadecimal identifier must not collide with an encoded one.
    if re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{0,39}', value):
        return 'RAW-' + value
    return 'HASH-' + hashlib.sha256(value.encode()).hexdigest()[:24].upper()

def row_identity(record, row_number, *, snapshot_id=None, compact=False):
    """Unidentified rows have continuity only within the same source snapshot."""
    snapshot = snapshot_id or hashlib.sha256(json.dumps(
        record, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str
    ).encode()).hexdigest()
    # Mobile display keys stay within 64 characters; 128 bits scope their rows.
    return (snapshot[:32] if compact else snapshot) + ':' + str(row_number)


def inventory_identity(record, row_number, *, snapshot_id=None):
    """Keep real PC hostnames; identify mobile assets without using generic CI labels."""
    source = str(record.get('machine_name') or '').strip()
    kind = device_kind(source, record.get('model_category'), record.get('model_id'),
                       record.get('sys_class_name'))
    if kind not in NON_WINDOWS_KINDS:
        name = canonical_machine_name(source)
        if name and '\\' not in name and '.' not in name:
            domain = next((str(record.get(column) or '').strip().upper()
                           for column in ('domain', 'domain_name', 'netbios_domain', 'ad_domain')
                           if str(record.get(column) or '').strip().casefold() not in EMPTY_IDENTIFIERS), '')
            if domain:
                name = canonical_machine_name(domain) + '\\' + name
        return name, 'hostname' if source else ''
    for column, namespace in (('sys_id', 'CMDB:'), ('serial_number', 'SERIAL:'), ('asset_tag', 'ASSET:')):
        value = str(record.get(column) or '').strip().upper()
        if value.casefold() not in EMPTY_IDENTIFIERS:
            return f'INVENTORY-{namespace}{_inventory_token(value)}', column
    # A meaningful CI is useful when the export has no hardware identifier.
    generic = EMPTY_IDENTIFIERS | {'iphone', 'ipad', 'phone', 'tablet', 'mac', 'mobile device', 'mobile device - handheld'}
    if source and source.casefold() not in generic:
        return f'INVENTORY-CI:{_inventory_token(source.upper())}', 'ci'
    # Without an identifier, preserve each source row rather than merging unrelated phones.
    return 'INVENTORY-ROW:' + row_identity(record, row_number, snapshot_id=snapshot_id, compact=True), 'row'


def ensure_asset_columns(con):
    """Called inside a writable refresh transaction; old backups remain compatible."""
    known = {r[1] for r in con.execute('pragma table_info(machines)')}
    for column in ASSET_COLUMNS:
        if column not in known:
            con.execute(f"alter table machines add column {column} text not null default ''")
    con.execute('create index if not exists ix_machines_asset_lower on machines(lower(asset_tag))')
    con.execute('create index if not exists ix_machines_source_ci_lower on machines(lower(source_ci))')


def device_kind(name='', category='', model='', record_class=''):
    text = ' '.join(str(v or '') for v in (category, model, record_class)).lower()
    hostname = str(name or '').strip().upper().split('.')[0]
    if 'iphone' in text or hostname=='IPHONE' or hostname.startswith('IPHONE-'): return 'iphone'
    if re.search(r'\b(ipad|tablet)\b', text) or hostname in ('IPAD','TABLET') or hostname.startswith(('IPAD-','TABLET-')): return 'tablet'
    if re.search(r'mobile device|handheld|android|\b(phone|smartphone)\b', text) or hostname=='PHONE' or hostname.startswith('PHONE-'): return 'phone'
    if re.search(r'\b(macbook|imac|mac mini|mac pro)\b', text): return 'mac'
    if re.search(r'\b(vdi|virtual desktop|virtual machine)\b', text) or 'VDI' in hostname: return 'vdi'
    if re.search(r'\b(laptop|notebook|latitude|thinkpad|elitebook|zbook|probook)\b', text): return 'laptop'
    if re.match(r'^[A-Z]{3}PWMK', hostname): return 'kiosk'
    if re.match(r'^[A-Z]{3}PWMF', hostname): return 'desktop'
    if re.search(r'\b(computer|desktop|workstation)\b', text): return 'desktop'
    if _INVENTORY_NAME.match(hostname): return 'inventory'
    return 'other'


def supports_windows(record):
    name = str(record.get('machine_name', record.get('name', '')) or '').strip()
    if _INVENTORY_NAME.match(name.upper()) or '\\' in name:
        return False
    return device_kind(name,
                       record.get('model_category', ''), record.get('model_id', ''),
                       record.get('sys_class_name', '')) not in NON_WINDOWS_KINDS
