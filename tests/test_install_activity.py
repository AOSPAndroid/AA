"""Atlas waits for the installers a deployment script starts, and reports them. Windows calls are simulated."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from backend import main
from backend.axis_operations import AtlasOperations
from job_service import JobService

SETTLED = {"settled": True, "waited_seconds": 95, "still_running": [], "left_running": [], "windows_installer_busy": False,
           "tracking": "job object", "software": {"added": [{"name": "Example App", "version": "2.1"}], "removed": [], "changed": []}}


class InstallerActivity(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.base / 'repo' / 'Example').mkdir(parents=True)
        (self.base / 'repo' / 'Example' / 'setup_i.ps1').write_text('exit 0')
        self.service = JobService(lambda: self.base / 'operations.db')
        self.stack.callback(self.service.pool.shutdown)
        self.stack.enter_context(patch.multiple(main, job_service=self.service, jobs=self.service.jobs, lock=self.service.lock,
                                                HISTORY_DB=self.base / 'operations.db', REPO=self.base / 'repo'))
        self.stack.enter_context(patch.object(main, 'validate_pc', lambda pc: pc.upper()))
        self.stack.enter_context(patch.object(main, 'identity', return_value='FICTIONAL OPERATOR'))
        # The target's C$ share, as a local folder.
        self.stack.enter_context(patch.object(main, 'unc', lambda pc, path='C:': str(self.base / 'target' / path.replace(':', '').replace('\\', '/').lstrip('/'))))
        (self.base / 'target' / 'C' / 'Temp').mkdir(parents=True)

    def deploy(self, activity, statuses=(), job_id='job'):
        def monitor(pc, pid, log, ex, progress=None, found=None):
            for status in statuses:
                progress(status)
            found.update(activity)
            return '0', ['done']
        self.stack.enter_context(patch.object(main.os.path, 'isdir', return_value=True))
        self.stack.enter_context(patch.object(main, 'copy_pkg', return_value=1))
        self.stack.enter_context(patch.object(main, 'launch', return_value=(4321, 'run.log', r'C:\Temp\Example_x.exitcode')))
        self.stack.enter_context(patch.object(main, 'monitor', side_effect=monitor))
        self.service.jobs[job_id] = {'state': 'queued', 'events': []}
        main.history_create(job_id, 'FICT-PC', 'Example', 'Install', 'setup_i.ps1', 'full')
        main._deploy_worker(job_id, main.Deploy(computer='FICT-PC', folder='Example', script='setup_i.ps1'))
        return self.service.jobs[job_id]

    def test_the_wait_and_newly_registered_software_reach_the_job_history_and_axis(self):
        job = self.deploy(SETTLED, ['Script exited with code 0; waiting for setup.exe to finish'])
        messages = [e['message'] for e in job['events']]
        self.assertIn('Script exited with code 0; waiting for setup.exe to finish', messages)
        self.assertEqual(job['state'], 'launched')
        self.assertEqual(messages[-1], 'Launched; installer activity finished after 1 min 35 s; newly registered: Example App 2.1')
        self.assertEqual(job['events'][-1]['install']['software']['added'][0]['name'], 'Example App')
        self.assertNotIn('FICT-PC', self.service.unresolved)
        with main.hist_db() as c:
            self.assertIn('newly registered: Example App 2.1', c.execute("select details from deployments where id='job'").fetchone()[0])
        result = AtlasOperations(main, lambda action: False).deployment('job')
        self.assertEqual(result['software_changes']['added'], [{'name': 'Example App', 'version': '2.1'}])
        self.assertTrue(result['installer_activity']['settled'])
        self.assertIn('launched, exit code 0', result['outcome'])

    def test_installers_still_running_when_monitoring_stops_hold_the_pc(self):
        job = self.deploy(dict(SETTLED, settled=False, still_running=['setup.exe'], windows_installer_busy=True))
        self.assertTrue(job['recovery_required'])
        self.assertIn('FICT-PC', self.service.unresolved)
        self.assertIn('still running when monitoring stopped (setup.exe, Windows Installer)', job['events'][-1]['message'])
        self.assertIn('unknown', AtlasOperations(main, lambda action: False).deployment('job')['outcome'])
        self.service.unresolved.discard('FICT-PC')

    def test_completion_not_confirmed_by_a_job_object_record_holds_the_pc(self):
        for job_id, activity, reason in (('missing', {}, 'no installer-activity record was written'),
                                         ('tree', dict(SETTLED, tracking='process tree'), 'could not track every process the script started')):
            with self.subTest(reason=reason):
                job = self.deploy(activity, job_id=job_id)
                self.assertTrue(job['recovery_required'])
                self.assertIn('FICT-PC', self.service.unresolved)
                self.assertIn(reason, job['events'][-1]['message'])
                self.service.unresolved.discard('FICT-PC')

    def test_monitor_relays_the_targets_status_and_reads_its_record(self):
        status, record = (self.base / 'target' / 'C' / 'Temp' / name for name in ('Example_x.status', 'Example_x.activity.json'))
        exitfile = self.base / 'target' / 'C' / 'Temp' / 'Example_x.exitcode'
        checks = iter((True, True, False))
        def running(pc, pid):
            alive = next(checks)
            if alive:
                status.write_text('Script exited with code 0; waiting for msiexec.exe to finish', encoding='utf-8-sig')
            else:
                record.write_text(json.dumps(SETTLED), encoding='utf-8-sig')
                exitfile.write_text('0')
            return alive
        progress, found = [], {}
        with patch.object(main, 'wmi_running', side_effect=running), patch.object(main.time, 'sleep'):
            ec, _ = main.monitor('FICT-PC', 4321, r'C:\Temp\Example_x.log', r'C:\Temp\Example_x.exitcode', progress.append, found)
        self.assertEqual(ec, '0')
        self.assertEqual(progress, ['Script exited with code 0; waiting for msiexec.exe to finish'])
        self.assertEqual(found, SETTLED)


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell runs the remote command')
class RemoteCommand(unittest.TestCase):
    """The command Atlas hands to WMI, run on this machine with a harmless payload. No other PC is contacted."""

    def test_the_compressed_command_runs_its_payload_and_keeps_the_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'rän.txt'  # A non-ASCII path shows the payload is decoded as UTF-8.
            command = main.remote_command("Set-Content -LiteralPath %s -Value ran\nexit 7\n" % main.quote(marker))
            result = subprocess.run(command, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertTrue(marker.exists())

    def test_the_launch_payload_is_valid_windows_powershell(self):
        commands = []
        with patch.object(main, 'wmi_create', side_effect=lambda pc, command: commands.append(command) or 1):
            main.launch('TESTPC', r'C:\Temp\Packages\Exämple\setup_i.ps1', 'Exämple')
        bootstrap = base64.b64decode(commands[0].split()[-1]).decode('utf-16le')
        payload = zlib.decompress(base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", bootstrap).group(1)), -15).decode('utf-8')
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'payload.ps1'
            script.write_text(payload, encoding='utf-8-sig')
            parse = ("$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile(%s, [ref]$null, [ref]$errors); "
                     "$errors | ForEach-Object { $_.Message }; exit $errors.Count" % main.quote(script))
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', parse], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
