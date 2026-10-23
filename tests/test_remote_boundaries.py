"""Browser-origin restrictions tested without network or Windows operations."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest
from unittest.mock import patch

from backend import main
from fastapi.testclient import TestClient


class RemoteBoundaries(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app, base_url='http://127.0.0.1',
                                 client=('127.0.0.1', 12345))
        self.addCleanup(self.client.close)

    def test_originless_cross_site_image_requests_never_probe_remote_hosts(self):
        metadata = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors',
                    'Sec-Fetch-Dest': 'image'}
        with patch.object(main.os.path, 'isdir') as share, patch.object(main, 'run') as run, patch.object(main, 'ps') as ps:
            for path in ['/api/access/attacker.example', '/api/ping/attacker.example',
                         '/api/machine-health/attacker.example/cshare']:
                self.assertEqual(self.client.get(path, headers=metadata).status_code, 403)
            share.assert_not_called()
            run.assert_not_called()
            ps.assert_not_called()

    def test_cross_site_mutation_without_origin_never_controls_service(self):
        with patch.object(main, 'ps') as ps, patch.object(main, 'identity') as operator:
            response = self.client.post('/api/services/stop', headers={'Sec-Fetch-Site': 'cross-site'},
                                        json={'computer': 'FICT-PC', 'name': 'Example', 'expected_identity': 'a' * 64})
            self.assertEqual(response.status_code, 403)
            ps.assert_not_called()
            operator.assert_not_called()

    def test_same_origin_and_metadata_absent_local_clients_remain_usable(self):
        with patch.object(main, 'validate_pc', return_value='FICT-PC'), patch.object(main.os.path, 'isdir', return_value=True) as share:
            for headers in ({}, {'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'none'}):
                response = self.client.get('/api/access/FICT-PC', headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['available'])
            self.assertEqual(share.call_count, 3)

    def test_admin_documents_only_allow_same_origin_embedding(self):
        for path in ['/installer', '/manage-database']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-security-policy'], "frame-ancestors 'self'")
            self.assertEqual(response.headers['x-frame-options'], 'SAMEORIGIN')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')


if __name__ == '__main__':
    unittest.main()
