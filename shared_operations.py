"""Atlas operations and Axis jobs share one per-PC lock and one unknown-outcome guard.

Axis workers keep their durable job files under data/axis/state; Atlas reads them,
and Axis reads Atlas's operation_guard table, so neither app starts work on a PC
that the other is changing or left with an unresolved outcome.
"""
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from axis import it_tools

# AA_AXIS_STATE lets tests use a disposable folder, as ATLAS_DB_PATH does for the database.
AXIS_STATE = Path(os.environ.get('AA_AXIS_STATE') or Path(__file__).resolve().parent / 'data' / 'axis' / 'state')
# Jobs an earlier Axis terminal left in its own folder keep guarding their PCs until acknowledged.
TERMINAL_STATE = Path(os.environ.get('AA_AXIS_TERMINAL_STATE') or Path(__file__).resolve().parent / 'axis' / 'state')
_cache, _cache_lock = {}, threading.Lock()


class TargetLock:
    """Non-blocking per-PC lock that also excludes Axis workers. Another thread may release it."""
    def __init__(self, pc):
        self.pc = pc
        self.local = threading.Lock()
        self.held = None

    def acquire(self, blocking=False):
        if blocking:
            raise ValueError('Target locks are never waited on')
        if not self.local.acquire(blocking=False):
            return False
        held = it_tools.target_lock(AXIS_STATE, self.pc)
        try:
            held.__enter__()
        except RuntimeError:
            self.local.release()
            return False
        except ValueError:
            held = None  # Axis cannot address this name, so only Atlas can use it.
        except BaseException:
            self.local.release()
            raise
        self.held = held
        return True

    def release(self):
        held, self.held = self.held, None
        try:
            if held is not None:
                held.__exit__(None, None, None)
        finally:
            self.local.release()


def axis_ready(pc):
    """Atlas's target check: refuse a PC with an active or unresolved Axis job."""
    for folder in (AXIS_STATE, TERMINAL_STATE):
        job = it_tools.ITTools(folder).blocking_job(pc)
        if job:
            raise HTTPException(409, f"{pc} has an active or unresolved Axis job {job['id']}. "
                                     f"Check it with /jobs {job['id']} in Axis chat before starting Atlas work.")


def _jobs():
    """(modified time, job) per Axis job file; a file is parsed again only after a worker replaces it."""
    folder = AXIS_STATE / 'jobs'
    with _cache_lock:
        current = {}
        for path in folder.glob('*.json') if folder.is_dir() else ():
            try:
                info = path.stat()
                signature = (info.st_mtime_ns, info.st_size)
                cached = _cache.get(path)
                current[path] = cached if cached and cached[0] == signature else (signature, info.st_mtime, it_tools.read_json(path))
            except (OSError, ValueError):
                continue  # Being replaced right now; the next poll reads it.
        _cache.clear()
        _cache.update(current)
        return [(updated, job) for _, updated, job in current.values()]


def _state(job):
    """A queued or running job whose worker is gone has an unknown outcome. Reads only."""
    state = job.get('state', 'unknown')
    if (state in it_tools.ACTIVE and time.time() - job.get('created_epoch', 0) > 20
            and not it_tools.process_alive(job.get('worker_pid'))):
        return 'unknown'
    return state


def axis_busy():
    """True while an Axis worker runs; directory imports wait for it like Atlas jobs."""
    return any(_state(job) in it_tools.ACTIVE for _, job in _jobs())


def axis_activity():
    """Axis deployments and reboots as rows for Atlas's activity feed. Reads only."""
    rows = []
    for updated, job in _jobs():
        events = job.get('events', [])
        state, message = _state(job), job.get('error')
        if state == 'unknown' and job.get('state') in it_tools.ACTIVE:
            message = 'Axis worker stopped without a final result. Inspect the PC before retrying.'
        if not message:
            message = (events[-1].get('computer', '') + ': ' + events[-1].get('message', '')) if events else 'Queued'
        title = 'Axis · Reboot' if job.get('kind') == 'reboot' else f"Axis · {job.get('action', 'Deploy')} · {job.get('package', '')}"
        rows.append(dict(id='axis-' + job['id'], title=title, target=', '.join(job.get('computers', [])),
                         state=state, started=job.get('created_epoch'), updated=updated, message=message,
                         log='\n'.join(f"[{e.get('at', '')}] {e.get('computer', '')}: {e.get('message', '')}"
                                       for e in events[-30:])[-6000:],
                         controls=[], view='workspace'))
    return rows
