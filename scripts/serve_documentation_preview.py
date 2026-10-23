"""Render the real Atlas map with invented data for documentation screenshots.

No database, exported workbook, real plan, configuration or backend is loaded.
Only the explicitly listed UI assets and generated fixture responses are served.
Run: py -3.12 scripts/serve_documentation_preview.py
"""
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAP_ASSETS = (
    'map-furniture.js','map-amenities.js','map-plan-details.js','official-app.js', 'camera-motion.js', 'map-cursor.js', 'operations.js',
    'catalogue.js', 'command-palette.js', 'command-registry.js',
    'style.css', 'operations.css', 'official.css', 'command-palette.css',
)
SHARED_ASSETS = (
    'ui-tokens.css', 'shared-ui.js', 'client.js', 'machine-health.js',
    'machine-health.css', 'atlas-shell.css', 'catalogue.css', 'barclays-eagle.svg',
)
ASSETS = {'/' + name: ROOT / 'atlas' / name for name in MAP_ASSETS}
ASSETS.update({'/assets/' + name: ROOT / 'frontend/assets' / name for name in SHARED_ASSETS})


def rect(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def edges(points):
    return [[p, points[(i + 1) % len(points)]] for i, p in enumerate(points)]


def floor(level):
    outline = [[170, 130], [1480, 130], [1630, 280], [1630, 1070],
               [170, 1070]]
    rooms = [
        {'name': 'Meeting room', 'kind': 'office', 'points': rect(200, 160, 260, 210)},
        {'name': 'Meeting room', 'kind': 'office', 'points': rect(490, 160, 260, 210)},
        {'name': 'Project room', 'kind': 'office', 'points': rect(780, 160, 300, 210)},
        {'name': 'Core', 'kind': 'core', 'points': rect(1160, 160, 300, 210)},
        {'name': 'Meeting room', 'kind': 'office', 'points': rect(1260, 790, 340, 250)},
    ]
    records = []
    for row in range(4 if level == 2 else 3):
        for col in range(12):
            x = 255 + col * 73 + (col // 4) * 78
            y = 470 + row * 155
            for side in range(2):
                number = len(records) + 1
                records.append({
                    'id': f'custom-sample-{level}-{number:03d}',
                    'name': f'Sample desk {number:03d}', 'team': 'Unassigned',
                    'floor': level, 'x': x / 1800, 'y': (y + side * 36) / 1800,
                    'angle': 180 if side == 0 else 0, 'kind': 'desk',
                    'occupancy': 'unconfirmed', 'verified': False, 'revision': 1,
                    'hostname': '', 'asset': '', 'outlet': '', 'status': '',
                    'notes': 'Fictional location for documentation only.',
                })
    tables = [rect(270, 215, 120, 80), rect(560, 215, 120, 80),
              rect(850, 210, 150, 90), rect(1350, 865, 150, 90)]
    tables.extend(rect(r['x'] * 1800 - 24, r['y'] * 1800 - 14, 48, 28)
                  for r in records)
    geometry = {
        'outline': outline, 'buildingPerimeter': outline, 'shear': 0,
        'rooms': rooms, 'zones': [], 'walls': [edge for r in rooms for edge in edges(r['points'])],
        'tables': tables, 'stairs': [], 'furniture': [], 'doorSwings': [],
        'wayfinding': [{'kind': 'lift', 'points': rect(1220, 210, 65, 95)}],
        'planLinework': [edge for t in tables for edge in edges(t)],
    }
    return {'level': level, 'label': f'{level:02d}',
            'title': 'Sample workspace' if level == 2 else 'Sample project floor',
            'width': 1800, 'height': 1200, 'geometry': geometry}, records


FLOORS, RECORDS = [], []
for level in (2, 3):
    f, r = floor(level)
    FLOORS.append(f)
    RECORDS.extend(r)


def plan_svg(level):
    f = next(f for f in FLOORS if f['level'] == level)
    elements = ['<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1200" viewBox="0 0 1800 1200">']
    def polygon(points, color, stroke='#9bb5c4'):
        elements.append(f'<polygon points="{" ".join(f"{x},{y}" for x, y in points)}" fill="{color}" stroke="{stroke}" stroke-width="2"/>')
    polygon(f['geometry']['outline'], '#f3f7fa', '#087cad')
    for room in f['geometry']['rooms']:
        polygon(room['points'], '#dfebf1' if room['kind'] == 'core' else '#e9f0f5')
    for table in f['geometry']['tables']:
        polygon(table, '#bbd8e5')
    for record in (r for r in RECORDS if r['floor'] == level):
        x, y = record['x'] * 1800, record['y'] * 1800
        polygon(rect(x - 24, y - 14, 48, 28), '#d5e8f1')
        polygon(rect(x - 19, y - 11 if record['angle'] else y + 7, 38, 4), '#597c90')
    elements.append('</svg>')
    return ''.join(elements).encode()


def preview_html():
    html = (ROOT / 'atlas/official-index.html').read_text(encoding='utf-8')
    html = html.replace('PARIS OFFICE MAP', 'SYNTHETIC MAP PREVIEW')
    html = html.replace('All Paris floors', 'All sample floors')
    html = html.replace('Paris · 10 official plans · B1–08', '2 fictional floors · No real office data')
    html = html.replace('PARIS · OFFICIAL DESK POSITIONS', 'ILLUSTRATIVE FLOOR · NO REAL DATA')
    html = html.replace('Paris map · Europe-wide directory', 'Documentation preview · Fictional floor plans')
    html = html.replace('Official desk codes from the PDFs. Hover or select a desk for its\n            official number. Seating names carry across from the previous\n            register.', 'Invented floor geometry and sample desk identifiers. No people, machines or real office plans are loaded.')
    # Restrict all browser connections to this isolated server, including in screenshots.
    html = html.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; connect-src \'self\'">')
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/':
            body, kind = preview_html(), 'text/html'
        elif path == '/site-info.js':
            # Never put real site contacts or network identifiers in the public screenshot fixture.
            body, kind = b'export function openSiteInfo(){const {body}=AtlasUI.dialog("Site information");body.textContent="Fictional preview: site references are omitted.";}', 'text/javascript'
        elif path == '/official-data.json':
            body, kind = json.dumps({'floors': FLOORS, 'records': RECORDS}).encode(), 'application/json'
        elif path == '/api/official/state':
            body, kind = json.dumps({'records': RECORDS, 'legacy': [], 'mappings': {}}).encode(), 'application/json'
        elif path in [f'/{prefix}-floor-{level}.{ext}' for level in (2, 3)
                      for prefix, ext in [('studio', 'svg'), ('official', 'jpg')]]:
            body, kind = plan_svg(int(path.rsplit('-', 1)[1].split('.')[0])), 'image/svg+xml'
        elif path in ASSETS:
            body = ASSETS[path].read_bytes()
            kind = 'text/javascript' if path.endswith('.js') else mimetypes.guess_type(path)[0]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', f'{kind}; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    print('Synthetic documentation preview: http://127.0.0.1:8894', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8894), Handler).serve_forever()
