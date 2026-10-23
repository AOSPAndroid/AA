"""Clipboard history: what the operator copied, kept with what Atlas knows about it.

Every capture (Capture button, Ctrl+V, returning to Atlas, the Live Inbox clipboard reader) is stored
with its text and enriched from the Atlas database: machines (user, model, status), people (account,
email, department), desks (occupant, floor), ticket numbers and IP addresses. Admin only; the history
is a JSON file next to the database, newest first, capped at LIMIT items. Nothing leaves this PC.
"""
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

LIMIT = 300
TEXT = 20000
MACHINES = 500
SOURCES = ('button', 'paste', 'return', 'screenshot', 'inbox', 'companion')
HOSTNAME = re.compile(r'(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9-]{4,29})(?![A-Za-z0-9_-])')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
ACCOUNT = re.compile(r'(?<![A-Za-z0-9])(?:[A-Za-z]{1,3}\\)?[A-Za-z]{1,2}[0-9]{6,9}(?![A-Za-z0-9])')
NAME = re.compile(r"\b([A-ZÀ-Ý][a-zà-ÿ'’-]+(?: [A-ZÀ-Ý][A-Za-zÀ-ÿ'’-]+){1,3})\b")
DESK = re.compile(r'(?<![0-9A-Za-z])([0-9]{1,2})\s?([RB])\s?([0-9]{6})(?![0-9])', re.I)
TICKET = re.compile(r'\b(?:INC|RITM|REQ|CHG|PRB|SCTASK|TASK)[0-9]{6,10}\b', re.I)
IPV4 = re.compile(r'(?<![0-9.])(?:(?:25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])(?![0-9.])')


class Capture(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=TEXT)
    source: Literal['button', 'paste', 'return', 'screenshot', 'inbox'] = 'button'


def candidates(text):
    """Hostname-like words, lower-cased (as Atlas stores them) and mapped to how they were written.
    Letters then letters/digits/hyphens, with a digit (OCR may read 0 as O)."""
    seen = {}
    for match in HOSTNAME.finditer(text):
        value = match.group(1)
        key = value.casefold()
        numeric = any(c.isdigit() for c in key) or re.search(r'-[0-9oil]{2,}$', key)
        if numeric and 6 <= len(key) <= 30 and not EMAIL.fullmatch(value) and key not in seen:
            seen[key] = value
    return dict(list(seen.items())[:MACHINES])


def person(row):
    data = dict(row)
    return {k: data.get(k) or '' for k in ('id', 'full_name', 'name', 'user_name', 'email', 'department', 'location', 'job_role', 'canonical_key')}


def find_machines(c, names):
    from mail_inbox import mentioned_machines
    found, users = [], {}
    for start in range(0, len(names), 400):
        found += mentioned_machines(c, names[start:start + 400])
    if not found:
        return []
    columns = {row[1] for row in c.execute('pragma table_info(legacy_machines)')}
    wanted = [k for k in ('assigned_user', 'last_logged_on_user', 'location', 'serial_number', 'asset_tag') if k in columns]
    extra = {}
    if wanted:
        names_found = [m['name'] for m in found]
        for start in range(0, len(names_found), 400):
            chunk = names_found[start:start + 400]
            for row in c.execute(f"select name,{','.join(wanted)} from legacy_machines where name in ({','.join('?' * len(chunk))})", chunk):
                extra[row[0]] = dict(zip(wanted, row[1:]))
    # The user comes from Atlas's machine-user links: assigned first, then last logged on.
    owners = {}
    names_found = [m['name'] for m in found]
    for start in range(0, len(names_found), 400):
        chunk = names_found[start:start + 400]
        for row in c.execute(
                "select m.name as machine, u.* from assignments a join legacy_machines m on m.id=a.machine_id "
                "join legacy_users u on u.id=a.user_id_ref where m.name in (%s) "
                "order by a.relationship_type='assigned_to' desc" % ','.join('?' * len(chunk)), chunk):
            owners.setdefault(row['machine'], {**person(row), 'relationship': row['relationship_type'] if 'relationship_type' in row.keys() else ''})
    out = []
    for machine in found:
        info = extra.get(machine['name'], {})
        out.append({**machine, **{k: v for k, v in info.items() if v}, 'user': owners.get(machine['name'])})
    return out


def find_users(c, text):
    from directory_lookup import exact_users
    found = {}
    def add(rows, basis):
        if len(rows) == 1:
            row = person(rows[0]); found.setdefault(row['id'], {**row, 'basis': basis})
    for email in dict.fromkeys(e.casefold() for e in EMAIL.findall(text)):
        add(exact_users(c, email, field='email'), 'email')
    for account in dict.fromkeys(ACCOUNT.findall(text)):
        add(exact_users(c, account), 'account')
    for name in dict.fromkeys(NAME.findall(text)):
        if len(found) >= 100:
            break
        add(exact_users(c, name, field='name'), 'name')
    return list(found.values())[:100]


def find_desks(c, text):
    if not c.execute("select 1 from sqlite_master where name='official_records'").fetchone():
        return []
    desks = []
    for floor, letter, digits in dict.fromkeys((f, l.upper(), d) for f, l, d in DESK.findall(text)):
        desk = f'{int(floor):02d}{letter}{digits}'
        row = c.execute('select body from official_records where id=?', (desk,)).fetchone()
        if row:
            body = json.loads(row[0])
            desks.append({'desk': desk, 'name': body.get('name', ''), 'team': body.get('team', ''), 'floor': body.get('floor'),
                          'occupancy': body.get('occupancy', '')})
    return desks[:200]


def enrich(c, text):
    written = candidates(text)
    names = list(written)
    machines = find_machines(c, names)
    from mail_inbox import lookalike_key
    known = {m['name'].casefold() for m in machines} | {str(m.get('written_as', '')).casefold() for m in machines}
    # A misread spelling of a machine already found (LAPT0P-OOO1 for LAPTOP-0001) is not unknown.
    lookalikes = {lookalike_key(m['name'].casefold()) for m in machines}
    users = find_users(c, text)
    emails = {u['email'].casefold() for u in users if u.get('email')}
    tickets = {t.casefold() for t in TICKET.findall(text)}
    unknown = [n for n in names if n not in known and lookalike_key(n) not in lookalikes and n not in emails and n not in tickets
               and re.search(r'[0-9]', n) and not ACCOUNT.fullmatch(n)]
    return {'machines': machines, 'unknown_machines': [written[n] for n in unknown[:200]], 'users': users, 'desks': find_desks(c, text),
            'tickets': list(dict.fromkeys(t.upper() for t in TICKET.findall(text)))[:100],
            'ips': list(dict.fromkeys(IPV4.findall(text)))[:100]}


class History:
    def __init__(self, path, db):
        self._path, self.db, self.lock = path, db, threading.Lock()

    @property
    def path(self):
        return Path(self._path() if callable(self._path) else self._path)

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data.get('items', []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            return []

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'items': items[:LIMIT]}, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)

    def enriched(self, text):
        try:
            with self.db() as c:
                return enrich(c, text)
        except sqlite3.Error as error:
            return {'machines': [], 'users': [], 'desks': [], 'tickets': [], 'ips': [], 'unknown_machines': [], 'error': str(error)}

    def record(self, text, source='button'):
        text = str(text or '')[:TEXT]
        if not text.strip():
            raise HTTPException(422, 'The clipboard is empty.')
        data = self.enriched(text)
        with self.lock:
            items = self.load()
            # The same text copied again moves to the top instead of repeating.
            old = next((item for item in items[:50] if item.get('text') == text), None)
            items = [item for item in items if item is not old]
            item = {'id': old['id'] if old else uuid.uuid4().hex, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'source': source,
                    'text': text, **data, 'times': (old or {}).get('times', 0) + 1}
            self.save([item, *items])
        return item

    def refresh(self, item_id):
        with self.lock:
            items = self.load()
            for index, item in enumerate(items):
                if item.get('id') == item_id:
                    items[index] = {**item, **self.enriched(item['text'])}
                    self.save(items)
                    return items[index]
        raise HTTPException(404, 'This clipboard item is no longer in the history.')

    def delete(self, item_id=None):
        with self.lock:
            items = self.load()
            kept = [] if item_id is None else [item for item in items if item.get('id') != item_id]
            if item_id is not None and len(kept) == len(items):
                raise HTTPException(404, 'This clipboard item is no longer in the history.')
            self.save(kept)
        return {'items': len(kept)}


history = None


def record(text, source):
    """Used by the Live Inbox clipboard reader; never fails the reading itself."""
    if history is None:
        return None
    try:
        return history.record(text, source)
    except Exception:
        return None


def register(app, wmi, check_token, path):
    global history
    history = History(path, wmi.db)

    @app.get('/api/clipboard')
    def items(summary: bool = False):
        loaded = history.load()
        if summary:
            # Cheap check for open pages: the Companion adds items in the background.
            return {'count': len(loaded), 'latest': loaded[0]['id'] + loaded[0]['at'] if loaded else ''}
        return {'items': loaded, 'limit': LIMIT}

    @app.post('/api/clipboard')
    def capture(body: Capture, request: Request):
        check_token(request)
        return history.record(body.text, body.source)

    @app.post('/api/clipboard/{item_id}/refresh')
    def refresh(item_id: str, request: Request):
        check_token(request)
        return history.refresh(item_id)

    @app.delete('/api/clipboard/{item_id}')
    def delete(item_id: str, request: Request):
        check_token(request)
        return history.delete(item_id)

    @app.delete('/api/clipboard')
    def clear(request: Request):
        check_token(request)
        return history.delete()
    return history
