"""Bounded worker admission and durable, consistent operation snapshots."""
import copy
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from fastapi import HTTPException

TERMINAL = {'launched', 'complete', 'failed', 'cancelled', 'interrupted', 'unknown'}


class JobService:
    def __init__(self, path, retained=200):
        self.path = path
        self.retained = retained
        self.lock = threading.RLock()
        self.jobs = {}
        self.queues = {}
        self.pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix='atlas-job')
        self.admission = threading.BoundedSemaphore(32)
        self.execution = threading.BoundedSemaphore(8)
        self.inventory = threading.BoundedSemaphore(3)
        self.unresolved = set()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path(), timeout=20)
        c.execute('create table if not exists operation_state(id text primary key,kind text,body text,updated real)')
        c.execute('create table if not exists operation_guard(target text primary key)')
        try:
            with c:yield c
        finally:c.close()

    def snapshot(self, pool, key):
        with self.lock:
            if key not in pool:
                raise HTTPException(404, 'Operation not found; consult history.')
            return copy.deepcopy(pool[key])

    def save(self, key, queue=False):
        with self.lock:
            pool = self.queues if queue else self.jobs
            data = pool[key]
            data['updated'] = time.time()
            if 'events' in data:
                data['events'] = data['events'][-200:]
            body = json.dumps(data)
            with self.connect() as c:
                c.execute('insert or replace into operation_state values(?,?,?,?)', (key, 'queue' if queue else 'job', body, data['updated']))
                if (data.get('state') in ('unknown', 'interrupted') or data.get('recovery_required')) and not data.get('recovery_acknowledged'):
                    targets = [data.get('target')] + [r.get('target') or r.get('machine') for r in data.get('items', data.get('results', []))]
                    pending = [t for t in targets if t and t not in data.get('acknowledged_targets', [])]
                    self.unresolved.update(pending)
                    c.executemany('insert or ignore into operation_guard values(?)', ((t,) for t in pending))
            finished = sorted((k for k,v in pool.items() if v.get('state') in TERMINAL), key=lambda k:pool[k].get('updated',0))
            expired = finished[:-self.retained] if len(finished)>self.retained else []
            for old in expired:
                del pool[old]
            if expired:
                with self.connect() as c:
                    c.executemany('delete from operation_state where id=?', ((old,) for old in expired))

    def recover(self):
        """Never replay work automatically after a process restart."""
        with self.connect() as c:
            rows = c.execute('select id,kind,body from operation_state order by updated').fetchall()
            self.unresolved.update(r[0] for r in c.execute('select target from operation_guard'))
        for key, kind, body in rows:
            data = json.loads(body)
            if data.get('state') not in TERMINAL:
                data['state'] = 'interrupted'
                data.setdefault('events', []).append({'message':'Atlas restarted. Inspect the target and history before starting new work.'})
                targets = [data.get('target')] + [r.get('target') or r.get('machine') for r in data.get('items',data.get('results',[]))]
                self.unresolved.update(t for t in targets if t)
            if (data.get('state') in ('unknown','interrupted') or data.get('recovery_required')) and not data.get('recovery_acknowledged'):
                targets=[data.get('target')]+[r.get('target') or r.get('machine') for r in data.get('items',data.get('results',[]))]
                self.unresolved.update(t for t in targets if t and t not in data.get('acknowledged_targets',[]))
            (self.queues if kind=='queue' else self.jobs)[key] = data
            self.save(key, queue=kind=='queue')

    def submit(self, fn, *args):
        if not self.admission.acquire(blocking=False):
            raise HTTPException(429, 'Atlas has 32 admitted operations. Wait for a running operation to finish.')
        def run():
            try:
                return fn(*args)
            finally:
                self.admission.release()
        try:
            return self.pool.submit(run)
        except BaseException:
            self.admission.release()
            raise

    def target_ready(self, pc):
        if pc in self.unresolved:
            raise HTTPException(409, 'A previous operation has an unknown outcome. Review the target and acknowledge it in operation recovery.')

    def acknowledge(self, pc):
        with self.lock, self.connect() as c:
            c.execute('delete from operation_guard where target=?', (pc,))
            self.unresolved.discard(pc)
