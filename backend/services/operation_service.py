"""One admission, locking and durable-outcome policy for Admin and Axis changes."""
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException

from backend.services.job_service import TERMINAL
from backend.services.target_identity import same_target


@dataclass(frozen=True)
class OperationContext:
    """Only the dependencies required by mutation policy; no FastAPI/module access."""
    store: Callable
    reboots: Callable
    target_lock: Callable

    @property
    def job_service(self):return self.store()
    @property
    def jobs(self):return self.store().jobs
    @property
    def queue_jobs(self):return self.store().queues
    @property
    def lock(self):return self.store().lock
    @property
    def reboot_monitor(self):return self.reboots()


class OperationService:
    def __init__(self, backend):
        self.backend = backend

    def ready(self, pc):
        backend = self.backend
        backend.job_service.target_ready(pc)
        with backend.lock:
            pools = [dict(backend.jobs), dict(getattr(backend, 'queue_jobs', {}))]
        for pool in pools:
            for key, job in pool.items():
                names = [job.get('target')] + list(job.get('targets') or [])
                names += [r.get('target') or r.get('machine') for r in job.get('items', job.get('results', []))]
                if job.get('state') not in TERMINAL and any(same_target(pc, name) for name in names):
                    raise HTTPException(409, f'Atlas is working on {pc} ({key}); wait for it to finish.')
        self.no_reboot(pc)

    def no_reboot(self, pc):
        for row in self.backend.reboot_monitor.snapshot()['reboots']:
            if row.get('state') in ('requesting', 'waiting_offline', 'waiting_online') and same_target(pc, row.get('target')):
                raise HTTPException(409, f'{pc} is rebooting; wait for its monitor to finish.')

    @contextmanager
    def held(self, pc):
        guard = self.backend.target_lock(pc)
        if not guard.acquire(blocking=False):
            raise HTTPException(409, f'Another Atlas operation is active on {pc}; wait for it to finish.')
        try:
            self.ready(pc)
            yield
        finally:
            guard.release()

    def change(self, pc, action, dispatch):
        """Journal before dispatch; a missing/uncertain response is never retryable."""
        backend = self.backend
        with self.held(pc):
            key = uuid.uuid4().hex
            row = dict(id=key, kind='mutation', target=pc, action_title=action,
                       state='running', started_at=time.time(), events=[{'message': action}])
            with backend.lock:
                backend.jobs[key] = row
                backend.job_service.save(key)
            try:
                result = dispatch()
            except BaseException as error:
                known_rejection = isinstance(error, HTTPException) and 400 <= error.status_code < 500
                row.update(state='failed' if known_rejection else 'unknown', recovery_required=not known_rejection)
                row['events'].append({'message': str(getattr(error, 'detail', error))})
                backend.job_service.save(key)
                raise
            uncertain = isinstance(result, dict) and (result.get('outcome') in ('pending', 'unknown') or
                any(r.get('state') in ('pending', 'unknown') for r in result.get('items', []) if isinstance(r, dict)))
            row.update(state='unknown' if uncertain else 'complete', recovery_required=uncertain)
            row['events'].append({'message': 'Inspect the target and acknowledge recovery before another change.' if uncertain else 'Change returned a verified response.'})
            backend.job_service.save(key)
            return result

    def reboot(self, pc):
        with self.held(pc):
            return self.backend.reboot_monitor.start(pc)
