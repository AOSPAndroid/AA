"""Atlas Companion logic that does not touch Windows: the connection to Atlas, what to send for a
clipboard change, and forwarding Outlook mail from the Companion's own queue. atlas_companion.py
adds the Windows parts (clipboard listener, tray icon, Outlook) around these classes."""
import hashlib
import json
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = '1.0'
TEXT_LIMIT = 20000
# Formats password managers and Windows set to keep a copy out of clipboard history and monitors.
PRIVATE_FORMATS = {'ExcludeClipboardContentFromMonitorProcessing', 'Clipboard Viewer Ignore'}
NO_HISTORY = 'CanIncludeInClipboardHistory'


class Offline(Exception):
    """Atlas is not reachable (not started, restarting) or refused the request."""


def connection_file():
    if os.environ.get('ATLAS_COMPANION_DIR'):
        return Path(os.environ['ATLAS_COMPANION_DIR']) / 'connection.json'
    return Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'Atlas' / 'Companion' / 'connection.json'


def read_connection(path=None):
    """(url, token) written by Atlas Admin, or Offline with what to do."""
    path = Path(path or connection_file())
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        url, token = str(data['url']).rstrip('/'), str(data['token'])
    except FileNotFoundError as error:
        raise Offline(f'Start Atlas Admin once so it writes {path}.') from error
    except PermissionError as error:
        raise Offline(f'This Windows account cannot read {path}.') from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Offline(f'{path} is unreadable: {error}') from error
    if not url.startswith(('http://127.0.0.1:', 'http://localhost:')):
        raise Offline('The Companion only connects to Atlas on this PC.')
    return url, token


class Client:
    def __init__(self, url, token, opener=None, timeout=20):
        self.url, self.token, self.timeout = url, token, timeout
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def send(self, path, data, content_type):
        request = urllib.request.Request(self.url + path, data=data, method='POST',
                                         headers={'Content-Type': content_type, 'X-Atlas-Companion': self.token})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get('detail')
            except (ValueError, AttributeError, OSError):
                detail = None
            raise Offline(f'Atlas refused {path}: {detail or error.code}') from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise Offline(f'Atlas is not reachable at {self.url}: {error}') from error

    def post(self, path, body):
        return self.send(path, json.dumps(body).encode('utf-8'), 'application/json')

    def image(self, data):
        return self.send('/api/companion/image', data, 'image/bmp')


def dib_to_bmp(dib):
    """A BMP file from clipboard CF_DIB data (a BITMAPINFO header and pixels), for Atlas's OCR."""
    if len(dib) < 40:
        raise ValueError('Clipboard image is incomplete')
    header_size, = struct.unpack_from('<I', dib, 0)
    bit_count, compression = struct.unpack_from('<HI', dib, 14)
    colors_used, = struct.unpack_from('<I', dib, 32)
    masks = 12 if compression == 3 and header_size == 40 else 0  # BI_BITFIELDS colour masks follow the header.
    palette = (colors_used or (1 << bit_count if bit_count <= 8 else 0)) * 4
    offset = 14 + header_size + masks + palette
    return b'BM' + struct.pack('<IHHI', 14 + len(dib), 0, 0, offset) + dib


def private(formats, no_history=None):
    """True when the copying app asked monitors to ignore this copy (password managers do)."""
    return bool(PRIVATE_FORMATS & set(formats)) or (NO_HISTORY in formats and no_history == 0)


def signature(kind, data):
    return kind + ':' + hashlib.sha256(data if isinstance(data, bytes) else str(data).encode('utf-8')).hexdigest()


class ClipboardForwarder:
    """Sends each new copy to Atlas once; the same content copied again is skipped here."""

    def __init__(self, client):
        self.client, self.last, self.captured, self.paused, self.private = client, None, 0, False, 0
        self.state, self.detail = 'watching', ''

    def handle(self, content):
        """content: {'text': str} | {'image': bmp bytes} | {'files': [paths]} | {'private': True} | {}."""
        if self.paused or not content:
            return None
        if content.get('private'):
            self.private += 1  # A password manager or Windows asked monitors to ignore this copy.
            return None
        if 'image' in content:
            kind, data = 'image', content['image']
        else:
            text = content.get('text') or '\n'.join(content.get('files') or [])
            if not text.strip():
                return None
            kind, data = 'text', text[:TEXT_LIMIT]
        seen = signature(kind, data)
        if seen == self.last:
            return None
        try:
            result = self.client.image(data) if kind == 'image' else self.client.post('/api/companion/clipboard', {'text': data})
        except Offline as error:
            self.state, self.detail = 'error', str(error)
            raise
        self.last, self.captured = seen, self.captured + 1
        self.state, self.detail = 'watching', ''
        return result

    def report(self):
        detail = self.detail or (f'{self.private} private copies skipped (password managers)' if self.private else '')
        return {'state': 'paused' if self.paused else self.state, 'detail': detail, 'captured': self.captured, 'paused': self.paused}


class MailForwarder:
    """Forwards messages from the Companion's own Outlook queue (outlook_watcher.MailQueue, with its
    checkpoints) to Atlas, in order, remembering the last one Atlas accepted."""

    FIELDS = ('entry_id', 'received_at', 'conversation_id', 'sender_name', 'sender_address', 'subject', 'body', 'body_truncated')

    def __init__(self, queue, client, batch=50):
        self.queue, self.client, self.batch = queue, client, batch

    def pending(self):
        after = self.queue.get('forwarded') or 0
        return self.queue.db.execute(
            f"SELECT id, source, {', '.join(self.FIELDS)} FROM messages WHERE id > ? AND content_kind='mail' ORDER BY id LIMIT ?",
            (after, self.batch)).fetchall()

    def forward(self):
        sent = 0
        while True:
            rows = self.pending()
            if not rows:
                return sent
            for source in dict.fromkeys(row['source'] for row in rows):
                group = [row for row in rows if row['source'] == source]
                self.client.post('/api/companion/mail', {'source': source, 'messages': [{k: row[k] for k in self.FIELDS} for row in group]})
            with self.queue.db:
                self.queue.set('forwarded', rows[-1]['id'])
            sent += len(rows)
            if len(rows) < self.batch:
                return sent


def hello(client, user, computer, clipboard, mail):
    """Check in with Atlas; returns its settings ({'clipboard': bool, 'mail': bool})."""
    response = client.post('/api/companion/hello', {'version': VERSION, 'user': user, 'computer': computer,
                                                    'clipboard': clipboard, 'mail': mail})
    return response.get('settings') or {}


def backoff(failures, low=5, high=60):
    return min(high, low * (2 ** max(0, failures - 1)))


def sleep_until(stop, seconds):
    """Wait, waking early when stop (a threading.Event) is set."""
    end = time.monotonic() + seconds
    while not stop.is_set() and time.monotonic() < end:
        stop.wait(min(0.5, end - time.monotonic()))
