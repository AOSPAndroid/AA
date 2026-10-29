"""Live floor plan: keep official seating in step with the assistants' Excel plan.

Atlas watches one folder (for example the OneDrive-synced "02_Current_plan"). When the newest
desk-plan workbook there changes, it is read (seating_grid), compared with the map
(seating_excel.plan_sheet) and, when the result is clean and of a normal size, applied with a
backup. Large or unclear changes wait for review in Manage Database. Desks the plan does not
mention are left alone. Admin only: the Demo just sees the updated database.
"""
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

from backend import atlas_store as store
from backend.atlas_store import ClosingConnection
from backend.directory.identity_links import key
from backend.seating.seating_excel import apply_sheet, layout_records, occupied, plan_sheet
from backend.seating.seating_grid import VERSION as READER, floor_tabs, read_plan

SOURCE = 'Live floor plan'
STABLE_SECONDS = 30
KEEP_BACKUPS = 10
MIN_DESKS = 10


def large(changes, desks):
    """More than this many changes in one save is held for review (a reorganisation or a broken sheet)."""
    return changes > max(40, round(desks * .15))


def seating_version(con):
    """Cheap change marker for maps that refresh themselves; also names the latest sync."""
    seq = con.execute('select coalesce(max(seq),0) from history').fetchone()[0] if table(con, 'history') else 0
    links = con.execute('select count(*) from desk_link_history').fetchone()[0] if table(con, 'desk_link_history') else 0
    latest = None
    if table(con, 'seating_import_history'):
        row = con.execute("select at,source from seating_import_history where source like ? order by at desc limit 1", (SOURCE + '%',)).fetchone()
        if row:
            latest = {'at': row[0], 'source': row[1][len(SOURCE) + 3:] or row[1]}
    return {'version': f'{seq}.{links}', 'live_plan': latest}


def table(con, name):
    return con.execute("select 1 from sqlite_master where name=?", (name,)).fetchone() is not None


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    folder: str = Field(default='', max_length=1024)
    enabled: bool = False
    # Off: every saved plan reaches the map straight away, however many desks change.
    review_large: bool = True


class ApplyReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=64)


class SeatingSync:
    def __init__(self, db, state_path, backups, busy=lambda: False, interval=60, clock=time.time):
        # db/backups may be callables, so the sync follows the server's current database path.
        self._db, self._backups, self.state_path = db, backups, Path(state_path)
        self.busy, self.interval, self.clock = busy, interval, clock
        self.lock = threading.Lock()
        self.held = None
        self.plans = {}
        self.thread = None
        self.checked = None
        self.stop_event = threading.Event()
        self.state = self.load()
        self.state.setdefault('status', {'state': 'off', 'message': 'Choose the folder with the desk plan, then turn the live link on.'})

    @property
    def db(self):
        return Path(self._db() if callable(self._db) else self._db)

    @property
    def backups(self):
        return Path(self._backups() if callable(self._backups) else self._backups)

    # Settings and state survive restarts; held plans do not (they are rebuilt on the next check).
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

    def set_status(self, state, message, **extra):
        self.state['status'] = {'state': state, 'message': message, 'at': now(), **extra}
        self.save()

    def configure(self, settings):
        folder = settings.folder.strip().strip('"').strip()
        with self.lock:
            self.state.update(folder=folder, enabled=settings.enabled and bool(folder), review_large=settings.review_large)
            self.state.pop('last', None)
            self.held = None
            if not self.state['enabled']:
                self.set_status('off', 'Live link is off.' if folder else 'Choose the folder with the desk plan, then turn the live link on.')
            else:
                self.set_status('checking', 'Checking the folder…')
        return self.summary()

    def summary(self):
        status = dict(self.state.get('status', {}))
        proposal = self.held
        held = proposal and {'id': proposal['id'], 'reason': proposal['reason'], 'file': proposal['file'], 'report': proposal['report'], 'reader': proposal['reader']}
        return {'folder': self.state.get('folder', ''), 'enabled': bool(self.state.get('enabled')), 'review_large': self.state.get('review_large', True), 'status': status,
                'checked': self.checked, 'last': self.state.get('last'), 'history': self.state.get('history', [])[:15], 'held': held,
                'duplicates': self.duplicates()}

    def duplicates(self):
        """People on more than one official desk right now: the same account, or the same assigned name."""
        try:
            with sqlite3.connect(self.db.resolve().as_uri() + '?mode=ro', uri=True, factory=ClosingConnection) as c:
                records, links = layout_records(c, 'official')
        except (sqlite3.Error, OSError, ValueError):
            return []
        people = {}
        for desk, record in records.items():
            if not occupied(record):
                continue
            # Team and room labels ("Credit Sales") repeat by design; only accounts and assigned names count.
            if links.get(desk):
                identity = ('account', links[desk])
            elif record.get('occupancy') == 'assigned':
                identity = ('name', key(record['name']))
            else:
                continue
            people.setdefault(identity, {'name': record['name'], 'desks': []})['desks'].append(desk)
        return sorted(({'name': p['name'], 'desks': sorted(p['desks'])} for p in people.values() if len(p['desks']) > 1), key=lambda p: p['name'].casefold())

    def candidates(self, folder):
        """Newest first, but a workbook with a tab per floor beats newer lists (New Joiners...)."""
        files = [p for p in folder.iterdir() if p.suffix.lower() == '.xlsx' and not p.name.startswith(('~$', '.'))]
        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        def plan_like(path):
            try:
                return floor_tabs(path) > 0
            except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
                return False
        return sorted(files, key=lambda p: not plan_like(p))

    def check(self, force=False):
        """One pass: find the plan, and apply or hold its changes. Safe to call at any time."""
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
            self.set_status('error', f'Folder not reachable: {folder}. Check that OneDrive is running and the folder is synced to this PC.')
            return self.summary()
        with tempfile.TemporaryDirectory(prefix='atlas_plan_') as work:
            for path in self.candidates(folder):
                stat = path.stat()
                signature = [path.name, stat.st_mtime_ns, stat.st_size, READER]
                if not force and self.plans.get(tuple(signature)) is False:
                    continue
                if self.clock() - stat.st_mtime < STABLE_SECONDS:
                    self.set_status('waiting', f'{path.name} was just saved; reading it in a moment.')
                    return self.summary()
                last = self.state.get('last') or {}
                rebuild_held = last.get('result') == 'held' and self.held is None
                if not force and last.get('signature') == signature and not rebuild_held:
                    return self.summary()
                copy = Path(work) / path.name
                try:
                    shutil.copy2(path, copy)
                    with sqlite3.connect(self.db, factory=ClosingConnection) as c:
                        c.execute('begin')
                        records, _ = layout_records(c, 'official')
                        reader = read_plan(copy, c, records)
                except (OSError, zipfile.BadZipFile) as error:
                    self.set_status('waiting', f'{path.name} could not be opened yet ({error.__class__.__name__}); retrying.')
                    return self.summary()
                except (ValueError, KeyError, IndexError, ET.ParseError):
                    self.plans[tuple(signature)] = False
                    continue
                if len(reader['rows']) < MIN_DESKS:
                    self.plans[tuple(signature)] = False
                    continue
                return self.consider(path, signature, reader)
        self.set_status('error', 'No desk plan found in this folder: no recent .xlsx contains desk codes like 02R015079.')
        return self.summary()

    def consider(self, path, signature, reader):
        modified = datetime.fromtimestamp(signature[1] / 1e9, timezone.utc).isoformat()
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            c.execute('begin')
            records, _ = layout_records(c, 'official')
            labels = {key(row['name']) for row in reader['rows'] if row['kind'] == 'label'}
            labels |= {key(record['name']) for record in records.values() if record.get('occupancy') == 'unconfirmed'}
            rows = [{k: v for k, v in row.items() if k in ('desk', 'name', 'status', 'account', 'team', '_row')} for row in reader['rows']]
            # The plan is the authority: nothing in it blocks the update; problems become notes.
            plan = plan_sheet(c, rows, 'official', False, frozenset(labels), lenient=True)
        report = plan['report']
        info = {'file': path.name, 'modified': modified, 'signature': signature, 'desks': len(rows),
                'reader': {k: reader[k] for k in ('fixes', 'matched_partly', 'not_in_directory', 'unknown_desks', 'conflicts', 'sheets', 'hidden_sheets', 'blank', 'other_floor')},
                'notes': report.get('notes', [])}
        counts = tally(report['changes'])
        reason = ('The plan has problems Atlas cannot resolve on its own.' if report['errors'] else
                  '' if not self.state.get('review_large', True) else
                  'The same desk appears with different names in the plan.' if reader['conflicts'] else
                  f'{len(report["changes"])} changes in one save; review them before they reach the map.' if large(len(report['changes']), len(rows)) else '')
        if reason:
            self.held = {'id': uuid4().hex, 'reason': reason, 'file': path.name, 'plan': plan, 'report': report, 'reader': info['reader'], 'info': info}
            self.state['last'] = {**info, 'result': 'held', 'counts': counts}
            self.set_status('held', f'{path.name}: {reason}', counts=counts)
            return self.summary()
        if not plan['updates']:
            self.held = None
            self.state['last'] = {**info, 'result': 'unchanged', 'counts': counts}
            self.set_status('synced', f'The map matches {path.name}.')
            return self.summary()
        if self.busy():
            self.set_status('waiting', 'Deployments or queue jobs are running; seating updates once they finish.')
            return self.summary()
        return self.apply(plan, info, counts)

    def apply(self, plan, info, counts):
        try:
            backup = apply_sheet(self.db, plan, self.backups, f'{SOURCE} · {info["file"]}')
        except store.Conflict:
            self.state.pop('last', None)
            self.set_status('waiting', 'Seating changed while reading the plan; comparing again.')
            return self.summary()
        self.held = None
        entry = {'at': now(), 'file': info['file'], 'counts': counts, 'backup': backup, 'desks': sorted(plan['updates'])}
        self.state['history'] = [entry, *self.state.get('history', [])][:50]
        self.state['last'] = {**info, 'result': 'applied', 'counts': counts}
        self.prune()
        self.set_status('synced', f'Updated from {info["file"]}: {describe(counts)}.', counts=counts)
        return self.summary()

    def apply_held(self, expected_id):
        with self.lock:
            if not self.held:
                raise HTTPException(409, 'Nothing is waiting for review. Check the folder again.')
            if self.held['id'] != expected_id:
                raise HTTPException(409, 'This seating review is out of date. Review the latest changes before applying.')
            if self.held['report']['errors']:
                raise HTTPException(409, 'Fix the plan problems listed below in the Excel file; Atlas picks up the corrected file.')
            if self.busy():
                raise HTTPException(409, 'Finish active jobs and queues first.')
            held = self.held
            return self.apply(held['plan'], held['info'], tally(held['report']['changes']))

    def prune(self):
        """Keep the most recent live-plan backups; older ones are removed (imports keep their own)."""
        kept = {entry.get('backup') for entry in self.state.get('history', [])[:KEEP_BACKUPS]}
        for entry in self.state.get('history', [])[KEEP_BACKUPS:]:
            name = entry.get('backup')
            if name and name not in kept:
                (self.backups / name).unlink(missing_ok=True)

    def run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.check()
            except Exception as error:  # A bad file never stops the watcher.
                self.set_status('error', f'Live floor plan check failed: {error}')

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self.run, name='atlas-seating-sync', daemon=True)
            self.thread.start()

    def close(self):
        self.stop_event.set()


    def undo(self, backup):
        """Put the desks one live update changed back as they were in its backup.
        The plan file is not read again until it is saved again."""
        with self.lock:
            entry = next((h for h in self.state.get('history', []) if h.get('backup') == backup and not h.get('undone')), None)
            if not entry:
                raise HTTPException(404, 'This update cannot be undone any more.')
            source = self.backups / backup
            if not source.is_file():
                raise HTTPException(409, 'The backup for this update was removed.')
            if self.busy():
                raise HTTPException(409, 'Finish active jobs and queues first.')
            desks = entry.get('desks') or self.changed_desks(backup)
            plan = restore_plan(self.db, source, desks)
            if plan['report']['errors']:
                raise HTTPException(409, ' '.join(plan['report']['errors']))
            if not plan['updates']:
                entry['undone'] = now()
                self.save()
                raise HTTPException(409, 'These desks already match the backup.')
            try:
                done = apply_sheet(self.db, plan, self.backups, f'{SOURCE} · undo {entry["file"]}')
            except store.Conflict:
                raise HTTPException(409, 'Seating or directory changed while preparing Undo. Review the current map and try again.')
            entry['undone'] = now()
            self.state['history'] = [{'at': now(), 'file': f'Undo of {entry["file"]}', 'counts': {'restored': len(plan['updates'])}, 'backup': done, 'desks': sorted(plan['updates'])},
                                     *self.state['history']][:50]
            self.held = None
            self.prune()
            self.set_status('synced', f'Restored {len(plan["updates"])} desks from before {entry["file"]}. The plan is read again when it is next saved.')
            return self.summary()

    def changed_desks(self, backup):
        # Updates made before desk lists were kept: the import log holds the report.
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            if not table(c, 'seating_import_history'):
                return []
            for path, report in c.execute('select backup, report from seating_import_history'):
                if Path(path).name == backup:
                    return sorted({change['desk'] for change in json.loads(report).get('changes', [])})
        return []


def restore_plan(db, backup, desks):
    """Restore only seating fields, retaining current desk details and rejecting new duplicate occupants."""
    from backend.seating.seating_excel import stamp
    with sqlite3.connect(Path(backup).resolve().as_uri() + '?mode=ro', uri=True, factory=ClosingConnection) as old:
        before, before_links = layout_records(old, 'official')
    with sqlite3.connect(db, factory=ClosingConnection) as c:
        c.execute('begin')
        records, links = layout_records(c, 'official')
        updates, changes = {}, []
        for desk in desks:
            if desk not in records or desk not in before:
                continue
            record = dict(records[desk], **{field: before[desk][field] for field in ('name', 'team', 'occupancy')})
            link = before_links.get(desk)
            if all(record.get(k) == records[desk].get(k) for k in ('name', 'team', 'occupancy')) and link == links.get(desk):
                continue
            record['verified'] = False
            updates[desk] = {'record': record, 'link': link}
            changes.append({'desk': desk, 'kind': 'restored', 'before': {'name': records[desk]['name']}, 'after': {'name': record['name']}})

        def people(seats, account_links):
            found = {}
            for desk, record in seats.items():
                link = account_links.get(desk)
                # Unlinked unconfirmed text is a team/room label, as in live-plan imports.
                if not occupied(record) or (record['occupancy'] == 'unconfirmed' and not link):
                    continue
                identity = ('account', link) if link else ('name', key(record['name']))
                found.setdefault(identity, set()).add(desk)
            return found

        current_people = people(records, links)
        final_people = people({**records, **{desk: item['record'] for desk, item in updates.items()}},
                              {**links, **{desk: item['link'] for desk, item in updates.items()}})
        errors = ['Cannot undo this update: the same person would occupy ' + ', '.join(sorted(locations))
                  + '. A later seating change must be resolved first; no other desks were changed.'
                  for identity, locations in final_people.items()
                  if len(locations) > 1 and locations - current_people.get(identity, set())]
        return {'fingerprint': stamp(c, 'official'), 'layout': 'official', 'updates': updates,
                'report': {'changes': changes, 'errors': errors, 'warnings': []}}


class UndoUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    backup: str = Field(min_length=1, max_length=200)


def tally(changes):
    counts = {}
    for change in changes:
        counts[change['kind']] = counts.get(change['kind'], 0) + 1
    return counts


def describe(counts):
    words = {'moved': 'moved', 'assigned': 'assigned', 'vacated': 'freed', 'updated': 'updated', 'restored': 'restored'}
    return ', '.join(f'{n} {words.get(kind, kind)}' for kind, n in counts.items()) or 'no changes'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def register(app, wmi, check_token, busy, state_path):
    sync = SeatingSync(lambda: wmi.MASTER_DB, state_path, lambda: Path(wmi.MASTER_DB).resolve().parent / 'backups', busy)

    @app.get('/api/seating-sync')
    def status():
        return sync.summary()

    @app.post('/api/seating-sync/settings')
    def settings(body: Settings, request: Request):
        check_token(request)
        sync.configure(body)
        return sync.check(force=True)

    @app.post('/api/seating-sync/check')
    def check(request: Request):
        check_token(request)
        return sync.check(force=True)

    @app.post('/api/seating-sync/apply')
    def apply(body: ApplyReview, request: Request):
        check_token(request)
        return sync.apply_held(body.id)

    @app.post('/api/seating-sync/undo')
    def undo(body: UndoUpdate, request: Request):
        check_token(request)
        return sync.undo(body.backup)

    @app.get('/api/official/version')
    def version():
        with sqlite3.connect(Path(wmi.MASTER_DB).resolve().as_uri() + '?mode=ro', uri=True, factory=ClosingConnection) as c:
            return seating_version(c)

    @app.on_event('startup')
    def begin():
        sync.start()

    @app.on_event('shutdown')
    def end():
        sync.close()

    return sync
