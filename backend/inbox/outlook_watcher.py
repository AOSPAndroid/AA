"""Read new mail from running classic Outlook into a private, local SQLite queue.

Run in the logged-on Outlook user's session. This module does not import the
Atlas servers, send messages, mark mail read, or execute diagnostic commands.
"""
from __future__ import annotations

import argparse
import errno
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

UTC = timezone.utc
OVERLAP = timedelta(minutes=5)
RECONCILE_SECONDS = 900
BODY_LIMIT = 100_000


def utcnow():
    return datetime.now(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat()


def default_directory():
    config = Path(__file__).resolve().parents[2] / 'data' / 'inbox-integration.json'
    if config.is_file():
        saved = json.loads(config.read_text(encoding='utf-8-sig'))
        if saved.get('version') == 1 and isinstance(saved.get('directory'), str):
            return Path(saved['directory']).resolve()
    if os.environ.get('ATLAS_MAIL_DIR'):
        return Path(os.environ['ATLAS_MAIL_DIR']).expanduser().resolve()
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'Atlas' / 'OutlookWatcher'


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class AlreadyRunning(Exception):
    pass


class OutlookUnavailable(Exception):
    pass


class StopRequested(Exception):
    pass


@contextmanager
def process_lock(directory, filename='watcher.lock'):
    """An OS-held lock is released even if the process crashes or the PC restarts."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / filename).open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise AlreadyRunning('The Outlook watcher is already running for this data folder.') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def is_running(directory, filename='watcher.lock'):
    # Atlas may run as a different Windows account with READ access only.
    # Probe the existing OS lock without creating, rewriting or appending files.
    try:
        handle = (directory / filename).open('rb')
    except FileNotFoundError:
        return False
    with handle:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return True  # Permission to open was checked separately above.
            raise
    return False


class MailQueue:
    def __init__(self, directory, since, mailbox=None, subfolder=None):
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'inbox.sqlite3', timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path(__file__).with_name('inbox_schema.sql').read_text(encoding='utf-8'))
        # Serialize migration with the notification writer. Existing mail IDs,
        # checkpoints and bodies are preserved; old watcher versions still work.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in self.db.execute('PRAGMA table_info(messages)')}
            for column, default in (('channel', 'outlook'), ('content_kind', 'mail'), ('app_name', '')):
                if column not in columns:
                    self.db.execute(f"ALTER TABLE messages ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
        if self.get('since') is None:
            self.set('since', stamp(since))
            self.set('cursor', stamp(since))
            self.set('config', {'mailbox': mailbox or '', 'subfolder': subfolder or ''})
            self.db.commit()
        config = self.get('config')
        for key, value in (('mailbox', mailbox), ('subfolder', subfolder)):
            if value is not None and value != config[key]:
                self.close()
                raise ValueError('This data folder already watches a different inbox. Use a separate --data-dir.')

    def close(self):
        self.db.close()

    def get(self, key):
        row = self.db.execute('SELECT value FROM watcher_state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key, value):
        self.db.execute('INSERT INTO watcher_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, json.dumps(value)))

    def pin(self, identity):
        previous = self.get('identity')
        if previous and previous != identity:
            raise OutlookUnavailable('The selected Outlook profile or inbox changed; reopen the original profile.')
        self.set('identity', identity)
        self.db.commit()

    def contains(self, source, entry_id):
        return self.db.execute('SELECT 1 FROM messages WHERE source=? AND entry_id=?', (source, entry_id)).fetchone() is not None

    def insert(self, source, message):
        fields = ('entry_id', 'received_at', 'conversation_id', 'sender_name', 'sender_address', 'subject', 'body', 'body_truncated')
        with self.db:
            result = self.db.execute('''INSERT OR IGNORE INTO messages
                (source,imported_at,entry_id,received_at,conversation_id,sender_name,sender_address,subject,body,body_truncated)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (source, stamp(utcnow()), *(message[key] for key in fields)))
        return result.rowcount

    def count(self):
        return self.db.execute("SELECT count(*) FROM messages WHERE content_kind='mail'").fetchone()[0]


def scan(queue, inbox, now, should_stop=lambda: False):
    """Commit a checkpoint only after a complete pass; retries are idempotent."""
    queue.pin(inbox.identity)
    source = hashlib.sha256(json.dumps(inbox.identity, sort_keys=True).encode()).hexdigest()
    since = datetime.fromisoformat(queue.get('since'))
    cursor = datetime.fromisoformat(queue.get('cursor'))
    reconciled = queue.get('reconciled')
    full = not reconciled or (now - datetime.fromisoformat(reconciled)).total_seconds() >= RECONCILE_SECONDS
    lower = since if full else max(since, cursor - OVERLAP)
    added = 0
    first_error = None
    for entry_id in inbox.entries(lower):
        if should_stop():
            raise StopRequested()
        if queue.contains(source, entry_id):
            continue
        try:
            message = inbox.read(entry_id)
        except Exception as error:
            # One temporarily inaccessible/protected item must not prevent the
            # remaining readable messages from reaching the local queue.
            if first_error is None:
                first_error = error
            continue
        if message is None:
            continue  # Meeting requests and other non-mail items.
        if datetime.fromisoformat(message['received_at']) < since:
            continue  # Outlook filters have minute precision; preserve the exact start boundary.
        added += queue.insert(source, message)
    if should_stop():
        raise StopRequested()
    if first_error is not None:
        raise first_error
    with queue.db:
        queue.set('cursor', stamp(max(cursor, now)))
        if full:
            queue.set('reconciled', stamp(now))
    return added


def windows_dependencies():
    if os.name != 'nt':
        raise ValueError('The Outlook watcher requires Windows and classic Outlook.')
    try:
        import pythoncom
        import win32api
        import win32com.client
    except ImportError as error:
        raise ValueError('Run windows\\Install-Inbox-Collectors.bat first (pywin32 is missing).') from error
    return pythoncom, win32api, win32com.client


class OutlookInbox:
    def __init__(self, config, pinned=None):
        self.pythoncom, self.win32api, client = windows_dependencies()
        try:
            # GetActiveObject attaches only; Dispatch("Outlook.Application") would launch Outlook.
            self.application = client.GetActiveObject('Outlook.Application')
        except self.pythoncom.com_error as error:
            code = error.hresult & 0xffffffff
            message = ('Classic Outlook is not installed for this Windows account.' if code == 0x80040154 else
                       'Waiting for classic Outlook in this Windows user session. Open Outlook normally.')
            raise OutlookUnavailable(message) from error
        self.namespace = self.application.GetNamespace('MAPI')
        profile = str(self.namespace.CurrentProfileName)
        if pinned:
            if profile != pinned['profile']:
                raise OutlookUnavailable('Open the Outlook profile originally selected for this watcher.')
            self.folder = self.namespace.GetFolderFromID(pinned['folder_id'], pinned['store_id'])
        else:
            if config['mailbox']:
                stores = [store for store in self.namespace.Stores if str(store.DisplayName).casefold() == config['mailbox'].casefold()]
                if len(stores) != 1:
                    raise OutlookUnavailable('Mailbox name did not match exactly one open store. Use the inboxes command to list stores.')
                self.folder = stores[0].GetDefaultFolder(6)
            else:
                self.folder = self.namespace.GetDefaultFolder(6)
            if config['subfolder']:
                for name in config['subfolder'].split('/'):
                    self.folder = self.folder.Folders.Item(name)
        self.identity = {'profile': profile, 'store_id': str(self.folder.StoreID), 'folder_id': str(self.folder.EntryID)}

    def entries(self, since):
        # DASL namespace comparisons use UTC, formatted with Windows regional settings.
        # pywin32 converts datetime arguments via their timestamps. Keeping UTC
        # attached prevents the Windows local offset from being applied twice.
        date = since.astimezone(UTC).replace(second=0, microsecond=0)
        date_text = self.win32api.GetDateFormat(0, 1, date, None)
        time_text = self.win32api.GetTimeFormat(0, 2, date, None)  # TIME_NOSECONDS
        literal = (date_text + ' ' + time_text).replace("'", "''")
        table = self.folder.GetTable(f'@SQL="urn:schemas:httpmail:datereceived" >= \'{literal}\'')
        table.Columns.RemoveAll()
        table.Columns.Add('EntryID')
        table.Columns.Add('MessageClass')
        while not table.EndOfTable:
            rows = table.GetArray(100)
            if not rows:
                break
            for entry_id, message_class in rows:
                if str(message_class).lower().startswith('ipm.note'):
                    yield str(entry_id)

    def read(self, entry_id):
        item = self.namespace.GetItemFromID(entry_id, self.identity['store_id'])
        if item.Class != 43:
            return None
        # Access through the Outlook object model may prompt according to company policy.
        sender_address = str(item.SenderEmailAddress or '')
        if item.SenderEmailType == 'EX':
            sender = item.Sender
            if sender:
                try:
                    exchange_user = sender.GetExchangeUser()
                    if exchange_user:
                        sender_address = str(exchange_user.PrimarySmtpAddress or sender_address)
                except self.pythoncom.com_error:
                    pass  # Retain the supplied Exchange address; do not guess an SMTP identity.
        body = str(item.Body or '')
        return {'entry_id': entry_id, 'received_at': stamp(item.ReceivedTime),
                'conversation_id': str(item.ConversationID or ''), 'sender_name': str(item.SenderName or ''),
                'sender_address': sender_address, 'subject': str(item.Subject or ''),
                'body': body[:BODY_LIMIT], 'body_truncated': int(len(body) > BODY_LIMIT)}


def status(directory):
    result = read_json(directory / 'status.json')
    result['running'] = is_running(directory)
    result['data_directory'] = str(directory)
    if not result['running']:
        result['state'] = 'stopped'
    return result


def run(args):
    pythoncom, _, _ = windows_dependencies()
    directory = args.data_dir
    with process_lock(directory):
        run_id = getattr(args, 'run_id', None) or uuid.uuid4().hex
        current = {'pid': os.getpid(), 'run_id': run_id, 'started_at': stamp(utcnow()), 'state': 'starting',
                   'messages_saved': 0, 'last_success_at': None, 'detail': '', 'interval': args.interval}

        def report(state, detail='', **extra):
            current.update(state=state, detail=detail, updated_at=stamp(utcnow()), **extra)
            write_json(directory / 'status.json', current)

        def stopped():
            return read_json(directory / 'stop.json').get('run_id') == run_id

        report('starting')
        queue = None
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        try:
            queue = MailQueue(directory, utcnow() - timedelta(hours=args.lookback_hours), args.mailbox, args.subfolder)
            current['config'] = queue.get('config')
            while not stopped():
                result = 0
                inbox = None
                try:
                    inbox = OutlookInbox(queue.get('config'), queue.get('identity'))
                    report('scanning', messages_saved=queue.count())
                    scan(queue, inbox, utcnow(), stopped)
                    report('watching', messages_saved=queue.count(), last_success_at=stamp(utcnow()))
                except OutlookUnavailable as error:
                    report('waiting_for_outlook', str(error), messages_saved=queue.count())
                    result = 2
                except StopRequested:
                    break
                except pythoncom.com_error as error:
                    # Never put email content, sender details, or provider exception strings in logs.
                    report('retrying', f'Outlook read failed (0x{error.hresult & 0xffffffff:08X}); retrying without advancing the checkpoint.',
                           messages_saved=queue.count())
                    result = 2
                finally:
                    inbox = None  # COM objects stay on this single thread and are released after each pass.
                if args.once:
                    return result
                deadline = time.monotonic() + args.interval
                while time.monotonic() < deadline and not stopped():
                    pythoncom.PumpWaitingMessages()
                    time.sleep(.25)
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            report('error', f'{type(error).__name__}: watcher stopped. Check configuration, disk space and local folder access.')
            raise
        finally:
            if queue:
                queue.close()
            pythoncom.CoUninitialize()
            if args.once or current['state'] == 'error':
                current['exited'] = True
                write_json(directory / 'status.json', current)
            else:
                report('stopped')


def start(args):
    windows_dependencies()
    directory = args.data_dir
    directory.mkdir(parents=True, exist_ok=True)
    if is_running(directory):
        current = status(directory)
        for key, requested in (('mailbox', args.mailbox), ('subfolder', args.subfolder)):
            if requested is not None and requested != current.get('config', {}).get(key):
                raise ValueError('A watcher already uses this data folder with another configuration. Use a different --data-dir.')
        return current
    requested_run = uuid.uuid4().hex
    command = [sys.executable, '-m', 'backend.inbox.outlook_watcher', 'run', '--data-dir', str(directory),
               '--interval', str(args.interval), '--lookback-hours', str(args.lookback_hours), '--run-id', requested_run]
    for flag, value in (('--mailbox', args.mailbox), ('--subfolder', args.subfolder)):
        if value is not None:
            command.extend([flag, value])
    child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise ValueError('Watcher could not stay running. Run python -m backend.inbox.outlook_watcher run from the AA folder to see the startup error.')
        current = status(directory)
        # A Windows virtualenv's python.exe can forward to another process, so
        # Popen.pid is not necessarily the PID reported by the Python worker.
        if current.get('run_id') == requested_run and current['running'] and current['state'] != 'starting':
            if current['state'] == 'error':
                raise ValueError(current['detail'])
            return current
        time.sleep(.1)
    raise ValueError('Watcher startup has not reported its status yet. Check Live Inbox > Collectors and alerts in Atlas, or run: python -m backend.inbox.outlook_watcher status')


def stop(directory):
    current = status(directory)
    if not current['running']:
        return current
    if not current.get('run_id'):
        raise ValueError('Watcher is still starting. Retry Stop in a moment.')
    write_json(directory / 'stop.json', {'run_id': current['run_id']})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and is_running(directory):
        time.sleep(.1)
    result = status(directory)
    if result['running']:
        result['detail'] = 'Stop requested. Waiting for the current Outlook call to return.'
    return result


def inboxes():
    pythoncom, _, client = windows_dependencies()
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    try:
        try:
            application = client.GetActiveObject('Outlook.Application')
        except pythoncom.com_error as error:
            raise ValueError('Open classic Outlook normally under this Windows account first.') from error
        namespace = application.GetNamespace('MAPI')
        result = []
        for store in namespace.Stores:
            try:
                folder = store.GetDefaultFolder(6)
                result.append({'mailbox': str(store.DisplayName), 'inbox': str(folder.Name)})
                folder = None
            except pythoncom.com_error:
                continue
        store = namespace = application = None
        return result
    finally:
        pythoncom.CoUninitialize()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'run', 'stop', 'status', 'inboxes'))
    parser.add_argument('--data-dir', type=Path, default=default_directory())
    parser.add_argument('--mailbox', help='Exact display name from the inboxes command; default: your Outlook Inbox')
    parser.add_argument('--subfolder', help='Path below the selected Inbox, with / between folder names')
    parser.add_argument('--interval', type=int, default=5, help='Poll interval in seconds (5-300; default 5)')
    parser.add_argument('--lookback-hours', type=float, default=0, help='Initial history to import, only for a new data folder (default 0)')
    parser.add_argument('--once', action='store_true', help='With run: make one connection/scan attempt, then exit')
    parser.add_argument('--run-id', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.data_dir = args.data_dir.expanduser().resolve()
    if not 5 <= args.interval <= 300 or not 0 <= args.lookback_hours <= 720:
        parser.error('Interval must be 5-300 seconds and initial lookback 0-720 hours.')
    if args.once and args.action != 'run':
        parser.error('--once is only valid with run.')
    if args.subfolder is not None and any(not name.strip() for name in args.subfolder.split('/')):
        parser.error('Subfolder must contain non-empty folder names separated by /.')
    try:
        if args.action == 'run':
            result = run(args)
            if args.once:
                print(json.dumps(status(args.data_dir), indent=2))
            return result
        result = (start(args) if args.action == 'start' else stop(args.data_dir) if args.action == 'stop' else
                  inboxes() if args.action == 'inboxes' else status(args.data_dir))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, AlreadyRunning, OSError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
