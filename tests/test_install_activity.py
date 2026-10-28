"""Atlas waits for the installers a deployment script starts and reports them, reading the PC from outside.
Only the package's own script runs on the target. Windows calls are simulated."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import install_watch
from backend import main
from axis.it_tools import install_unconfirmed
from backend.axis_operations import AtlasOperations
from job_service import JobService

SETTLED = {"settled": True, "waited_seconds": 95, "still_running": [], "left_running": [], "windows_installer_busy": False,
           "tracking": "process watch", "software": {"added": [{"name": "Example App", "version": "2.1"}], "removed": [], "changed": []}}


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
        self.stack.enter_context(patch.object(main, 'watch_for', lambda pc: install_watch.Watch(lambda script: '{}', pc)))
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



def process(pid, parent, name, created, cpu=0, line=''):
    return {'id': pid, 'parent': parent, 'name': name, 'created': '20261028%06d.000000+060' % created, 'cpu': cpu, 'line': line}


class FakeTarget:
    """Answers Atlas's read-only queries the way the PC's WMI would, one process table per look."""

    def __init__(self, tables, before=None, after=None, busy=()):
        self.tables, self.busy, self.looks = list(tables), list(busy), 0
        self.registered = [before or {}, after or {}]
        self.scripts = []

    def __call__(self, script):
        self.scripts.append(script)
        if 'Win32_Process' in script:
            table = self.tables[min(self.looks, len(self.tables) - 1)]
            busy = self.busy[min(self.looks, len(self.busy) - 1)] if self.busy else False
            self.looks += 1
            if isinstance(table, Exception):
                raise table
            return json.dumps({'processes': table, 'installer': busy})
        current = self.registered[0] if len(self.registered) == 1 else self.registered.pop(0)
        if isinstance(current, Exception):
            raise current
        return json.dumps(current)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class AtlasSideWatch(unittest.TestCase):
    EXPLORER = process(900, 800, 'explorer.exe', 1)

    def watch(self, target, clock=None):
        clock = clock or Clock()
        return install_watch.Watch(target, "'FICT-PC'", clock=clock, sleep=clock.sleep)

    def test_a_handed_off_installer_is_waited_for_and_the_new_software_recorded(self):
        root, setup = process(4321, 700, 'powershell.exe', 10), process(50, 4321, 'setup.exe', 11)
        msi = process(60, 50, 'msiexec.exe', 12, line='"C:\\Windows\\System32\\msiexec.exe" /i example.msi /qn')
        service = process(70, 600, 'msiexec.exe', 13, line='C:\\Windows\\System32\\msiexec.exe /V')
        reused = process(50, 999, 'notepad.exe', 20)  # setup.exe's process ID, later given to someone else's program
        target = FakeTarget([[root, setup, self.EXPLORER], [setup, msi, self.EXPLORER], [msi, service, self.EXPLORER],
                             [service, reused, self.EXPLORER], [service, reused, self.EXPLORER]],
                            before={'Machine\\{OLD}': ['Old App', '1.0']},
                            after={'Machine\\{OLD}': ['Old App', '1.1'], 'Machine\\{NEW}': ['Example App', '2.1']})
        temp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, temp)
        (temp / 'C' / 'Temp').mkdir(parents=True)
        def unc(pc, path='C:'):
            return str(temp / path.replace(':', '').replace('\\', '/').lstrip('/'))
        watch = self.watch(target)
        watch.remember_software(); watch.ready()
        looks = []
        def exit_when_the_script_is_gone(script):
            answer = target(script)
            if 'Win32_Process' in script and target.looks == 2:
                (temp / 'C' / 'Temp' / 'Example_x.exitcode').write_text('0')
                (temp / 'C' / 'Temp' / 'Example_x.log').write_text('installing\n', encoding='utf-8')
            looks.append(target.looks)
            return answer
        watch.run = exit_when_the_script_is_gone
        progress, record = [], install_watch.Record(watch)
        with patch.object(main, 'unc', unc), patch.object(main.time, 'sleep'):
            ec, lines = main.monitor('FICT-PC', 4321, r'C:\Temp\Example_x.log', r'C:\Temp\Example_x.exitcode', progress.append, record)
        self.assertEqual((ec, lines), ('0', ['installing']))
        self.assertEqual(progress, ['Script exited with code 0; waiting for msiexec.exe, Windows Installer to finish'])
        self.assertTrue(record['settled'])
        self.assertEqual(record['tracking'], 'process watch')
        self.assertEqual(record['software'], {'added': [{'name': 'Example App', 'version': '2.1'}], 'removed': [],
                                              'changed': [{'name': 'Old App', 'from': '1.0', 'to': '1.1'}]})
        self.assertIsNone(install_unconfirmed(dict(record)))
        self.assertEqual(json.loads(json.dumps(dict(record)))['software']['added'][0]['name'], 'Example App')
        # Every query only reads: WMI process lists and the registry provider's Enum/Get methods.
        for script in target.scripts:
            self.assertNotRegex(script, r'(?i)\.Create\(|Invoke-WmiMethod|Invoke-Command|SetStringValue|CreateKey|DeleteKey|Terminate')

    def test_the_idle_msiexec_service_is_not_an_installation_but_its_in_progress_key_is(self):
        service = process(70, 600, 'msiexec.exe', 13, line='C:\\Windows\\System32\\msiexec.exe /V')
        self.assertFalse(self.watch(FakeTarget([[service]])).look()[1])
        self.assertTrue(self.watch(FakeTarget([[service]], busy=[True])).look()[1])
        self.assertTrue(self.watch(FakeTarget([[process(71, 4321, 'msiexec.exe', 14, line='msiexec /x {GUID} /qn')]])).look()[1])

    def test_an_application_the_installer_leaves_running_settles_after_a_quiet_minute(self):
        app = process(80, 4321, 'example.exe', 11, cpu=5_000_000)
        clock = Clock()
        watch = self.watch(FakeTarget([[app]], before={}, after={'Machine\\{NEW}': ['Example App', '2.1']}), clock)
        watch.tree = {4321: app['created'][:-14] + '000010.000000+060', 80: app['created']}
        watch.before = {}
        result = watch.settle('0', deadline=600)
        self.assertTrue(result['settled'])
        self.assertEqual(result['left_running'], ['example.exe'])
        self.assertGreaterEqual(result['waited_seconds'], 60)

    def test_activity_still_running_at_the_deadline_is_not_settled(self):
        clock = Clock()
        watch = self.watch(FakeTarget([[process(80, 4321, 'setup.exe', 11, cpu=0)]], busy=[True]), clock)
        watch.tree = {4321: '0', 80: process(80, 4321, 'setup.exe', 11)['created']}
        result = watch.settle('0', deadline=30)
        self.assertEqual((result['settled'], result['still_running'], result['windows_installer_busy']), (False, ['setup.exe'], True))
        self.assertIn('still running when monitoring stopped (setup.exe, Windows Installer)', install_unconfirmed(result))

    def test_a_pc_that_stops_answering_is_not_settled_and_unreadable_software_is_left_out(self):
        clock = Clock()
        watch = self.watch(FakeTarget([RuntimeError('RPC server unavailable')], before=RuntimeError('access denied')), clock)
        watch.remember_software(); watch.ready()
        self.assertIsNone(watch.before)
        result = watch.settle('0', deadline=30)
        self.assertFalse(result['settled'])
        self.assertEqual(result['still_running'], ['the PC could not be read'])
        self.assertNotIn('software', result)

    def test_a_read_that_finishes_after_the_launch_is_not_used_as_before(self):
        started, release = threading.Event(), threading.Event()
        def run(script):
            started.set(); release.wait(5)
            return '{"Machine\\\\{X}": ["Example App", "1.0"]}'
        watch = install_watch.Watch(run, "'FICT-PC'")
        watch.remember_software(); started.wait(5)
        watch.ready(timeout=0)
        release.set(); watch.reading.join(5)
        self.assertIsNone(watch.before, 'It could already include the installation')

    def test_a_deployment_reads_the_registrations_before_it_launches(self):
        order = []
        class Watch:
            def remember_software(self): order.append('read before')
            def ready(self): order.append('ready')
        stack = ExitStack(); self.addCleanup(stack.close)
        base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (base / 'repo' / 'Example').mkdir(parents=True); (base / 'repo' / 'Example' / 'setup_i.ps1').write_text('exit 0')
        service = JobService(lambda: base / 'operations.db'); stack.callback(service.pool.shutdown)
        stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs, lock=service.lock,
                                           HISTORY_DB=base / 'operations.db', REPO=base / 'repo'))
        stack.enter_context(patch.object(main, 'validate_pc', lambda pc: pc.upper()))
        stack.enter_context(patch.object(main, 'identity', return_value='FICTIONAL OPERATOR'))
        stack.enter_context(patch.object(main.os.path, 'isdir', return_value=True))
        stack.enter_context(patch.object(main, 'watch_for', lambda pc: Watch()))
        stack.enter_context(patch.object(main, 'copy_pkg', side_effect=lambda *a: order.append('copy') or 1))
        stack.enter_context(patch.object(main, 'launch', side_effect=lambda *a: order.append('launch') or (1, 'log', 'exit')))
        def monitor(pc, pid, log, ex, progress, activity):
            self.assertIsInstance(activity, install_watch.Record)
            activity.update(SETTLED)
            return '0', []
        stack.enter_context(patch.object(main, 'monitor', side_effect=monitor))
        service.jobs['job'] = {'state': 'queued', 'events': []}
        main.history_create('job', 'FICT-PC', 'Example', 'Install', 'setup_i.ps1', 'full')
        main._deploy_worker('job', main.Deploy(computer='FICT-PC', folder='Example', script='setup_i.ps1'))
        self.assertEqual(order, ['read before', 'copy', 'ready', 'launch'])
        self.assertIs(type(service.jobs['job']['events'][-1]['install']), dict, 'The job keeps a plain record')
        service.snapshot(service.jobs, 'job')  # and it copies


class LaunchCommand(unittest.TestCase):
    """What WMI starts on the target: one readable line around the package's own script."""

    def test_the_target_sees_one_readable_line_that_runs_the_package_script(self):
        for script, runner in ((r'C:\Temp\Packages\Example App\sub\setup_i.ps1', "& 'C:\\Temp\\Packages\\Example App\\sub\\setup_i.ps1'"),
                               (r'C:\Temp\Packages\Example App\install_i.vbs', "& cscript.exe //B //NoLogo 'C:\\Temp\\Packages\\Example App\\install_i.vbs'")):
            with self.subTest(script=script):
                command = main.launch_command(script, r'C:\Temp\Example_x.log', r'C:\Temp\Example_x.exitcode')
                self.assertTrue(command.startswith('powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "'))
                self.assertTrue(command.endswith('"'))
                self.assertNotIn('"', command[command.index('"') + 1:-1], 'One quoted argument, as WMI passes it')
                self.assertIn(runner, command)
                self.assertIn("Set-Location -LiteralPath '%s'" % script.rsplit('\\', 1)[0], command)
                self.assertIn("Out-File -LiteralPath 'C:\\Temp\\Example_x.exitcode' -Encoding ascii", command)
                self.assertIn('Get-ChildItem -Recurse -File -Filter *.ps1 | Unblock-File;', command, 'As Atlas always has, for scripts the package starts itself')
                for hidden in ('EncodedCommand', 'FromBase64String', 'DeflateStream', 'ScriptBlock', 'Add-Type', 'DllImport', 'IntPtr'):
                    self.assertNotIn(hidden, command)
                self.assertLess(len(command), 1000)
        self.assertIn("'C:\\Temp\\Packages\\O''Brien\\setup_i.ps1'", main.launch_command(r"C:\Temp\Packages\O'Brien\setup_i.ps1", 'l', 'e'))
        commands = []
        with patch.object(main, 'wmi_create', side_effect=lambda pc, command: commands.append(command) or 1):
            pid, log, ex = main.launch('TESTPC', r'C:\Temp\Packages\Example\setup_i.ps1', 'Example')
        self.assertEqual(commands[0], main.launch_command(r'C:\Temp\Packages\Example\setup_i.ps1', log, ex))
        self.assertRegex(ex, r'^C:\\Temp\\Example_[a-f0-9]{32}\.exitcode$')


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell runs the command')
class LaunchCommandOnWindows(unittest.TestCase):
    """The line Atlas hands to WMI, run on this machine against a harmless local script. No other PC is contacted."""

    def run_script(self, name, body, marked=()):
        folder = Path(tempfile.mkdtemp(prefix='atlas-launch-')) / 'Exämple pkg'  # spaces and non-ASCII
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder.parent, True)
        self.folder = folder
        for helper in marked:  # downloaded from the internet, as Windows marks it
            (folder / helper).write_text('exit 0\n', encoding='ascii')
            with open(str(folder / helper) + ':Zone.Identifier', 'w', encoding='ascii') as stream:
                stream.write('[ZoneTransfer]\nZoneId=3\n')
        script = folder / name
        script.write_text(body, encoding='utf-8-sig' if name.endswith('.ps1') else 'ascii')
        log, exitcode = folder.parent / 'run.log', folder.parent / 'run.exitcode'
        subprocess.run(main.launch_command(str(script), str(log), str(exitcode)), timeout=120)
        return exitcode.read_text(encoding='ascii').strip(), log.read_text(encoding='utf-8-sig', errors='replace')

    def test_a_script_runs_in_its_folder_and_its_exit_code_and_output_are_kept(self):
        code, log = self.run_script('setup_i.ps1', "Write-Output ('in ' + (Split-Path -Leaf (Get-Location)))\nexit 7\n")
        self.assertEqual(code, '7')
        self.assertIn('in Exämple pkg', log)

    def test_the_package_scripts_are_unblocked_for_the_script_to_start(self):
        code, log = self.run_script('setup_i.ps1', "exit 0\n", marked=('helper.ps1',))
        self.assertEqual(code, '0', log)
        self.assertTrue((self.folder / 'helper.ps1').is_file())
        self.assertFalse(os.path.exists(str(self.folder / 'helper.ps1') + ':Zone.Identifier'))

    def test_a_failing_script_reports_exit_code_1_with_its_error(self):
        code, log = self.run_script('setup_i.ps1', "throw 'example failure'\n")
        self.assertEqual(code, '1')
        self.assertIn('example failure', log)

    def test_a_vbscript_runs_through_cscript_in_its_folder(self):
        # Batch mode (//B) keeps a script from waiting on a prompt; it also hides WScript.Echo, so the script leaves a file.
        code, log = self.run_script('setup_i.vbs', 'CreateObject("Scripting.FileSystemObject").CreateTextFile("vbs ran.txt").Close\r\nWScript.Quit 3\r\n')
        self.assertEqual(code, '3', log)
        self.assertTrue((self.folder / 'vbs ran.txt').is_file())

    def test_the_read_only_queries_are_valid_windows_powershell(self):
        for script in (install_watch.SOFTWARE, install_watch.PROCESSES):
            with self.subTest(script=script[:40]), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'query.ps1'
                path.write_text(script.replace('TARGET', "'EXAMPLE-PC'"), encoding='utf-8-sig')
                parse = ("$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile(%s, [ref]$null, [ref]$errors); "
                         "$errors | ForEach-Object { $_.Message }; exit $errors.Count" % main.quote(path))
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', parse], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
