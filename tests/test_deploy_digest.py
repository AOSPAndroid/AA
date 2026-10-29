"""An approved deployment runs exactly the approved script. Windows copy and launch are simulated."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
from contextlib import ExitStack
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_watch
from backend import main
from install_fixture import finished
from job_service import JobService


class DeploymentDigest(unittest.TestCase):
    def run_worker(self, approved, source=b'exit 0', staged=b'exit 0', mode='full'):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            base = Path(tmp)
            (base / 'repo' / 'Example').mkdir(parents=True)
            (base / 'repo' / 'Example' / 'setup_i.ps1').write_bytes(source)
            service = JobService(lambda: base / 'operations.db')
            stack.callback(service.pool.shutdown)
            stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs, lock=service.lock,
                                              HISTORY_DB=base / 'operations.db', REPO=base / 'repo'))
            stack.enter_context(patch.object(main, 'validate_pc', lambda pc: pc.upper()))
            stack.enter_context(patch.object(main, 'identity', return_value='FICTIONAL OPERATOR'))

            def unc(pc, path='C:'):  # The target's C$ share, as a local folder.
                return str(base / 'target' / path.replace(':', '').replace('\\', '/').lstrip('/'))

            def copy(source_folder, destination, fresh=False, threads=8):
                Path(destination).mkdir(parents=True, exist_ok=True)
                (Path(destination) / 'setup_i.ps1').write_bytes(staged)
                return 1

            stack.enter_context(patch.object(main, 'unc', unc))
            stack.enter_context(patch.object(main.os.path, 'isdir', return_value=True))
            copied = stack.enter_context(patch.object(main, 'copy_pkg', side_effect=copy))
            # The PC's registrations are read locally here; no PC is contacted.
            stack.enter_context(patch.object(main, 'watch_for', lambda pc: install_watch.Watch(lambda script: '{}', pc)))
            launched = stack.enter_context(patch.object(main, 'launch', return_value=(4321, 'run.log', 'run.exit')))
            stack.enter_context(patch.object(main, 'monitor', side_effect=finished('0', ['done'])))
            if mode == 'execute':  # Whatever already sits in the staging folder on the PC.
                Path(unc('FICT-PC', main.REMOTE_ROOT + r'\Example')).mkdir(parents=True)
                (Path(unc('FICT-PC', main.REMOTE_ROOT + r'\Example')) / 'setup_i.ps1').write_bytes(staged)
            service.jobs['job'] = {'state': 'queued', 'events': []}
            request = main.Deploy(computer='FICT-PC', folder='Example', script='setup_i.ps1', mode=mode,
                                  sha256=hashlib.sha256(approved).hexdigest())
            main.history_create('job', request.computer, 'Example', 'Install', request.script, mode)
            main._deploy_worker('job', request)
            return service.jobs['job'], copied, launched

    def test_the_approved_script_is_copied_checked_and_launched(self):
        job, copied, launched = self.run_worker(b'exit 0')
        self.assertEqual(job['state'], 'launched')
        copied.assert_called_once()
        launched.assert_called_once()

    def test_a_script_changed_after_approval_is_never_copied(self):
        job, copied, launched = self.run_worker(b'exit 0', source=b'Remove-Item C:\\ -Recurse')
        self.assertEqual(job['state'], 'failed')
        self.assertIn('changed after approval', job['events'][-1]['message'])
        copied.assert_not_called()
        launched.assert_not_called()

    def test_a_different_staged_script_is_never_launched(self):
        for mode in ('full', 'execute', 'copy'):
            with self.subTest(mode=mode):
                job, _, launched = self.run_worker(b'exit 0', staged=b'planted by a local user', mode=mode)
                self.assertEqual(job['state'], 'failed')
                self.assertIn('differs from the approved script', job['events'][-1]['message'])
                launched.assert_not_called()


if __name__ == '__main__':
    unittest.main()
