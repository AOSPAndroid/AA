"""Installable local Admin shell. No mail, API responses or UI assets are cached."""
from pathlib import Path
from fastapi.responses import FileResponse

WEB = Path(__file__).resolve().parents[1] / 'frontend'


def register(app):
    @app.get('/api/app')
    def capabilities():
        return {'mode': 'admin', 'installable': True}

    @app.get('/atlas.webmanifest')
    def manifest():
        return FileResponse(WEB / 'atlas.webmanifest', media_type='application/manifest+json',
                            headers={'Cache-Control': 'no-cache'})

    @app.get('/atlas-sw.js')
    def service_worker():
        return FileResponse(WEB / 'atlas-sw.js', media_type='application/javascript',
                            headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})
