import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.action_activity import register


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.backend=SimpleNamespace(lock=threading.RLock(),jobs={},queue_jobs={})
        self.app=FastAPI()
        register(self.app,self.backend)
        self.client=TestClient(self.app)
        self.psexec=patch('backend.remote.psexec_runner.runner.jobs',{});self.psexec.start()

    def tearDown(self):
        self.client.close();self.psexec.stop()

    def test_running_request_visible_without_repeating_scan(self):
        entered,release=threading.Event(),threading.Event()
        calls=[]
        @self.app.get('/api/disk/{pc}')
        def disk(pc):
            calls.append(pc);entered.set();release.wait(3);return {'free':42}
        with ThreadPoolExecutor() as pool:
            future=pool.submit(self.client.get,'/api/disk/TESTPC')
            try:
                self.assertTrue(entered.wait(2))
                feed=self.client.get('/api/actions').json()
                self.assertEqual(feed['count'],1)
                self.assertEqual(feed['actions'][0]['target'],'TESTPC')
                self.assertEqual(calls,['TESTPC'])
            finally: release.set()
            self.assertEqual(future.result().status_code,200)
        row=self.client.get('/api/actions').json()['actions'][0]
        self.assertEqual(row['state'],'complete')
        self.client.post('/api/actions/'+row['id']+'/dismiss')
        self.assertEqual(self.client.get('/api/actions').json()['actions'],[])

    def test_grouped_jobs_psexec_and_terminal_expiration(self):
        now=time.time()
        self.backend.jobs.update(child={'state':'running','target':'ONE','updated':now},
            solo={'state':'running','target':'TWO','action_title':'Install App','updated':now},
            old={'state':'complete','updated':now-1000},
            recent={'state':'launched','updated':now})
        self.backend.queue_jobs['q']={'state':'paused','updated':now,'items':[{'job':'child','target':'ONE','state':'running'}]}
        from backend.remote.psexec_runner import runner
        runner.jobs['px']={'title':'Command','target':'THREE','state':'running','output':'hello','finished':None}
        result=self.client.get('/api/actions').json()
        self.assertEqual(result['count'],3)
        ids={row['id'] for row in result['actions']}
        self.assertNotIn('job-child',ids);self.assertNotIn('job-old',ids)
        queue=next(row for row in result['actions'] if row['id']=='queue-q')
        self.assertEqual(queue['controls'][0]['label'],'Resume')
        self.assertEqual(self.client.post('/api/actions/job-solo/dismiss').status_code,409)
        self.assertIn('job-recent',ids)

if __name__=='__main__':unittest.main()
