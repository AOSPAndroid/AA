"""Local service routes use a simulated transport; no Windows service is changed."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import main


class ServiceRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database = Path(self.tmp.name) / 'empty.db'
        sqlite3.connect(database).close()
        self.patches = [
            patch.object(main, 'MASTER_DB', database),
            patch.object(main, 'ps'),
            patch.object(main, 'identity', return_value='FIXTURE OPERATOR'),
            patch.object(main, 'run', side_effect=AssertionError('Real Windows transport is forbidden')),
        ]
        self.transport = [item.start() for item in self.patches][1]
        self.client = TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
        self.payload = {'computer': 'testpc', 'name': 'FixtureService', 'expected_identity': 'a' * 64}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def response(self, action):
        state = 'Stopped' if action == 'stop' else 'Running'
        outcome = {'start': 'started', 'stop': 'stopped', 'restart': 'restarted'}[action]
        return {'ok': True, 'computer': 'TESTPC', 'name': 'FixtureService', 'state': state, 'outcome': outcome,
                'message': 'Verified fixture state', 'item': {
                    'name': 'FixtureService', 'display_name': 'Fixture service', 'state': state,
                    'start_mode': 'Manual', 'pid': 0 if state == 'Stopped' else 4321, 'identity': 'a' * 64,
                    'can_start': state == 'Stopped', 'start_reason': '', 'can_stop': state == 'Running',
                    'stop_reason': '', 'can_restart': state == 'Running', 'restart_reason': '',
                }}

    def test_control_routes_dispatch_exact_action_and_verified_item(self):
        for action in ('start', 'stop', 'restart'):
            with self.subTest(action=action):
                self.transport.return_value = json.dumps(self.response(action))
                response = self.client.post('/api/services/' + action, json=self.payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['item']['state'], self.response(action)['state'])
                command = self.transport.call_args
                self.assertIn("-Computer 'TESTPC' -Action '" + action + "'", command.args[0])
                self.assertIn("-Name 'FixtureService'", command.args[0])
                self.assertIn("-ExpectedIdentity '" + 'a' * 64 + "'", command.args[0])
                self.assertEqual(command.kwargs['timeout'], 60)

    def test_invalid_requests_never_reach_transport(self):
        for action in ('start', 'stop', 'restart'):
            for values in ({'name': ''}, {'name': 'bad\nname'}, {'expected_identity': '*'}, {'computer': "PC';bad"}):
                with self.subTest(action=action, values=values):
                    response = self.client.post('/api/services/' + action, json={**self.payload, **values})
                    self.assertIn(response.status_code, (400, 422), response.text)
        self.transport.assert_not_called()

    def test_wrong_target_or_unverified_state_is_not_success(self):
        for action in ('start', 'stop', 'restart'):
            for values in ({'computer': 'OTHER'}, {'name': 'OtherService'}, {'state': 'Start Pending'}):
                with self.subTest(action=action, values=values):
                    self.transport.return_value = json.dumps({**self.response(action), **values})
                    response = self.client.post('/api/services/' + action, json=self.payload)
                    self.assertEqual(response.status_code, 502, response.text)

    def test_remote_host_and_cross_origin_cannot_control_services(self):
        clients = [
            (TestClient(main.app, base_url='http://127.0.0.1', client=('192.0.2.20', 12345)), {}),
            (TestClient(main.app, base_url='http://other.example', client=('127.0.0.1', 12345)), {}),
            (self.client, {'Origin': 'https://other.example'}),
        ]
        try:
            for client, headers in clients:
                for path in ('/api/services', '/api/services/start', '/api/services/stop', '/api/services/restart'):
                    with self.subTest(path=path, headers=headers):
                        self.assertEqual(client.post(path, json=self.payload, headers=headers).status_code, 403)
            self.transport.assert_not_called()
        finally:
            for client, _ in clients[:2]:
                client.close()


if __name__ == '__main__':
    unittest.main()
