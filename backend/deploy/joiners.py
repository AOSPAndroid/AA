"""New joiners: the two steps for each person joining a desk, tracked until both are done.

1. Access: the requests their persona's desk raises (persona_access), copied into the joiner when
   it is created. Each row shows an earlier joiner's ticket to copy; the operator records the new
   ticket number and ticks it raised. Atlas never raises requests itself.
2. Software: the persona's packages, installed on the joiner's machine in one click through the
   persona install (one deployment queue, with its checks).

Joiners are saved in joiners.json beside personas.json. Start dates in the directory suggest who
starts soon; the directory covers every site, so the page shows the site named by "new_joiner_site"
in config.json (Paris by default) unless another is chosen.
"""
import json
import os
import re
import secrets
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

JOINER_ID = re.compile(r'^[a-f0-9]{12}$')
# Suggest people who started up to two weeks ago or start in the next six.
SOON = (14, 42)


class Create(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(default='', max_length=254)
    user: str = Field(default='', max_length=120)
    start: str = Field(default='', max_length=32)
    computer: str = Field(default='', max_length=255)
    persona: str = Field(pattern=r'^[a-f0-9]{12}$')


class RequestChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    index: int = Field(ge=0)
    ticket: str | None = Field(default=None, max_length=40)
    raised: bool | None = None


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    computer: str | None = Field(default=None, max_length=255)
    done: bool | None = None
    request: RequestChange | None = None


class Store:
    """Joiners in one JSON file, written atomically; each change sets only the fields it names."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def all(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise HTTPException(503, f'Cannot read new joiners in {self.path}.') from error
        joiners = data.get('joiners') if isinstance(data, dict) else None
        if not isinstance(joiners, list):
            raise HTTPException(503, f'Cannot read new joiners in {self.path}.')
        return [item for item in joiners if isinstance(item, dict) and JOINER_ID.fullmatch(str(item.get('id', '')))]

    def write(self, joiners):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'joiners': joiners}, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)

    def change(self, joiner_id, apply):
        with self.lock:
            joiners = self.all()
            joiner = next((item for item in joiners if item['id'] == joiner_id), None)
            if not joiner:
                raise HTTPException(404, 'This new joiner was removed in another window.')
            if apply(joiner) is False:
                joiners = [item for item in joiners if item['id'] != joiner_id]
            else:
                joiner['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            self.write(joiners)
            return joiner

    def add(self, joiner):
        with self.lock:
            joiners = self.all()
            taken = {item['id'] for item in joiners}
            joiner['id'] = secrets.token_hex(6)
            while joiner['id'] in taken:
                joiner['id'] = secrets.token_hex(6)
            self.write([joiner, *joiners])
            return joiner


def register(app, path, backend, personas, access):
    """backend is the Admin app module; personas and access are the persona and request stores."""
    store = Store(path)

    def authorize(request):
        from backend.atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before changing new joiners')

    def valid(joiner_id):
        if not JOINER_ID.fullmatch(joiner_id):
            raise HTTPException(404, 'New joiner not found.')

    def site():
        value = getattr(backend, 'CONFIG', {}).get('new_joiner_site', 'Paris')
        return value.strip() if isinstance(value, str) else 'Paris'

    def machine(computer):
        computer = ' '.join(computer.split())
        return backend.validate_pc(computer) if computer else ''

    def progress(joiner):
        """The latest software install as the queue reports it; history keeps it after Atlas forgets the queue."""
        install = (joiner.get('installs') or [None])[0]
        if not install:
            return None
        with backend.lock:
            queue = backend.queue_jobs.get(install.get('queue'))
            rows = [row.get('state') for row in queue.get('items', [])] if queue else []
            state = queue.get('state') if queue else 'unknown'
        return {**install, 'state': state, 'total': len(rows) or install.get('count', 0),
                'finished': sum(row not in ('waiting', 'running') for row in rows),
                'failed': sum(row in ('failed', 'interrupted', 'unknown') for row in rows),
                'cancelled': sum(row == 'cancelled' for row in rows)}

    @app.get('/api/joiners')
    def joiners():
        items = store.all()
        for joiner in items:
            joiner['install'] = progress(joiner)
        return {'joiners': items}

    @app.get('/api/joiners/starting')
    def starting():
        """Directory users whose start date is near and who have no checklist yet."""
        from backend.directory.device_inventory import supports_windows
        from backend.directory.directory_lookup import linked_machines
        today = date.today()
        first, last = (today - timedelta(days=SOON[0])).isoformat(), (today + timedelta(days=SOON[1])).isoformat() + ' 99'
        known = {value.casefold() for joiner in store.all() for value in (joiner.get('user'), joiner.get('email')) if value}
        people = []
        with backend.db() as c:
            fields = {row[1] for row in c.execute("select * from pragma_table_info('legacy_users')")}
            if 'start_date' not in fields:
                return {'people': [], 'from': first, 'to': last[:10], 'site': site()}
            pick = lambda *names: next((name for name in names if name in fields), None)
            title, department, location = pick('job_title', 'job_role'), pick('department', 'organisational_unit', 'organisation'), pick('location')
            extra = ''.join(',' + name for name in (title, department, location) if name)
            rows = c.execute(f"select id,canonical_key,name,email,start_date{extra} "
                             "from legacy_users where start_date>=? and start_date<=? order by start_date,name limit 500", (first, last)).fetchall()
            for row in rows:
                row = dict(row)
                if {str(row.get('canonical_key') or '').casefold(), str(row.get('email') or '').casefold()} & known:
                    continue
                computers = [str(m.get('name') or m.get('machine_name') or '') for m in linked_machines(c, row['id']) if supports_windows(m)]
                email = str(row.get('email') or '')
                people.append({'user': row.get('canonical_key') or '', 'name': row.get('name') or '', 'email': email if '@' in email else '',
                               'start': str(row.get('start_date') or '')[:10], 'title': (row.get(title) or '') if title else '',
                               'department': (row.get(department) or '') if department else '',
                               'location': (row.get(location) or '') if location else '', 'computer': next(iter(computers), '')})
                if len(people) >= 300:
                    break
        return {'people': people, 'from': first, 'to': last[:10], 'site': site()}

    @app.post('/api/joiners')
    def create(body: Create, request: Request):
        authorize(request)
        persona = personas.get(body.persona)
        if not persona:
            raise HTTPException(404, 'Persona not found. It may have been deleted in another window.')
        name = ' '.join(body.name.split())
        if not name:
            raise HTTPException(400, 'Enter the new joiner\'s name.')
        desk = access.desk(persona.get('desk') or persona['name'])
        joiner = {'name': name, 'email': body.email.strip(), 'user': body.user.strip(), 'start': body.start.strip()[:10],
                  'computer': machine(body.computer), 'persona_id': persona['id'], 'persona': persona['name'],
                  'desk': desk['name'] if desk else '', 'area': desk.get('area', '') if desk else '',
                  'created': time.strftime('%Y-%m-%dT%H:%M:%S'), 'updated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'done': False,
                  # A copy: a later workbook does not change a checklist already in progress.
                  'requests': [{'catalog': row['catalog'], 'reference': row.get('ticket', ''), 'notes': row.get('notes', ''),
                                'ticket': '', 'raised': False} for row in (desk['requests'] if desk else [])],
                  'installs': []}
        return store.add(joiner)

    @app.put('/api/joiners/{joiner_id}')
    def update(joiner_id: str, body: Change, request: Request):
        authorize(request)
        valid(joiner_id)
        computer = machine(body.computer) if body.computer is not None else None

        def apply(joiner):
            if computer is not None:
                joiner['computer'] = computer
            if body.done is not None:
                joiner['done'] = body.done
            if body.request is not None:
                if body.request.index >= len(joiner['requests']):
                    raise HTTPException(409, 'This checklist changed in another window. Reload it.')
                row = joiner['requests'][body.request.index]
                if body.request.ticket is not None:
                    row['ticket'] = ' '.join(body.request.ticket.split())
                    # A new ticket number means the request was raised.
                    if row['ticket'] and body.request.raised is None:
                        row['raised'] = True
                if body.request.raised is not None:
                    row['raised'] = body.request.raised
        joiner = store.change(joiner_id, apply)
        joiner['install'] = progress(joiner)
        return joiner

    @app.delete('/api/joiners/{joiner_id}')
    def delete(joiner_id: str, request: Request):
        authorize(request)
        valid(joiner_id)
        store.change(joiner_id, lambda joiner: False)
        return {'deleted': joiner_id}

    @app.post('/api/joiners/{joiner_id}/install')
    def install(joiner_id: str, request: Request):
        authorize(request)
        valid(joiner_id)
        joiner = next((item for item in store.all() if item['id'] == joiner_id), None)
        if not joiner:
            raise HTTPException(404, 'New joiner not found.')
        if not joiner.get('computer'):
            raise HTTPException(400, f'Enter {joiner["name"]}\'s machine first.')
        result = personas.install(joiner['persona_id'], joiner['computer'])
        record = {'queue': result['queue'], 'computer': result['computer'], 'count': result['count'], 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
        store.change(joiner_id, lambda item: item.update(installs=[record, *item.get('installs', [])][:10]))
        return {**result, 'joiner': joiner_id}

    return store
