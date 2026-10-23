from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import gzip, json, subprocess, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from backend import viewer

ROOT = Path(__file__).resolve().parents[1]


class MapAssetCaching(unittest.TestCase):
    """The map's large files must revalidate to 304 and travel compressed."""

    def setUp(self):
        self.client = TestClient(viewer.app, base_url='http://192.0.2.10:8771', client=('192.0.2.11', 12345))

    def test_floor_data_revalidates_and_is_gzipped(self):
        first = self.client.get('/official-data.json', headers={'accept-encoding': 'gzip'})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers['content-encoding'], 'gzip')
        self.assertEqual(first.json(), json.loads((ROOT / 'atlas/official-data.json').read_bytes()))
        self.assertLess(int(first.headers['content-length']), (ROOT / 'atlas/official-data.json').stat().st_size // 3)
        again = self.client.get('/official-data.json', headers={'if-none-match': first.headers['etag']})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b'')

    def test_images_and_identity_requests_are_sent_unchanged(self):
        jpg = self.client.get('/official-floor-2.jpg', headers={'accept-encoding': 'gzip'})
        self.assertNotIn('content-encoding', jpg.headers)
        self.assertEqual(jpg.content, (ROOT / 'atlas/official-floor-2.jpg').read_bytes())
        plain = self.client.get('/official-app.js', headers={'accept-encoding': 'identity'})
        self.assertNotIn('content-encoding', plain.headers)
        self.assertEqual(plain.content, (ROOT / 'atlas/official-app.js').read_bytes())

    def test_shared_console_assets_revalidate(self):
        first = self.client.get('/assets/shared-ui.js')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.get('/assets/shared-ui.js', headers={'if-none-match': first.headers['etag']}).status_code, 304)

    def test_demo_serves_the_terminal_files(self):
        for name in ('xterm-6.0.0.js', 'xterm-6.0.0.css', 'xterm-addon-fit-0.11.0.js', 'xterm-addon-search-0.16.0.js', 'terminal-view.js'):
            self.assertEqual(self.client.get('/assets/' + name).status_code, 200, name)

    def test_demo_serves_the_knowledge_base_files_but_not_articles(self):
        for name in ('knowledge-articles.js', 'marked-18.0.14.js', 'dompurify-3.4.16.js', 'mermaid-12.0.0.js'):
            self.assertEqual(self.client.get('/assets/' + name).status_code, 200, name)
        for url in ('/api/knowledge/articles', '/api/search-everything?q=vpn', '/api/search-everything/similar/1'):
            self.assertNotEqual(self.client.get(url).status_code, 200, url)

    def test_stale_etag_gets_the_current_file(self):
        response = self.client.get('/official-app.js', headers={'if-none-match': '"stale"'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content)


class MapStartupWork(unittest.TestCase):
    def test_corrections_skip_floors_with_nothing_to_exclude(self):
        # The exclusion filters previously serialised every plan segment on every floor.
        script = r'''
import fs from "fs";
import { pathToFileURL } from "node:url";
const data = JSON.parse(fs.readFileSync(process.argv[1] + "/atlas/official-data.json"));
const { applyFurnitureCorrections } = await import(pathToFileURL(process.argv[1] + "/atlas/map-furniture.js"));
const { applyMapAmenities } = await import(pathToFileURL(process.argv[1] + "/atlas/map-amenities.js"));
const before = new Map(data.floors.map(f => [f.level, f.geometry.planLinework]));
const start = performance.now();
applyMapAmenities(data); applyFurnitureCorrections(data);
const unchanged = data.floors.filter(f => f.geometry.planLinework === before.get(f.level)).map(f => f.level);
console.log(JSON.stringify({ unchanged, ms: performance.now() - start }));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script, str(ROOT)], cwd=ROOT,
                                capture_output=True, text=True, check=True, timeout=60)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        # Floors 2 and -1 carry plan exclusions; every other floor keeps its original array.
        self.assertEqual(sorted(report['unchanged']), [0, 1, 3, 4, 5, 6, 7, 8])

    def test_generators_emit_the_shipped_runtime(self):
        details = (ROOT / 'atlas/map-plan-details.js').read_text(encoding='utf-8').split('\n', 2)[2]
        self.assertEqual(details, (ROOT / 'tools/plan-details-runtime.js').read_text(encoding='utf-8'))
        furniture = (ROOT / 'atlas/map-furniture.js').read_text(encoding='utf-8')
        source = (ROOT / 'tools/build_curved_tables.py').read_text(encoding='utf-8')
        runtime = furniture[furniture.index('\n\nconst without'):]
        self.assertIn(json.dumps(runtime)[1:-1].replace('\\"', '"'), source)


if __name__ == '__main__':
    unittest.main()
