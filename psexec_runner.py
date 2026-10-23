"""Admin-only, explicitly started PsExec sessions with bounded terminal output."""
import base64
import codecs
import ctypes
import getpass
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import subprocess
import threading
import time
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
CATALOGUE = {c['id']: c for c in json.loads((ROOT / 'psexec_catalogue.json').read_text(encoding='utf-8'))}
HOST = r'(?![-.])(?!.*\.\.)[A-Za-z0-9_.-]{1,64}'
EXE = r'[A-Za-z]:\\(?:[A-Za-z0-9 _.-]+\\)*PsExec(?:64)?\.exe'
TOOLS = {'PsExec', 'PsFile', 'PsGetSid', 'PsInfo', 'PsPing', 'PsKill', 'PsList', 'PsLoggedOn', 'PsLogList', 'PsPasswd', 'PsService', 'PsShutdown', 'PsSuspend'}
TOOL_EXE = r'[A-Za-z]:\\(?:[A-Za-z0-9 _.-]+\\)*(?:' + '|'.join(TOOLS) + r')(?:64)?\.exe'
TERMINAL = {'complete', 'failed', 'stopped', 'timed_out'}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    template: str = Field(max_length=64)
    target: str = Field(max_length=64)
    path: str = Field(max_length=260)
    elevated: bool = False
    values: dict[str, str] = Field(default_factory=dict, max_length=4)
    confirmation: str = Field(default='', max_length=64)


class TerminalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    line: str = Field(max_length=4096)


def prepare(p):
    item = CATALOGUE.get(p.template)
    if not item:
        raise HTTPException(400, 'Unknown PsExec template')
    target, executable = p.target.strip().upper(), p.path.strip()
    if not re.fullmatch(HOST, target) or not re.fullmatch(EXE, executable, re.I):
        raise HTTPException(400, 'Enter a valid target and full local PsExec executable path')
    values = {}
    fields = item.get('fields', [])
    if set(p.values) - {f['key'] for f in fields}:
        raise HTTPException(400, 'Unexpected command parameter')
    for f in fields:
        value = p.values.get(f['key'], '').strip()
        if len(value) > 253 or not re.fullmatch(f['pattern'], value):
            raise HTTPException(400, 'Invalid ' + f['label'])
        values[f['key']] = value
    if 'port' in values and not 1 <= int(values['port']) <= 65535:
        raise HTTPException(400, 'Port must be between 1 and 65535')
    if 'pid' in values and not 1 <= int(values['pid']) <= 4294967295:
        raise HTTPException(400, 'Invalid process ID')
    if 'session' in values and not 0 <= int(values['session']) <= 65535:
        raise HTTPException(400, 'Invalid Windows session ID')
    if item.get('change') and p.confirmation.strip().upper() != target:
        raise HTTPException(400, 'Confirm the target hostname for this change')
    if item.get('direct'):
        tool = item['tool']
        if tool not in TOOLS:
            raise HTTPException(400, 'Unknown PsTools executable')
        original = PureWindowsPath(executable)
        suffix = '64' if original.stem.lower().endswith('64') else ''
        executable = str(original.with_name(tool + suffix + '.exe'))
        if 'pid' in values and int(values['pid']) <= 4 and item.get('change'):
            raise HTTPException(400, 'System process IDs cannot be changed')
        substitutions = {**values, 'target': target, 'unc': '\\\\' + target}
        args = [executable, '-accepteula'] + [re.sub(r'\{([a-z]+)\}', lambda m: substitutions[m[1]], a) for a in item['args']]
        return item, target, args, subprocess.list2cmdline(args)
    def fill(text):
        return re.sub(r'\{(service|destination|port|pid)\}', lambda m: values[m[1]], text)
    script = item.get('script')
    if script:
        readable = "$ErrorActionPreference='Stop'; " + fill(script)
        remote = ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                  base64.b64encode(readable.encode('utf-16le')).decode('ascii')]
    else:
        remote = [fill(a) for a in item['args']]
        readable = ' '.join(remote)
    args = [executable, '\\\\' + target, '-accepteula', '-n', '10', '-nobanner']
    if item.get('system'):
        args.append('-s')
    elif p.elevated:
        args.append('-h')
    if item.get('interactive'):
        args += ['-i', values['session']]
    return item, target, args + remote, readable


def host_status(path):
    exists = bool(re.fullmatch(TOOL_EXE, path, re.I) and Path(path).is_file())
    elevated = False
    if os.name == 'nt':
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    return {'account': os.environ.get('USERDOMAIN', '') + '\\' + getpass.getuser(),
            'elevated': elevated, 'exists': exists}


class Runner:
    def __init__(self, popen=subprocess.Popen, preflight=host_status, limit=262144, timeout=180, shell_timeout=900):
        self.popen, self.preflight, self.limit = popen, preflight, limit
        self.timeout, self.shell_timeout = timeout, shell_timeout
        self.lock = threading.RLock()
        self.jobs = {}

    def snapshot(self, key):
        with self.lock:
            if key not in self.jobs:
                raise HTTPException(404, 'Session expired or Atlas restarted. Inspect the target before retrying.')
            return {k: v for k, v in self.jobs[key].items() if not k.startswith('_')}

    def append(self, key, text):
        with self.lock:
            j = self.jobs[key]
            output = j['output'] + text
            if len(output) > self.limit:
                j['truncated'] = True
            j['output'] = output[-self.limit:]

    prepare = staticmethod(prepare)
    catalogue = CATALOGUE
    session_label = 'PsExec'
    stop_notice = 'Local PsExec session ended. The remote command may still be running; inspect the target before retrying.'

    def start(self, p):
        item, target, args, readable = self.prepare(p)
        key = str(p.id)
        fingerprint = p.model_dump_json()
        with self.lock:
            if key in self.jobs:
                if self.jobs[key]['_request'] != fingerprint:
                    raise HTTPException(409, 'This run ID already belongs to another command')
                return self.snapshot(key)
            if any(j['state'] not in TERMINAL for j in self.jobs.values()):
                raise HTTPException(409, f'A {self.session_label} session is already running. Finish or stop it first.')
            status = self.preflight(args[0])
            if not status.get('elevated', False):
                raise HTTPException(403, f'Run Atlas from an elevated Windows account to use {self.session_label}.')
            if not status['exists']:
                raise HTTPException(400, 'Tool not found on the Atlas host: ' + args[0])
            # Expire completed transcripts only; never lose an active handle.
            while len(self.jobs) >= 20:
                del self.jobs[next(iter(self.jobs))]
            self.jobs[key] = {'id': key, 'target': target, 'title': item['title'],
                'template': item['id'], 'state': 'starting', 'interactive': bool(item.get('interactive')),
                'started': time.time(), 'finished': None, 'exit_code': None,
                'output': f"Atlas > {target} · {item['title']}\n{readable}\n\n",
                'truncated': False, 'account': status['account'], 'host_elevated': status['elevated'],
                '_request': fingerprint, '_process': None, '_stop': threading.Event(), '_input_lock': threading.Lock()}
            threading.Thread(target=self.work, args=(key, args), daemon=True, name='atlas-psexec').start()
            return self.snapshot(key)

    def work(self, key, args):
        process = None
        reader = None
        state = 'failed'
        try:
            with self.lock:
                j = self.jobs[key]
                # Stop can arrive before the worker gets a process handle.
                if j['_stop'].is_set():
                    state = 'stopped'
                    return
                process = self.popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=0, creationflags=0x08000000 if os.name == 'nt' else 0)
                j['_process'] = process
                j['state'] = 'running'
            def read():
                encoding = f'cp{ctypes.windll.kernel32.GetOEMCP()}' if os.name == 'nt' else 'utf-8'
                decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
                try:
                    while True:
                        chunk = process.stdout.read(4096)
                        if not chunk:
                            break
                        self.append(key, decoder.decode(chunk))
                    self.append(key, decoder.decode(b'', final=True))
                except (OSError, ValueError):
                    pass
            reader = threading.Thread(target=read, daemon=True, name='atlas-psexec-output')
            reader.start()
            deadline = time.monotonic() + (self.shell_timeout if j['interactive'] else self.catalogue[j['template']].get('timeout_seconds',self.timeout))
            while process.poll() is None:
                if j['_stop'].wait(.1):
                    state = 'stopped'
                    break
                if time.monotonic() >= deadline:
                    state = 'timed_out'
                    break
            else:
                state = 'complete' if process.returncode in self.catalogue[j['template']].get('success_exit_codes',[0]) else 'failed'
            if state in ('stopped', 'timed_out'):
                if process.poll() is None:
                    process.kill()
                self.append(key, '\nAtlas > ' + self.stop_notice + '\n')
            process.wait(timeout=5)
            reader.join(timeout=3)
            with self.lock:
                self.jobs[key]['exit_code'] = process.returncode
            self.append(key, f'\nAtlas > {state} · exit code {process.returncode}\n')
            if state == 'complete' and process.returncode == 3010:
                self.append(key, 'Atlas > Restart required. No automatic restart was requested.\n')
        except Exception as error:
            self.append(key, '\nAtlas > ' + str(error) + '\n')
            if process and process.poll() is None:
                process.kill()
        finally:
            if process:
                for stream in (process.stdin, process.stdout):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            with self.lock:
                self.jobs[key].update(state=state, finished=time.time(), _process=None)

    def send(self, key, line):
        if not line.strip() or any(c in line for c in '\r\n\x00'):
            raise HTTPException(400, 'Enter one command line')
        with self.lock:
            self.snapshot(key)
            j = self.jobs[key]
            if not j['interactive'] or j['state'] != 'running' or j['_stop'].is_set():
                raise HTTPException(409, 'This session does not accept terminal input')
            guard, process = j['_input_lock'], j['_process']
            if not guard.acquire(blocking=False):
                raise HTTPException(409, 'Previous terminal input is still being sent')
        try:
            encoding = f'cp{ctypes.windll.kernel32.GetOEMCP()}' if os.name == 'nt' else 'utf-8'
            process.stdin.write((line + '\r\n').encode(encoding, errors='strict'))
            process.stdin.flush()
        except (OSError, ValueError, UnicodeError) as error:
            raise HTTPException(409, 'Input could not be sent: ' + str(error)) from error
        finally:
            guard.release()
        return {'sent': True}

    def stop(self, key):
        with self.lock:
            self.snapshot(key)
            self.jobs[key]['_stop'].set()
        return self.snapshot(key)

    def close(self):
        with self.lock:
            for j in self.jobs.values():
                j['_stop'].set()
                process = j['_process']
                if process and process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass


runner = Runner()


def register(app, validate_target=None):
    def token(request):
        from atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before running a command')

    @app.get('/api/psexec/runs')
    def runs():
        with runner.lock:
            return [{'id': k, 'target': j['target'], 'title': j['title'], 'state': j['state']}
                    for k, j in reversed(runner.jobs.items())]

    @app.post('/api/psexec/run')
    def start(body: RunRequest, request: Request):
        token(request)
        if validate_target: body.target = validate_target(body.target)
        return runner.start(body)

    @app.get('/api/psexec/runs/{key}')
    def result(key: UUID):
        return runner.snapshot(str(key))

    @app.post('/api/psexec/runs/{key}/input')
    def send(key: UUID, body: TerminalInput, request: Request):
        token(request)
        return runner.send(str(key), body.line)

    @app.post('/api/psexec/runs/{key}/stop')
    def stop(key: UUID, request: Request):
        token(request)
        return runner.stop(str(key))

    @app.on_event('shutdown')
    def close():
        runner.close()
