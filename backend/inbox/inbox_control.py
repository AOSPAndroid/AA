"""Admin-side lifecycle control. Mail data remains a read-only handoff.

The on-demand Windows task runs the agent with the mail user's interactive,
limited token. No passwords, browser cookies or Outlook credentials are stored.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import secrets
import sys
import threading
import time
from typing import Literal
import uuid

from fastapi import HTTPException, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from backend.inbox.outlook_watcher import AlreadyRunning, is_running, process_lock, stamp, utcnow, write_json

ROOT = Path(__file__).resolve().parents[2]
MUTEX = threading.RLock()
DEFAULTS = {'running': False, 'outlook': True, 'notifications': True, 'outlook_previews': False}


class IntegrationError(RuntimeError):
    pass


@contextmanager
def control_lock(config):
    directory = Path(config['control_directory'])
    if not directory.is_dir():
        raise IntegrationError('The protected control folder is missing. Reconnect collectors before starting.')
    try:
        with process_lock(directory, 'control.lock'):
            yield
    except AlreadyRunning as error:
        raise IntegrationError('Another Atlas window is updating collector settings. Retry in a moment.') from error


def read_object(path):
    if path.stat().st_size > 65536:
        raise IntegrationError('Inbox configuration is too large.')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise IntegrationError('Inbox configuration must be a JSON object.')
    return value


def powershell(script, *arguments):
    if os.name != 'nt':
        raise IntegrationError('Integrated collectors require Windows.')
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script), *map(str, arguments)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IntegrationError('The Windows inbox task did not respond. Check Task Scheduler and retry.') from error
    if result.returncode:
        raise IntegrationError((result.stderr or result.stdout or 'Windows inbox setup failed.').strip()[:2500])
    return result.stdout


class InboxIntegration:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.path = self.root / 'data' / 'inbox-integration.json'

    def config(self):
        try:
            data = read_object(self.path)
            required = ('directory', 'control_directory', 'mail_user', 'mail_sid', 'atlas_user', 'task_name', 'python')
            if data.get('version') != 1 or any(not isinstance(data.get(key), str) or not data[key] for key in required):
                raise IntegrationError('Inbox setup is incomplete. Run Connect collectors again.')
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise IntegrationError('Cannot read the saved inbox setup. Check data/inbox-integration.json.') from error

    def desired(self, config):
        try:
            value = read_object(Path(config['control_directory']) / 'desired.json')
        except FileNotFoundError:
            return dict(DEFAULTS)
        if any(type(value.get(key)) is not bool for key in DEFAULTS):
            raise IntegrationError('Inbox control settings are invalid. Reconnect the collectors.')
        return value

    def status(self):
        result = {'configured': False, 'state': 'not_configured', 'desired': dict(DEFAULTS),
                  'default_python': sys.executable, 'atlas_user': '\\'.join(filter(None, (os.getenv('USERDOMAIN'), os.getenv('USERNAME'))))}
        try:
            config = self.config()
            if not config:
                return result
            desired = self.desired(config)
            result.update(configured=True, desired=desired,
                          **{key: config[key] for key in ('mail_user', 'atlas_user', 'directory', 'task_name', 'python')})
            directory = Path(config['directory'])
            running = is_running(directory, 'agent.lock')
            try:
                agent = read_object(directory / 'agent-status.json')
            except FileNotFoundError:
                agent = {}
            age = time.time() - float(agent.get('heartbeat', 0))
            fresh = running and -60 <= age < 30
            state = agent.get('state', 'starting') if fresh else 'unresponsive' if running else 'stopped'
            pending = desired.get('revision') != agent.get('revision') or not fresh
            result.update(state=state, agent_running=running, pending=pending,
                          detail=agent.get('detail', '') if fresh else 'Start collectors while the mail account is signed in. Python and the Atlas folder must be readable by that account.',
                          errors=agent.get('errors', {}) if fresh else {})
        except (IntegrationError, OSError, ValueError, TypeError) as error:
            result.update(state='error', detail=str(error))
        return result

    def configure(self, mail_user, python=None):
        with MUTEX:
            current = self.config()
            if current and is_running(Path(current['directory']), 'agent.lock'):
                raise IntegrationError('Stop collectors before changing their Windows account or Python path.')
            powershell(self.root / 'windows' / 'Configure-Inbox-Integration.ps1', '-MailUser', mail_user,
                       '-PythonPath', python or sys.executable)
            if not self.config():
                raise IntegrationError('Windows setup did not save its configuration.')
            return self.command('start')

    def command(self, action, **preferences):
        with MUTEX:
            config = self.config()
            if not config:
                raise IntegrationError('Connect the collectors in Live Inbox first.')
            with control_lock(config):
                return self._command(config, action, preferences)

    def _command(self, config, action, preferences):
        desired = self.desired(config)
        if action == 'source':
            if len(preferences) != 1 or next(iter(preferences), '') not in ('outlook', 'notifications'):
                raise IntegrationError('Choose one email or notification watcher switch.')
            # A switch starts only that source after Stop, even when other
            # sources were enabled before the supervisor was stopped.
            if not desired['running']:
                desired.update(outlook=False, notifications=False)
        if action == 'start':
            desired['running'] = True
        elif action == 'stop':
            desired['running'] = False
        elif action == 'show':
            desired.update(running=True, show_window=uuid.uuid4().hex)
        elif action not in ('preferences', 'source'):
            raise IntegrationError('Unsupported inbox action.')
        for key, value in preferences.items():
            if key not in ('outlook', 'notifications', 'outlook_previews') or type(value) is not bool:
                raise IntegrationError('Unsupported inbox preference.')
            desired[key] = value
        if action == 'source':
            desired['running'] = desired['outlook'] or desired['notifications']
        desired.update(revision=uuid.uuid4().hex, updated_at=stamp(utcnow()))
        write_json(Path(config['control_directory']) / 'desired.json', desired)
        directory = Path(config['directory'])
        orphaned = not desired['running'] and any(is_running(directory, name) for name in ('watcher.lock', 'notifications.lock'))
        if desired['running'] or orphaned:
            # Re-running is harmless: the Windows task ignores duplicate
            # starts and the agent holds an OS lock for the queue.
            powershell(self.root / 'windows' / 'Invoke-Inbox-Task.ps1', '-Configuration', self.path)
        return self.status()

class Setup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mail_user: str = Field(min_length=1, max_length=256, pattern=r'^[^\x00-\x1f\"/]+$')
    python: str | None = Field(default=None, max_length=1024, pattern=r'^[^\x00-\x1f\"]+$')

    @field_validator('mail_user', 'python', mode='before')
    @classmethod
    def unquote(cls, value):
        # Windows "Copy as path" wraps paths in quotes; spaces come from pasting.
        if isinstance(value, str):
            value = value.strip().strip('"\'').strip()
            return value or None
        return value


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['start', 'stop', 'show', 'preferences', 'source']
    outlook: StrictBool | None = None
    notifications: StrictBool | None = None
    outlook_previews: StrictBool | None = None


def register(app, integration=None, token_getter=None):
    integration = integration or InboxIntegration()

    def check_token(request: Request):
        from backend.atlas_api import TOKEN
        expected = token_getter() if token_getter else TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), expected):
            raise HTTPException(403, 'Refresh Atlas before changing collector settings.')

    @app.get('/api/inbox/control')
    def control_status():
        return integration.status()

    @app.post('/api/inbox/control/setup', dependencies=[Depends(check_token)])
    def setup(body: Setup):
        try:
            return integration.configure(body.mail_user, body.python)
        except (IntegrationError, OSError, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post('/api/inbox/control', dependencies=[Depends(check_token)])
    def command(body: Command):
        try:
            return integration.command(body.action, **body.model_dump(exclude={'action'}, exclude_none=True))
        except (IntegrationError, OSError, ValueError) as error:
            raise HTTPException(409, str(error)) from error


def launcher_action(action):
    """An optional collector failure must not prevent the main GUI from opening."""
    integration = InboxIntegration()
    try:
        if integration.config():
            state = integration.command(action)
            print('Atlas inbox: ' + ('start requested for ' + state.get('mail_user', 'mail user') if action == 'start' else 'stop requested'))
            if action == 'stop':
                directory = Path(integration.config()['directory'])
                for attempt in range(51):
                    if not any(is_running(directory, name) for name in ('agent.lock', 'watcher.lock', 'notifications.lock')):
                        return True
                    if attempt < 50:
                        time.sleep(.2)
                print('Atlas inbox is still closing. Finish any Outlook access prompt, then retry Stop before updating Atlas.')
                return False
        elif action == 'start':
            print('Atlas inbox: open Live Inbox > Connect collectors for first-time setup.')
        return True
    except (IntegrationError, OSError, ValueError) as error:
        print('Atlas inbox needs attention: ' + str(error))
        return False
