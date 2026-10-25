"""Retry and re-queue past deployments with the same options. No remote command runs."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json, sqlite3, sys, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from backend import main as app
from fastapi.testclient import TestClient


class DeploymentRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for name, value in (('HISTORY_DB', base / 'history.db'), ('REPO', base / 'repo')):
            patcher = patch.object(app, name, value); patcher.start(); self.addCleanup(patcher.stop)
        (base / 'repo' / 'Example').mkdir(parents=True); (base / 'repo' / 'Example' / 'setup_i.ps1').write_text('exit 0')
        self.started = []
        for target, value in (('identity', lambda: 'TEST OPERATOR'),
                              ('start_job', lambda fn, j, p: self.started.append((j, p.model_dump())))):
            patcher = patch.object(app, target, value); patcher.start(); self.addCleanup(patcher.stop)
        self.client = TestClient(app.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)); self.addCleanup(self.client.close)

    def deploy(self, **extra):
        body = {'computer': 'TESTPC', 'folder': 'Example', 'script': 'setup_i.ps1', 'fresh': True, 'threads': 16, **extra}
        response = self.client.post('/api/deploy', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['job']

    def test_a_failed_deployment_runs_again_with_the_same_options(self):
        first = self.deploy(mode='copy')
        app.jobs[first]['state'] = 'failed'; app.history_update(first, state='failed')
        payload = self.client.get(f'/api/deploy/{first}/payload').json()
        self.assertEqual((payload['fresh'], payload['threads'], payload['action'], payload['mode']), (True, 16, 'Install', 'copy'))
        retried = self.client.post(f'/api/deploy/{first}/retry').json()
        self.assertNotEqual(retried['job'], first)
        self.assertEqual((retried['target'], retried['package'], retried['action']), ('TESTPC', 'Example', 'Install'))
        self.assertEqual(self.started[-1][1], self.started[0][1], 'The retry asks for exactly what the first run did')
        history = self.client.get('/api/history').json()
        self.assertEqual({row['id'] for row in history}, {first, retried['job']}, 'The retry is a new history row')
        self.assertNotIn('payload', history[0], 'History rows stay as they were')

    def test_older_rows_without_a_saved_request_are_rebuilt(self):
        old = uuid.uuid4().hex
        with app.hist_db() as c:
            c.execute("insert into deployments(id,started,target,package,action,script,mode,state) values(?,datetime('now'),'TESTPC','Example','Install','setup_i.ps1','full','failed')", (old,))
        payload = self.client.get(f'/api/deploy/{old}/payload').json()
        self.assertEqual((payload['computer'], payload['folder'], payload['fresh'], payload['threads']), ('TESTPC', 'Example', False, 8))
        self.assertEqual(self.client.post(f'/api/deploy/{old}/retry').status_code, 200)
        self.assertEqual(self.client.post('/api/deploy/missing/retry').status_code, 404)

    def test_an_axis_deployment_appears_in_history_and_retries_through_atlas(self):
        from axis import it_tools
        job = {'id': 'd' * 32, 'kind': 'deploy', 'computers': ['TESTPC'], 'repository': str(app.REPO), 'package': 'Example',
               'script': 'setup_i.ps1', 'script_sha256': '0' * 64, 'action': 'Install', 'mode': 'full', 'timeout': 60,
               'state': 'queued', 'created': it_tools.now(), 'created_epoch': 0, 'results': [], 'events': [],
               'worker_pid': None, 'atlas_db': str(app.HISTORY_DB), 'atlas_history': True}
        with app.hist_db():
            pass  # Atlas's database exists; Axis history never creates one.
        path = Path(self.tmp.name) / 'axis' / 'jobs' / (job['id'] + '.json')
        it_tools.write_json(path, job)
        with patch.object(it_tools.ITTools, 'deploy_one', return_value={'computer': 'TESTPC', 'state': 'failed', 'message': 'Access denied'}):
            it_tools.run_worker(path)
        row = next(r for r in self.client.get('/api/history').json() if r['id'] == 'axis-' + 'd' * 32 + '-0')
        self.assertEqual((row['target'], row['package'], row['state']), ('TESTPC', 'Example', 'failed'))
        self.assertTrue(row['operator'].endswith('(Axis)'))
        retried = self.client.post('/api/deploy/' + row['id'] + '/retry')
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual((self.started[-1][1]['computer'], Path(self.started[-1][1]['folder']).name), ('TESTPC', 'Example'))

    def test_monitor_cards_offer_retry_for_single_deployments_only(self):
        single = self.deploy()
        self.assertTrue(app.deployment_details(single, app.jobs[single])['retry'])
        self.assertFalse(app.deployment_details('bulk', {'targets': ['PC1', 'PC2'], 'package': 'Example'})['retry'])


if __name__ == '__main__':
    unittest.main()
