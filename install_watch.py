"""Watch a deployment from Atlas, so the only code that runs on the target is the package's own script.

Atlas reads the PC over WMI, the way its other checks do, and starts nothing there for this:
- the programs registered for uninstall (machine-wide, 64- and 32-bit) before and after the installation;
- the processes the script starts, followed by parent process ID while the script runs and after it exits,
  so a setup.exe that hands over to msiexec, or an uninstaller that copies itself and exits, is waited for;
- Windows Installer: its InProgress key, or an msiexec.exe that is not the idle service (/V).
A process that starts and exits between two looks is missed. Windows Installer is still waited for.
"""
import json
import re
import threading
import time

# Read-only remote queries, run by Atlas's local PowerShell. TARGET is replaced by the quoted computer name.
SOFTWARE = r"""
$registry = [wmiclass]('\\' + TARGET + '\root\default:StdRegProv')
$items = [ordered]@{}
foreach ($entry in @(@('Machine', 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
                     @('Machine32', 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'))) {
    $list = $registry.EnumKey(2147483650, $entry[1])
    if ($list.ReturnValue -eq 2) { continue }
    if ($list.ReturnValue -ne 0) { throw 'Cannot read the uninstall registrations' }
    foreach ($key in @($list.sNames)) {
        $path = $entry[1] + '\' + $key
        $name = $registry.GetStringValue(2147483650, $path, 'DisplayName').sValue
        if ($name) { $items[$entry[0] + '\' + $key] = @([string]$name, [string]$registry.GetStringValue(2147483650, $path, 'DisplayVersion').sValue) }
    }
}
$items | ConvertTo-Json -Compress
"""
PROCESSES = r"""
$table = @(Get-WmiObject -ComputerName TARGET -Class Win32_Process -ErrorAction Stop | ForEach-Object {
    @{id = [long]$_.ProcessId; parent = [long]$_.ParentProcessId; name = [string]$_.Name; created = [string]$_.CreationDate
      cpu = [long]$_.KernelModeTime + [long]$_.UserModeTime; line = $(if ($_.Name -eq 'msiexec.exe') { [string]$_.CommandLine } else { '' })} })
$registry = [wmiclass]('\\' + TARGET + '\root\default:StdRegProv')
$busy = $registry.EnumKey(2147483650, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\InProgress').ReturnValue -eq 0
@{processes = $table; installer = [bool]$busy} | ConvertTo-Json -Compress -Depth 3
"""
IDLE_SERVICE = re.compile(r'\s/V\s*$', re.I)


def compare(before, after):
    """Registrations added, removed or changed, at most 20 of each, by name."""
    added = [{'name': name, 'version': version} for key, (name, version) in after.items() if key not in before]
    removed = [{'name': name, 'version': version} for key, (name, version) in before.items() if key not in after]
    changed = [{'name': after[key][0], 'from': before[key][1], 'to': after[key][1]}
               for key in after if key in before and before[key] != after[key]]
    first = lambda items: sorted(items, key=lambda item: str(item['name']).casefold())[:20]
    return {'added': first(added), 'removed': first(removed), 'changed': first(changed)}


class Watch:
    """One deployment's installation, read from Atlas. run(script) returns the output of a local PowerShell script."""

    def __init__(self, run, target, clock=time.monotonic, sleep=time.sleep):
        self.run, self.target, self.clock, self.sleep = run, target, clock, sleep
        self.before = None
        self.tree = {}  # process ID -> creation time, for the script and every process it started
        self.reading, self.launched, self.lock = None, False, threading.Lock()

    def query(self, script):
        return json.loads((self.run(script.replace('TARGET', self.target)) or '').strip().splitlines()[-1])

    def software(self):
        """The registered programs, or None when they cannot be read."""
        try:
            data = self.query(SOFTWARE)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return {key: (str(value[0]), str(value[1] or '')) for key, value in data.items() if isinstance(value, list) and len(value) == 2}

    def remember_software(self):
        """Read the registrations in the background while the package copies; ready() waits for them."""
        def read():
            found = self.software()
            with self.lock:
                if not self.launched:
                    self.before = found
        self.reading = threading.Thread(target=read, name='atlas-install-before', daemon=True)
        self.reading.start()

    def ready(self, timeout=180):
        """Called just before the launch. A read still running then is ignored: it could include the installation."""
        if self.reading:
            self.reading.join(timeout)
        with self.lock:
            self.launched = True

    def look(self):
        """The target's processes and whether Windows Installer is busy. Raises when the PC cannot be read."""
        data = self.query(PROCESSES)
        table = data.get('processes') or []
        if isinstance(table, dict):
            table = [table]
        busy = bool(data.get('installer')) or any(
            str(p.get('name', '')).lower() == 'msiexec.exe' and not IDLE_SERVICE.search(str(p.get('line') or '')) for p in table)
        return table, busy

    def follow(self, table, root=None):
        """The script's processes still running: the script and everything it started, by parent process ID.
        Each is matched with its creation time too, so a reused process ID is not mistaken for it."""
        alive = {p['id']: p for p in table}
        if root is not None and not self.tree and root in alive:
            self.tree[root] = alive[root]['created']
        grew = True
        while grew:
            grew = False
            for p in table:
                if p['id'] not in self.tree and p['parent'] in self.tree and p['created'] >= self.tree[p['parent']]:
                    self.tree[p['id']] = p['created']
                    grew = True
        return [p for p in table if self.tree.get(p['id']) == p['created']]

    def settle(self, exit_code, deadline, progress=None):
        """After the script exits: wait for the processes it started and for Windows Installer, then record what changed.
        Same record as the target used to write, with tracking 'process watch'."""
        started, quiet, shown, idle, names, busy = self.clock(), 0, '', None, [], False
        result = {'settled': False, 'waited_seconds': 0, 'still_running': [], 'left_running': [],
                  'windows_installer_busy': False, 'tracking': 'process watch'}
        while True:
            try:
                table, busy = self.look()
                running = [p for p in self.follow(table) if str(p['name']).lower() != 'conhost.exe']
                names = sorted({str(p['name']) for p in running})
            except Exception:
                running, quiet = None, 0
            if running is not None and not names and not busy:
                # Confirm once, in case the next step of a chained installer is just starting.
                quiet += 1
                if quiet >= 2:
                    result['settled'] = True
                    break
                self.sleep(2)
                continue
            quiet = 0
            if running is not None:
                # A finished installer can leave its application running. Accept that once Windows Installer is idle,
                # the remaining processes have used under a second of CPU for a minute and the registered software changed.
                cpu = sum(int(p.get('cpu') or 0) for p in running) / 1e7
                key = ','.join(names)
                if not busy and self.before is not None and idle and idle[0] == key and cpu - idle[1] < 1:
                    if self.clock() - idle[2] >= 60:
                        after = self.software()
                        if after is not None and any(compare(self.before, after).values()):
                            result.update(settled=True, left_running=names)
                            break
                else:
                    idle = (key, cpu, self.clock())
            if self.clock() >= deadline:
                result.update(still_running=names if running is not None else ['the PC could not be read'],
                              windows_installer_busy=bool(busy))
                break
            waiting = names + (['Windows Installer'] if busy else [])
            status = f'Script exited with code {exit_code}; waiting for {", ".join(waiting) or "the PC to answer"} to finish'
            if progress and status != shown:
                progress(status)
                shown = status
            self.sleep(5)
        result['waited_seconds'] = int(self.clock() - started)
        if self.before is not None:
            after = self.software()
            if after is not None:
                result['software'] = compare(self.before, after)
        return result


class Record(dict):
    """The installer-activity record a monitor fills in. It carries the watch started before the launch, which is
    not part of the record itself."""

    def __init__(self, watch):
        super().__init__()
        self.watch = watch
