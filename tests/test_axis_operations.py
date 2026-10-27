"""Axis's Windows tools run Atlas's own operations. Simulated Windows: no PC, share or process is touched."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import hashlib, json, os, tempfile, time, unittest
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend import main as app
from backend.axis_operations import MAX_TARGETS, SNAPSHOT_SECONDS, TOOLS_OPENED, AtlasOperations
from axis import agent as axis_agent
from axis import it_tools

SERVICE = {'name': 'Spooler', 'display_name': 'Print Spooler', 'state': 'Running', 'start_mode': 'Auto', 'pid': 100,
           'can_stop': True, 'stop_reason': '', 'can_start': False, 'start_reason': 'Already running',
           'can_restart': True, 'restart_reason': '', 'identity': 'a' * 64}
PROCESS = {'PID': 4242, 'Process': 'app.exe', 'MemoryMB': 12.5, 'CreatedAt': '20261026101010.000000+060', 'SessionId': 1,
           'CommandLine': 'C:\\app.exe ' + 'x' * 400, 'CanTerminate': True, 'BlockReason': '', 'CPU': 50.0}


class Windows:
    """Answers Atlas's PowerShell calls the way the remote scripts do, and records each one."""
    def __init__(self):
        self.calls = []

    def __call__(self, script, timeout=120):
        self.calls.append(script)
        if "-Action 'restart'" in script:
            item = dict(SERVICE, state='Running')
            return json.dumps({'ok': True, 'computer': 'TESTPC', 'name': 'Spooler', 'outcome': 'restarted', 'state': 'Running', 'item': item})
        if "-Action 'list'" in script and '-Kind' in script:
            return json.dumps({'ok': True, 'items': [PROCESS]})
        if "-Action 'list'" in script:
            return json.dumps({'ok': True, 'computer': 'TESTPC', 'items': [SERVICE]})
        if "-Action 'kill'" in script:
            return json.dumps({'ok': True, 'items': [{'PID': 4242, 'Process': 'app.exe', 'state': 'terminated', 'message': ''}]})
        if 'Win32_OperatingSystem' in script and 'LastBoot' in script:
            return json.dumps({'Computer': 'TESTPC', 'OS': 'Windows 11', 'LastBoot': 'today', 'LoggedOn': 'EXAMPLE\\alex', 'MemoryGB': 16})
        if 'Get-ADUser' in script or 'ActiveDirectory' in script:
            return json.dumps({'details': {'SamAccountName': 'alex'}, 'groups': ['Staff']})
        raise AssertionError('Unexpected PowerShell call: ' + script[:200])


class Reboots:
    def __init__(self):
        self.rows = {}

    def start(self, pc):
        self.rows['b' * 32] = {'id': 'b' * 32, 'target': pc, 'state': 'waiting_offline', 'message': 'Reboot accepted'}
        return {'job': 'b' * 32, 'target': pc}

    def snapshot(self):
        return {'reboots': list(self.rows.values()), 'count': len(self.rows)}


class AtlasOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        repo = base / 'repo'
        (repo / 'Example App').mkdir(parents=True); (repo / 'Example App' / 'setup_i.ps1').write_text('exit 0')
        (repo / 'Example App' / 'remove_u.ps1').write_text('exit 0'); (repo / 'Other').mkdir()
        self.windows, self.reboots, self.started, self.opened = Windows(), Reboots(), [], []
        for name, value in (('HISTORY_DB', base / 'history.db'), ('REPO', repo), ('identity', lambda: 'EXAMPLE\\operator'),
                            ('start_job', lambda fn, j, p: self.started.append((j, p.model_dump()))),
                            ('ps', self.windows), ('reboot_monitor', self.reboots),
                            ('_start_local', self.opened.append), ('_start_msc', self.opened.append)):
            patcher = patch.object(app, name, value); patcher.start(); self.addCleanup(patcher.stop)
        jobs = dict(app.jobs); self.addCleanup(lambda: (app.jobs.clear(), app.jobs.update(jobs)))
        unresolved = set(app.job_service.unresolved)
        self.addCleanup(lambda: (app.job_service.unresolved.clear(), app.job_service.unresolved.update(unresolved)))
        self.confirm = MagicMock(return_value=True)
        self.legacy = base / 'axis-state'
        self.ops = AtlasOperations(app, self.confirm, legacy_state=self.legacy)

    def history(self, job):
        with app.hist_db() as c:
            return dict(c.execute('select * from deployments where id=?', (job,)).fetchone())

    def test_packages_come_from_atlas_repository(self):
        found = self.ops.call('find_packages', {'query': 'example'})
        self.assertEqual((found['packages'], found['scripts']), (['Example App'], ['setup_i.ps1']))
        self.assertEqual(self.ops.call('find_packages', {'package': 'Example App', 'action': 'Uninstall'})['scripts'], ['remove_u.ps1'])
        with self.assertRaises(ValueError):
            self.ops.call('find_packages', {'package': '..\\outside'})

    def test_bulk_inspection_uses_atlas_readers_and_preserves_order(self):
        barrier = threading.Barrier(2)
        def overview(pc):
            barrier.wait(timeout=5)
            if pc == 'PC2':
                raise RuntimeError('PC2 is unreachable')
            return {'fixture': pc}
        with patch.object(app, 'overview', side_effect=overview):
            result = self.ops.call('inspect_computers', {'computers': ['pc1', 'PC2', 'PC1'], 'view': 'overview'})
        self.assertEqual([(r['computer'], r['ok']) for r in result['results']], [('PC1', True), ('PC2', False)])
        self.assertEqual(result['results'][0]['data']['overview'], {'fixture': 'PC1'})
        self.assertIn('unreachable', result['results'][1]['error'])
        self.confirm.assert_not_called()

    def test_invalid_bulk_targets_are_rejected_before_any_atlas_read(self):
        with patch.object(app, 'overview') as read:
            for computers, view in ((['PC1', 'bad name'], 'overview'), (['PC1'], 'services'), ([], 'overview')):
                with self.subTest(computers=computers, view=view), self.assertRaises(ValueError):
                    self.ops.call('inspect_computers', {'computers': computers, 'view': view})
        read.assert_not_called()

    def test_a_deployment_axis_starts_is_an_atlas_deployment(self):
        self.confirm.return_value = False
        self.assertEqual(self.ops.call('deploy_package', {'computers': ['testpc'], 'package': 'Example App',
                                                          'script': 'setup_i.ps1', 'action': 'Install'})['state'], 'declined')
        self.assertEqual(self.started, [])
        detail = self.confirm.call_args[0][0]
        self.assertIn('Install Example App using setup_i.ps1 on TESTPC', detail)
        self.assertIn('Atlas deployment', detail)
        self.confirm.return_value = True
        result = self.ops.call('deploy_package', {'computers': ['TESTPC', 'testpc'], 'package': 'Example App',
                                                  'script': 'setup_i.ps1', 'action': 'Install', 'mode': 'copy'})
        [row] = result['jobs']
        job = row['job_id']
        self.assertEqual(self.started, [(job, dict(self.started[0][1], computer='TESTPC', mode='copy'))])
        self.assertEqual(app.jobs[job]['requested_by'], 'Axis')
        saved = self.history(job)
        self.assertEqual((saved['operator'], saved['target'], saved['package'], saved['state']),
                         ('EXAMPLE\\operator (Axis)', 'TESTPC', 'Example App', 'queued'))
        self.assertEqual(app.Deploy(**app.saved_payload(job)).mode, 'copy', "Atlas's retry repeats exactly this request")
        status = self.ops.call('it_job_status', {'job_id': job})
        self.assertEqual((status['state'], status['target'], status['requested_by']), ('queued', 'TESTPC', 'Axis'))
        listed = self.ops.call('it_job_status', {})
        self.assertIn(job, [r['job_id'] for r in listed['jobs']])
        self.assertEqual(self.ops.find_job(job[:6]), job)

    def test_atlas_refuses_before_approval_is_asked(self):
        for args, message in (({'script': 'remove_u.ps1'}, 'Installer does not match'),
                              ({'computers': ['bad name!']}, 'Invalid computer name')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.ops.call('deploy_package', dict({'computers': ['TESTPC'], 'package': 'Example App',
                                                      'script': 'setup_i.ps1', 'action': 'Install'}, **args))
        app.job_service.unresolved.add('TESTPC')
        with self.assertRaisesRegex(ValueError, 'unknown outcome'):
            self.ops.call('deploy_package', {'computers': ['TESTPC'], 'package': 'Example App', 'script': 'setup_i.ps1', 'action': 'Install'})
        with self.assertRaisesRegex(ValueError, 'unknown outcome'):
            self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'reboot'})
        self.confirm.assert_not_called()

    def test_an_unknown_outcome_is_released_only_after_confirmed_inspection(self):
        job = self.ops.call('deploy_package', {'computers': ['TESTPC'], 'package': 'Example App', 'script': 'setup_i.ps1',
                                               'action': 'Install'})['jobs'][0]['job_id']
        app.jobs[job].update(state='launched', recovery_required=True); app.job_service.unresolved.add('TESTPC')
        self.assertTrue(self.ops.call('it_job_status', {'job_id': job})['recovery_required'])
        self.confirm.reset_mock(return_value=False)
        self.confirm.return_value = False
        self.ops.call('it_job_status', {'job_id': job, 'acknowledge_unknown': True})
        self.assertIn('TESTPC', app.job_service.unresolved)
        self.confirm.return_value = True
        released = self.ops.call('it_job_status', {'job_id': job, 'acknowledge_unknown': True})
        self.assertNotIn('TESTPC', app.job_service.unresolved)
        self.assertFalse(released['recovery_required'])
        self.assertIn("Operation recovery", self.confirm.call_args[0][0])

    def test_service_changes_use_atlas_identity_checks_from_the_snapshot(self):
        listed = self.ops.call('inspect_computer', {'computer': 'TESTPC', 'view': 'services', 'query': 'spool'})
        self.assertEqual([i['name'] for i in listed['items']], ['Spooler'])
        self.assertNotIn('identity', listed['items'][0])
        args = {'computer': 'TESTPC', 'action': 'service_restart', 'name': 'spooler', 'snapshot': listed['snapshot']}
        result = self.ops.call('computer_action', args)
        self.assertEqual(result['outcome'], 'restarted')
        self.assertIn("-ExpectedIdentity '" + 'a' * 64 + "'", self.windows.calls[-1])
        self.assertIn('restart service Spooler (Print Spooler) on TESTPC', self.confirm.call_args[0][0])
        with self.assertRaisesRegex(ValueError, 'will not start'):
            self.ops.call('computer_action', dict(args, action='service_start'))
        with self.assertRaisesRegex(ValueError, 'another PC or view'):
            self.ops.call('computer_action', dict(args, computer='OTHERPC'))
        self.ops.snapshots[listed['snapshot']]['created'] -= SNAPSHOT_SECONDS + 1
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.ops.call('computer_action', args)

    def test_process_stop_binds_the_listed_process_identity(self):
        listed = self.ops.call('inspect_computer', {'computer': 'TESTPC', 'view': 'processes'})
        self.assertEqual(len(listed['items'][0]['CommandLine']), 200)
        self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'process_stop', 'pid': 4242, 'snapshot': listed['snapshot']})
        kill = self.windows.calls[-1]
        self.assertIn("-ExpectedCreated '20261026101010.000000+060'", kill)
        self.assertIn("-ExpectedName 'app.exe'", kill)
        with self.assertRaisesRegex(ValueError, 'exact item'):
            self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'process_stop', 'pid': 99, 'snapshot': listed['snapshot']})

    def test_reboots_use_atlas_monitor_and_stay_answerable_after_it_drops_them(self):
        started = self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'reboot'})
        self.assertEqual((started['job_id'], started['state']), ('b' * 32, 'requested'))
        self.assertEqual(self.ops.call('it_job_status', {'job_id': 'b' * 32})['state'], 'waiting_offline')
        self.reboots.rows.clear()  # Atlas removes a completed reboot after ten seconds.
        gone = self.ops.call('it_job_status', {'job_id': 'b' * 32})
        self.assertEqual(gone['state'], 'no longer listed')
        self.assertIn('inspect_computer overview', gone['message'])
        with self.assertRaisesRegex(ValueError, 'No Atlas deployment or reboot'):
            self.ops.call('it_job_status', {'job_id': 'c' * 32})

    def test_reads_tools_and_directory_go_through_atlas(self):
        self.assertEqual(self.ops.call('inspect_computer', {'computer': 'TESTPC', 'view': 'overview'})['overview']['OS'], 'Windows 11')
        self.assertEqual(self.ops.call('directory_lookup', {'kind': 'user', 'identity': 'alex'})['groups'], ['Staff'])
        self.ops.call('open_remote_tool', {'computer': 'TESTPC', 'tool': 'remote_assistance'})
        self.assertEqual(self.opened[-1][-2:], ['/offerra', 'TESTPC'])
        self.confirm.return_value = False
        self.assertEqual(self.ops.call('open_remote_tool', {'computer': 'TESTPC', 'tool': 'rdp'})['state'], 'declined')
        self.assertEqual(len(self.opened), 1)
        with self.assertRaisesRegex(ValueError, 'Unexpected arguments'):
            self.ops.call('inspect_computer', {'computer': 'TESTPC', 'view': 'overview', 'command': 'x'})

    def test_earlier_axis_jobs_stay_readable_and_can_be_acknowledged(self):
        job = {'id': 'e' * 32, 'kind': 'deploy', 'computers': ['TESTPC'], 'state': 'unknown', 'created': it_tools.now(),
               'created_epoch': time.time() - 100, 'results': [], 'events': [], 'worker_pid': None}
        it_tools.write_json(self.legacy / 'jobs' / (job['id'] + '.json'), job)
        listed = self.ops.call('it_job_status', {})
        self.assertIn(('e' * 32, 'earlier Axis job'), [(r['job_id'], r.get('source')) for r in listed['jobs']])
        self.ops.call('it_job_status', {'job_id': 'e' * 32, 'acknowledge_unknown': True})
        self.assertTrue(it_tools.read_json(self.legacy / 'jobs' / (job['id'] + '.json')).get('acknowledged'))

    def deploy(self, **extra):
        return self.ops.call('deploy_package', dict({'computers': ['TESTPC'], 'package': 'Example App',
                                                     'script': 'setup_i.ps1', 'action': 'Install'}, **extra))

    def test_the_approved_script_digest_travels_with_the_atlas_job(self):
        job = self.deploy()['jobs'][0]['job_id']
        approved = hashlib.sha256(b'exit 0').hexdigest()
        self.assertIn('script SHA256=' + approved, self.confirm.call_args[0][0])
        self.assertEqual(self.started[-1][1]['sha256'], approved)
        self.assertNotIn('sha256', app.deployment_payload(job), "Atlas's own Retry and Queue are approved anew in Atlas")

    def test_package_names_are_folder_names_never_paths(self):
        for name in ('\\\\secret.attacker.example\\s\\p', 'C:\\Windows', '..', 'a/b'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'exact package folder name'):
                    self.ops.call('find_packages', {'package': name})
                with self.assertRaisesRegex(ValueError, 'exact package folder name'):
                    self.deploy(package=name)
        self.confirm.assert_not_called()

    def test_every_package_is_reachable_and_linked_packages_are_refused(self):
        for index in range(520):
            (app.REPO / ('Pkg%03d' % index)).mkdir()
        self.assertEqual(self.ops.call('find_packages', {'query': 'pkg', 'offset': 500})['packages'][-1], 'Pkg519')
        (app.REPO / 'Example App' / 'elsewhere').symlink_to(Path(self.tmp.name), target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link or junction'):
            self.deploy()
        self.confirm.assert_not_called()

    def test_atlas_work_in_progress_and_any_name_form_block_axis(self):
        app.jobs['f' * 32] = {'state': 'running', 'target': 'TESTPC', 'events': []}
        for args in ({'action': 'reboot'}, {'action': 'enable_remote_registry'}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'Atlas is working on TESTPC'):
                self.ops.call('computer_action', dict({'computer': 'testpc.corp.example'}, **args))
        with self.assertRaisesRegex(ValueError, 'Atlas is working on'):
            self.deploy(computers=['TESTPC.corp.example'])
        app.jobs['f' * 32]['state'] = 'failed'
        app.job_service.unresolved.add('TESTPC')
        with self.assertRaisesRegex(ValueError, 'unknown outcome'):
            self.deploy(computers=['testpc.corp.example'])
        self.confirm.assert_not_called()

    def test_a_change_approved_while_the_pc_became_busy_does_not_run(self):
        listed = self.ops.call('inspect_computer', {'computer': 'TESTPC', 'view': 'services'})
        calls = len(self.windows.calls)
        def busy(action):
            app.job_service.unresolved.add('TESTPC')  # Something went wrong on the PC during the approval.
            return True
        self.confirm.side_effect = busy
        with self.assertRaisesRegex(ValueError, 'unknown outcome'):
            self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'service_restart', 'name': 'Spooler',
                                              'snapshot': listed['snapshot']})
        self.assertEqual(len(self.windows.calls), calls, 'Nothing was sent to the PC')
        app.job_service.unresolved.discard('TESTPC')
        self.confirm.side_effect = None
        guard = app.target_lock('TESTPC')
        self.assertTrue(guard.acquire(blocking=False))  # An Atlas operation holds the PC.
        try:
            with self.assertRaisesRegex(ValueError, 'Another Atlas operation'):
                self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'reboot'})
        finally:
            guard.release()
        self.assertEqual(self.reboots.rows, {})

    def test_jobs_left_in_either_earlier_axis_folder_keep_blocking(self):
        terminal = Path(self.tmp.name) / 'terminal-state'
        job = {'id': '9' * 32, 'kind': 'deploy', 'computers': ['TESTPC'], 'state': 'unknown', 'created': it_tools.now(),
               'created_epoch': time.time() - 100, 'results': [], 'events': [], 'worker_pid': None}
        it_tools.write_json(terminal / 'jobs' / (job['id'] + '.json'), job)
        ops = AtlasOperations(app, self.confirm, legacy_state=(self.legacy, terminal))
        with self.assertRaisesRegex(ValueError, 'earlier Axis job ' + job['id']):
            ops.call('deploy_package', {'computers': ['testpc'], 'package': 'Example App', 'script': 'setup_i.ps1',
                                        'action': 'Install'})
        self.confirm.assert_not_called()

    def test_too_many_targets_are_refused_before_atlas_admits_any(self):
        with self.assertRaisesRegex(ValueError, '1 to 25'):
            self.deploy(computers=['PC%02d' % i for i in range(26)])
        self.assertEqual(self.started, [])

    def test_outcomes_say_what_atlas_states_mean(self):
        job = self.deploy()['jobs'][0]['job_id']
        app.jobs[job].update(state='launched', events=[{'message': 'Launched', 'exit_code': '0'}])
        self.assertIn('exit code 0', self.ops.call('it_job_status', {'job_id': job})['outcome'])
        app.jobs[job].update(recovery_required=True, events=[{'message': 'Launched', 'log': ['Monitoring timed out']}])
        self.assertTrue(self.ops.call('it_job_status', {'job_id': job})['outcome'].startswith('unknown'))
        app.jobs[job].update(state='launched', recovery_required=False, events=[{'message': 'x', 'exit_code': 'not written'}])
        self.assertTrue(self.ops.call('it_job_status', {'job_id': job})['outcome'].startswith('unknown'))
        self.assertIn('ping only', self.ops.call('computer_action', {'computer': 'TESTPC', 'action': 'reboot'})['message'])
        # Atlas holds a PC whose installer left no exit code (backend/main.py); Axis then refuses it.
        self.reboots.rows.clear()
        app.jobs[job]['recovery_required'] = True; app.job_service.unresolved.add('TESTPC')
        with self.assertRaisesRegex(ValueError, 'unknown outcome'):
            self.deploy()

    def test_saved_tool_output_is_pruned_after_thirty_days(self):
        outputs = Path(self.tmp.name) / 'outputs'
        outputs.mkdir()
        old, new = outputs / ('a' * 32 + '.txt'), outputs / ('b' * 32 + '.txt')
        old.write_text('private inbox text'); new.write_text('recent')
        stale = time.time() - it_tools.OUTPUT_SECONDS - 60
        os.utime(old, (stale, stale))
        AtlasOperations(app, self.confirm, outputs=outputs).prune()
        self.assertEqual(sorted(p.name for p in outputs.iterdir()), [new.name])

    def test_bundled_skills_describe_the_operations_axis_runs_in_aa(self):
        from axis.skill_library import SkillLibrary
        skills, errors = SkillLibrary().scan()
        self.assertEqual(errors, [])
        deployment = skills['package-deployment'].body
        self.assertIn('At most %d explicit PCs' % MAX_TARGETS, deployment)
        for old in ('script_succeeded', 'processed in order', '200'):
            self.assertNotIn(old, deployment)
        for tool in TOOLS_OPENED:
            self.assertIn('`%s`' % tool, skills['pc-health'].body)
        self.assertIn('ping only', skills['job-recovery'].body)

    def test_the_agent_runs_these_operations_in_place_of_its_own_engine(self):
        ui = MagicMock(); ui.confirm.return_value = True
        root = Path(self.tmp.name)
        with patch.object(axis_agent, 'system_facts', return_value=('Test PC', False)):
            agent = axis_agent.Agent('http://127.0.0.1:8080/v1', 'fixture', str(root), False, False, notes=str(root / 'notes'),
                                     state_dir=str(root / 'state'), ui=ui, web_enabled=False,
                                     operations=lambda confirm: AtlasOperations(app, confirm))
        names = [t['function']['name'] for t in agent.tools]
        self.assertEqual(names.count('deploy_package'), 1)
        self.assertIn('Atlas', next(t for t in agent.tools if t['function']['name'] == 'deploy_package')['function']['description'])
        system = agent.messages[0]['content']
        self.assertIn("run Atlas's own operations", system)
        self.assertNotIn('They work without Atlas running', system)
        self.assertIn(str(app.REPO), system)
        reply = json.loads(agent.call_tool('deploy_package', {'computers': ['TESTPC'], 'package': 'Example App',
                                                              'script': 'setup_i.ps1', 'action': 'Install'}))
        self.assertEqual(reply['jobs'][0]['state'], 'queued')
        self.assertIn('Atlas deployment', ui.confirm.call_args[0][0])
        self.assertFalse((root / 'state' / 'jobs').exists(), 'No Axis job files inside AA')


if __name__ == '__main__':
    unittest.main()
