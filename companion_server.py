"""Atlas side of the Atlas Companion.

Atlas Admin runs under an elevated, otherwise empty account (x01426046_dsk), so it cannot see the
operator's Outlook or clipboard. The Companion (atlas_companion.py) runs in the operator's normal
Windows session and sends what it collects here over the loopback connection:

- every clipboard copy (text, a copied screenshot for OCR, copied file names) into the clipboard
  history, enriched by clipboard_history;
- new classic Outlook mail into an Atlas-owned queue that Live Inbox reads.

At start-up Atlas writes connection.json (address and a dedicated Companion key) to a folder the
normal account can read, %ProgramData%\\Atlas\\Companion by default. The key only opens the
/api/companion/* intake routes: it cannot run remote actions, deployments or read data back.
Settings (clipboard on/off, Outlook on/off) are changed from Atlas and returned at each check-in.
"""
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

ONLINE_SECONDS = 45
BATCH = 50
DEFAULTS = {'clipboard': True, 'mail': False}


def connection_folder():
    """Readable by the normal account: %ProgramData%\\Atlas\\Companion, or ATLAS_COMPANION_DIR."""
    if os.environ.get('ATLAS_COMPANION_DIR'):
        return Path(os.environ['ATLAS_COMPANION_DIR'])
    if os.name == 'nt':
        return Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'Atlas' / 'Companion'
    from runtime_paths import clipboard_path
    return clipboard_path().parent / 'companion'


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat(timespec='seconds')


class Part(BaseModel):
    model_config = ConfigDict(extra='ignore')
    state: str = Field('off', max_length=40)
    detail: str = Field('', max_length=500)
    captured: int = Field(0, ge=0)
    last_success_at: str | None = Field(None, max_length=40)
    paused: bool = False


class Hello(BaseModel):
    model_config = ConfigDict(extra='ignore')
    version: str = Field('', max_length=40)
    user: str = Field('', max_length=200)
    computer: str = Field('', max_length=100)
    clipboard: Part = Part()
    mail: Part = Part()


class ClipboardText(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=20000)


class Mail(BaseModel):
    model_config = ConfigDict(extra='ignore')
    entry_id: str = Field(min_length=1, max_length=1024)
    received_at: str = Field(min_length=10, max_length=40)
    conversation_id: str = Field('', max_length=1024)
    sender_name: str = Field('', max_length=500)
    sender_address: str = Field('', max_length=500)
    subject: str = Field('', max_length=2000)
    body: str = Field('', max_length=100_000)
    body_truncated: int = Field(0, ge=0, le=1)


class MailBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str = Field(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9]+$')
    messages: list[Mail] = Field(max_length=BATCH)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    clipboard: bool | None = None
    mail: bool | None = None


class Companion:
    def __init__(self, state_path, inbox_folder, folder=connection_folder, url='http://127.0.0.1:8770'):
        self._state_path, self._inbox, self._folder, self.url = state_path, inbox_folder, folder, url
        self.lock = threading.Lock()
        self.state = self.load()
        self._token = None

    def _path(self, value):
        return Path(value() if callable(value) else value)

    @property
    def state_path(self):
        return self._path(self._state_path)

    @property
    def inbox(self):
        return self._path(self._inbox)

    @property
    def folder(self):
        return self._path(self._folder)

    def load(self):
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2), encoding='utf-8')
        os.replace(temporary, self.state_path)

    def settings(self):
        return {**DEFAULTS, **self.state.get('settings', {})}

    def token(self):
        """The Companion key, created once and written with the address for the normal account."""
        path = self.folder / 'connection.json'
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved.get('url') == self.url and len(saved.get('token', '')) >= 32:
                return saved['token']
        except (OSError, ValueError):
            pass
        token = secrets.token_urlsafe(32)
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'url': self.url, 'token': token}, indent=2), encoding='utf-8')
        os.replace(temporary, path)
        return token

    def check(self, request):
        if self._token is None:
            self._token = self.token()
        if not secrets.compare_digest(request.headers.get('x-atlas-companion', ''), self._token):
            raise HTTPException(403, 'Unknown Companion key. Restart the Atlas Companion so it reads the current connection.')

    def hello(self, body):
        with self.lock:
            self.state['companion'] = {**body.model_dump(), 'seen': stamp(), 'seen_epoch': time.time()}
            self.save()
            return {'settings': self.settings(), 'server_time': stamp()}

    def seen(self):
        info = self.state.get('companion')
        return info if info else None

    def online(self):
        info = self.seen()
        return bool(info) and time.time() - float(info.get('seen_epoch', 0)) < ONLINE_SECONDS

    def status(self):
        info = self.seen() or {}
        return {'known': bool(info), 'online': self.online(), 'user': info.get('user', ''), 'computer': info.get('computer', ''),
                'version': info.get('version', ''), 'last_seen': info.get('seen'), 'clipboard': info.get('clipboard', {}),
                'mail': info.get('mail', {}), 'settings': self.settings()}

    def update(self, body):
        with self.lock:
            settings = self.settings()
            settings.update({key: value for key, value in body.model_dump().items() if value is not None})
            self.state['settings'] = settings
            self.save()
        return self.status()

    # Mail: Live Inbox reads this Atlas-owned queue while the Companion supplies Outlook.
    def mail_active(self):
        return bool(self.seen()) and self.settings()['mail']

    def mail_status(self):
        info = self.seen() or {}
        mail = info.get('mail', {})
        online = self.online()
        state = mail.get('state', 'starting') if online else 'stopped'
        detail = mail.get('detail', '') if online else 'The Atlas Companion is not running. Start it from your normal Windows account.'
        return {'state': state, 'running': online, 'last_success_at': mail.get('last_success_at'), 'updated_at': info.get('seen'),
                'detail': detail, 'config': {'mailbox': 'Atlas Companion · ' + info.get('user', '')}, 'stale': False, 'interval': 15}

    def receive_mail(self, batch):
        from outlook_watcher import MailQueue
        queue = MailQueue(self.inbox, now())
        try:
            return sum(queue.insert(batch.source, message.model_dump()) for message in batch.messages)
        finally:
            queue.close()


class CompanionInbox:
    """Live Inbox collector controls: the Companion's Outlook watcher once a Companion has connected,
    otherwise the original normal-user collectors (InboxIntegration)."""

    def __init__(self, companion, original):
        self.companion, self.original = companion, original

    def status(self):
        if not self.companion.seen():
            return self.original.status()
        info, settings, online = self.companion.status(), self.companion.settings(), self.companion.online()
        running = settings['mail']
        mail = info.get('mail') or {}
        return {'configured': True, 'companion': True, 'state': (mail.get('state') or 'starting') if online and running else 'stopped',
                'agent_running': online, 'pending': running and not online, 'mail_user': info['user'],
                'atlas_user': '\\'.join(filter(None, (os.getenv('USERDOMAIN'), os.getenv('USERNAME')))),
                'desired': {'running': running, 'outlook': running, 'notifications': False, 'outlook_previews': False},
                'detail': mail.get('detail', '') if online else 'Start the Atlas Companion from your normal Windows account.',
                'errors': {}}

    def configure(self, mail_user, python=None):
        return self.original.configure(mail_user, python)

    def command(self, action, **preferences):
        if not self.companion.seen():
            return self.original.command(action, **preferences)
        if preferences.get('notifications'):
            from inbox_control import IntegrationError
            raise IntegrationError('Teams notifications are not part of the Atlas Companion yet; they still use the notification listener.')
        if action in ('start', 'stop'):
            self.companion.update(Settings(mail=action == 'start'))
        elif action == 'source' and 'outlook' in preferences:
            self.companion.update(Settings(mail=bool(preferences['outlook'])))
        return self.status()


companion = None


def register(app, wmi, check_token, state_path, inbox_folder, folder=connection_folder, url=None):
    global companion
    port = os.environ.get('ATLAS_ADMIN_PORT', '8770')
    companion = Companion(state_path, inbox_folder, folder, url or f'http://127.0.0.1:{port}')
    try:
        companion._token = companion.token()
    except OSError:
        pass  # Reported when the Companion connects; Atlas itself keeps working.

    @app.post('/api/companion/hello')
    def hello(body: Hello, request: Request):
        companion.check(request)
        return companion.hello(body)

    @app.post('/api/companion/clipboard')
    def clipboard(body: ClipboardText, request: Request):
        companion.check(request)
        if not companion.settings()['clipboard']:
            raise HTTPException(409, 'Clipboard capture is off in Atlas.')
        from clipboard_history import record
        item = record(body.text, 'companion')
        return {'id': item and item['id']}

    @app.post('/api/companion/image')
    async def image(request: Request):
        companion.check(request)
        if not companion.settings()['clipboard']:
            raise HTTPException(409, 'Clipboard capture is off in Atlas.')
        from screen_reader import IMAGE_LIMIT, ocr_image
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > IMAGE_LIMIT:
                raise HTTPException(413, 'The image is larger than 15 MB.')
        captured = ocr_image(wmi.ps, bytes(data))
        from clipboard_history import record
        item = record(captured['text'], 'screenshot')
        return {'id': item and item['id']}

    @app.post('/api/companion/mail')
    def mail(body: MailBatch, request: Request):
        companion.check(request)
        if not companion.settings()['mail']:
            raise HTTPException(409, 'The Outlook watcher is off in Atlas.')
        try:
            return {'added': companion.receive_mail(body)}
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(503, f'Atlas could not save the mail: {error}') from error

    @app.get('/api/companion')
    def status():
        return companion.status()

    @app.post('/api/companion/settings')
    def settings(body: Settings, request: Request):
        check_token(request)
        return companion.update(body)
    return companion
