"""Import folder: ServiceNow and Citrix exports saved in one folder update the database by themselves.

Save the exports in one folder (C:\\AtlasXL by default): the users and devices exports (sys_user,
alm_asset), the Citrix SingleSessionMachines export and the ServiceNow package CSV
(u_cmdb_software_package). Atlas checks the folder every minute and recognises each file by its
column headers, not its name. When the newest file of a kind changes, it runs the same import as
Manage Database, with the same backup and import history:

- users + devices: a full directory snapshot. One that removes more than 10% of the users or the
  devices waits for review in Manage Database (Ask before large removals). It also waits while
  deployments or queue jobs run.
- Citrix VDI: replaces the VDIs in the file and keeps the others (the default Citrix mode).
- packages: adds and updates package data; nothing is removed.
- new joiner requests (the requests workbook, one sheet per desk): replaces the requests Atlas keeps
  for each desk and adds a persona for any new desk (persona_access).

A file that cannot be imported is reported and not read again until it is saved again.
Admin only: the Demo just sees the updated database.
"""
import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from atlas_store import ClosingConnection

DEFAULT_FOLDER = r'C:\AtlasXL'
STABLE_SECONDS = 30
FIRST_CHECK_SECONDS = 5
LARGE_REMOVAL = .1
KEEP_HISTORY = 30
LABELS = {'users': 'Users', 'devices': 'Devices', 'vdi': 'Citrix VDI', 'packages': 'Packages', 'access': 'New joiner requests'}
GROUPS = {'directory': ('users', 'devices'), 'vdi': ('vdi',), 'packages': ('packages',), 'access': ('access',)}
GROUP_LABELS = {'directory': 'Users & devices', 'vdi': 'Citrix VDI', 'packages': 'Package data', 'access': 'New joiner requests'}
PACKAGE_STATES = {'u_package_sub_state', 'package state'}
DEVICE_FIELDS = {'infrastructure_itsi', 'sys_class_name', 'operational_status', 'correlation_id', 'serial_number',
                 'model_id', 'last_discovered', 'discovery_source', 'last_logon_user', 'asset_tag', 'model_category',
                 'last_used', 'install_status'}


class ExportChanged(OSError):
    """The export no longer matches the version selected by the watcher; retry it without writing."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def default_folder():
    return os.environ.get('ATLAS_IMPORT_FOLDER') or DEFAULT_FOLDER


def headers(path):
    """The header row of a .csv, or of the first non-empty sheet of an .xlsx."""
    path = Path(path)
    with path.open('rb') as handle:
        head = handle.read(65536)
    if head.startswith(b'PK\x03\x04'):
        from directory_workbook import iter_rows, workbook_parts, workbook_scope

        @workbook_scope
        def first():
            for _, part in workbook_parts(path):
                for _, row in iter_rows(path, part, raw=True):
                    if any(str(value).strip() for value in row):
                        return [str(value) for value in row]
            return []
        return first()
    encoding = 'utf-16' if head.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        text = head.decode(encoding)
    except UnicodeDecodeError:
        text = head.decode('utf-8-sig' if encoding == 'utf-16' else 'cp1252', errors='replace')
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().casefold().startswith('sep='):
        lines.pop(0)
    if not lines:
        return []
    try:
        delimiter = csv.Sniffer().sniff(lines[0], delimiters=',;\t').delimiter
    except csv.Error:
        delimiter = ','
    return next(csv.reader(io.StringIO(lines[0]), delimiter=delimiter), [])


def kind_of(names):
    """'vdi', 'packages', 'users', 'devices' or '' from a header row. The exports share column
    names (Name, User, State), so the most specific export is recognised first."""
    import vdi_data
    from directory_pair import kind_of as directory_kind
    names = [str(name).strip() for name in names]
    keys = {vdi_data.header_key(name) for name in names}
    fields = vdi_data.FIELDS
    if keys & set(fields['original_name']) and keys & set(fields['users']) and keys & set(fields['catalog'] + fields['delivery_group']):
        return 'vdi'
    lowered = {name.casefold() for name in names}
    if lowered & PACKAGE_STATES and lowered & {'name', 'short package name', 'short_package_name'}:
        return 'packages'
    kind = directory_kind(names)
    if kind == 'user':
        return 'users'
    if kind == 'machine':
        from directory_workbook import directory_columns
        # Manual imports explicitly select a device file; an automatic folder cannot trust Name alone.
        if {field for _, _, field in directory_columns('machine', names)} & DEVICE_FIELDS:
            return 'devices'
    return ''


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    folder: str = Field(default='', max_length=1024)
    enabled: bool = True
    # Off: every users & devices snapshot is applied straight away, however many records it removes.
    review_large: bool = True


class HeldReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=64)


class ImportFolder:
    def __init__(self, db, state_path, busy=lambda: False, repo=lambda: None, interval=60, clock=time.time, access=None):
        # db may be a callable, so the folder follows the server's current database path.
        # access returns the new joiner requests store and the persona store.
        self._db, self.state_path, self.busy, self.repo, self.access = db, Path(state_path), busy, repo, access
        self.interval, self.clock = interval, clock
        self.lock = threading.Lock()
        self.kinds = {}
        self.pending = []
        self.held = None
        self.checked = None
        self.thread = None
        self.stop_event = threading.Event()
        self.state = self.load()
        self.state.setdefault('folder', default_folder())
        self.state.setdefault('enabled', True)
        self.state.setdefault('review_large', True)
        self.state.setdefault('groups', {})
        self.state.setdefault('status', {'state': 'checking', 'message': 'Checking the import folder…'})

    @property
    def db(self):
        return Path(self._db() if callable(self._db) else self._db)

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

    def set_status(self, state, message):
        self.state['status'] = {'state': state, 'message': message, 'at': now()}
        self.save()

    def configure(self, settings):
        folder = settings.folder.strip().strip('"').strip()
        with self.lock:
            self.drop_held()
            if folder != self.state.get('folder'):
                self.state.update(groups={}, files=[])
                self.kinds.clear()
                self.pending = []
            self.state.update(folder=folder, enabled=settings.enabled and bool(folder), review_large=settings.review_large)
            if self.state['enabled']:
                self.set_status('checking', 'Checking the import folder…')
            else:
                self.set_status('off', 'Import folder is off.' if folder else 'Choose the folder where you save the exports.')
        return self.summary()

    def summary(self):
        held = self.held and {key: self.held[key] for key in ('id', 'reason', 'files', 'report')}
        return {'folder': self.state.get('folder', ''), 'enabled': bool(self.state.get('enabled')),
                'review_large': self.state.get('review_large', True), 'status': dict(self.state.get('status', {})),
                'checked': self.checked, 'files': self.state.get('files', []), 'groups': self.state.get('groups', {}),
                'held': held, 'history': self.state.get('history', [])[:15]}

    def record(self, group, signature, result, message, **extra):
        entry = {'result': result, 'message': message, 'at': now(), 'signature': signature, **extra}
        self.state['groups'][group] = entry
        if result in ('applied', 'error', 'skipped'):
            files = extra.get('files', [])
            self.state['history'] = [{'at': entry['at'], 'kind': GROUP_LABELS[group], 'files': files, 'result': result,
                                      'message': message, 'backup': extra.get('backup')},
                                     *self.state.get('history', [])][:KEEP_HISTORY]

    # Finding the exports.
    def scan(self, folder):
        found = []
        self.pending = []
        for path in sorted(folder.iterdir()):
            if path.suffix.casefold() not in ('.csv', '.xlsx') or path.name.startswith(('~$', '.')):
                continue
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
            except OSError:
                self.pending.append(path.name)
                continue
            signature = (path.name, stat.st_mtime_ns, stat.st_size)
            item = {'path': path, 'name': path.name, 'kind': '', 'signature': list(signature),
                    'modified': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec='seconds'), 'size': stat.st_size}
            if self.clock() - stat.st_mtime < STABLE_SECONDS:
                self.pending.append(path.name)
            else:
                try:
                    if signature not in self.kinds:
                        try:
                            kind = kind_of(headers(path)) or (path.suffix.casefold() == '.xlsx' and self.access_kind(path)) or ''
                        except OSError:
                            raise  # Locked or temporarily unavailable: do not cache an unrecognised file.
                        except Exception:
                            kind = ''
                        self.ensure_current(item)
                        self.kinds[signature] = kind
                    self.ensure_current(item)
                    item['kind'] = self.kinds[signature]
                except OSError:
                    self.kinds.pop(signature, None)
                    self.pending.append(path.name)
            found.append(item)
        seen = {tuple(item['signature']) for item in found}
        self.kinds = {signature: kind for signature, kind in self.kinds.items() if signature in seen}
        newest = {}
        for item in found:
            if item['kind'] and (item['kind'] not in newest or item['signature'][1] > newest[item['kind']]['signature'][1]):
                newest[item['kind']] = item
        for item in found:
            item['used'] = bool(item['kind']) and newest.get(item['kind']) is item
        self.state['files'] = [{k: v for k, v in item.items() if k not in ('path', 'signature')} for item in found]
        return newest

    def check(self, force=False):
        """One pass over the folder. Safe to call at any time."""
        if not self.lock.acquire(blocking=False):
            return self.summary()
        try:
            return self._check(force)
        finally:
            self.lock.release()

    def _check(self, force):
        self.checked = now()
        if not self.state.get('enabled') or not self.state.get('folder'):
            return self.summary()
        folder = Path(self.state['folder']).expanduser()
        if not folder.is_dir():
            self.state['files'] = []
            self.set_status('empty', f'Create {folder} and save the exports there; Atlas imports them within a minute.')
            return self.summary()
        try:
            newest = self.scan(folder)
        except OSError as error:
            self.set_status('waiting', f'Could not read the import folder yet ({error.__class__.__name__}); retrying.')
            return self.summary()
        if self.pending:
            message = f'Waiting for {", ".join(self.pending)}: files were just saved or are temporarily unreadable. Atlas will retry.'
            for entry in self.state['groups'].values():
                if entry.get('result') in ('held', 'waiting'):
                    entry.update(result='waiting', message=message, at=now())
            self.drop_held()
            self.set_status('waiting', message)
            return self.summary()
        if not newest:
            self.set_status('empty', f'No exports recognised in {folder} yet. Save the users, devices, Citrix and package exports or the new joiner requests workbook there.')
            return self.summary()
        # Directory first: Citrix links and package owners are matched against the updated directory.
        for group in GROUPS:
            items = [newest.get(kind) for kind in GROUPS[group]]
            if not any(items):
                self.state['groups'].pop(group, None)
                continue
            if group == 'directory' and not all(items):
                missing = 'devices' if items[0] else 'users'
                self.state['groups'][group] = {'result': 'waiting', 'message': f'Save the {missing} export too; users and devices are imported together.', 'at': now()}
                continue
            signature = [item['signature'] for item in items]
            last = self.state['groups'].get(group) or {}
            if last.get('signature') == signature:
                result = last.get('result')
                # Imported or skipped files are read again only once saved again; Check now retries errors.
                # A review lost with a restart is prepared again.
                if result in ('applied', 'skipped') or (result == 'error' and not force) or (result == 'held' and self.held):
                    continue
            fresh = [item['name'] for item in items if self.clock() - item['signature'][1] / 1e9 < STABLE_SECONDS]
            if fresh:
                self.state['groups'][group] = {'result': 'waiting', 'message': f'{", ".join(fresh)} was just saved; reading it in a moment.',
                                               'at': now(), 'files': [item['name'] for item in items]}
                continue
            getattr(self, 'import_' + group)(items, signature)
        return self.finish()

    def finish(self):
        groups = self.state['groups']
        results = {group: entry.get('result') for group, entry in groups.items()}
        for state, result in (('error', 'error'), ('held', 'held'), ('waiting', 'waiting')):
            group = next((g for g, r in results.items() if r == result), None)
            if group:
                message = 'waiting for your review below.' if state == 'held' else groups[group]['message']
                self.set_status(state, f'{GROUP_LABELS[group]}: {message}')
                return self.summary()
        done = [f'{GROUP_LABELS[g]} from {", ".join(groups[g].get("files", []))}' for g in GROUPS if g in groups]
        self.set_status('synced', 'Up to date: ' + '; '.join(done) + '.')
        return self.summary()

    def copies(self, items, work):
        paths = []
        for item in items:
            self.ensure_current(item)
            copy = Path(work) / item['name']
            shutil.copy2(item['path'], copy)
            self.ensure_current(item)
            paths.append(copy)
        for item in items:
            self.ensure_current(item)
        return paths

    @staticmethod
    def ensure_current(item):
        stat = Path(item['path']).stat()
        if [item['name'], stat.st_mtime_ns, stat.st_size] != item['signature']:
            raise ExportChanged(f'{item["name"]} changed while being read')

    # Users & devices: the Manage Database snapshot import.
    def import_directory(self, items, signature):
        import directory_exports
        from database_manager import apply_directory, compare, fingerprint
        from directory_pair import combine
        from refresh_directory import prepare
        files = [item['name'] for item in items]
        if self.busy():
            self.state['groups']['directory'] = {'result': 'waiting', 'message': 'Deployments or queue jobs are running; the directory updates once they finish.', 'at': now(), 'files': files}
            return
        self.drop_held()
        work = tempfile.mkdtemp(prefix='atlas_import_folder_')
        keep = False
        try:
            try:
                users, devices = self.copies(items, work)
            except OSError as error:
                self.state['groups']['directory'] = {'result': 'waiting', 'message': f'Could not open the exports yet ({error.__class__.__name__}); retrying.', 'at': now(), 'files': files}
                return
            expected = fingerprint(self.db)
            source = Path(work) / 'extract.xlsx'
            candidate = Path(work) / 'candidate.db'
            try:
                combine(users, devices, source)
                prepare(source, candidate)
            except (ValueError, KeyError, IndexError, StopIteration, zipfile.BadZipFile, sqlite3.Error) as error:
                self.record('directory', signature, 'error', str(error) or 'The exports could not be read.', files=files)
                return
            name = (files[0] + ' + ' + files[1])[:200]
            with sqlite3.connect(candidate, factory=ClosingConnection) as c:
                if directory_exports.exists(c):
                    c.execute('update directory_export_sheets set source_file=?', (name,))
            report = compare(self.db, candidate)
            removed = [f'{report[t]["removed"]:,} of {report[t]["before"]:,} {label}' for t, label in (('users', 'users'), ('machines', 'devices'))
                       if report[t]['removed'] > report[t]['before'] * LARGE_REMOVAL]
            counts = {t: {k: report[t][k] for k in ('before', 'after', 'added', 'removed', 'changed')} for t in ('users', 'machines')}
            if removed and self.state.get('review_large', True):
                reason = 'This snapshot removes ' + ' and '.join(removed) + '. Check that the exports are complete, then apply or skip it.'
                self.held = {'id': uuid4().hex, 'reason': reason, 'files': files, 'signature': signature, 'work': work,
                             'candidate': str(candidate), 'source': name, 'report': report, 'fingerprint': expected, 'counts': counts}
                keep = True
                self.record('directory', signature, 'held', reason, files=files, counts=counts)
                return
            self.apply_directory_candidate(candidate, name, report, expected, signature, files, counts, apply_directory)
        finally:
            if not keep:
                shutil.rmtree(work, ignore_errors=True)

    def apply_directory_candidate(self, candidate, name, report, expected, signature, files, counts, apply_directory):
        try:
            # Not behind the HTTP mutation gate: jobs are checked again inside the write.
            backup = apply_directory(self.db, candidate, name, report, expected, busy=self.busy)
        except HTTPException as error:
            self.state['groups']['directory'] = {'result': 'waiting', 'message': f'{error.detail} Trying again.', 'at': now(), 'files': files}
            return False
        users, machines = counts['users'], counts['machines']
        message = (f'{users["after"]:,} users (+{users["added"]:,} / −{users["removed"]:,}), '
                   f'{machines["after"]:,} devices (+{machines["added"]:,} / −{machines["removed"]:,}).')
        self.record('directory', signature, 'applied', message, files=files, counts=counts, backup=Path(backup).name)
        return True

    def drop_held(self):
        if self.held:
            shutil.rmtree(self.held['work'], ignore_errors=True)
            self.held = None

    def apply_held(self, expected_id):
        from database_manager import apply_directory
        with self.lock:
            held = self.held
            if not held:
                raise HTTPException(409, 'Nothing is waiting for review. Check the folder again.')
            if held['id'] != expected_id:
                raise HTTPException(409, 'This review is out of date. Review the latest snapshot before applying.')
            if self.busy():
                raise HTTPException(409, 'Finish active jobs and queues first.')
            try:
                applied = self.apply_directory_candidate(held['candidate'], held['source'], held['report'], held['fingerprint'],
                                                         held['signature'], held['files'], held['counts'], apply_directory)
            finally:
                self.drop_held()
            if not applied:
                raise HTTPException(409, self.state['groups']['directory']['message'] + ' Atlas prepares a fresh review on the next check.')
            return self.finish()

    def skip_held(self, expected_id):
        with self.lock:
            held = self.held
            if not held or held['id'] != expected_id:
                raise HTTPException(409, 'This review is out of date.')
            self.record('directory', held['signature'], 'skipped', 'Skipped; Atlas waits for the next saved users or devices export.', files=held['files'])
            self.drop_held()
            return self.finish()

    # Citrix VDI and package data: the Manage Database imports, applied straight away.
    def read(self, item, limit):
        self.ensure_current(item)
        if item['size'] > limit:
            raise ValueError(f'{item["name"]} is larger than {limit // (1024 * 1024)} MB.')
        with Path(item['path']).open('rb') as source:
            content = source.read(limit + 1)
        self.ensure_current(item)
        if len(content) != item['size']:
            raise ExportChanged(f'{item["name"]} changed while being read')
        return content

    def import_vdi(self, items, signature):
        import vdi_data
        from vdi_data_api import apply_import
        item = items[0]
        try:
            content = self.read(item, vdi_data.MAX_FILE_BYTES)
        except ValueError as error:
            self.record('vdi', signature, 'error', str(error), files=[item['name']])
            return
        except OSError as error:
            self.state['groups']['vdi'] = {'result': 'waiting', 'message': f'Could not open {item["name"]} yet ({error.__class__.__name__}); retrying.', 'at': now(), 'files': [item['name']]}
            return
        try:
            incoming, parsed = vdi_data.parse(content, item['name'])
            with sqlite3.connect(self.db, timeout=20, factory=ClosingConnection) as con:
                con.execute('begin')
                report = vdi_data.report(con, incoming, parsed, full_snapshot=False)
                fingerprint = vdi_data.fingerprint(con)
            result = apply_import(self.db, {'rows': incoming, 'source': item['name'], 'report': report,
                                            'fingerprint': fingerprint, 'full_snapshot': False})
        except ValueError as error:
            self.record('vdi', signature, 'error', str(error), files=[item['name']])
            return
        except HTTPException as error:
            self.state['groups']['vdi'] = {'result': 'waiting', 'message': f'{error.detail} Trying again.', 'at': now(), 'files': [item['name']]}
            return
        self.record('vdi', signature, 'applied', f'{result["count"]:,} VDIs.', files=[item['name']], backup=result['backup'])

    def import_packages(self, items, signature):
        import package_data
        from package_data_api import apply_import
        item = items[0]
        if not item['name'].casefold().endswith('.csv'):
            self.record('packages', signature, 'error', f'Save {item["name"]} as CSV: package data is imported from the CSV export.', files=[item['name']])
            return
        try:
            content = self.read(item, 10 * 1024 * 1024)
        except ValueError as error:
            self.record('packages', signature, 'error', str(error), files=[item['name']])
            return
        except OSError as error:
            self.state['groups']['packages'] = {'result': 'waiting', 'message': f'Could not open {item["name"]} yet ({error.__class__.__name__}); retrying.', 'at': now(), 'files': [item['name']]}
            return
        try:
            incoming, parsed = package_data.parse_csv(content)
            with sqlite3.connect(self.db, timeout=20, factory=ClosingConnection) as con:
                existing = package_data.load(con)
            report = package_data.report(incoming, existing, self.repo(), parsed)
            result = apply_import(self.db, {'rows': incoming, 'source': item['name'], 'report': report,
                                            'fingerprint': package_data.fingerprint(existing)})
        except ValueError as error:
            self.record('packages', signature, 'error', str(error), files=[item['name']])
            return
        except HTTPException as error:
            self.state['groups']['packages'] = {'result': 'waiting', 'message': f'{error.detail} Trying again.', 'at': now(), 'files': [item['name']]}
            return
        self.record('packages', signature, 'applied', f'{result["count"]:,} packages (+{report["added"]:,} new, {report["changed"]:,} updated).',
                    files=[item['name']], backup=result['backup'])

    @staticmethod
    def access_kind(path):
        from persona_access import recognise
        return recognise(path)

    # New joiner requests: the workbook replaces the requests Atlas keeps; each new desk gets a persona.
    def import_access(self, items, signature):
        import persona_access
        item = items[0]
        if not self.access:
            self.record('access', signature, 'error', 'New joiner requests are imported by Atlas Admin.', files=[item['name']])
            return
        work = tempfile.mkdtemp(prefix='atlas_import_folder_')
        try:
            try:
                copy, = self.copies(items, work)
            except OSError as error:
                self.state['groups']['access'] = {'result': 'waiting', 'message': f'Could not open {item["name"]} yet ({error.__class__.__name__}); retrying.', 'at': now(), 'files': [item['name']]}
                return
            try:
                parsed = persona_access.parse(copy)
            except (ValueError, KeyError, IndexError, zipfile.BadZipFile, SyntaxError) as error:
                self.record('access', signature, 'error', str(error) or 'The workbook could not be read.', files=[item['name']])
                return
            requests, personas = self.access()
            requests.replace(parsed, item['name'])
            added = personas.add_desks([desk['name'] for desk in parsed['desks']])
            count = sum(len(desk['requests']) for desk in parsed['desks'])
            self.record('access', signature, 'applied', f'{len(parsed["desks"])} desks, {count:,} requests'
                        + (f'; {added} new persona{"s" if added != 1 else ""}' if added else '') + '.', files=[item['name']])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def run(self):
        wait = FIRST_CHECK_SECONDS
        while not self.stop_event.wait(wait):
            wait = self.interval
            try:
                self.check()
            except Exception as error:  # A bad file never stops the watcher.
                self.set_status('error', f'Import folder check failed: {error}')

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self.run, name='atlas-import-folder', daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()
        with self.lock:
            self.drop_held()


def register(app, wmi, check_token, busy, state_path):
    watcher = ImportFolder(lambda: wmi.MASTER_DB, state_path, busy, lambda: wmi.REPO,
                           access=lambda: (wmi.persona_access_store, wmi.persona_store))

    @app.get('/api/import-folder')
    def status():
        return watcher.summary()

    @app.post('/api/import-folder/settings')
    def settings(body: Settings, request: Request):
        check_token(request)
        watcher.configure(body)
        return watcher.check(force=True)

    @app.post('/api/import-folder/check')
    def check(request: Request):
        check_token(request)
        return watcher.check(force=True)

    @app.post('/api/import-folder/apply')
    def apply(body: HeldReview, request: Request):
        check_token(request)
        return watcher.apply_held(body.id)

    @app.post('/api/import-folder/skip')
    def skip(body: HeldReview, request: Request):
        check_token(request)
        return watcher.skip_held(body.id)

    @app.on_event('startup')
    def begin():
        watcher.start()

    @app.on_event('shutdown')
    def end():
        watcher.close()

    return watcher
