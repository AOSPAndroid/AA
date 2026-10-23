import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import inbox_control as control
from inbox_agent import Agent
import outlook_watcher as outlook


class InboxControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = self.root / 'mail'
        self.commands = self.root / 'commands'
        for folder in (self.queue, self.commands, self.root / 'data'):
            folder.mkdir()
        self.config = dict(version=1, directory=str(self.queue), control_directory=str(self.commands),
                           mail_user='DOMAIN\\Mail', mail_sid='S-1-5-21-1-2-3-1234', atlas_user='DOMAIN\\Atlas',
                           task_name='Atlas-Inbox-0123456789abcdef', python='C:\\Python312\\python.exe')
        self.integration = control.InboxIntegration(self.root)
        outlook.write_json(self.integration.path, self.config)
        self.ps = patch.object(control, 'powershell', return_value='requested').start()
        self.addCleanup(patch.stopall)

    def test_start_and_stop_only_write_control_folder(self):
        sentinel = self.queue / 'inbox.sqlite3'
        sentinel.write_bytes(b'Existing inbox data')
        before = {path.name: path.read_bytes() for path in self.queue.iterdir()}
        first = self.integration.command('start')
        second = self.integration.command('start')
        self.assertTrue(first['desired']['running'])
        self.assertNotEqual(first['desired']['revision'], second['desired']['revision'])
        self.assertEqual(self.ps.call_args.args, (self.root / 'Invoke-Inbox-Task.ps1', '-Configuration', self.integration.path))
        stopped = self.integration.command('stop')
        self.assertFalse(stopped['desired']['running'])
        self.assertEqual(self.ps.call_count, 2, 'Stop is cooperative and never kills a user process')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.queue.iterdir()})

    def test_source_preferences_survive_restart_and_show_does_not_enable_capture(self):
        self.integration.command('preferences', outlook=False, notifications=False, outlook_previews=True)
        result = self.integration.command('show')
        self.assertFalse(result['desired']['notifications'])
        self.assertTrue(result['desired']['show_window'])
        self.integration.command('stop')
        result = control.InboxIntegration(self.root).command('start')
        self.assertFalse(result['desired']['outlook'])
        self.assertTrue(result['desired']['outlook_previews'])

    def test_switches_start_only_chosen_source_and_stop_last_source(self):
        result = self.integration.command('source', outlook=True)
        self.assertTrue(result['desired']['running'])
        self.assertTrue(result['desired']['outlook'])
        self.assertFalse(result['desired']['notifications'])
        self.integration.command('source', notifications=True)
        result = self.integration.command('source', outlook=False)
        self.assertTrue(result['desired']['running'])
        self.assertTrue(result['desired']['notifications'])
        result = self.integration.command('source', notifications=False)
        self.assertFalse(result['desired']['running'])
        result = control.InboxIntegration(self.root).command('start')
        self.assertFalse(result['desired']['outlook'])
        self.assertFalse(result['desired']['notifications'])

    def test_switch_does_not_resume_other_source_after_master_stop(self):
        self.integration.command('start')
        self.integration.command('stop')
        result = self.integration.command('source', notifications=True)
        self.assertTrue(result['desired']['notifications'])
        self.assertFalse(result['desired']['outlook'])
        for values in ({}, {'outlook': True, 'notifications': True}, {'outlook_previews': True}, {'outlook': 'yes'}):
            with self.assertRaises(control.IntegrationError):
                self.integration.command('source', **values)

    def test_failure_is_actionable_and_retry_retains_preferences(self):
        self.ps.side_effect = control.IntegrationError('Mail user is not signed in')
        with self.assertRaisesRegex(control.IntegrationError, 'not signed in'):
            self.integration.command('start')
        self.assertTrue(self.integration.status()['desired']['running'])
        self.assertFalse(self.integration.status()['agent_running'])

    def test_stop_can_recover_collectors_after_supervisor_failure(self):
        with patch.object(control, 'is_running', side_effect=lambda path, filename: filename == 'notifications.lock'):
            result = self.integration.command('stop')
        self.ps.assert_called_once()
        self.assertFalse(result['desired']['running'])

    def test_launcher_does_not_report_success_while_a_collector_holds_its_lock(self):
        with patch.object(control, 'InboxIntegration', return_value=self.integration), \
             patch.object(self.integration, 'command', return_value={}), \
             patch.object(control, 'is_running', return_value=True), patch.object(control.time, 'sleep'):
            self.assertFalse(control.launcher_action('stop'))

    def test_alive_agent_does_not_hide_stale_heartbeat(self):
        outlook.write_json(self.queue / 'agent-status.json', dict(heartbeat=time.time() - 200, state='running'))
        with patch.object(control, 'is_running', return_value=True):
            self.assertEqual(self.integration.status()['state'], 'unresponsive')
        (self.integration.path).write_text('{broken')
        self.assertEqual(self.integration.status()['state'], 'error')

    def test_api_rejects_arbitrary_operations_and_bad_input(self):
        app = FastAPI()
        control.register(app, self.integration, token_getter=lambda: 'test-session')
        with TestClient(app, headers={'X-Atlas-Token': 'test-session'}) as client:
            for body in ({'action': 'shell'}, {'action': 'start', 'command': 'whoami'},
                         {'action': 'preferences', 'outlook': 'yes'}):
                self.assertEqual(client.post('/api/inbox/control', json=body).status_code, 422)
            self.assertEqual(client.post('/api/inbox/control/setup', json={'mail_user': 'user\ncommand'}).status_code, 422)
            self.assertEqual(client.post('/api/inbox/control', json={'action': 'start'}).status_code, 200)
            self.ps.reset_mock()
            self.assertEqual(client.post('/api/inbox/control', json={'action': 'start'}, headers={'X-Atlas-Token': 'wrong'}).status_code, 403)
            self.ps.assert_not_called()

    def test_setup_accepts_pasted_paths_in_quotes(self):
        # Windows "Copy as path" adds quotes; pasted values often carry spaces.
        app = FastAPI()
        control.register(app, self.integration, token_getter=lambda: 'test-session')
        with patch.object(self.integration, 'configure', return_value={'configured': True}) as configure, \
                TestClient(app, headers={'X-Atlas-Token': 'test-session'}) as client:
            response = client.post('/api/inbox/control/setup', json={'mail_user': ' INTRANET\\x01426046 ',
                                   'python': '"C:\\devhome\\tools\\python3.12\\current\\python.exe"'})
            self.assertEqual(response.status_code, 200, response.text)
            configure.assert_called_once_with('INTRANET\\x01426046', 'C:\\devhome\\tools\\python3.12\\current\\python.exe')
            configure.reset_mock()
            self.assertEqual(client.post('/api/inbox/control/setup', json={'mail_user': 'INTRANET\\x01426046', 'python': '  '}).status_code, 200)
            configure.assert_called_once_with('INTRANET\\x01426046', None)
            self.assertEqual(client.post('/api/inbox/control/setup', json={'mail_user': 'user', 'python': 'C:\\a"b.exe'}).status_code, 422,
                             'A quote inside the path is still refused')

    def test_two_atlas_processes_cannot_overwrite_each_others_preferences(self):
        with outlook.process_lock(self.commands, 'control.lock'):
            with self.assertRaisesRegex(control.IntegrationError, 'Another Atlas window'):
                self.integration.command('preferences', outlook=False)

    def test_backend_uses_saved_bridge_without_environment_variables(self):
        from mail_inbox import mail_directory
        with patch.object(control, 'InboxIntegration', return_value=self.integration), patch.dict('os.environ', {'ATLAS_MAIL_DIR': str(self.root / 'wrong')}):
            self.assertEqual(mail_directory(), self.queue.resolve())

    def test_all_local_launch_paths_share_lifecycle_hook(self):
        import launcher
        with patch.object(launcher, 'ROOT', self.root), patch.object(launcher, 'start_server'), \
             patch.object(launcher, 'running', return_value=True), patch.object(launcher, 'read_record', return_value={}), \
             patch.object(control, 'launcher_action') as lifecycle:
            self.assertEqual(launcher.run(False), 0)
            lifecycle.assert_called_once_with('start')
            lifecycle.reset_mock()
            self.assertEqual(launcher.stop(), 0)
            lifecycle.assert_called_once_with('stop')


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name)
        self.agent = Agent({'directory': str(self.queue), 'control_directory': str(self.queue)})
        self.desired = dict(running=True, outlook=True, notifications=True, outlook_previews=False, revision='a')
        self.alive = {'watcher.lock': False, 'notifications.lock': False}
        self.running = patch.object(outlook, 'is_running', side_effect=lambda path, filename='watcher.lock': self.alive[filename]).start()
        self.mail = patch.object(outlook, 'start').start()
        self.notifications = patch.object(self.agent, 'start_notifications').start()
        self.addCleanup(patch.stopall)

    def test_missing_outlook_dependency_does_not_stop_teams_and_retries_are_bounded(self):
        self.mail.side_effect = ValueError('Install pywin32')
        self.agent.reconcile(self.desired)
        self.assertIn('pywin32', self.agent.errors['outlook'])
        self.notifications.assert_called_once_with(False)
        self.agent.reconcile(self.desired)
        self.assertEqual(self.mail.call_count, 1)
        self.assertEqual(self.notifications.call_count, 1)

    def test_running_collectors_are_adopted_and_start_resumes_paused_listener(self):
        self.alive.update({'watcher.lock': True, 'notifications.lock': True})
        self.agent.reconcile(self.desired)
        initial = outlook.read_json(self.queue / 'notifications-command.json')
        self.agent.reconcile(dict(self.desired, revision='b'))
        later = outlook.read_json(self.queue / 'notifications-command.json')
        self.assertEqual(later['operation'], 'start')
        self.assertNotEqual(initial['id'], later['id'])
        self.mail.assert_not_called()
        self.notifications.assert_not_called()

    def test_stop_targets_run_token_and_waits_for_locks(self):
        self.alive.update({'watcher.lock': True, 'notifications.lock': True})
        with patch.object(outlook, 'status', return_value={'running': True, 'run_id': 'owned-run'}):
            self.assertFalse(self.agent.reconcile(dict(self.desired, running=False)))
        self.assertEqual(outlook.read_json(self.queue / 'stop.json'), {'run_id': 'owned-run'})
        self.assertEqual(outlook.read_json(self.queue / 'notifications-command.json')['operation'], 'exit')
        self.alive.update({'watcher.lock': False, 'notifications.lock': False})
        self.assertTrue(self.agent.reconcile(dict(self.desired, running=False)))

    def test_settings_window_can_open_without_capturing_notifications(self):
        self.agent.reconcile(dict(self.desired, notifications=False, show_window='open-settings'))
        self.notifications.assert_called_once_with(True)
        self.assertEqual(outlook.read_json(self.queue / 'notifications-command.json')['operation'], 'pause_show')

    def test_invalid_preferences_cannot_be_used_as_commands(self):
        outlook.write_json(self.queue / 'desired.json', dict(self.desired, outlook='execute'))
        with self.assertRaises(ValueError):
            self.agent.desired()


class InboxSetupScript(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'), 'PowerShell is unavailable')
    def test_python_reached_through_links_is_saved_as_its_real_path(self):
        shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        script = Path(__file__).with_name('test_inbox_link_paths.ps1')
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
