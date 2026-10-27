"""Data folder: keep the directory, Citrix VDI data and package data in step with exports saved in one folder.

Save the ServiceNow exports (users such as sys_user, devices such as alm_asset or alm_hardware, and the
package list u_cmdb_software_package) and the Citrix SingleSessionMachines export in one folder, as CSV
or XLSX, under any name. Atlas recognises each file by its columns. When one changes, it runs the same
validation as Manage Database and applies it with the same backup and import history: users and devices
first, so Citrix links see new accounts, then Citrix, then packages. A users-and-devices snapshot that
would remove more than 10% of users or devices, or loses columns, waits for review. Admin only.
"""
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from atlas_store import ClosingConnection

SOURCE = 'Data folder'
FOLDERS = (r'C:\AtlasXL', r'C:\AxisXL')  # The first that exists is used until a person saves another folder
DEFAULT_FOLDER = FOLDERS[0]
CHECK_SECONDS = 15 * 60  # Exports change a few times a week; Check now imports straight away
STABLE_SECONDS = 30
KEEP_BACKUPS = 10
SUFFIXES = ('.csv', '.xlsx')
ORDER = ('directory', 'vdi', 'packages')
LABELS = {'directory': 'Users & devices', 'vdi': 'Citrix VDI', 'packages': 'Package data'}
PACKAGE_STATE = ('u_package_sub_state', 'package state')
READ_ERRORS = (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError, csv.Error, UnicodeError)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    folder: str = Field(default='', max_length=1024)
    enabled: bool = False
    # Off: a users-and-devices snapshot that removes many records is applied without asking.
    review_large: bool = True


class ApplyReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=64)


def header(path):
    from directory_pair import rows
    found = rows(path)
    try:
        first = next(found, None)
    finally:
        found.close()
    return [str(value).strip() for value in first or []]


def classify(path):
    """'user', 'machine', 'vdi', 'package' or '' (not an export Atlas imports), from the header row."""
    import directory_pair
    import package_data
    import vdi_data
    try:
        headers = header(path)
    except READ_ERRORS:
        return ''
    if not headers:
        return ''
    kind = directory_pair.kind_of(headers)
    if kind == 'user':
        return kind
    # Citrix and package exports also have a Name column, which alone would read as devices.
    try:
        vdi_data._mapping(headers)
        return 'vdi'
    except ValueError:
        pass
    names = {value.casefold() for value in headers}
    if names & set(package_data.FIELDS['short_name']) and names & set(PACKAGE_STATE):
        return 'package'
    return kind


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class DataFolder:
    def __init__(self, db, repo, state_path, busy=lambda: False, interval=CHECK_SECONDS, clock=time.time, settle=2, default_folder=None):
        # db/repo may be callables, so the folder follows the server's current database and repository.
        self._db, self._repo, self.state_path = db, repo, Path(state_path)
        self.busy, self.interval, self.clock, self.settle = busy, interval, clock, settle
        self.lock = threading.Lock()
        self.held = None
        self.files = {}  # (name, size, mtime) -> {'kind': ..., 'hash': ...}, so unchanged exports are not read again
        self.thread = None
        self.checked = None
        self.stop_event = threading.Event()
        # Until a person saves settings, the built-in folder is used and the data folder is on.
        self.default_folder = default_folder
        self.state = self.load()
        self.state.setdefault('status', {'state': 'checking', 'message': 'Checking the exports folder…'} if self.uses_default() else
                                        {'state': 'off', 'message': 'Choose the folder with the exports, then turn the data folder on.'})

    def uses_default(self):
        return 'folder' not in self.state and self.default_folder is not None

    def folder(self):
        return str(self.default_folder()) if self.uses_default() else self.state.get('folder', '')

    def enabled(self):
        return self.uses_default() or bool(self.state.get('enabled'))

    @property
    def db(self):
        return Path(self._db() if callable(self._db) else self._db)

    @property
    def repo(self):
        return self._repo() if callable(self._repo) else self._repo

    # Settings and results survive restarts; a held review does not (it is prepared again on the next check).
    def load(self):
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.state_path)

    def configure(self, settings):
        folder = settings.folder.strip().strip('"').strip()
        with self.lock:
            if folder != self.folder():
                self.state['kinds'] = {}  # Files in another folder are new to Atlas.
            self.state.update(folder=folder, enabled=settings.enabled and bool(folder), review_large=settings.review_large)
            self.discard_held()
            self.set_status('checking' if self.state['enabled'] else 'off',
                            'Checking the folder…' if self.state['enabled'] else 'The data folder is off.')
        return self.summary()

    def set_status(self, state, message):
        self.state['status'] = {'state': state, 'message': message, 'at': now()}
        self.save()

    def summary(self):
        held = self.held and {key: self.held[key] for key in ('id', 'kind', 'files', 'reason', 'report')}
        return {'folder': self.folder() or DEFAULT_FOLDER, 'enabled': self.enabled(),
                'review_large': self.state.get('review_large', True), 'status': dict(self.state.get('status', {})),
                'checked': self.checked, 'kinds': [{'kind': kind, 'label': LABELS[kind], **self.state.get('kinds', {}).get(kind, {})} for kind in ORDER],
                'ignored': self.state.get('ignored', []), 'history': self.state.get('history', [])[:20], 'held': held}

    def mark(self, kind, result, message, **extra):
        entry = {'result': result, 'message': message, 'at': now(), **extra}
        previous = self.state.setdefault('kinds', {}).get(kind, {})
        if 'hash' not in entry and result in ('waiting', 'missing') and previous.get('hash'):
            entry['hash'], entry['handled'] = previous['hash'], previous.get('handled')  # Keep what was last applied.
        self.state['kinds'][kind] = entry

    def handled(self, kind, h, force):
        """Whether these exact files were already applied, found unchanged or (unless forced) refused."""
        last = self.state.get('kinds', {}).get(kind, {})
        return last.get('hash') == h and (last.get('handled') or (last.get('result') == 'error' and not force))

    def discard_held(self):
        if self.held:
            shutil.rmtree(self.held['folder'], ignore_errors=True)
        self.held = None

    @staticmethod
    def signature(path):
        try:
            stat = path.stat()
        except OSError:
            return None
        return (path.name, stat.st_size, stat.st_mtime_ns)

    def scan(self, folder):
        """Newest file of each kind first. Files still being saved or copied are left until they settle:
        saved in the last 30 seconds, or growing between two looks (a copy keeps the old modified time)."""
        found = {'user': [], 'machine': [], 'vdi': [], 'package': []}
        ignored, fresh = [], []
        candidates = {}
        for path in folder.iterdir():
            if path.suffix.casefold() in SUFFIXES and not path.name.startswith(('~$', '.')) and path.is_file():
                candidates[path] = self.signature(path)
        if any(signature not in self.files for signature in candidates.values()) and self.settle:
            time.sleep(self.settle)
        for path, signature in candidates.items():
            if not signature or self.signature(path) != signature or self.clock() - signature[2] / 1e9 < STABLE_SECONDS:
                fresh.append(path.name)
                continue
            if signature not in self.files:
                self.files[signature] = {'kind': classify(path)}
            kind = self.files[signature]['kind']
            (found[kind] if kind else ignored).append(path)
        self.files = {signature: info for signature, info in self.files.items() if signature in candidates.values()}
        for paths in found.values():
            paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return found, sorted(path.name for path in ignored), fresh

    def digest(self, paths):
        """One hash for these files' names and contents, read once per saved version."""
        h = hashlib.sha256()
        for path in paths:
            info = self.files.setdefault(self.signature(path), {'kind': ''})
            if 'hash' not in info:
                info['hash'] = file_hash(path)
            h.update(path.name.encode() + b'\0' + info['hash'].encode())
        return h.hexdigest()

    def check(self, force=False):
        """One pass over the folder. Safe to call at any time; a pass already running is not repeated."""
        if not self.lock.acquire(blocking=False):
            return self.summary()
        try:
            return self._check(force)
        finally:
            self.lock.release()

    def _check(self, force):
        self.checked = now()
        if not self.enabled() or not self.folder():
            return self.summary()
        folder = Path(self.folder()).expanduser()
        if not folder.is_dir():
            self.set_status('error', f'Folder not reachable: {folder}. Create it, or check the path.')
            return self.summary()
        found, self.state['ignored'], fresh = self.scan(folder)
        with tempfile.TemporaryDirectory(prefix='atlas_data_folder_') as work:
            for kind in ORDER:
                try:
                    getattr(self, '_' + kind)(found, Path(work), force)
                except HTTPException as error:  # The data changed underneath, or jobs started: try again next time.
                    self.mark(kind, 'waiting', str(error.detail))
                except OSError as error:  # Open in Excel, being synced, or just removed: try again next time.
                    self.mark(kind, 'waiting', f'Could not read the export yet ({error.__class__.__name__}); retrying.')
                except READ_ERRORS + (sqlite3.Error,) as error:
                    # Refused until the export changes: the same file would fail the same way.
                    files = self.files_for(kind, found)
                    try:
                        h = self.digest(files) if files else None
                    except OSError:
                        h = None
                    self.mark(kind, 'error', f'{", ".join(p.name for p in files)}: {error}', files=[p.name for p in files], hash=h)
        self.overall(fresh)
        return self.summary()

    def overall(self, fresh=()):
        """The card's headline: the most pressing state among the exports."""
        results = [entry.get('result') for entry in self.state.get('kinds', {}).values()]
        state = 'error' if 'error' in results else 'held' if 'held' in results else 'waiting' if 'waiting' in results or fresh else 'synced'
        self.set_status(state, {'error': 'An export could not be imported; see below.',
                                'held': 'A users-and-devices snapshot is waiting for your review.',
                                'waiting': 'Waiting: ' + (', '.join(fresh) + ' still being saved.' if fresh else 'see below.'),
                                'synced': 'Up to date with the exports in the folder.'}[state])

    @staticmethod
    def files_for(kind, found):
        if kind == 'directory':
            return [paths[0] for paths in (found['user'], found['machine']) if paths]
        return found['vdi' if kind == 'vdi' else 'package'][:1]

    def copy(self, paths, work):
        """Read from copies: Excel and OneDrive may hold or rewrite the originals."""
        folder = work / uuid4().hex
        folder.mkdir()
        copies = []
        for path in paths:
            shutil.copy2(path, folder / path.name)
            copies.append(folder / path.name)
        return copies

    def _directory(self, found, work, force):
        users, devices = found['user'], found['machine']
        if not users or not devices:
            if users or devices:
                have, need = (users[0].name, 'devices export (such as alm_asset)') if users else (devices[0].name, 'users export (such as sys_user)')
                self.mark('directory', 'waiting', f'Found {have}; add the {need} too. Both are needed for a directory update.', files=[have])
            else:
                self.mark('directory', 'missing', 'No users or devices export in the folder.')
            return
        files = [users[0], devices[0]]
        h = self.digest(files)
        if self.held and self.held['hash'] == h:
            return
        if self.handled('directory', h, force):
            return
        self.discard_held()
        if self.busy():  # Imports wait for deployments and queues, as in Manage Database.
            self.mark('directory', 'waiting', 'Deployments or queue jobs are running; users and devices update once they finish.',
                      files=[p.name for p in files])
            return
        from database_manager import compare, fingerprint
        from directory_pair import combine
        import directory_exports
        from refresh_directory import prepare
        source = f'{SOURCE} · {files[0].name} + {files[1].name}'
        copies = self.copy(files, work)
        held_folder = Path(tempfile.mkdtemp(prefix='atlas_data_folder_directory_'))
        try:
            combine(copies[0], copies[1], held_folder / 'extract.xlsx')
            candidate = held_folder / 'candidate.db'
            prepare(held_folder / 'extract.xlsx', candidate)
            with sqlite3.connect(candidate, factory=ClosingConnection) as c:
                if directory_exports.exists(c):
                    c.execute('update directory_export_sheets set source_file=?', (source[len(SOURCE) + 3:],))
            report = compare(self.db, candidate)
            expected = fingerprint(self.db)
            names = [p.name for p in files]
            changes = sum(report[t][k] for t in ('users', 'machines') for k in ('added', 'removed', 'changed'))
            changes += report['relationships']['added'] + report['relationships']['removed']
            if not changes:
                self.mark('directory', 'unchanged', 'Users and devices already match these exports.', files=names, hash=h, handled=True)
                return
            if report.get('review') and self.state.get('review_large', True):
                self.held = {'id': uuid4().hex, 'kind': 'directory', 'files': names, 'hash': h, 'reason': ' '.join(report['review']),
                             'report': report, 'folder': str(held_folder), 'candidate': str(candidate), 'source': source, 'fingerprint': expected}
                held_folder = None  # Kept until applied or replaced.
                self.mark('directory', 'held', 'Large change: waiting for your review below.', files=names, hash=h)
                return
            self.commit_directory(str(candidate), source, report, expected, names, h)
        finally:
            if held_folder:
                shutil.rmtree(held_folder, ignore_errors=True)

    def commit_directory(self, candidate, source, report, expected, names, h):
        from database_manager import commit_directory
        backup = commit_directory(self.db, candidate, source, report, expected, busy=self.busy)
        counts = {t: {k: report[t][k] for k in ('added', 'removed', 'changed')} for t in ('users', 'machines')}
        summary = '; '.join(f"{label} {counts[t]['added']:,} added, {counts[t]['removed']:,} removed, {counts[t]['changed']:,} updated"
                            for t, label in (('users', 'users'), ('machines', 'devices')))
        self.mark('directory', 'applied', 'Updated: ' + summary, files=names, hash=h, handled=True, backup=backup.name)
        self.remember('directory', names, summary, backup.name)
        self.state['directory_backups'] = [backup.name, *self.state.get('directory_backups', [])]
        self.prune()

    def _vdi(self, found, work, force):
        import vdi_data_api
        paths = found['vdi']
        if not paths:
            self.mark('vdi', 'missing', 'No Citrix SingleSessionMachines export in the folder.')
            return
        path = paths[0]
        h = self.digest([path])
        if self.handled('vdi', h, force):
            return
        copy, = self.copy([path], work)
        # Update mode: supplied VDIs are replaced and omitted ones kept, as Manage Database does by default.
        value = vdi_data_api.prepare(self.db, copy.read_bytes(), path.name, False, source=f'{SOURCE} · {path.name}')
        report = value['report']
        if not (report['added'] or report['changed'] or report['removed']):
            self.mark('vdi', 'unchanged', 'Citrix VDI data already matches this export.', files=[path.name], hash=h, handled=True)
            return
        result = vdi_data_api.commit(self.db, value)
        summary = f"{report['added']:,} added, {report['changed']:,} updated"
        self.mark('vdi', 'applied', 'Updated: ' + summary, files=[path.name], hash=h, handled=True, backup=result['backup'])
        self.remember('vdi', [path.name], summary, result['backup'])

    def _packages(self, found, work, force):
        import package_data_api
        paths = found['package']
        if not paths:
            self.mark('packages', 'missing', 'No package export (u_cmdb_software_package) in the folder.')
            return
        path = paths[0]
        h = self.digest([path])
        if self.handled('packages', h, force):
            return
        if path.suffix.casefold() != '.csv':
            self.mark('packages', 'error', f'{path.name}: save the package export as CSV.', files=[path.name], hash=h)
            return
        copy, = self.copy([path], work)
        value = package_data_api.prepare(self.db, self.repo, copy.read_bytes(), f'{SOURCE} · {path.name}')
        report = value['report']
        if not (report['added'] or report['changed']):
            self.mark('packages', 'unchanged', 'Package data already matches this export.', files=[path.name], hash=h, handled=True)
            return
        result = package_data_api.commit(self.db, value)
        summary = f"{report['added']:,} added, {report['changed']:,} updated"
        self.mark('packages', 'applied', 'Updated: ' + summary, files=[path.name], hash=h, handled=True, backup=result['backup'])
        self.remember('packages', [path.name], summary, result['backup'])

    def remember(self, kind, files, summary, backup):
        entry = {'at': now(), 'kind': kind, 'label': LABELS[kind], 'files': files, 'summary': summary, 'backup': backup}
        self.state['history'] = [entry, *self.state.get('history', [])][:50]

    def prune(self):
        """Keep the newest full-database backups this folder made; Manage Database imports keep their own."""
        made = self.state.get('directory_backups', [])
        for name in made[KEEP_BACKUPS:]:
            (Path(self.db).parent / 'backups' / name).unlink(missing_ok=True)
        self.state['directory_backups'] = made[:KEEP_BACKUPS]

    def apply_held(self, expected_id):
        with self.lock:
            held = self.held
            if not held:
                raise HTTPException(409, 'Nothing is waiting for review. Check the folder again.')
            if held['id'] != expected_id:
                raise HTTPException(409, 'This review is out of date. Review the latest changes before applying.')
            if self.busy():
                raise HTTPException(409, 'Finish active jobs and queues first.')
            try:
                self.commit_directory(held['candidate'], held['source'], held['report'], held['fingerprint'], held['files'], held['hash'])
            except HTTPException:
                self.discard_held()  # Prepared against data that has since changed: prepare it again.
                self.state['kinds']['directory'] = {'result': 'waiting', 'message': 'The directory changed; comparing again.', 'at': now()}
                self.save()
                raise
            self.discard_held()
            self.overall()
            return self.summary()

    def run(self):
        self.stop_event.wait(5)  # First look once Admin has started, then every CHECK_SECONDS.
        while not self.stop_event.is_set():
            try:
                self.check()
            except Exception as error:  # A bad export never stops the watcher.
                self.set_status('error', f'Data folder check failed: {error}')
            self.stop_event.wait(self.interval)

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self.run, name='atlas-data-folder', daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()
        self.discard_held()


def default_exports_folder():
    return next((folder for folder in FOLDERS if os.path.isdir(folder)), FOLDERS[0])


def register(app, wmi, check_token, busy, state_path):
    folder = DataFolder(lambda: wmi.MASTER_DB, lambda: wmi.REPO, state_path, busy, default_folder=default_exports_folder)

    @app.get('/api/data-folder')
    def status():
        return folder.summary()

    @app.post('/api/data-folder/settings')
    def settings(body: Settings, request: Request):
        check_token(request)
        folder.configure(body)
        return folder.check(force=True)

    @app.post('/api/data-folder/check')
    def check(request: Request):
        check_token(request)
        return folder.check(force=True)

    @app.post('/api/data-folder/apply')
    def apply(body: ApplyReview, request: Request):
        check_token(request)
        return folder.apply_held(body.id)

    @app.on_event('startup')
    def begin():
        folder.start()

    @app.on_event('shutdown')
    def end():
        folder.close()

    return folder
