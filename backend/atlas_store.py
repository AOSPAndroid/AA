import json,sqlite3,re,math,uuid
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"atlas"
from backend.runtime_paths import database_path
DB=database_path()

class Conflict(ValueError):
    pass

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect():
    return sqlite3.connect(str(DB), timeout=15, factory=ClosingConnection)

def get_record(con, desk_id):
    row = con.execute('SELECT body FROM records WHERE id=?', (desk_id,)).fetchone()
    layout = 'previous'
    if not row and con.execute("select 1 from sqlite_master where type='table' and name='official_records'").fetchone():
        row = con.execute('SELECT body FROM official_records WHERE id=?', (desk_id,)).fetchone()
        layout = 'official'
    if not row:
        return None
    record = json.loads(row[0])
    record.setdefault('layout', layout)
    return record

def all_records(con):
    return [dict(json.loads(row[0]),layout='previous') for row in con.execute('SELECT body FROM records ORDER BY id')]

def check_revision(old, revision):
    if (old or {}).get('revision', 0) != revision:
        raise Conflict('This desk changed in another window. Refresh, review the latest record and retry.')

def validate(item):
    if not isinstance(item, dict):
        raise ValueError('Invalid record')
    r = {}
    for key, limit in [('id',180),('name',160),('team',120),('asset',120),('hostname',120),('outlet',160),('notes',4000),('status',120)]:
        value = item.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Invalid ' + key)
        r[key] = value.strip()
    if not re.fullmatch(r'(L[2-7]-[0-9]+|custom-[a-zA-Z0-9-]+|[0-9]{2}[A-Z][0-9]{6})', r['id']):
        raise ValueError('Invalid desk ID')
    if type(item.get('floor')) is not int or not -1 <= item['floor'] <= 8:
        raise ValueError('Invalid floor')
    r['floor'] = item['floor']
    for key in ['x', 'y', 'angle']:
        value = item.get(key, 0)
        if type(value) not in (int, float) or not math.isfinite(value) or (key != 'angle' and not 0 <= value <= 1):
            raise ValueError('Invalid ' + key)
        r[key] = value % 360 if key == 'angle' else value
    r['kind'] = item.get('kind', 'desk')
    r['occupancy'] = item.get('occupancy', 'unconfirmed')
    if r['kind'] not in ['desk', 'area'] or r['occupancy'] not in ['assigned', 'vacant', 'unconfirmed']:
        raise ValueError('Invalid desk type or occupancy')
    if not r['name']:
        if r['occupancy'] == 'assigned':
            raise ValueError('Assigned desks require a name')
        r['name'] = 'Vacant desk' if r['occupancy'] == 'vacant' else 'Unconfirmed desk'
    if 'layout' in item:
        if item['layout'] not in ('official','previous'):raise ValueError('Invalid layout')
        r['layout']=item['layout']
    r['verified'] = item.get('verified') is True
    return r

def save_record(con, record, old, action):
    record = validate(record)
    prior_layout=(old or {}).get('layout')
    if prior_layout and record.get('layout',prior_layout)!=prior_layout:raise ValueError('Use the seating mapping workflow to change layouts')
    record['layout']=prior_layout or record.get('layout') or ('official' if re.fullmatch(r'[0-9]{2}[A-Z][0-9]{6}',record['id']) else 'previous')
    record['revision'] = (old or {}).get('revision', 0) + 1
    record['updatedAt'] = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(record, ensure_ascii=False)
    table='official_records' if record['layout']=='official' else 'records'
    con.execute('INSERT OR REPLACE INTO '+table+'(id, body) VALUES (?, ?)', (record['id'], encoded))
    con.execute('INSERT INTO history(desk_id, at, action, before_json, after_json) VALUES (?, ?, ?, ?, ?)',
                (record['id'], record['updatedAt'], action, json.dumps(old) if old else None, encoded))

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY, desk_id TEXT NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL)')
        con.execute('CREATE INDEX IF NOT EXISTS history_desk ON history(desk_id, seq)')
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
            con.execute('CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users(lower(email))')
            con.execute('CREATE INDEX IF NOT EXISTS ix_users_employee_lower ON users(lower(employee_number))')
            con.execute('CREATE INDEX IF NOT EXISTS ix_alias_kind_norm ON user_aliases(alias_type,alias_norm)')
            con.execute('CREATE INDEX IF NOT EXISTS ix_alias_user ON user_aliases(user_id_ref)')
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='machines'").fetchone():
            con.execute('CREATE INDEX IF NOT EXISTS ix_machines_serial_lower ON machines(lower(serial_number))')
            con.execute('CREATE INDEX IF NOT EXISTS ix_machines_correlation_lower ON machines(lower(correlation_id))')
            from backend.directory.directory_lookup import MACHINE_SHORT_SQL
            con.execute('CREATE INDEX IF NOT EXISTS ix_machines_short ON machines('+MACHINE_SHORT_SQL+')')
        con.execute('BEGIN IMMEDIATE')
        from backend.directory.identity_links import MATCHING_VERSION,rebuild_links
        tables={row[0] for row in con.execute("select name from sqlite_master where type='table'")}
        if {'users','user_aliases','machines','assignments'} <= tables:
            version=con.execute("select value from metadata where key='directory.matching_version'").fetchone()
            if not version or version[0]!=MATCHING_VERSION:
                rebuild_links(con,preserve_manual=True)
                from backend.directory.vdi_data import exists as vdi_exists,relink as relink_vdi,initialize as initialize_vdi
                if vdi_exists(con):
                    initialize_vdi(con);relink_vdi(con)
                con.execute('insert or replace into metadata values(?,?)',('directory.matching_version',MATCHING_VERSION))
                con.execute('insert or replace into metadata values(?,?)',('directory.generation',uuid.uuid4().hex))
        if not con.execute("SELECT 1 FROM metadata WHERE key='atlas.seeded'").fetchone():
            for r in json.loads((ROOT / 'data.json').read_text(encoding='utf-8'))['records']:
                save_record(con, r, None, 'initial plan import')
            con.execute("INSERT INTO metadata VALUES ('atlas.seeded', '1')")
