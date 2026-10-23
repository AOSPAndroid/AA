"""Normal-user supervisor for the Outlook watcher and packaged toast listener."""
from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import outlook_watcher as outlook

ROOT = Path(__file__).resolve().parent


def read_object(path):
    if path.stat().st_size > 65536:
        raise ValueError('Inbox control file is too large.')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Inbox control file is not an object.')
    return value


def assert_mail_user(config):
    if os.name != 'nt' or ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError('The inbox agent must run as the normal, non-elevated mail user.')
    identity = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'], text=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
    sid = next(csv.reader(identity.strip().splitlines()))[-1]
    if sid != config['mail_sid']:
        raise ValueError('The inbox task is running under the wrong Windows account.')


class Agent:
    def __init__(self, config):
        self.config = config
        self.directory = Path(config['directory'])
        self.control = Path(config['control_directory'])
        self.revision = None
        self.show_window = None
        self.notifications_command = None
        self.last_launch = {'outlook': 0, 'notifications': 0}
        self.errors = {}

    def desired(self):
        value = read_object(self.control / 'desired.json')
        if any(type(value.get(key)) is not bool for key in ('running', 'outlook', 'notifications', 'outlook_previews')):
            raise ValueError('Invalid collector preferences; reconnect the collectors in Atlas.')
        return value

    def stop_outlook(self):
        current = outlook.status(self.directory)
        if current.get('running') and current.get('run_id'):
            outlook.write_json(self.directory / 'stop.json', {'run_id': current['run_id']})

    def notify(self, operation, previews):
        outlook.write_json(self.directory / 'notifications-command.json', {
            'id': uuid.uuid4().hex, 'operation': operation, 'outlook_previews': previews,
            'expires_at': outlook.stamp(outlook.utcnow() + timedelta(seconds=30))})

    def start_notifications(self, show):
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                   str(ROOT / 'Start-Notification-Listener.ps1'), '-DataDirectory', str(self.directory), '-AutoStart']
        if not show:
            command.append('-Background')
        result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError((result.stderr or result.stdout or 'Notification listener failed to open.').strip()[:1200])

    def reconcile(self, desired):
        running = desired['running']
        mail_on = running and desired['outlook']
        notify_on = running and desired['notifications']
        show = running and bool(desired.get('show_window')) and desired['show_window'] != self.show_window
        changed = desired.get('revision') != self.revision
        now = time.monotonic()
        try:
            if not mail_on:
                self.stop_outlook()
                self.errors.pop('outlook', None)
            elif not outlook.is_running(self.directory) and (changed or now - self.last_launch['outlook'] > 30):
                self.last_launch['outlook'] = now
                outlook.start(SimpleNamespace(data_dir=self.directory, mailbox=None, subfolder=None,
                                              interval=5, lookback_hours=0))
                self.errors.pop('outlook', None)
        except Exception as error:
            self.errors['outlook'] = str(error)[:1200]
        try:
            alive = outlook.is_running(self.directory, 'notifications.lock')
            operation = 'start' if notify_on else 'pause' if running else 'exit'
            # A show request opens settings even when capture is paused.
            signature = (operation, desired['outlook_previews'], desired.get('show_window'), desired.get('revision'))
            launch = (notify_on or show) and not alive and (changed or now - self.last_launch['notifications'] > 30)
            if launch or (alive and signature != self.notifications_command):
                self.notify(operation, desired['outlook_previews'])
                if launch:
                    self.last_launch['notifications'] = now
                    self.start_notifications(show)
                if show:
                    # Combined command retains the desired pause/capture state.
                    self.notify(operation + '_show', desired['outlook_previews'])
                self.notifications_command = signature
                self.errors.pop('notifications', None)
            if not notify_on and not show:
                self.errors.pop('notifications', None)
        except Exception as error:
            self.errors['notifications'] = str(error)[:1200]
        self.show_window = desired.get('show_window')
        self.revision = desired.get('revision')
        stopped = not running and not outlook.is_running(self.directory) and not outlook.is_running(self.directory, 'notifications.lock')
        state = 'stopped' if stopped else 'stopping' if not running else 'attention' if self.errors else 'running'
        outlook.write_json(self.directory / 'agent-status.json', {
            'state': state, 'detail': 'Collectors are controlled by Atlas.' if running else 'Waiting for collectors to close.' if not stopped else 'Collectors stopped.',
            'heartbeat': time.time(), 'revision': self.revision, 'errors': self.errors})
        return stopped

    def run(self):
        with outlook.process_lock(self.directory, 'agent.lock'):
            while True:
                if self.reconcile(self.desired()):
                    # Recheck after an overlapping Start: do not exit using an
                    # old Stop request while Task Scheduler ignores the new run.
                    time.sleep(.5)
                    if not self.desired()['running']:
                        return 0
                time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, required=True)
    args = parser.parse_args()
    config = read_object(args.configuration)
    if config.get('version') != 1:
        raise ValueError('Unsupported inbox configuration.')
    assert_mail_user(config)
    try:
        return Agent(config).run()
    except outlook.AlreadyRunning:
        return 0
    except Exception:
        # Task Scheduler may retry. Existing collectors retain their data and
        # their locks; a new supervisor can safely adopt them.
        outlook.write_json(Path(config['directory']) / 'agent-status.json', {
            'state': 'error', 'heartbeat': time.time(), 'detail': 'Inbox agent stopped. Check the control folder and reconnect in Atlas.'})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
