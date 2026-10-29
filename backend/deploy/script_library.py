"""Scripts: a library of PowerShell scripts run on the Atlas host against a list of machines.

Built-in scripts ship with Atlas and cannot be edited; saved scripts live in data/scripts.json.
Atlas builds every run on the server: it validates the machine names, quotes each value and
prepends them as PowerShell variables ($Computers, $Services, ...), so typed text never becomes code.
Scripts report one line per result: [OK], [FAIL], [WARN] or [INFO], which the page colours.
"""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from backend.remote.local_terminal import LocalRunner, preflight

HOSTNAME = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$')
SCRIPT_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
MAX_TARGETS = 500

EXPORT_HELPERS = r'''
function Write-Ok([string]$Text) { Write-Host "[OK] $Text" }
function Write-Fail([string]$Text) { Write-Host "[FAIL] $Text" }
function Write-Warn([string]$Text) { Write-Host "[WARN] $Text" }
function Write-Info([string]$Text) { Write-Host "[INFO] $Text" }
function Get-Wmi([string]$Computer, [string]$Class, [string]$Filter) {
    if ($Filter) { Get-WmiObject -Class $Class -ComputerName $Computer -Filter $Filter -ErrorAction Stop }
    else { Get-WmiObject -Class $Class -ComputerName $Computer -ErrorAction Stop }
}
function Get-WqlText([string]$Text) { $Text.Replace('\', '\\').Replace("'", "\'") }
'''

HELPERS = EXPORT_HELPERS + r'''
# Scripts cannot prompt here: Read-Host answers with the Target machines box, comma separated.
function Read-Host { param([Parameter(Position = 0)][object]$Prompt, [switch]$AsSecureString) $Computers -join ',' }
'''

SERVICE_LOOKUP = r'''
        $wql = Get-WqlText $Name
        $service = Get-Wmi $Computer Win32_Service "Name='$wql' OR DisplayName='$wql'"
'''

BUILTIN = [
    {
        'id': 'services-disable', 'name': 'Stop and disable services', 'category': 'Services', 'changes': True,
        'description': 'Stops each service and sets its startup type to Disabled. Use "Enable and start services" to undo.',
        'params': [{'name': 'Services', 'label': 'Services (name or display name, one per line)', 'kind': 'list',
                    'default': ''}],
        'code': r'''
foreach ($Computer in $Computers) {
    Write-Host "===== $Computer ====="
    foreach ($Name in $Services) {
        try {''' + SERVICE_LOOKUP + r'''
        } catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; break }
        if (-not $service) { Write-Warn "$Computer · $Name · not found"; continue }
        foreach ($item in @($service)) {
            if ($item.State -ne 'Stopped') {
                $result = $item.StopService()
                if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · $($item.Name) · stop requested" }
                else { Write-Fail "$Computer · $($item.Name) · stop failed (code $($result.ReturnValue))" }
            } else { Write-Info "$Computer · $($item.Name) · already stopped" }
            $result = $item.ChangeStartMode('Disabled')
            if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · $($item.Name) · disabled" }
            else { Write-Fail "$Computer · $($item.Name) · disable failed (code $($result.ReturnValue))" }
        }
    }
}
''',
    },
    {
        'id': 'services-enable', 'name': 'Enable and start services', 'category': 'Services', 'changes': True,
        'description': 'Sets the startup type, then starts each service. Undoes "Stop and disable services".',
        'params': [{'name': 'Services', 'label': 'Services (name or display name, one per line)', 'kind': 'list',
                    'default': ''},
                   {'name': 'StartMode', 'label': 'Startup type', 'kind': 'choice',
                    'options': ['Automatic', 'Manual'], 'default': 'Automatic'}],
        'code': r'''
foreach ($Computer in $Computers) {
    Write-Host "===== $Computer ====="
    foreach ($Name in $Services) {
        try {''' + SERVICE_LOOKUP + r'''
        } catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; break }
        if (-not $service) { Write-Warn "$Computer · $Name · not found"; continue }
        foreach ($item in @($service)) {
            $result = $item.ChangeStartMode($StartMode)
            if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · $($item.Name) · startup $StartMode" }
            else { Write-Fail "$Computer · $($item.Name) · startup change failed (code $($result.ReturnValue))" }
            if ($item.State -ne 'Running') {
                $result = $item.StartService()
                if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · $($item.Name) · start requested" }
                else { Write-Fail "$Computer · $($item.Name) · start failed (code $($result.ReturnValue))" }
            } else { Write-Info "$Computer · $($item.Name) · already running" }
        }
    }
}
''',
    },
    {
        'id': 'services-status', 'name': 'Check services', 'category': 'Services', 'changes': False,
        'description': 'Shows whether each service exists, its state and startup type. Changes nothing.',
        'params': [{'name': 'Services', 'label': 'Services (name or display name, one per line)', 'kind': 'list',
                    'default': ''}],
        'code': r'''
foreach ($Computer in $Computers) {
    foreach ($Name in $Services) {
        try {''' + SERVICE_LOOKUP + r'''
        } catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; break }
        if (-not $service) { Write-Warn "$Computer · $Name · not found"; continue }
        foreach ($item in @($service)) {
            $line = "$Computer · $($item.Name) · $($item.State) · startup $($item.StartMode)"
            if ($item.State -eq 'Running') { Write-Ok $line } else { Write-Warn $line }
        }
    }
}
''',
    },
    {
        'id': 'processes-stop', 'name': 'Stop processes by name', 'category': 'Processes', 'changes': True,
        'description': 'Ends every process whose name contains one of the words, in all sessions. Unsaved work in those apps is lost.',
        'params': [{'name': 'Processes', 'label': 'Process name contains (one per line)', 'kind': 'list', 'default': 'OpenFin'}],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $all = Get-Wmi $Computer Win32_Process '' }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    foreach ($Word in $Processes) {
        $found = @($all | Where-Object { $_.Name -like "*$Word*" })
        if (-not $found.Count) { Write-Info "$Computer · no process matching $Word"; continue }
        foreach ($process in $found) {
            $result = $process.Terminate()
            if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · ended $($process.Name) (PID $($process.ProcessId))" }
            else { Write-Fail "$Computer · could not end $($process.Name) (PID $($process.ProcessId), code $($result.ReturnValue))" }
        }
    }
}
''',
    },
    {
        'id': 'online', 'name': 'Online check', 'category': 'Health', 'changes': False,
        'description': 'Resolves each name in DNS and pings it once.',
        'params': [],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $address = ([System.Net.Dns]::GetHostAddresses($Computer) | Select-Object -First 1).IPAddressToString }
    catch { Write-Fail "$Computer · not found in DNS"; continue }
    if (Test-Connection -ComputerName $Computer -Count 1 -Quiet) { Write-Ok "$Computer · online · $address" }
    else { Write-Fail "$Computer · no ping reply · $address" }
}
''',
    },
    {
        'id': 'uptime', 'name': 'Uptime and last restart', 'category': 'Health', 'changes': False,
        'description': 'Last boot time and uptime. Flags machines up for more than the chosen number of days.',
        'params': [{'name': 'MaxDays', 'label': 'Warn after (days)', 'kind': 'choice', 'options': ['3', '7', '8', '14', '30'], 'default': '8'}],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $os = Get-Wmi $Computer Win32_OperatingSystem '' }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    $boot = $os.ConvertToDateTime($os.LastBootUpTime)
    $up = (Get-Date) - $boot
    $line = "$Computer · up $([int]$up.TotalDays) d $($up.Hours) h · last restart $($boot.ToString('yyyy-MM-dd HH:mm'))"
    if ($up.TotalDays -gt [int]$MaxDays) { Write-Warn $line } else { Write-Ok $line }
}
''',
    },
    {
        'id': 'disk-space', 'name': 'Disk free space', 'category': 'Health', 'changes': False,
        'description': 'Free space on each fixed drive. Flags drives under 10% or 5 GB free.',
        'params': [],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $disks = Get-Wmi $Computer Win32_LogicalDisk 'DriveType=3' }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    foreach ($disk in @($disks)) {
        if (-not $disk.Size) { continue }
        $free = [math]::Round($disk.FreeSpace / 1GB, 1); $size = [math]::Round($disk.Size / 1GB, 1)
        $percent = [math]::Round(100 * $disk.FreeSpace / $disk.Size)
        $line = "$Computer · $($disk.DeviceID) · $free GB free of $size GB ($percent%)"
        if ($percent -lt 10 -or $free -lt 5) { Write-Fail $line } elseif ($percent -lt 20) { Write-Warn $line } else { Write-Ok $line }
    }
}
''',
    },
    {
        'id': 'logged-on', 'name': 'Who is logged on', 'category': 'Health', 'changes': False,
        'description': 'The console user and everyone running a desktop (explorer.exe), including remote sessions.',
        'params': [],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $system = Get-Wmi $Computer Win32_ComputerSystem ''; $shells = Get-Wmi $Computer Win32_Process "Name='explorer.exe'" }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    $users = @($shells | ForEach-Object { $owner = $_.GetOwner(); if ($owner.User) { "$($owner.Domain)\$($owner.User)" } } | Sort-Object -Unique)
    if ($system.UserName -or $users.Count) { Write-Ok "$Computer · console $(if ($system.UserName) { $system.UserName } else { 'none' }) · desktops $($users -join ', ')" }
    else { Write-Info "$Computer · nobody logged on" }
}
''',
    },
    {
        'id': 'software-find', 'name': 'Find installed software', 'category': 'Software', 'changes': False,
        'description': 'Searches the installed programs list (64- and 32-bit) through Remote Registry.',
        'params': [{'name': 'Names', 'label': 'Program name contains (one per line)', 'kind': 'list', 'default': ''}],
        'code': r'''
$paths = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
foreach ($Computer in $Computers) {
    try { $hive = [Microsoft.Win32.RegistryKey]::OpenRemoteBaseKey('LocalMachine', $Computer) }
    catch { Write-Fail "$Computer · Remote Registry unavailable: $($_.Exception.Message)"; continue }
    $found = 0
    foreach ($path in $paths) {
        $key = $hive.OpenSubKey($path); if (-not $key) { continue }
        foreach ($sub in $key.GetSubKeyNames()) {
            $app = $key.OpenSubKey($sub); $display = $app.GetValue('DisplayName')
            if ($display -and ($Names | Where-Object { $display -like "*$_*" })) {
                Write-Ok "$Computer · $display · $($app.GetValue('DisplayVersion'))"; $found++
            }
        }
    }
    $hive.Close()
    if (-not $found) { Write-Warn "$Computer · no matching program" }
}
''',
    },
    {
        'id': 'gpupdate', 'name': 'Group Policy update', 'category': 'Maintenance', 'changes': True,
        'description': 'Starts "gpupdate /force" on each machine (computer policy). It runs in the background there.',
        'params': [],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $result = Invoke-WmiMethod -ComputerName $Computer -Class Win32_Process -Name Create -ArgumentList 'cmd.exe /c gpupdate /target:computer /force' -ErrorAction Stop }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · gpupdate started (PID $($result.ProcessId))" }
    else { Write-Fail "$Computer · gpupdate not started (code $($result.ReturnValue))" }
}
''',
    },
    {
        'id': 'restart', 'name': 'Restart machines', 'category': 'Maintenance', 'changes': True,
        'description': 'Forces an immediate restart. Anyone logged on loses unsaved work.',
        'params': [],
        'code': r'''
foreach ($Computer in $Computers) {
    try { $os = Get-Wmi $Computer Win32_OperatingSystem '' }
    catch { Write-Fail "$Computer · cannot reach WMI: $($_.Exception.Message)"; continue }
    $os.PSBase.Scope.Options.EnablePrivileges = $true
    $result = $os.Win32Shutdown(6)
    if ($result.ReturnValue -eq 0) { Write-Ok "$Computer · restart requested" }
    else { Write-Fail "$Computer · restart refused (code $($result.ReturnValue))" }
}
''',
    },
]
BUILTIN_BY_ID = {script['id']: script for script in BUILTIN}


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def split_items(text):
    return [item.strip() for item in re.split(r'[\r\n,;]+', text or '') if item.strip()]


def parse_targets(text):
    names, seen = [], set()
    for name in re.split(r'[\s,;]+', text or ''):
        name = name.strip().strip('\\')
        if not name:
            continue
        if not HOSTNAME.fullmatch(name):
            raise HTTPException(422, f'"{name[:80]}" is not a valid machine name.')
        if name.upper() not in seen:
            seen.add(name.upper())
            names.append(name)
    if not names:
        raise HTTPException(422, 'Enter at least one target machine.')
    if len(names) > MAX_TARGETS:
        raise HTTPException(422, f'Run at most {MAX_TARGETS} machines at a time.')
    return names


def parameter_lines(params, values):
    lines = []
    for param in params:
        raw = values.get(param['name'], param.get('default', ''))
        if not isinstance(raw, str) or '\x00' in raw:
            raise HTTPException(422, f'{param["label"]}: enter text.')
        if param['kind'] == 'choice':
            if raw not in param['options']:
                raise HTTPException(422, f'{param["label"]}: choose one of {", ".join(param["options"])}.')
            lines.append(f'${param["name"]} = {ps_quote(raw)}')
        else:
            items = split_items(raw)
            if not items:
                raise HTTPException(422, f'{param["label"]}: enter at least one value.')
            if len(items) > 100 or any(len(item) > 256 for item in items):
                raise HTTPException(422, f'{param["label"]}: at most 100 values of 256 characters.')
            lines.append(f'${param["name"]} = @({", ".join(map(ps_quote, items))})')
    return lines


def build(code, targets, params=(), values=None):
    """The exact script Atlas runs: quoted values first, then the helpers, then the script."""
    header = ['$ErrorActionPreference = "Continue"', f'$Computers = @({", ".join(map(ps_quote, targets))})',
              *parameter_lines(params, values or {})]
    return '\n'.join(header) + '\n' + HELPERS + '\n' + code.strip() + '\n'


class Store:
    """Saved scripts in one JSON file, written atomically."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def all(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise HTTPException(503, f'Cannot read saved scripts in {self.path}.') from error
        return [item for item in data.get('scripts', []) if isinstance(item, dict) and SCRIPT_ID.fullmatch(str(item.get('id', '')))]

    def write(self, scripts):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'scripts': scripts}, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)

    def get(self, script_id):
        return next((item for item in self.all() if item['id'] == script_id), None)

    def save(self, script_id, body):
        with self.lock:
            scripts = self.all()
            current = next((item for item in scripts if item['id'] == script_id), None)
            if current and current.get('revision', 0) != body.revision:
                raise HTTPException(409, 'This script was changed in another window. Reopen it before saving.')
            if not current and body.revision:
                raise HTTPException(404, 'This script was deleted in another window.')
            item = {'id': script_id, 'name': body.name.strip(), 'description': body.description.strip(),
                    'changes': body.changes, 'code': body.code, 'revision': body.revision + 1,
                    'updated': time.strftime('%Y-%m-%dT%H:%M:%S')}
            scripts = [item if entry['id'] == script_id else entry for entry in scripts] if current else [*scripts, item]
            self.write(scripts)
            return item

    def delete(self, script_id, revision):
        with self.lock:
            scripts = self.all()
            current = next((item for item in scripts if item['id'] == script_id), None)
            if not current:
                raise HTTPException(404, 'Script not found.')
            if current.get('revision', 0) != revision:
                raise HTTPException(409, 'This script was changed in another window. Reopen it before deleting.')
            self.write([item for item in scripts if item['id'] != script_id])
            return {'deleted': script_id}


class Saved(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=1000)
    changes: bool = True
    code: str = Field(min_length=1, max_length=65536)
    revision: int = Field(default=0, ge=0)


class Run(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    script: str = Field(min_length=1, max_length=64)
    targets: str = Field(max_length=20000)
    values: dict[str, str] = Field(default_factory=dict)
    code: str | None = Field(default=None, max_length=65536)
    confirmed: bool = False


class Job(BaseModel):
    """What the runner sees: the finished script, its title and how many machines it touches."""
    id: UUID
    title: str
    code: str
    targets: list[str]


def prepare(job):
    from backend.remote.local_terminal import Command, prepare as powershell
    _, host, args, _ = powershell(Command(id=job.id, shell='powershell', code=job.code))
    shown = ', '.join(job.targets[:12]) + (f' and {len(job.targets) - 12} more' if len(job.targets) > 12 else '')
    item = {'id': 'script', 'title': job.title}
    return item, f'{len(job.targets)} machine{"s" if len(job.targets) != 1 else ""}', args, f'Atlas host {host} · targets: {shown}'


class ScriptRunner(LocalRunner):
    prepare = staticmethod(prepare)
    session_label = 'script'
    stop_notice = 'Script process ended. A remote action that had already started may still finish on its machine.'
    catalogue = {'script': {'timeout_seconds': 1800}}


runner = ScriptRunner(preflight=preflight)


def register(app, path):
    store = Store(path)

    def authorize(request):
        from backend.atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before using Scripts')

    def valid_id(script_id):
        if not SCRIPT_ID.fullmatch(script_id) or script_id in BUILTIN_BY_ID:
            raise HTTPException(400, 'Use lowercase letters, digits and dashes for a saved script ID.')

    @app.get('/api/script-library')
    def library():
        return {'builtin': [{k: v for k, v in item.items()} for item in BUILTIN], 'saved': store.all(),
                'helpers': HELPERS.strip(), 'export_helpers': EXPORT_HELPERS.strip(), 'max_targets': MAX_TARGETS}

    @app.put('/api/script-library/saved/{script_id}')
    def save(script_id: str, body: Saved, request: Request):
        authorize(request)
        valid_id(script_id)
        return store.save(script_id, body)

    @app.delete('/api/script-library/saved/{script_id}')
    def delete(script_id: str, revision: int, request: Request):
        authorize(request)
        valid_id(script_id)
        return store.delete(script_id, revision)

    @app.post('/api/script-library/run')
    def run(body: Run, request: Request):
        authorize(request)
        builtin = BUILTIN_BY_ID.get(body.script)
        if builtin:
            code, title, params, changes = builtin['code'], builtin['name'], builtin['params'], builtin['changes']
        else:
            saved = store.get(body.script) if SCRIPT_ID.fullmatch(body.script) else None
            # An open, unsaved draft runs exactly what is in the editor.
            code = body.code if body.code is not None else saved and saved['code']
            if not code or not code.strip():
                raise HTTPException(404, 'Script not found. Save it or paste its code first.')
            title, params, changes = (saved or {}).get('name') or 'Unsaved script', [], (saved or {}).get('changes', True)
        if changes and not body.confirmed:
            raise HTTPException(428, 'Confirm the target machines before running a script that changes them.')
        targets = parse_targets(body.targets)
        return runner.start(Job(id=body.id, title=title, code=build(code, targets, params, body.values), targets=targets))

    @app.get('/api/script-library/runs')
    def runs(request: Request):
        authorize(request)
        with runner.lock:
            return [runner.snapshot(key) for key in reversed(runner.jobs)]

    @app.get('/api/script-library/runs/{key}')
    def result(key: UUID, request: Request):
        authorize(request)
        return runner.snapshot(str(key))

    @app.post('/api/script-library/runs/{key}/stop')
    def stop(key: UUID, request: Request):
        authorize(request)
        return runner.stop(str(key))

    @app.on_event('shutdown')
    def close():
        runner.close()
