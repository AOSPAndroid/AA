"""Pause/cancel and the next queue item have one consistent transition boundary."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend import main
from job_service import JobService


class QueueBoundaries(unittest.TestCase):
    def test_accepted_pause_or_cancel_cannot_start_a_still_waiting_item(self):
        for action in ('pause', 'cancel'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                service = JobService(lambda: Path(tmp) / 'operations.db')
                stack.callback(service.pool.shutdown)
                stack.enter_context(patch.multiple(main, job_service=service, jobs=service.jobs,
                                                  queue_jobs=service.queues, lock=service.lock))
                boundary, attempted, accepted = threading.Event(), threading.Event(), threading.Event()
                claim_states, executions, errors = [], [], []

                class BoundaryQueue(dict):
                    blocked = False
                    def get(self, key, default=None):
                        value = super().get(key, default)
                        if key == 'pause_requested' and not self.blocked:
                            self.blocked = True
                            boundary.set()
                            if not attempted.wait(2):
                                raise AssertionError('Control request did not reach boundary')
                            # Unlocked implementations accept while this item is still waiting.
                            accepted.wait(.1)
                        return value

                items = [main.QueueItem(computer='FICT-PC', folder='Fixture', script='setup_i.ps1') for _ in range(2)]
                service.queues['fixture'] = BoundaryQueue(id='fixture', state='queued', items=[
                    {'target':item.computer, 'state':'waiting', 'events':[], 'payload':item.model_dump()}
                    for item in items
                ])

                def control():
                    try:
                        if not boundary.wait(2):
                            raise AssertionError('Worker did not reach boundary')
                        attempted.set()
                        with service.lock:
                            getattr(main, action + '_queue')('fixture')
                            claim_states.extend(row['state'] for row in service.queues['fixture']['items'])
                            accepted.set()
                    except BaseException as error:
                        errors.append(error)
                        accepted.set()

                def history(*args):
                    if not accepted.wait(2):
                        raise AssertionError('Control request remained blocked after claim')

                def complete(job, item):
                    executions.append(item)
                    service.jobs[job].update(state='complete', events=[])

                stack.enter_context(patch.object(main, 'history_create', history))
                stack.enter_context(patch.object(main, 'deploy_worker', complete))
                thread = threading.Thread(target=control, daemon=True)
                thread.start()
                main._queue_worker('fixture', items)
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(executions), sum(state != 'waiting' for state in claim_states))
                self.assertLessEqual(len(executions), 1)
                self.assertEqual(service.queues['fixture']['state'], 'paused' if action == 'pause' else 'cancelled')
                self.assertEqual(service.queues['fixture']['items'][1]['state'], 'waiting' if action == 'pause' else 'cancelled')


if __name__ == '__main__':
    unittest.main()
