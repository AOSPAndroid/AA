"""LAN viewer: only explicit read routes, with read-only SQLite connections.

Never import backend.main here: its startup registers administrative operations
and performs database migrations. The launcher starts that process first.
"""
import os
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from directory_lookup import exact_users, linked_machines, search_directory, prepare_views
from desk_directory import desk_context,person_desks,machine_context,palette_search
import directory_exports
from backend import __version__
from response_compression import compress_responses
from static_responses import cached_file, prewarm

ROOT = Path(__file__).resolve().parent.parent
from runtime_paths import database_path
DB = database_path()
ATLAS = ROOT / 'atlas'
app = FastAPI(title='Atlas read-only viewer', version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
compress_responses(app)


@contextmanager
def connect():
    con = sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    prepare_views(con)
    con.execute('PRAGMA query_only=ON')
    try:
        yield con
    finally:
        con.close()


@app.middleware('http')
async def read_only(request: Request, call_next):
    if request.method not in ('GET', 'HEAD'):
        return JSONResponse({'detail': 'This shared Atlas is read only. Changes and remote operations require the local admin version.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') or request.url.path=='/' else 'public, max-age=0, must-revalidate'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
    return response


@app.get('/api/health')
def health():
    with connect() as con:
        con.execute('select body from official_records limit 1').fetchone()
        counts = {key: con.execute(f'select count(*) from {key}').fetchone()[0] for key in ('users','machines','assignments')}
        from vdi_inventory import count
        counts['vdi_machines'] = count(con)
    return {'application': 'Office Atlas', 'mode': 'viewer', 'version': __version__, 'read_only': True, 'instance_id': os.environ.get('ATLAS_INSTANCE_ID'), 'identity': 'Demo · read-only directory', 'database': True, 'repository': False, **counts}


@app.get('/api/capabilities')
def capabilities():
    return {'read_only': True, 'elevated_operations': False}


@app.get('/api/master/status')
def master_status():
    data = health()
    return {'available': True, **{key: data[key] for key in ('users','machines','assignments','vdi_machines')}}


@app.get('/api/package-data')
def packages(term: str = Query('', max_length=200), state: str = Query('', max_length=200),
             coverage: str = Query('', pattern='^(|matched|source-only|metadata-only|ambiguous)$'),
             offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    from package_data import browse
    with connect() as con:
        return browse(con, term=term, state=state, coverage=coverage, offset=offset, limit=limit)


@app.get('/api/master/resolve/{key}')
def resolve(key: str):
    from directory_lookup import resolve_directory
    with connect() as con:
        con.execute('begin')
        return resolve_directory(con,key)


@app.get('/api/palette/desks')
def palette_desks():
    with connect() as con:
        return {'records': [json.loads(row[0]) for row in con.execute('select body from official_records order by id')]}


@app.get('/api/official/version')
def official_version():
    from seating_sync import seating_version
    with connect() as con:
        return seating_version(con)


@app.get('/api/official/state')
def state():
    with connect() as con:
        return {'read_only': True, 'records': [dict(json.loads(r[0]),layout='official') for r in con.execute('select body from official_records order by id')],
                'legacy': [json.loads(r[0]) for r in con.execute('select body from records order by id')],
                'mappings': dict(con.execute('select legacy_id,official_id from official_seating_mappings'))}


@app.get('/api/search')
def search(term: str, palette: bool = False):
    with connect() as con:
        con.execute('begin')
        result = search_directory(con, term)
        return palette_search(con, result) if palette else result


@app.get('/api/directory/record')
def export_record(kind: str, key: str):
    with connect() as con:
        try:
            result = directory_exports.record(con, kind, key, include_unmapped=False)
        except ValueError as error:
            raise HTTPException(400, str(error))
        if result is None:
            raise HTTPException(404, 'Directory record not found')
        return result


@app.get('/api/user/{uid}')
def user(uid: str):
    with connect() as con:
        con.execute('begin')
        rows = con.execute('select * from legacy_users where id=?', (int(uid[3:]),)).fetchall() if uid.startswith('id:') and uid[3:].isdigit() else exact_users(con, uid)
        if not rows:
            raise HTTPException(404, 'User not found')
        if len(rows) != 1:
            raise HTTPException(409, 'Select a user from search results')
        person = dict(rows[0])
        desks=person_desks(con,person)
        return {'user': person, 'machines': linked_machines(con, person['id']), 'desks':[d['id'] for d in desks], 'desk_matches':desks}

@app.get('/api/vdi-data/record/{key:path}')
def vdi_record(key:str):
    from vdi_data import record
    with connect() as con:
        result=record(con,key,include_unmapped=False)
        if result is None:
            raise HTTPException(404,'Citrix inventory record not found.')
        return result



@app.get('/api/desks/{desk_id}/context')
def context(desk_id: str):
    with connect() as con:
        row = con.execute('select body from official_records where id=? union all select body from records where id=? limit 1', (desk_id, desk_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Desk not found')
        desk = json.loads(row[0])
        return desk_context(con, desk)


@app.get('/api/palette/person/{uid}')
def palette_person(uid: str):
    if not (uid.startswith('id:') and uid[3:].isdigit()) and ':' not in uid:
        raise HTTPException(400,'Select a directory result')
    with connect() as con:
        con.execute('begin')
        person = con.execute('select * from legacy_users where id=?', (int(uid[3:]),)).fetchone() if uid.startswith('id:') and uid[3:].isdigit() else con.execute('select * from legacy_users where canonical_key=?',(uid,)).fetchone()
        if not person:
            raise HTTPException(404, 'Person not found')
        return {'desks': person_desks(con, person)}


@app.get('/api/machine/{computer}')
def machine(computer: str):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', computer) or '..' in computer:
        raise HTTPException(400, 'Invalid computer name')
    with connect() as con:
        result = machine_context(con, computer)
        if result is None:
            raise HTTPException(404, 'Machine not found in directory')
        if result.get('ambiguous'):
            raise HTTPException(409, 'Ambiguous VDI hostname; select its fully qualified name.')
        return result


prewarm(ATLAS / 'official-data.json', ATLAS / 'studio-floor-2.svg')


@app.get('/')
def home():
    html = (ATLAS / 'official-index.html').read_text(encoding='utf-8')
    html = re.sub(r'<(?:script|link)\b[^>]*(?:src|href)="/assets/(?:machine-health|client|axis-chat)[^"]*"[^>]*>(?:</script>)?', '', html)
    # The mode is supplied by this server, never by a URL or browser preference.
    html = html.replace('<head>', '<head><meta name="atlas-mode" content="viewer"><link rel="stylesheet" href="/viewer.css">')
    html = html.replace('<span class="atlas-admin-badge">Admin</span>', '<span class="atlas-demo-badge">Demo</span>', 1)
    html = html.replace('aria-label="Atlas Admin home"', 'aria-label="Atlas Demo home"', 1)
    return HTMLResponse(html)


@app.get('/installer')
@app.get('/installer/')
def console():
    html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    html = html.replace('<head>', '<head><meta name="atlas-mode" content="viewer">')
    html = html.replace('<span class="atlas-admin-badge">Admin</span>', '<span class="atlas-demo-badge">Demo</span>')
    html = html.replace('Atlas Admin home', 'Atlas Demo home')
    return HTMLResponse(html)


@app.get('/assets/{filename}')
def shared_asset(filename:str, request:Request):
    # Only assets referenced by the shared console template. No API registration.
    template = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    allowed = set(re.findall(r'/assets/([\w.-]+)', template))
    if filename not in allowed:raise HTTPException(404,'Not available')
    return cached_file(request, ROOT/'frontend/assets'/filename)


@app.get('/{filename}')
def asset(filename: str, request: Request):
    allowed = {'catalogue.js','service-actions.js','site-info.js','command-palette.js', 'command-palette.css', 'command-registry.js', 'map-furniture.js','map-amenities.js','map-plan-details.js','official-app.js','camera-motion.js','map-cursor.js', 'official-data.json', 'official.css', 'style.css', 'operations.css', 'viewer.js', 'viewer.css'}
    if filename not in allowed and not re.fullmatch(r'(official-floor-(-1|[0-8])\.(jpg|pdf)|studio-floor-(-1|[0-8])\.svg)', filename):
        raise HTTPException(404, 'Not available in the shared viewer')
    return cached_file(request, ATLAS / filename)

# Bundled open-source Draw.io static editor (no server-side editor endpoints).
from fastapi.staticfiles import StaticFiles
app.mount('/drawio', StaticFiles(directory=ROOT/'frontend/drawio', html=True), name='drawio')
