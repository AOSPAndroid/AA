import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.pwa import register


class PwaTests(unittest.TestCase):
    def test_manifest_icons_worker_and_capabilities(self):
        app = FastAPI()
        register(app)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/app').json()['mode'], 'admin')
            response = client.get('/atlas.webmanifest')
            self.assertEqual(response.status_code, 200)
            self.assertIn('application/manifest+json', response.headers['content-type'])
            manifest = response.json()
            self.assertEqual(manifest['display'], 'standalone')
            self.assertEqual(manifest['start_url'], '/installer?command=inbox')
            for icon in manifest['icons']:
                payload = (Path(__file__).resolve().parents[1] / 'frontend' / icon['src'].lstrip('/')).read_bytes()
                self.assertEqual(payload[:8], b'\x89PNG\r\n\x1a\n')
                size = int(icon['sizes'].split('x')[0])
                self.assertEqual(int.from_bytes(payload[16:20], 'big'), size)
                self.assertEqual(int.from_bytes(payload[20:24], 'big'), size)
            worker = client.get('/atlas-sw.js')
            self.assertEqual(worker.status_code, 200)
            self.assertEqual(worker.headers['service-worker-allowed'], '/')
            self.assertEqual(worker.headers['cache-control'], 'no-cache')


if __name__ == '__main__':
    unittest.main()
