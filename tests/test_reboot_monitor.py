"""All reboot and ping activity is mocked; never contacts a machine."""
import threading
import unittest
from unittest.mock import Mock, patch
from fastapi import HTTPException
from reboot_monitor import RebootMonitor, ping_once


class RebootTests(unittest.TestCase):
    def run_watch(self, sequence, reboot=None):
        manager = RebootMonitor(reboot or Mock(), ping=Mock(side_effect=[(x, 'reply' if x else 'timeout') for x in sequence]), interval=0)
        manager.rows['job'] = dict(id='job', target='TESTPC', state='requesting', events=[])
        manager.stops['job'] = threading.Event()
        manager._run('job')
        return manager

    def test_requires_offline_then_stable_replies(self):
        manager = self.run_watch([True, True, False, True, False, False, True, False, True, True])
        self.assertEqual(manager.rows['job']['state'], 'complete')
        self.assertEqual(manager.ping.call_count, 10)
        manager.reboot.assert_called_once_with('TESTPC')

    def test_no_offline_transition_is_not_success(self):
        ticks = iter([0, 1, 2, 100])
        manager = RebootMonitor(Mock(), ping=Mock(return_value=(True, 'reply')), timeout=10, interval=0, clock=lambda:next(ticks))
        manager.rows['job'] = dict(target='TESTPC', state='requesting', events=[])
        manager.stops['job'] = threading.Event()
        # Separate terminal clock read after deadline.
        with patch.object(manager, '_event', wraps=manager._event):
            manager.clock = Mock(side_effect=[0,1,2,100,101])
            manager._run('job')
        self.assertEqual(manager.rows['job']['state'], 'timeout')
        self.assertIn('No offline transition', manager.rows['job']['message'])

    def test_start_failure_never_pings(self):
        manager = self.run_watch([], Mock(side_effect=RuntimeError('Access denied')))
        self.assertEqual(manager.rows['job']['state'], 'failed')
        manager.ping.assert_not_called()

    def test_stop_ends_watch_without_reboot_retry(self):
        manager = RebootMonitor(Mock(), interval=0)
        manager.rows['job'] = dict(target='TESTPC', state='requesting', events=[])
        manager.stops['job'] = threading.Event()
        def ping(pc):
            manager.stop('job')
            return False, 'timeout'
        manager.ping = Mock(side_effect=ping)
        manager._run('job')
        self.assertEqual(manager.rows['job']['state'], 'cancelled')
        manager.reboot.assert_called_once()
        manager.ping.assert_called_once()

    def test_completed_watch_expires(self):
        manager = self.run_watch([False, False, True, True])
        manager.clock = lambda:manager.rows['job']['finished'] + 11
        self.assertEqual(manager.snapshot()['reboots'], [])

    def test_duplicate_target_rejected_and_shutdown_signals_watch(self):
        manager = RebootMonitor(Mock())
        with patch('reboot_monitor.threading.Thread'):
            manager.start('TESTPC')
            with self.assertRaises(HTTPException) as error: manager.start('TESTPC')
            self.assertEqual(error.exception.status_code,409)
        manager.shutdown()
        self.assertTrue(all(s.is_set() for s in manager.stops.values()))

    def test_unreachable_zero_exit_code_is_not_reply(self):
        with patch('reboot_monitor.subprocess.run', return_value=Mock(returncode=0, stdout='Reply from gateway: Destination host unreachable.')):
            self.assertFalse(ping_once('TESTPC')[0])
        with patch('reboot_monitor.subprocess.run', return_value=Mock(returncode=0, stdout='Reply from 1.2.3.4: bytes=32 time<1ms TTL=128')):
            self.assertTrue(ping_once('TESTPC')[0])


if __name__ == '__main__': unittest.main()
