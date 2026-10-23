"""Independent, staged package-data imports; directory and package files stay intact."""
import gzip
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from fastapi import HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from atlas_store import ClosingConnection
import package_data as data


def register(app, wmi, check_token):
    staged = {}
    with sqlite3.connect(wmi.MASTER_DB, factory=ClosingConnection) as con:
        data.initialize(con)

    def connect():
        return sqlite3.connect(wmi.MASTER_DB, timeout=20, factory=ClosingConnection)

    def clean():
        for key, value in list(staged.items()):
            if time.time() - value['at'] > 3600:
                del staged[key]

    @app.get('/api/package-data')
    def packages(term: str = Query('', max_length=200), state: str = Query('', max_length=200),
                 coverage: str = Query('', pattern='^(|matched|source-only|metadata-only|ambiguous)$'),
                 offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
        with connect() as con:
            return data.browse(con, wmi.REPO, term=term, state=state, coverage=coverage, offset=offset, limit=limit)

    @app.get('/api/package-data/import/status')
    def status():
        with connect() as con:
            count = con.execute('select count(*) from package_data').fetchone()[0]
            row = con.execute('select at,source,report from package_data_imports order by at desc limit 1').fetchone()
        return {'count': count, 'last_import': {'at': row[0], 'source': row[1], 'report': json.loads(row[2])} if row else None}

    def stage(content, source):
        clean()
        incoming, parsed = data.parse_csv(content)
        with connect() as con:
            existing = data.load(con)
        preview = data.report(incoming, existing, wmi.REPO, parsed)
        key = uuid.uuid4().hex
        staged.clear()
        staged[key] = {'at': time.time(), 'rows': incoming, 'source': source,
                       'fingerprint': data.fingerprint(existing), 'report': preview}
        return {'id': key, 'source': source, 'report': preview, 'expires_minutes': 60}

    @app.post('/api/package-data/import/preview')
    async def preview(request: Request):
        check_token(request)
        filename = Path(unquote(request.headers.get('x-file-name', 'packages.csv')).replace('\\', '/')).name[:200]
        if not filename.lower().endswith('.csv'):
            raise HTTPException(400, 'Use the ServiceNow package CSV export.')
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(400, 'Package CSV exceeds 10 MB.')
        try:
            return await run_in_threadpool(stage, bytes(content), filename)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.delete('/api/package-data/import/preview/{key}')
    def discard(key: str, request: Request):
        check_token(request)
        staged.pop(key, None)
        return {'ok': True}

    @app.post('/api/package-data/import/apply/{key}')
    def apply(key: str, request: Request):
        check_token(request); clean()
        value = staged.get(key)
        if not value:
            raise HTTPException(409, 'Package preview expired or was replaced. Validate the CSV again.')
        at = datetime.now(timezone.utc).isoformat()
        import_id = uuid.uuid4().hex
        backups = Path(wmi.MASTER_DB).resolve().parent / 'backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / ('package-data-' + import_id + '.json.gz')
        try:
            with connect() as con:
                con.execute('begin immediate')
                existing = data.load(con)
                if data.fingerprint(existing) != value['fingerprint']:
                    raise HTTPException(409, 'Package data changed. Validate a fresh preview.')
                # A package-only backup avoids copying a global directory database.
                with gzip.open(backup, 'wt', encoding='utf-8') as archive:
                    json.dump({'schema': 1, 'at': at, 'packages': list(existing.values())}, archive, ensure_ascii=False)
                columns = ['name_key', *data.FIELDS, *data.SOURCE_FIELDS, 'source', 'imported_at']
                update = ','.join(f'{c}=excluded.{c}' for c in columns if c != 'name_key')
                sql = f"insert into package_data({','.join(columns)}) values({','.join('?' for _ in columns)}) on conflict(name_key) do update set {update}"
                for row in value['rows'].values():
                    item = {**row, 'source': value['source'], 'imported_at': at}
                    con.execute(sql, tuple(item[c] for c in columns))
                con.execute('insert into package_data_imports values(?,?,?,?,?)',
                            (import_id, at, value['source'], json.dumps(value['report']), str(backup)))
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        del staged[key]
        return {'ok': True, 'count': value['report']['after'], 'backup': backup.name, 'imported_at': at}
