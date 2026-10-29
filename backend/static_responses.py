"""File responses that honour browser revalidation for allow-listed routes.

Starlette's StaticFiles answers If-None-Match with 304, but a route that returns
FileResponse always resends the full body. The map's 7.6 MB floor data and plan
images are served through such routes, so every load re-downloaded them.

Text files are gzipped once per file version and kept in memory; compressing
the floor data on every request cost more than it saved on a local connection.
"""
import gzip
import os
import threading
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response

COMPRESSIBLE = {'.js', '.css', '.json', '.svg', '.html'}
_gzipped = {}
_lock = threading.Lock()


def _gzip_body(path, stat):
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        body = _gzipped.get(key)
    if body is None:
        body = gzip.compress(Path(path).read_bytes(), 6)
        with _lock:
            # Drop older versions of the same file; the set stays bounded by the allow-lists.
            for old in [k for k in _gzipped if k[0] == key[0]]:
                del _gzipped[old]
            _gzipped[key] = body
    return body


def cached_file(request: Request, path) -> Response:
    stat = os.stat(path)
    response = FileResponse(path, stat_result=stat)
    etag, modified = response.headers['etag'], response.headers['last-modified']
    sent = request.headers.get('if-none-match', '')
    if etag in (tag.strip().removeprefix('W/') for tag in sent.split(',')):
        return Response(status_code=304, headers={'etag': etag, 'last-modified': modified})
    if (os.path.splitext(str(path))[1].lower() in COMPRESSIBLE and stat.st_size > 1024
            and 'gzip' in request.headers.get('accept-encoding', '')):
        # Content-Encoding is set, so GZipMiddleware leaves this body alone.
        return Response(_gzip_body(path, stat), media_type=response.media_type, headers={
            'etag': etag, 'last-modified': modified, 'content-encoding': 'gzip', 'vary': 'Accept-Encoding'})
    return response


def prewarm(*paths):
    """Compress large map files in the background so the first visitor does not wait."""
    def work():
        for path in paths:
            try:
                _gzip_body(path, os.stat(path))
            except OSError:
                pass
    threading.Thread(target=work, name='atlas-gzip-prewarm', daemon=True).start()
