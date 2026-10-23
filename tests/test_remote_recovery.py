"""Remote-monitor failures remain guarded across restart; all Windows calls are mocked."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from backend import main
from job_service import JobService


class RemoteRecovery(unittest.TestCase):
    def test_launched_monitor_failure_stays_guarded_until_explicit_acknowledgment(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / 'operations.db'
            service = JobService(lambda: path)
            stack.callback(service.pool.shutdown)
            stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs,
                                              lock=service.lock, HISTORY_DB=path))
            stack.enter_context(patch.object(main, 'validate_pc', lambda pc: pc.upper()))
            stack.enter_context(patch.object(main, 'validate_deployment', lambda request: request))
            stack.enter_context(patch.object(main, 'identity', return_value='FICTIONAL OPERATOR'))
            stack.enter_context(patch.object(main.os.path, 'isdir', return_value=True))
            copy = stack.enter_context(patch.object(main, 'copy_pkg', return_value=1))
            stack.enter_context(patch.object(main, 'launch', return_value=(4321, 'fixture.log', 'fixture.exit')))
            stack.enter_context(patch.object(main, 'monitor', side_effect=RuntimeError('Monitoring timed out')))
            service.jobs['fixture'] = {'state': 'queued', 'events': []}
            request = main.Deploy(computer='FICT-PC', folder='FictionalPackage', script='setup_i.ps1')
            main.history_create('fixture', request.computer, request.folder, 'Install', request.script, 'full')
            main._deploy_worker('fixture', request)
            self.assertEqual(service.jobs['fixture']['state'], 'launched')
            recovered = JobService(lambda: path)
            stack.callback(recovered.pool.shutdown)
            recovered.recover()
            with self.assertRaises(HTTPException) as blocked:
                recovered.target_ready('FICT-PC')
            self.assertEqual(blocked.exception.status_code, 409)
            copy.assert_called_once()
            with patch.multiple(main, job_service=recovered, jobs=recovered.jobs, lock=recovered.lock):
                main.acknowledge_recovery('FICT-PC', {'confirmation': 'FICT-PC'})
            again = JobService(lambda: path)
            stack.callback(again.pool.shutdown)
            again.recover()
            again.target_ready('FICT-PC')

    def test_completed_monitor_does_not_require_recovery(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / 'operations.db'
            service = JobService(lambda: path)
            stack.callback(service.pool.shutdown)
            stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs,
                                              lock=service.lock, HISTORY_DB=path))
            for name, value in [('validate_pc', lambda pc: pc), ('validate_deployment', lambda request: request)]:
                stack.enter_context(patch.object(main, name, value))
            stack.enter_context(patch.object(main, 'identity', return_value='FICTIONAL OPERATOR'))
            stack.enter_context(patch.object(main.os.path, 'isdir', return_value=True))
            stack.enter_context(patch.object(main, 'copy_pkg', return_value=1))
            stack.enter_context(patch.object(main, 'launch', return_value=(4321, 'fixture.log', 'fixture.exit')))
            stack.enter_context(patch.object(main, 'monitor', return_value=('0', [])))
            service.jobs['fixture'] = {'state': 'queued', 'events': []}
            request = main.Deploy(computer='FICT-PC', folder='FictionalPackage', script='setup_i.ps1')
            main.history_create('fixture', request.computer, request.folder, 'Install', request.script, 'full')
            main._deploy_worker('fixture', request)
            recovered = JobService(lambda: path)
            stack.callback(recovered.pool.shutdown)
            recovered.recover()
            recovered.target_ready('FICT-PC')

    def test_guard_added_while_waiting_for_target_lock_blocks_new_work(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / 'operations.db'
            service = JobService(lambda: path)
            stack.callback(service.pool.shutdown)
            stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs,
                                              lock=service.lock, HISTORY_DB=path))
            stack.enter_context(patch.object(main, 'validate_pc', lambda pc: pc.upper()))
            stack.enter_context(patch.object(main, 'validate_deployment', lambda request: request))
            copy = stack.enter_context(patch.object(main, 'copy_pkg'))
            cleanup = stack.enter_context(patch.object(main, '_cleanup_package_folder'))
            import threading
            guard = threading.Lock()
            def prior_operation_finished(pc):
                # A prior operation records its unknown outcome after the first readiness check.
                service.unresolved.add(pc)
                return guard
            stack.enter_context(patch.object(main, 'target_lock', prior_operation_finished))
            service.jobs['fixture'] = {'state': 'queued', 'events': []}
            main._deploy_worker('fixture', main.Deploy(computer='FICT-PC', folder='FictionalPackage', script='setup_i.ps1'))
            self.assertEqual(service.jobs['fixture']['state'], 'failed')
            copy.assert_not_called()
            self.assertFalse(guard.locked())
            service.unresolved.clear()
            with self.assertRaises(HTTPException):
                main.cleanup_package_folder('FICT-PC')
            cleanup.assert_not_called()
            self.assertFalse(guard.locked())

    def test_recovery_guard_survives_retention_pruning(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            path = Path(tmp) / 'operations.db'
            service = JobService(lambda: path, retained=1)
            stack.callback(service.pool.shutdown)
            service.jobs['uncertain'] = {'state': 'launched', 'target': 'FICT-PC', 'recovery_required': True}
            service.save('uncertain')
            service.jobs['finished'] = {'state': 'complete'}
            service.save('finished')
            self.assertNotIn('uncertain', service.jobs)
            recovered = JobService(lambda: path)
            stack.callback(recovered.pool.shutdown)
            recovered.recover()
            with self.assertRaises(HTTPException):
                recovered.target_ready('FICT-PC')


if __name__ == '__main__':
    unittest.main()
