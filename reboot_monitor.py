"""Bounded, cancellable reboot connectivity watches. Never retries a reboot."""
import copy
import os
import re
import subprocess
import threading
import time
import uuid
from fastapi import HTTPException

ACTIVE = {'requesting', 'waiting_offline', 'waiting_online'}


def has_echo_reply(result):
    """Windows IPv4 ping succeeds only with an actual echo reply, not an ICMP error."""
    output = getattr(result, 'stdout', '') or ''
    return result.returncode == 0 and isinstance(output, str) and bool(re.search(r'\bTTL\s*=\s*\d+\b', output, re.I))


def ping_once(computer):
    # A Windows ping can return zero for "destination unreachable". Require TTL.
    try:
        result = subprocess.run(['ping.exe', '-4', '-n', '1', '-w', '1000', computer],
                                capture_output=True, text=True, errors='replace', timeout=3,
                                creationflags=0x08000000 if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired:
        return False, 'Ping timed out'
    reply = has_echo_reply(result)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    line = next((line for line in lines if re.search(r'\bTTL\s*=', line, re.I)), None)
    return reply, line or 'No echo reply'


class RebootMonitor:
    def __init__(self, reboot, ping=ping_once, timeout=900, interval=2, clock=time.monotonic):
        self.reboot, self.ping = reboot, ping
        self.timeout, self.interval, self.clock = timeout, interval, clock
        self.lock = threading.RLock()
        self.rows, self.stops = {}, {}

    def _event(self, key, message, state=None):
        with self.lock:
            row = self.rows[key]
            row['events'].append({'time': time.strftime('%H:%M:%S'), 'message': message})
            row['events'] = row['events'][-80:]
            row['message'] = message
            if state:
                row['state'] = state
                if state not in ACTIVE:
                    row['finished'] = self.clock()

    def start(self, computer):
        with self.lock:
            self._prune()
            if any(r['target'] == computer and r['state'] in ACTIVE for r in self.rows.values()):
                raise HTTPException(409, 'This machine already has a reboot being monitored.')
            if sum(r['state'] in ACTIVE for r in self.rows.values()) >= 8:
                raise HTTPException(429, 'Eight reboots are being monitored. Wait for one to finish.')
            key = uuid.uuid4().hex
            self.rows[key] = {'id': key, 'target': computer, 'state': 'requesting',
                              'message': 'Requesting reboot', 'events': []}
            self.stops[key] = threading.Event()
            worker = threading.Thread(target=self._run, args=(key,), daemon=True, name='atlas-reboot')
            try:
                worker.start()
            except Exception:
                del self.rows[key], self.stops[key]
                raise
            return {'job': key, 'target': computer}

    def _run(self, key):
        stop = self.stops[key]
        pc = self.rows[key]['target']
        requested = False
        try:
            self._event(key, 'Sending reboot request')
            self.reboot(pc)
            requested = True
            self._event(key, 'Reboot accepted. Waiting for two missed ping replies.', 'waiting_offline')
            deadline = self.clock() + self.timeout
            misses = replies = 0
            offline = False
            while not stop.is_set() and self.clock() < deadline:
                ok, message = self.ping(pc)
                self._event(key, message)
                if not offline:
                    misses = 0 if ok else misses + 1
                    if misses >= 2:
                        offline = True
                        self._event(key, 'Offline observed. Waiting for ping replies to resume.', 'waiting_online')
                else:
                    replies = replies + 1 if ok else 0
                    if replies >= 2 and not stop.is_set():
                        self._event(key, 'Complete — ping replies resumed. Monitoring stopped.', 'complete')
                        return
                stop.wait(self.interval)
            if stop.is_set():
                self._event(key, 'Monitoring stopped. The reboot request was not cancelled.', 'cancelled')
            else:
                reason = 'Machine has not returned' if offline else 'No offline transition was observed'
                self._event(key, reason + '. Reboot not confirmed; ping may be blocked. Monitoring timed out.', 'timeout')
        except Exception as error:
            prefix = 'Reboot was requested, but monitoring failed: ' if requested else 'Reboot request failed: '
            self._event(key, prefix + str(error), 'failed')

    def _prune(self):
        now = self.clock()
        for key, row in list(self.rows.items()):
            age = now - row.get('finished', now)
            if row['state'] not in ACTIVE and age >= (10 if row['state'] in ('complete', 'cancelled') else 3600):
                del self.rows[key], self.stops[key]

    def snapshot(self):
        with self.lock:
            self._prune()
            rows = copy.deepcopy(list(self.rows.values()))
        return {'reboots': rows, 'count': sum(r['state'] in ACTIVE for r in rows)}

    def stop(self, key):
        with self.lock:
            if key not in self.rows:
                raise HTTPException(404, 'Reboot monitor not found')
            if self.rows[key]['state'] in ACTIVE:
                self.stops[key].set()
            else:
                del self.rows[key], self.stops[key]
        return {'ok': True}

    def shutdown(self):
        with self.lock:
            for stop in self.stops.values():
                stop.set()
