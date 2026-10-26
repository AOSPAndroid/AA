"""Atlas and Axis refuse the same PC: one lock and one unknown-outcome guard."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import shared_operations as shared
from action_activity import register
from axis import it_tools
from job_service import JobService


class SharedOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / 'state'
        self.patch = patch.object(shared, 'AXIS_STATE', self.state)
        self.patch.start()
        shared._cache.clear()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def axis_job(self, key, state, computers=('PC1',), **extra):
        job = dict(id=key * 32, kind='deploy', computers=list(computers), package='Example', action='Install',
                   state=state, created=it_tools.now(), created_epoch=time.time(), worker_pid=os.getpid(),
                   results=[], events=[{'at': 'now', 'computer': computers[0], 'message': 'Copying package'}])
        job.update(extra)
        it_tools.write_json(self.state / 'jobs' / (job['id'] + '.json'), job)
        return job

    def test_atlas_lock_and_axis_worker_lock_exclude_each_other(self):
        guard = shared.TargetLock('PC1.CORP.EXAMPLE')
        self.assertTrue(guard.acquire(blocking=False))
        with self.assertRaisesRegex(RuntimeError, 'Another operation'):
            with it_tools.target_lock(self.state, 'pc1'):
                self.fail('Axis acquired a PC that Atlas holds')
        self.assertFalse(guard.acquire(blocking=False))
        # Atlas workers release on a pool thread, not the request thread.
        releaser = threading.Thread(target=guard.release)
        releaser.start(); releaser.join(2)
        with it_tools.target_lock(self.state, 'PC1'):
            self.assertFalse(shared.TargetLock('PC1').acquire(blocking=False))
        self.assertTrue(guard.acquire(blocking=False))
        guard.release()

    def test_name_axis_cannot_address_still_gets_atlas_lock(self):
        guard = shared.TargetLock('_LEGACY')
        self.assertTrue(guard.acquire(blocking=False))
        self.assertFalse(guard.acquire(blocking=False))
        guard.release()
        self.assertFalse((self.state / 'locks').exists())

    def test_axis_active_or_unknown_job_blocks_atlas_target_check(self):
        service = JobService(lambda: Path(self.temp.name) / 'operations.db', guard=shared.axis_ready)
        service.target_ready('PC1')
        for state, extra in (('running', {}), ('unknown', {})):
            with self.subTest(state=state):
                job = self.axis_job('a', state, computers=('PC1.CORP.EXAMPLE',), **extra)
                with self.assertRaises(HTTPException) as caught:
                    service.target_ready('PC1')
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn('/jobs ' + job['id'], caught.exception.detail)
                service.target_ready('PC2')
        self.axis_job('a', 'unknown', acknowledged=it_tools.now())
        service.target_ready('PC1')
        self.axis_job('a', 'complete')
        service.target_ready('PC1')

    def test_jobs_an_earlier_axis_terminal_left_still_block_atlas(self):
        terminal = Path(self.temp.name) / 'terminal-state'
        job = self.axis_job('t', 'unknown')
        (self.state / 'jobs' / (job['id'] + '.json')).rename(self.state.parent / 'moved.json')
        it_tools.write_json(terminal / 'jobs' / (job['id'] + '.json'), job)  # Only the earlier terminal folder has it.
        shared.axis_ready('PC1')  # Not read until that folder is Atlas's terminal folder.
        with patch.object(shared, 'TERMINAL_STATE', terminal):
            with self.assertRaises(HTTPException) as caught:
                shared.axis_ready('pc1.corp.example')
            self.assertIn(job['id'], caught.exception.detail)
            shared.axis_ready('PC2')

    def test_axis_jobs_appear_in_atlas_activity_without_writes(self):
        backend = SimpleNamespace(lock=threading.RLock(), jobs={}, queue_jobs={})
        app = FastAPI()
        register(app, backend)
        running = self.axis_job('b', 'running')
        stale = self.axis_job('c', 'running', computers=('PC2',), created_epoch=time.time() - 60, worker_pid=None)
        before = (self.state / 'jobs' / (stale['id'] + '.json')).read_bytes()
        with patch('psexec_runner.runner.jobs', {}), TestClient(app) as client:
            rows = {row['id']: row for row in client.get('/api/actions').json()['actions']}
        row = rows['axis-' + running['id']]
        self.assertEqual((row['title'], row['target'], row['state']), ('Axis · Install · Example', 'PC1', 'running'))
        self.assertIn('Copying package', row['log'])
        self.assertEqual(rows['axis-' + stale['id']]['state'], 'unknown')
        self.assertEqual((self.state / 'jobs' / (stale['id'] + '.json')).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
