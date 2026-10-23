from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest, uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import main as app


class DeploymentMonitorOrder(unittest.TestCase):
    """The Deployments drawer shows the latest deployment first, without scrolling."""

    def setUp(self):
        self.client = TestClient(app.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
        self.jobs = patch.dict(app.jobs, clear=True); self.jobs.start(); self.addCleanup(self.jobs.stop)
        self.queues = patch.dict(app.queue_jobs, clear=True); self.queues.start(); self.addCleanup(self.queues.stop)

    def job(self, target, started, state='running'):
        key = uuid.uuid4().hex
        app.jobs[key] = {'state': state, 'target': target, 'events': [{'message': target}]}
        if started is not None: app.jobs[key]['started_at'] = started
        return key

    def test_live_view_lists_newest_first_across_jobs_and_queues(self):
        self.job('LEGACY', None)  # saved before start times were recorded
        self.job('OLDER', 100)
        q = uuid.uuid4().hex
        app.queue_jobs[q] = {'state': 'running', 'started_at': 150, 'items': []}
        self.job('NEWEST', 200)
        rows = self.client.get('/api/deployments/active').json()['deployments']
        self.assertEqual([r.get('target') or r['kind'] for r in rows], ['NEWEST', 'queue', 'OLDER', 'LEGACY'])

    def test_recent_view_keeps_the_twenty_newest_with_latest_on_top(self):
        for n in range(25): self.job(f'PC{n:02}', 1000 + n, state='complete')
        targets = [r['target'] for r in self.client.get('/api/deployments/recent').json()['deployments']]
        self.assertEqual(targets, [f'PC{n:02}' for n in range(24, 4, -1)])


if __name__ == '__main__':
    unittest.main()
