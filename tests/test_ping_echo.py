"""IPv4 reachability checks use simulated Windows output; no host is contacted."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

from backend import main
from backend.remote.machine_health import HealthChecks
from backend.deploy.reboot_monitor import has_echo_reply, ping_once


class PingEchoTests(unittest.TestCase):
    def test_echo_reply_requires_success_and_numeric_ttl(self):
        cases = [
            (0, 'Reply from 192.0.2.1: Destination host unreachable.', False),
            (0, 'Request timed out.', False),
            (0, '', False),
            (0, None, False),
            (0, 'Reply from 192.0.2.10: bytes=32 time<1ms TTL=128', True),
            (0, 'Reply from 192.0.2.10: bytes=32 time=4ms ttl = 64', True),
            (1, 'Reply from 192.0.2.10: bytes=32 time<1ms TTL=128', False),
            (0, 'TTL=not-a-reply', False),
        ]
        for code, output, expected in cases:
            with self.subTest(code=code, output=output):
                self.assertIs(has_echo_reply(CompletedProcess([], code, output)), expected)

    def test_api_preflight_health_and_reboot_agree_on_unreachable_output(self):
        for output, expected in [
            ('Reply from 192.0.2.1: Destination host unreachable.', False),
            ('Reply from 192.0.2.10: bytes=32 time<1ms TTL=128', True),
        ]:
            with self.subTest(output=output):
                completed = CompletedProcess([], 0, output)
                transport = Mock()
                transport.validate_pc.return_value = 'FICT-PC'
                transport.run.return_value = completed
                with patch.object(main, 'validate_pc', return_value='FICT-PC'), \
                     patch.object(main, 'run', return_value=completed) as run, \
                     patch.object(main.os.path, 'isdir', return_value=False), \
                     patch.object(main, 'ps', return_value='false'), \
                     patch('backend.deploy.reboot_monitor.subprocess.run', return_value=completed) as reboot_ping:
                    self.assertIs(main.ping('FICT-PC')['online'], expected)
                    self.assertIs(main.preflight('FICT-PC')['ping'], expected)
                    health = HealthChecks(transport).check('FICT-PC', 'ping')
                    self.assertEqual(health['state'], 'ready')
                    self.assertIs(health['data']['available'], expected)
                    self.assertIs(ping_once('FICT-PC')[0], expected)
                    for call in [*run.call_args_list, transport.run.call_args, reboot_ping.call_args]:
                        self.assertIn('-4', call.args[0])
                        self.assertLessEqual(call.kwargs['timeout'], 5)


if __name__ == '__main__':
    unittest.main()
