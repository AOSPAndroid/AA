"""Policy regressions use a disposable journal and simulated Windows transport only."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from backend import main
from backend.services.job_service import JobService
from backend.services.target_identity import same_target
from reboot_monitor import RebootMonitor


class OperationPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=JobService(lambda:Path(self.tmp.name)/'journal.db')
        self.addCleanup(self.store.pool.shutdown,wait=True)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(main,job_service=self.store,jobs=self.store.jobs,queue_jobs=self.store.queues,lock=self.store.lock))
        self.stack.enter_context(patch.object(main,'identity',return_value='TEST OPERATOR'))
        self.transport=self.stack.enter_context(patch.object(main,'ps',side_effect=AssertionError('Unexpected Windows call')))
        self.client=TestClient(main.app,base_url='http://127.0.0.1',client=('127.0.0.1',1234))
        self.addCleanup(self.client.close)
        self.request={'computer':'EXAMPLE-NOT-IN-DIRECTORY','name':'FixtureService','expected_identity':'a'*64}

    def test_mutations_cannot_bypass_unresolved_guard(self):
        self.store.unresolved.add(self.request['computer'])
        for path,body in [('/api/services/stop',self.request),('/api/kill',dict(computer=self.request['computer'],value='fixture.exe')),
                          ('/api/remote-registry/enable',dict(computer=self.request['computer'])),('/api/reboot',dict(computer=self.request['computer']))]:
            self.assertEqual(self.client.post(path,json=body).status_code,409,path)
        self.transport.assert_not_called()

    def test_reboot_respects_deployment_lock(self):
        guard=main.target_lock(self.request['computer']);self.assertTrue(guard.acquire(False))
        try:
            with patch.object(main.reboot_monitor,'start') as start:
                self.assertEqual(self.client.post('/api/reboot',json=self.request).status_code,409)
                start.assert_not_called()
        finally:guard.release()

    def test_alias_guards_survive_restart_and_acknowledge(self):
        pc='EXAMPLE-NOT-IN-DIRECTORY'
        self.store.jobs['lost']={'state':'unknown','target':pc,'events':[]};self.store.save('lost')
        recovered=JobService(self.store.path);self.addCleanup(recovered.pool.shutdown,wait=True);recovered.recover()
        for alias in (pc.lower(),pc+'.EXAMPLE.TEST',pc+'.'):
            with self.assertRaises(Exception):recovered.target_ready(alias)
        recovered.jobs['lost']['recovery_acknowledged']=True;recovered.save('lost');recovered.acknowledge(pc+'.EXAMPLE.TEST')
        recovered.target_ready(pc)
        self.assertFalse(same_target('PC.ONE.TEST','PC.TWO.TEST'))
        self.assertFalse(same_target('192.0.2.1','192.0.2.2'))

    def test_lost_service_reply_is_durable_unknown(self):
        self.transport.side_effect=TimeoutError('Simulated lost reply')
        self.assertEqual(self.client.post('/api/services/restart',json=self.request).status_code,502)
        self.assertEqual(self.client.post('/api/services/restart',json=self.request).status_code,409)
        self.assertEqual(self.transport.call_count,1)
        recovered=JobService(self.store.path);self.addCleanup(recovered.pool.shutdown,wait=True);recovered.recover()
        self.assertIn(self.request['computer'],recovered.unresolved)
        self.assertEqual(next(iter(recovered.jobs.values()))['state'],'unknown')

    def test_accepted_reboot_persists_before_worker_starts(self):
        monitor=RebootMonitor(Mock(),store=self.store)
        with patch('reboot_monitor.threading.Thread'):
            result=monitor.start(self.request['computer'])
        recovered=JobService(self.store.path);self.addCleanup(recovered.pool.shutdown,wait=True);recovered.recover()
        self.assertEqual(recovered.jobs[result['job']]['kind'],'reboot')
        self.assertEqual(recovered.jobs[result['job']]['state'],'interrupted')
        self.assertIn(self.request['computer'],recovered.unresolved)
