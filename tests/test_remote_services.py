"""Service control uses simulated transport/providers; no live service is stopped."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from backend.remote import service_actions as services


class RemoteServices(unittest.TestCase):
    def setUp(self):
        self.wmi = SimpleNamespace(
            validate_pc=lambda pc: pc.upper(), quote=lambda value: "'" + str(value).replace("'", "''") + "'",
            ps=Mock(return_value=json.dumps({'ok': True, 'computer': 'TESTPC', 'items': []})), identity=lambda: 'TEST OPERATOR',
        )
        self.audit = self.enterContext(patch.object(services.logging, 'warning'))
        self.errors = self.enterContext(patch.object(services.logging, 'exception'))

    def request(self, **changes):
        return SimpleNamespace(**dict(dict(computer='testpc', name='TestService', expected_identity='a' * 64), **changes))

    def result(self, outcome, state='Running', name='TestService', computer='TESTPC', identity='a' * 64, **changes):
        item = None if outcome == 'gone' else {
            'name': name, 'display_name': 'Display ' + name, 'state': state, 'start_mode': 'Auto',
            'pid': 0 if state == 'Stopped' else 1234, 'identity': identity,
            'can_stop': state in ('Running', 'Paused'), 'stop_reason': '' if state in ('Running', 'Paused') else 'Not running',
            'can_start': state == 'Stopped', 'start_reason': '' if state == 'Stopped' else 'Not stopped',
            'can_restart': state in ('Running', 'Paused'), 'restart_reason': '' if state in ('Running', 'Paused') else 'Not running',
        }
        return dict({'ok': True, 'computer': computer, 'name': name, 'outcome': outcome,
                     'state': '' if outcome == 'gone' else state, 'item': item}, **changes)

    def test_inventory_is_explicit_targeted_and_bounded(self):
        self.assertEqual(services.list_services(self.wmi, 'testpc')['items'], [])
        command = self.wmi.ps.call_args
        self.assertIn("-Computer 'TESTPC' -Action 'list'", command.args[0])
        self.assertEqual(command.kwargs['timeout'], 60)

    def test_stop_passes_exact_name_and_identity_without_shell_interpolation(self):
        name = "Test's $(Get-Process) `service"
        for action, outcome, state in [('stop', 'stopped', 'Stopped'), ('start', 'started', 'Running'), ('restart', 'restarted', 'Running')]:
            with self.subTest(action=action):
                self.wmi.ps.return_value = json.dumps(self.result(outcome, state, name))
                result = getattr(services, action + '_service')(self.wmi, self.request(name=name))
                self.assertEqual(result['outcome'], outcome)
                self.assertIn("-Action '" + action + "'", self.wmi.ps.call_args.args[0])
                self.assertIn("-Name 'Test''s $(Get-Process) `service'", self.wmi.ps.call_args.args[0])
                self.assertIn("-ExpectedIdentity '" + 'a' * 64 + "'", self.wmi.ps.call_args.args[0])
                self.assertEqual(self.wmi.ps.call_args.kwargs['timeout'], 60)
                audit = self.audit.call_args.args
                self.assertEqual(audit[1:4], (action, 'TESTPC', name))
                self.assertEqual(audit[-1], 'TEST OPERATOR')

    def test_invalid_identity_or_name_never_calls_windows(self):
        for action in ('stop', 'start', 'restart'):
            for changes in [dict(name=''), dict(name='a' * 257), dict(name='Test\nService'), dict(name=None),
                            dict(expected_identity=''), dict(expected_identity='*'), dict(expected_identity='A' * 64), dict(expected_identity=None)]:
                with self.subTest(action=action, changes=changes), self.assertRaises(HTTPException) as error:
                    getattr(services, action + '_service')(self.wmi, self.request(**changes))
                self.assertEqual(error.exception.status_code, 400)
        self.wmi.ps.assert_not_called()

    def test_wrong_target_and_unverified_success_are_rejected(self):
        for action, outcome, state in [('stop', 'stopped', 'Stopped'), ('start', 'started', 'Running'), ('restart', 'restarted', 'Running')]:
            baseline = self.result(outcome, state)
            for changes in [dict(computer='OTHER'), dict(name='OtherService'), dict(state='Stop Pending'), dict(outcome='unknown'), dict(item=None)]:
                self.wmi.ps.return_value = json.dumps(dict(baseline, **changes))
                with self.subTest(action=action, changes=changes), self.assertRaises(HTTPException) as error:
                    getattr(services, action + '_service')(self.wmi, self.request())
                self.assertEqual(error.exception.status_code, 502)
            for changes in [dict(name='OtherService'), dict(identity='b' * 64), dict(state='Stop Pending'),
                            dict(state=[]), dict(pid=-1), dict(pid=True), dict(can_start='true'), dict(start_reason=None)]:
                self.wmi.ps.return_value = json.dumps(dict(baseline, item=dict(baseline['item'], **changes)))
                with self.subTest(action=action, snapshot=changes), self.assertRaises(HTTPException) as error:
                    getattr(services, action + '_service')(self.wmi, self.request())
                self.assertEqual(error.exception.status_code, 502)

    def test_pending_and_failure_are_not_reported_as_stopped(self):
        for outcome in ['pending', 'failed', 'blocked', 'gone', 'changed', 'already_stopped']:
            self.wmi.ps.return_value = json.dumps(self.result(outcome, 'Stopped' if outcome == 'already_stopped' else 'Running'))
            self.assertEqual(services.stop_service(self.wmi, self.request())['outcome'], outcome)
        self.wmi.ps.side_effect = subprocess.TimeoutExpired('simulated', 60)
        with self.assertRaises(HTTPException) as error: services.stop_service(self.wmi, self.request())
        self.assertIn('outcome may be unknown', error.exception.detail)

    def test_start_restart_truthful_outcomes_return_fresh_snapshot_without_retries(self):
        for action, outcomes in [('start', ['started', 'already_running', 'pending', 'failed', 'blocked', 'changed', 'gone']),
                                 ('restart', ['restarted', 'pending', 'failed', 'blocked', 'changed', 'gone'])]:
            for outcome in outcomes:
                state = 'Running' if outcome in ('started', 'already_running', 'restarted') else 'Stopped' if outcome == 'failed' else 'Start Pending'
                baseline = self.result(outcome, state, identity='b' * 64 if outcome == 'changed' else 'a' * 64, phase='start')
                self.wmi.ps.return_value = json.dumps(baseline)
                before = self.wmi.ps.call_count
                with self.subTest(action=action, outcome=outcome):
                    observed = getattr(services, action + '_service')(self.wmi, self.request())
                    self.assertEqual(observed, baseline)
                    self.assertEqual(self.wmi.ps.call_count, before + 1, 'No service outcome triggers an automatic retry')
                    if outcome == 'failed':
                        self.assertEqual(observed['item']['state'], 'Stopped')
                        self.assertTrue(observed['item']['can_start'])
            self.wmi.ps.side_effect = subprocess.TimeoutExpired('simulated', 60)
            with self.assertRaises(HTTPException) as error:
                getattr(services, action + '_service')(self.wmi, self.request())
            self.assertIn(action + ' outcome may be unknown', error.exception.detail)
            if action == 'restart':
                self.assertIn('may be stopped', error.exception.detail)
            self.wmi.ps.side_effect = None

    def test_concurrent_controls_for_same_target_service_conflict_without_blocking_or_interleaving(self):
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []
        def transport(command, timeout):
            if "-Name 'OtherService'" in command:
                return json.dumps(self.result('started', name='OtherService'))
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture control was not released')
            return json.dumps(self.result('restarted'))
        self.wmi.ps.side_effect = transport
        def worker():
            try:
                results.append(services.restart_service(self.wmi, self.request()))
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            for action in ('start', 'stop', 'restart'):
                with self.subTest(action=action), self.assertRaises(HTTPException) as error:
                    getattr(services, action + '_service')(self.wmi, self.request(computer='TESTPC', name='testservice'))
                self.assertEqual(error.exception.status_code, 409)
                self.assertIn('Refresh services', error.exception.detail)
            self.assertEqual(self.wmi.ps.call_count, 1)
            self.assertEqual(services.start_service(self.wmi, self.request(name='OtherService'))['outcome'], 'started', 'Unrelated services remain independent')
            self.assertEqual(self.wmi.ps.call_count, 2)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0]['outcome'], 'restarted')
        self.wmi.ps.side_effect = None
        self.wmi.ps.return_value = json.dumps(self.result('stopped', 'Stopped'))
        self.assertEqual(services.stop_service(self.wmi, self.request())['outcome'], 'stopped', 'The service lock is released after the action completes')

    def test_failed_transport_releases_service_lock_and_logs_exact_operation(self):
        self.wmi.ps.side_effect = subprocess.TimeoutExpired('simulated', 60)
        with self.assertRaises(HTTPException):
            services.restart_service(self.wmi, self.request())
        self.assertEqual(self.errors.call_args.args[1:], ('restart', 'TESTPC', 'TestService', 'TEST OPERATOR'))
        self.wmi.ps.side_effect = None
        self.wmi.ps.return_value = json.dumps(self.result('started'))
        self.assertEqual(services.start_service(self.wmi, self.request())['outcome'], 'started')

    @unittest.skipUnless(os.name == 'nt' or shutil.which('pwsh'), 'PowerShell is unavailable')
    def test_windows_service_provider_fixture(self):
        executable = 'powershell.exe' if os.name == 'nt' else shutil.which('pwsh')
        result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(Path(__file__).with_name('remote_services_fixture.ps1'))], capture_output=True, text=True, errors='replace', timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS:', result.stdout)


if __name__ == '__main__': unittest.main()
