"""Personas: the software a role needs, installed on a machine in one click.

A persona lists package folders from the repository, each with the action and script to run.
Personas are saved in personas.json beside the saved scripts. Installing one starts an ordinary
deployment queue for the machine: Atlas checks the machine and every package first and starts
nothing if any is refused, then runs them one after another with the queue's per-PC lock,
history and recovery rules.
"""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

PERSONA_ID = re.compile(r'^[a-f0-9]{12}$')
MAX_ITEMS = 40
# Work that holds a machine now; a paused queue waits for someone to resume it.
BUSY = {'queued', 'running', 'monitoring'}


class Item(BaseModel):
    model_config = ConfigDict(extra='forbid')
    folder: str = Field(min_length=1, max_length=260)
    script: str = Field(min_length=1, max_length=260)
    action: Literal['Install', 'Repair', 'Uninstall'] = 'Install'


class Persona(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default='', max_length=300)
    items: list[Item] = Field(min_length=1, max_length=MAX_ITEMS)
    fresh: bool = False
    threads: int = Field(default=8, ge=1, le=32)
    revision: int = Field(default=0, ge=0)


class Install(BaseModel):
    model_config = ConfigDict(extra='forbid')
    computer: str = Field(min_length=1, max_length=255)
    # The version the operator looked at; a persona edited since then is reviewed first.
    revision: int | None = Field(default=None, ge=0)


class Store:
    """Saved personas in one JSON file, written atomically."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def all(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise HTTPException(503, f'Cannot read saved personas in {self.path}.') from error
        personas = data.get('personas') if isinstance(data, dict) else None
        if not isinstance(personas, list):
            raise HTTPException(503, f'Cannot read saved personas in {self.path}.')
        return [item for item in personas if isinstance(item, dict) and PERSONA_ID.fullmatch(str(item.get('id', '')))
                and isinstance(item.get('items'), list)]

    def write(self, personas):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'personas': personas}, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)

    def get(self, persona_id):
        return next((item for item in self.all() if item['id'] == persona_id), None)

    def save(self, persona_id, body, items):
        name = ' '.join(body.name.split())
        if not name:
            raise HTTPException(400, 'Name the persona first.')
        with self.lock:
            personas = self.all()
            current = next((item for item in personas if item['id'] == persona_id), None) if persona_id else None
            if persona_id and not current:
                raise HTTPException(404, 'This persona was deleted in another window.')
            if current and current.get('revision', 0) != body.revision:
                raise HTTPException(409, 'This persona was changed in another window. Reopen it before saving.')
            if any(item['name'].casefold() == name.casefold() and item['id'] != persona_id for item in personas):
                raise HTTPException(409, f'A persona named {name} already exists.')
            taken = {item['id'] for item in personas}
            item_id = persona_id
            while not item_id or (not current and item_id in taken):
                item_id = secrets.token_hex(6)
            item = {'id': item_id, 'name': name, 'description': body.description.strip(), 'items': items,
                    'fresh': body.fresh, 'threads': body.threads, 'revision': (current or {}).get('revision', 0) + 1,
                    'updated': time.strftime('%Y-%m-%dT%H:%M:%S')}
            personas = [item if entry['id'] == persona_id else entry for entry in personas] if current else [*personas, item]
            self.write(sorted(personas, key=lambda entry: entry['name'].casefold()))
            return item

    def delete(self, persona_id, revision):
        with self.lock:
            personas = self.all()
            current = next((item for item in personas if item['id'] == persona_id), None)
            if not current:
                raise HTTPException(404, 'Persona not found.')
            if current.get('revision', 0) != revision:
                raise HTTPException(409, 'This persona was changed in another window. Reopen it before deleting.')
            self.write([item for item in personas if item['id'] != persona_id])
            return {'deleted': persona_id}


def register(app, path, backend):
    """backend is the Admin app module: its repository, deployment checks and queue."""
    store = Store(path)
    install_lock = threading.Lock()

    def authorize(request):
        from atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before changing personas')

    def find(persona_id):
        persona = store.get(persona_id) if PERSONA_ID.fullmatch(persona_id) else None
        if not persona:
            raise HTTPException(404, 'Persona not found. It may have been deleted in another window.')
        return persona

    def problem(folder, script, action):
        """Why this package cannot be installed as saved, or None."""
        if action not in backend.INSTALLER_SUFFIX:
            return 'Unknown action'
        try:
            try:
                backend.package_root(folder)
            except HTTPException:
                return 'Not in the package repository'
            try:
                backend.installer(folder, script, action)
            except HTTPException:
                return f'No {action.lower()} script named {script}'
        except OSError:
            return 'Cannot read the package repository'
        return None

    def checked(items):
        """Package names only, so a persona survives a repository move; each package listed once per action."""
        result, seen = [], set()
        for item in items:
            name = Path(item.folder).name or item.folder
            reason = problem(item.folder, item.script, item.action)
            if reason:
                raise HTTPException(400, f'{name}: {reason}.')
            folder = backend.package_root(item.folder).name
            if (folder.casefold(), item.action) in seen:
                raise HTTPException(400, f'{folder} is listed twice for {item.action}.')
            seen.add((folder.casefold(), item.action))
            result.append({'folder': folder, 'script': item.script, 'action': item.action})
        return result

    def busy(computer):
        same = computer.casefold()
        with backend.lock:
            if any(job.get('state') in BUSY and str(job.get('target') or '').casefold() == same for job in backend.jobs.values()):
                return True
            return any(queue.get('state') in BUSY and any(str(row.get('target') or '').casefold() == same and row.get('state') in ('waiting', 'running')
                                                          for row in queue.get('items', [])) for queue in backend.queue_jobs.values())

    @app.get('/api/personas')
    def personas():
        items = store.all()
        try:
            available = backend.REPO.is_dir()
        except OSError:
            available = False
        if available:
            for persona in items:
                for item in persona['items']:
                    item['problem'] = problem(item.get('folder', ''), item.get('script', ''), item.get('action', 'Install'))
        return {'personas': items, 'repository': available, 'max_items': MAX_ITEMS}

    @app.post('/api/personas')
    def create(body: Persona, request: Request):
        authorize(request)
        return store.save(None, body, checked(body.items))

    @app.put('/api/personas/{persona_id}')
    def update(persona_id: str, body: Persona, request: Request):
        authorize(request)
        find(persona_id)
        return store.save(persona_id, body, checked(body.items))

    @app.delete('/api/personas/{persona_id}')
    def delete(persona_id: str, revision: int, request: Request):
        authorize(request)
        find(persona_id)
        return store.delete(persona_id, revision)

    @app.post('/api/personas/{persona_id}/install')
    def install(persona_id: str, body: Install, request: Request):
        authorize(request)
        persona = find(persona_id)
        if body.revision is not None and persona.get('revision') != body.revision:
            raise HTTPException(409, f'{persona["name"]} was changed since you opened it. Review it, then install again.')
        computer = backend.validate_pc(body.computer)
        with install_lock:
            # Each item would wait for the machine's lock and fail; say so once instead.
            if busy(computer):
                raise HTTPException(409, f'{computer} already has a deployment running. Wait for it to finish or stop it, then install {persona["name"]}.')
            items = [backend.QueueItem(computer=computer, folder=item['folder'], script=item['script'], action=item['action'],
                                       fresh=bool(persona.get('fresh')), threads=int(persona.get('threads') or 8))
                     for item in persona['items']]
            started = backend.queue_items(items, persona=persona['name'])
        return {**started, 'persona': persona['name'], 'computer': computer, 'count': len(items),
                'items': [{'package': item['folder'], 'action': item['action']} for item in persona['items']]}

    return store
