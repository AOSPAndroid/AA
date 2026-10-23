"""Explicit local command execution, available only through the Admin server."""
import base64
import os
import secrets
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from psexec_runner import Runner, host_status


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    shell: Literal['powershell', 'cmd'] = 'powershell'
    code: str = Field(min_length=1, max_length=65536)


def prepare(command):
    if not command.code.strip() or '\x00' in command.code:
        raise HTTPException(400, 'Enter a command or script')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    if command.shell == 'powershell':
        executable = system / 'WindowsPowerShell/v1.0/powershell.exe'
        args = [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                base64.b64encode(command.code.encode('utf-16le')).decode('ascii')]
    else:
        args = [str(system / 'cmd.exe'), '/d', '/s', '/c', command.code]
    item = {'id': command.shell, 'title': command.shell + ' · local command'}
    return item, os.environ.get('COMPUTERNAME', 'Atlas host'), args, command.code


def preflight(path):
    status = host_status(path)
    status['exists'] = os.name == 'nt' and Path(path).is_file()
    return status


class LocalRunner(Runner):
    prepare = staticmethod(prepare)
    session_label = 'Terminal'
    stop_notice = 'Local process ended. Child or remote processes may still be running; inspect them separately.'
    catalogue = {'powershell': {'timeout_seconds': 900}, 'cmd': {'timeout_seconds': 900}}


runner = LocalRunner(preflight=preflight)


def register(app):
    def authorize(request):
        from atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before using Terminal')

    @app.get('/api/terminal/runs')
    def runs(request: Request):
        authorize(request)
        with runner.lock:
            return [runner.snapshot(key) for key in reversed(runner.jobs)]

    @app.post('/api/terminal/run')
    def start(body: Command, request: Request):
        authorize(request)
        return runner.start(body)

    @app.get('/api/terminal/runs/{key}')
    def result(key: UUID, request: Request):
        authorize(request)
        return runner.snapshot(str(key))

    @app.post('/api/terminal/runs/{key}/stop')
    def stop(key: UUID, request: Request):
        authorize(request)
        return runner.stop(str(key))

    @app.on_event('shutdown')
    def close():
        runner.close()
