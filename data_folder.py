"""Data folder: keep the directory, Citrix VDI data and package data in step with exports saved in one folder.

Save the ServiceNow exports (users such as sys_user, devices such as alm_asset or alm_hardware, and the
package list u_cmdb_software_package) and the Citrix SingleSessionMachines export in one folder, as CSV
or XLSX, under any name. Atlas recognises each file by its columns. When one changes, it runs the same
validation as Manage Database and applies it with the same backup and import history: users and devices
first, so Citrix links see new accounts, then Citrix, then packages. A users-and-devices snapshot that
would remove more than 10% of users or devices, or loses columns, waits for review. Admin only.
"""
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
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
RETRY_SECONDS = 60  # Sooner while a file is being saved, Admin is busy or the database is in use
STABLE_SECONDS = 30
KEEP_BACKUPS = 10
SUFFIXES = ('.csv', '.xlsx')
ORDER = ('directory', 'vdi', 'packages')
LABELS = {'directory': 'Users & devices', 'vdi': 'Citrix VDI', 'packages': 'Package data'}
PACKAGE_STATE = ('u_package_sub_state', 'package state')
# Citrix Studio's own columns: Name and User alone could be any list of people.
CITRIX_FIELDS = ('catalog', 'delivery_group', 'maintenance_mode', 'user_change_persistence', 'power_state')
# Asset and CI columns: Name alone could be any ServiceNow list.
DEVICE_FIELDS = {'infrastructure_itsi', 'sys_class_name', 'operational_status', 'correlation_id', 'serial_number', 'model_id',
                 'last_discovered', 'discovery_source', 'last_logon_user', 'asset_tag', 'model_category', 'last_used', 'install_status'}


class Changed(Exception):
    """An export changed while it was read: it is read again on the next look."""


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
    """('user' | 'machine' | 'vdi' | 'package' | '', why a file is left alone), from the header row.
    OSError (open elsewhere, still downloading) is raised: the file is looked at again."""
    try:
        headers = header(path)
    except OSError:
        raise
    except Exception:  # Not a CSV or workbook Atlas can read; the same file fails the same way.
        return '', 'not a CSV or XLSX export Atlas can read'
    return kind_of(headers)


def kind_of(headers):
    import directory_pair
    import package_data
    import vdi_data
    from directory_workbook import directory_columns
    if not headers:
        return '', 'no header row'
    if directory_pair.kind_of(headers) == 'user':
        return 'user', ''
    keys = {vdi_data.header_key(value) for value in headers}
    try:
        vdi_data._mapping(headers)
        if any(keys & set(vdi_data.FIELDS[field]) for field in CITRIX_FIELDS):
            return 'vdi', ''
    except ValueError:
        pass
    users = {field for _, _, field in directory_columns('user', headers)}
    if {'user_id', 'full_name'} <= users:
        return '', 'looks like a users export but has no email column; export it with email'
    names = {value.casefold() for value in headers}
    if names & set(package_data.FIELDS['short_name']) and names & set(PACKAGE_STATE):
        return 'package', ''
    machines = {field for _, _, field in directory_columns('machine', headers)}
    if 'machine_name' in machines and machines & DEVICE_FIELDS:
        return 'machine', ''
    return '', ''


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class DataFolder:
    def __init__(self, db, repo, state_path, busy=lambda: False, interval=CHECK_SECONDS, clock=time.time, settle=2,
                 default_folder=None, gate=nullcontext):
        # db/repo may be callables, so the folder follows the server's current database and repository.
        self._db, self._repo, self.state_path = db, repo, Path(state_path)
        self.busy, self.interval, self.clock, self.settle = busy, interval, clock, settle
        # Admin's change gate, held around each background import as an HTTP request holds it: an import
        # never interleaves with a deployment starting or a desk edit.
        self.gate = gate
        self.lock = threading.Lock()
        self.held = None
        self.files = {}  # (name, size, mtime) -> {'kind': ..., 'hash': ...}, so unchanged exports are not read again
        self.thread = None
        self.checked = None
        self.soon = False  # Look again in RETRY_SECONDS rather than the usual interval.
        self.stop_event, self.wake = threading.Event(), threading.Event()
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

    @contextmanager
    def locked(self):
        """For requests: a background check may be waiting for the change gate the request holds, so do not wait long."""
        if not self.lock.acquire(timeout=5):
            raise HTTPException(409, 'The folder is being checked. Try again in a moment.')
        try:
            yield
        finally:
            self.lock.release()

    def configure(self, settings):
        folder = settings.folder.strip().strip('"').strip()
        with self.locked():
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
        """Newest file of each kind first, unrecognised files, and files not ready: saved in the last 30 seconds,
        growing between two looks (a copy keeps the old modified time), or open elsewhere or still downloading."""
        found = {'user': [], 'machine': [], 'vdi': [], 'package': []}
        ignored, fresh = [], []
        candidates = {}
        for path in folder.iterdir():
            if path.suffix.casefold() in SUFFIXES and not path.name.startswith(('~$', '.')) and path.is_file():
                candidates[path] = self.signature(path)
        if self.settle and any(signature not in self.files for signature in candidates.values()):
            time.sleep(self.settle)
        for path, signature in candidates.items():
            if not signature or self.signature(path) != signature or 0 <= self.clock() - signature[2] / 1e9 < STABLE_SECONDS:
                fresh.append(path.name)
                continue
            if signature not in self.files:
                try:
                    kind, note = classify(path)
                except OSError:
                    fresh.append(path.name)
                    continue
                self.files[signature] = {'kind': kind, 'note': note}
            info = self.files[signature]
            if info['kind']:
                found[info['kind']].append(path)
            else:
                ignored.append(path.name + (f' ({info["note"]})' if info.get('note') else ''))
        self.files = {signature: info for signature, info in self.files.items() if signature in candidates.values()}
        for paths in found.values():
            paths.sort(key=lambda path: candidates[path][2], reverse=True)
        return found, sorted(ignored), sorted(fresh)

    def digest(self, paths):
        """One hash for these files' names and contents, read once per saved version."""
        h = hashlib.sha256()
        for path in paths:
            info = self.files.get(self.signature(path))
            if info is None:
                raise Changed(f'{path.name} changed while Atlas was reading it; reading it again shortly.')
            if 'hash' not in info:
                info['hash'] = file_hash(path)
            h.update(path.name.encode() + b'\0' + info['hash'].encode())
        return h.hexdigest()

    def check(self, force=False, gate=nullcontext):
        """One pass over the folder. Safe to call at any time; a pass already running is not repeated.
        Requests already hold Admin's change gate; the background thread passes it as gate."""
        if not self.lock.acquire(blocking=False):
            return self.summary()
        try:
            return self._check(force, gate)
        finally:
            self.lock.release()

    def _check(self, force, gate):
        self.checked = now()
        self.soon = False
        if not self.enabled() or not self.folder():
            return self.summary()
        folder = Path(self.folder()).expanduser()
        try:
            found, self.state['ignored'], fresh = self.scan(folder)
        except OSError:
            self.set_status('error', f'Folder not reachable: {folder}. Create it, or check the path.')
            return self.summary()
        if fresh:
            # A newer export may be half saved: importing the older one, or half of a new pair, would be wrong.
            self.soon = True
            self.overall(fresh)
            return self.summary()
        with tempfile.TemporaryDirectory(prefix='atlas_data_folder_') as work:
            for kind in ORDER:
                try:
                    getattr(self, '_' + kind)(found, Path(work), force, gate)
                except (HTTPException, Changed, OSError, sqlite3.OperationalError) as error:
                    # The data changed underneath, jobs started, an export is open or changing, or the
                    # database is in use: look again shortly.
                    self.soon = True
                    self.mark(kind, 'waiting', str(error.detail) if isinstance(error, HTTPException) else str(error) if isinstance(error, Changed)
                              else f'Could not finish yet ({error.__class__.__name__}: {error}); retrying in a minute.')
                except Exception as error:
                    # Refused until the export changes: the same file would fail the same way.
                    files = self.files_for(kind, found)
                    try:
                        h = self.digest(files) if files else None
                    except (OSError, Changed):
                        h = None
                    self.mark(kind, 'error', f'{", ".join(p.name for p in files)}: {error}', files=[p.name for p in files], hash=h)
        self.overall()
        return self.summary()

    def overall(self, fresh=()):
        """The card's headline: the most pressing state among the exports."""
        results = [entry.get('result') for entry in self.state.get('kinds', {}).values()]
        state = 'waiting' if fresh else 'error' if 'error' in results else 'held' if 'held' in results else 'waiting' if 'waiting' in results else 'synced'
        names = ', '.join(fresh)
        self.set_status(state, {'error': 'An export could not be imported; see below.',
                                'held': 'A users-and-devices snapshot is waiting for your review.',
                                'waiting': f'Waiting: {names} {"is" if len(fresh) == 1 else "are"} still being saved or in use; '
                                           'nothing is imported until it is ready.' if fresh else 'Waiting: see below.',
                                'synced': 'Up to date with the exports in the folder.'}[state])

    @staticmethod
    def files_for(kind, found):
        if kind == 'directory':
            return [paths[0] for paths in (found['user'], found['machine']) if paths]
        return found['vdi' if kind == 'vdi' else 'package'][:1]

    def copy(self, paths, work):
        """Read from copies: Excel and OneDrive may hold or rewrite the originals. A copy must match the version
        that was hashed, so what is recorded as imported is what was read."""
        folder = work / uuid4().hex
        folder.mkdir()
        copies = []
        for path in paths:
            target = folder / path.name
            shutil.copy2(path, target)
            if file_hash(target) != self.files.get(self.signature(path), {}).get('hash'):
                raise Changed(f'{path.name} changed while Atlas was reading it; reading it again shortly.')
            copies.append(target)
        return copies

    def _directory(self, found, work, force, gate):
        users, devices = found['user'], found['machine']
        if not users or not devices:
            self.discard_held()  # What was reviewed is no longer in the folder.
            if users or devices:
                have, need = (users[0].name, 'devices export (such as alm_asset)') if users else (devices[0].name, 'users export (such as sys_user)')
                self.mark('directory', 'waiting', f'Found {have}; add the {need} too. Both are needed for a directory update.', files=[have])
            else:
                self.mark('directory', 'missing', 'No users or devices export in the folder.')
            return
        files = [users[0], devices[0]]
        h = self.digest(files)
        if self.held and self.held['hash'] != h:
            self.discard_held()
        if self.held or self.handled('directory', h, force):
            return
        if self.busy():  # Imports wait for deployments and queues, as in Manage Database.
            self.soon = True
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
            # Taken first: a change made during the comparison is caught when applying, not applied over.
            expected = fingerprint(self.db)
            report = compare(self.db, candidate)
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
            self.commit_directory(str(candidate), source, report, expected, names, h, gate)
        finally:
            if held_folder:
                shutil.rmtree(held_folder, ignore_errors=True)

    def commit_directory(self, candidate, source, report, expected, names, h, gate=nullcontext):
        from database_manager import commit_directory
        with gate():
            backup = commit_directory(self.db, candidate, source, report, expected, busy=self.busy)
        counts = {t: {k: report[t][k] for k in ('added', 'removed', 'changed')} for t in ('users', 'machines')}
        summary = '; '.join(f"{label} {counts[t]['added']:,} added, {counts[t]['removed']:,} removed, {counts[t]['changed']:,} updated"
                            for t, label in (('users', 'users'), ('machines', 'devices')))
        self.mark('directory', 'applied', 'Updated: ' + summary, files=names, hash=h, handled=True, backup=backup.name)
        self.remember('directory', names, summary, backup.name)

    def _vdi(self, found, work, force, gate):
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
        with gate():
            result = vdi_data_api.commit(self.db, value)
        summary = f"{report['added']:,} added, {report['changed']:,} updated"
        self.mark('vdi', 'applied', 'Updated: ' + summary, files=[path.name], hash=h, handled=True, backup=result['backup'])
        self.remember('vdi', [path.name], summary, result['backup'])

    def _packages(self, found, work, force, gate):
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
        with gate():
            result = package_data_api.commit(self.db, value)
        summary = f"{report['added']:,} added, {report['changed']:,} updated"
        self.mark('packages', 'applied', 'Updated: ' + summary, files=[path.name], hash=h, handled=True, backup=result['backup'])
        self.remember('packages', [path.name], summary, result['backup'])

    def remember(self, kind, files, summary, backup):
        entry = {'at': now(), 'kind': kind, 'label': LABELS[kind], 'files': files, 'summary': summary, 'backup': backup}
        self.state['history'] = [entry, *self.state.get('history', [])][:50]
        self.prune(kind, backup)

    def prune(self, kind, backup):
        """Keep the newest backups each kind of import from this folder made; Manage Database imports keep their own."""
        made = [backup, *self.state.setdefault('backups', {}).get(kind, [])]
        for name in made[KEEP_BACKUPS:]:
            try:
                (self.db.parent / 'backups' / name).unlink(missing_ok=True)
            except OSError:
                pass  # Open elsewhere: it stays, and is no longer counted.
        self.state['backups'][kind] = made[:KEEP_BACKUPS]

    def apply_held(self, expected_id):
        with self.locked():
            held = self.held
            if not held:
                raise HTTPException(409, 'Nothing is waiting for review. Check the folder again.')
            if held['id'] != expected_id:
                raise HTTPException(409, 'This review is out of date. Review the latest changes before applying.')
            if self.busy():
                raise HTTPException(409, 'Finish active jobs and queues first.')
            try:
                # Only the exports that were reviewed, and only while they are still the newest in the folder.
                found, _, fresh = self.scan(Path(self.folder()).expanduser())
                current = None if fresh else self.digest(self.files_for('directory', found))
                if current != held['hash']:
                    raise HTTPException(409, 'The exports changed since this review. Atlas compares them again within a minute.')
                self.commit_directory(held['candidate'], held['source'], held['report'], held['fingerprint'], held['files'], held['hash'])
            except (HTTPException, OSError, Changed) as error:
                self.discard_held()  # Prepared against files or data that have since changed: prepare it again.
                self.mark('directory', 'waiting', 'The exports or the directory changed; comparing again.')
                self.soon = True
                self.wake.set()
                self.save()
                if isinstance(error, HTTPException):
                    raise
                raise HTTPException(409, 'The exports changed since this review. Atlas compares them again within a minute.')
            self.discard_held()
            self.overall()
            return self.summary()

    def run(self):
        delay = 5  # First look once Admin has started.
        while True:
            self.wake.wait(delay)
            self.wake.clear()
            if self.stop_event.is_set():
                return
            try:
                self.check(gate=self.gate)
            except Exception as error:  # A bad export or a full disk never stops the watcher.
                try:
                    self.set_status('error', f'Data folder check failed: {error}')
                except Exception:
                    pass
            delay = RETRY_SECONDS if self.soon else self.interval

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self.run, name='atlas-data-folder', daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.discard_held()


def default_exports_folder():
    return next((folder for folder in FOLDERS if os.path.isdir(folder)), FOLDERS[0])


def register(app, wmi, check_token, busy, state_path):
    loops = []

    @contextmanager
    def admin_gate():
        """Hold Admin's change gate (database_manager) from the background thread, as a request would."""
        gate = getattr(app.state, 'mutation_gate', None)
        if gate is None or not loops or loops[0].is_closed():
            yield
            return
        asyncio.run_coroutine_threadsafe(gate.acquire(), loops[0]).result()
        try:
            yield
        finally:
            loops[0].call_soon_threadsafe(gate.release)

    folder = DataFolder(lambda: wmi.MASTER_DB, lambda: wmi.REPO, state_path, busy, default_folder=default_exports_folder, gate=admin_gate)

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
    async def begin():
        loops.append(asyncio.get_running_loop())
        folder.start()

    @app.on_event('shutdown')
    def end():
        folder.close()

    return folder
