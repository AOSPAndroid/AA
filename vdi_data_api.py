"""Staged, supplemental Citrix CSV/XLSX imports with VDI-only backups."""
import gzip
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from atlas_store import ClosingConnection
import vdi_data as data


def apply_import(database, value):
    """Back up the VDI data, then write a parsed Citrix export; refused when VDI data or account identities changed since it was parsed."""
    database = Path(database).resolve()
    at = datetime.now(timezone.utc).isoformat(); import_id = uuid.uuid4().hex
    backups = database.parent / 'backups'; backups.mkdir(parents=True, exist_ok=True)
    backup = backups / ('vdi-data-' + import_id + '.json.gz')
    temporary = backup.with_name(backup.name + '.tmp')
    try:
        with sqlite3.connect(database, timeout=20, factory=ClosingConnection) as con:
            con.execute('begin immediate')
            if data.fingerprint(con) != value['fingerprint']:
                raise HTTPException(409, 'Citrix data or directory account identities changed. Validate a fresh preview.')
            with gzip.open(temporary, 'wt', encoding='utf-8') as archive:
                json.dump(data.backup_payload(con, at), archive, ensure_ascii=False)
            os.replace(temporary, backup)
            summary = data.write_rows(con, value['rows'], value['source'], at, full_snapshot=value['full_snapshot'])
            con.execute('insert into vdi_imports values(?,?,?,?,?,?)',
                        (import_id, at, value['source'], json.dumps(value['report']), str(backup), int(value['full_snapshot'])))
            count = con.execute('select count(*) from vdi_devices').fetchone()[0]
    except Exception:
        temporary.unlink(missing_ok=True); backup.unlink(missing_ok=True)
        raise
    return {'count': count, 'backup': backup.name, 'imported_at': at, 'full_snapshot': value['full_snapshot'], **summary}


def register(app, wmi, check_token):
    staged = {}; stage_lock = threading.RLock()
    database = Path(wmi.MASTER_DB).resolve()

    def connect():
        return sqlite3.connect(database, timeout=20, factory=ClosingConnection)

    with connect() as con:
        data.initialize(con)

    def clean():
        now = time.time()
        with stage_lock:
            for key, value in list(staged.items()):
                if now - value['at'] > 3600:
                    staged.pop(key, None)

    @app.get('/api/vdi-data/import/status')
    def status():
        with connect() as con:
            con.execute('begin')
            count = con.execute('select count(*) from vdi_devices').fetchone()[0]
            associations = con.execute('select count(*) from vdi_links').fetchone()[0]
            row = con.execute('select at,source,report,full_snapshot from vdi_imports order by at desc,id desc limit 1').fetchone()
        return {'count': count, 'associations': associations,
                'last_import': {'at': row[0], 'source': row[1], 'report': json.loads(row[2]),
                                'full_snapshot': bool(row[3])} if row else None}

    def stage(content, source, full_snapshot):
        incoming, parsed = data.parse(content, source)
        with connect() as con:
            con.execute('begin')
            report = data.report(con, incoming, parsed, full_snapshot=full_snapshot)
            fingerprint = data.fingerprint(con)
        key = uuid.uuid4().hex
        clean()
        with stage_lock:
            staged.clear()
            staged[key] = {'at': time.time(), 'rows': incoming, 'source': source,
                           'report': report, 'fingerprint': fingerprint, 'full_snapshot': full_snapshot}
        return {'id': key, 'source': source, 'full_snapshot': full_snapshot, 'report': report, 'expires_minutes': 60}

    @app.post('/api/vdi-data/import/preview')
    async def preview(request: Request, full_snapshot: str = 'false'):
        check_token(request)
        if full_snapshot.casefold() not in ('true', 'false'):
            raise HTTPException(400, 'full_snapshot must be true or false.')
        mode = full_snapshot.casefold() == 'true'
        source = Path(unquote(request.headers.get('x-file-name', 'citrix.csv')).replace('\\', '/')).name[:200]
        if Path(source).suffix.casefold() not in ('.csv', '.xlsx'):
            raise HTTPException(400, 'Choose the raw Citrix CSV or XLSX export.')
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > data.MAX_FILE_BYTES:
                raise HTTPException(400, 'Citrix export exceeds 50 MB.')
        try:
            return await run_in_threadpool(stage, bytes(content), source, mode)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.delete('/api/vdi-data/import/preview/{key}')
    def discard(key: str, request: Request):
        check_token(request)
        with stage_lock:
            staged.pop(key, None)
        return {'ok': True}

    @app.post('/api/vdi-data/import/apply/{key}')
    def apply(key: str, body: dict, request: Request):
        check_token(request); clean()
        if set(body) != {'full_snapshot'} or type(body.get('full_snapshot')) is not bool:
            raise HTTPException(400, 'Supply the full_snapshot boolean from the reviewed preview.')
        with stage_lock:
            value = staged.get(key)
        if value is None:
            raise HTTPException(409, 'Citrix preview expired or was replaced. Validate the export again.')
        if body['full_snapshot'] != value['full_snapshot']:
            raise HTTPException(409, 'The import mode changed. Validate a fresh Citrix preview.')
        result = apply_import(database, value)
        with stage_lock:
            staged.pop(key, None)
        return {'ok': True, **result}

    @app.get('/api/vdi-data/record/{key:path}')
    def record(key: str):
        with connect() as con:
            result = data.record(con, key)
        if result is None:
            raise HTTPException(404, 'Citrix inventory record not found.')
        return result
