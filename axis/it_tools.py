"""Standalone Windows administration for the local agent. Python 3.8+, no packages.

The model selects named operations; this module owns validation, approval, Windows
calls and durable deployment jobs. It does not import Atlas; with an Atlas database
it only reads Atlas's unresolved-target guard so both apps refuse the same PC.
"""
import argparse
import base64
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import sys
import time
import uuid


def tool(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(required), "additionalProperties": False}}}


STRING = {"type": "string"}
TOOLS = [
    tool("inspect_computer", "Read a Windows PC through WMI. Services/processes include a snapshot ID needed for changes. Software reads uninstall registry entries, never Win32_Product. Use query and offset to narrow/paginate results.", {
        "computer": STRING, "view": {"type": "string", "enum": ["preflight", "overview", "disks", "services", "processes", "software"]},
        "query": STRING, "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["computer", "view"]),
    tool("inspect_computers", "Read many Windows PCs at once for a quick picture: preflight (ping, admin share, logged-on user), overview (CPU, memory, uptime) or disks (free space). Returns one row per PC with its readings or its error; an unreachable PC never stops the others. Read-only. For services, processes or software, use inspect_computer on one PC.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50},
        "view": {"type": "string", "enum": ["preflight", "overview", "disks"]}}, ["computers", "view"]),
    tool("find_packages", "Search the configured package repository. A single match includes its action-specific scripts; reuse them without another lookup. Multiple matches require choosing an exact package. Supply package and offset for more script pages. Never guess a package or script.", {
        "query": STRING, "package": STRING,
        "action": {"type": "string", "enum": ["Install", "Uninstall", "Repair"]},
        "offset": {"type": "integer", "minimum": 0}}, []),
    tool("deploy_package", "Approve and start a durable deployment to explicit PC names. Discover package/script first. The worker checks WMI/admin-share access, copies with Robocopy, launches via WMI, waits for the script and the installer processes it starts (and Windows Installer) to finish, then records exit code, log and registered-software changes. Returns a queued job, NOT installation success. Report the job and /jobs ID; wait or verify only when requested. Supports multiple PCs, processed in order. Never automatically retry an unknown outcome.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 200},
        "package": STRING, "script": STRING,
        "action": {"type": "string", "enum": ["Install", "Uninstall", "Repair"]},
        "mode": {"type": "string", "enum": ["full", "copy", "execute"]}},
         ["computers", "package", "script", "action"]),
    tool("it_job_status", "List saved deployments/reboots, or read a job's per-PC outcomes and logs. When the user asks to wait, use wait_seconds=10 for a bounded wait instead of immediate repeated polls. Unknown means inspect the PC before retrying. acknowledge_unknown only releases an unknown job's target after the operator confirms inspection; it never retries or stops remote work.", {
        "job_id": STRING, "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 10},
        "acknowledge_unknown": {"type": "boolean"}}, []),
    tool("computer_action", "Change a Windows PC after approval. For service_start/stop/restart use name and the services snapshot ID; for process_stop use pid and the processes snapshot ID. Re-reads identity and verifies the outcome. enable_remote_registry explicitly enables/starts RemoteRegistry. reboot returns a monitored job. cleanup_packages deletes only this agent's staging folder.", {
        "computer": STRING, "action": {"type": "string", "enum": ["service_start", "service_stop", "service_restart", "process_stop", "enable_remote_registry", "reboot", "cleanup_packages"]},
        "name": STRING, "pid": {"type": "integer", "minimum": 5}, "snapshot": STRING}, ["computer", "action"]),
    tool("bulk_service_action", "Start, stop or restart one Windows service by name across several PCs after a single approval that lists them. Each PC is checked and verified on its own; a PC that fails (service missing, protected or unreachable) never stops the others. Protected system services are refused. The current service identity is inspected under each target's lock before changing it; no external snapshot is needed. For one PC bound to its inspect snapshot use computer_action; for more complex bulk changes run a saved script.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50},
        "action": {"type": "string", "enum": ["service_start", "service_stop", "service_restart"]},
        "name": STRING}, ["computers", "action", "name"]),
    tool("directory_lookup", "Read an exact Active Directory user, computer or group, including group membership. Requires the ActiveDirectory PowerShell module (RSAT). Does not change accounts or group membership.", {
        "kind": {"type": "string", "enum": ["user", "computer", "group"]},
        "identity": STRING, "server": STRING}, ["kind", "identity"]),
    tool("open_remote_tool", "Open a Windows support application for an explicit PC after approval. Opens the application's UI; does not establish or automate a remote session.", {
        "computer": STRING, "tool": {"type": "string", "enum": ["rdp", "remote_assistance", "computer_management", "event_viewer", "admin_share", "temp", "packages"]}}, ["computer", "tool"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
SUFFIXES = {"Install": ("_i", "_install", "_installs"),
            "Uninstall": ("_u", "_uninstall", "_uninstalls"),
            "Repair": ("_r", "_repair", "_repairs")}
ACTIVE = {"queued", "running"}
RETAINED_JOBS = 200          # finished jobs kept for /jobs; active and unresolved jobs are never pruned
SNAPSHOT_SECONDS = 3600      # snapshots expire after 15 minutes; keep a margin for in-flight approvals
OUTPUT_SECONDS = 30 * 86400  # saved full tool results
REMOTE_ROOT = r"C:\Temp\LocalAgent"
DEFAULT_PACKAGE_REPO = r"C:\Users\x01426046\OneDrive - Barclays Bank PLC\Shortcuts\EPP_PACKAGE_REPO_BetaPackages - BetaPackages"


class UnknownOutcome(RuntimeError):
    pass


def windows_account():
    """The Windows account running this process, as Atlas records it."""
    import getpass
    domain = os.environ.get("USERDOMAIN", "") if os.name == "nt" else ""
    return ((domain + "\\") if domain else "") + getpass.getuser()


# Atlas's deployment history. AA's Axis adds its own deployments so one history shows both apps.
HISTORY_TABLE = ("CREATE TABLE IF NOT EXISTS deployments(id text primary key,started text,finished text,operator text,"
                 "target text,package text,action text,script text,mode text,state text,robocopy_code text,pid text,"
                 "exit_code text,details text,payload text)")


def record_history(database, row_id, fields, create=False):
    # mode=rw: an absent database is an error, never a new empty file.
    con = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
    try:
        with con:
            if create:
                con.execute(HISTORY_TABLE)
                if "payload" not in {row[1] for row in con.execute("PRAGMA table_info(deployments)")}:
                    con.execute("ALTER TABLE deployments ADD COLUMN payload text")
                con.execute("INSERT OR REPLACE INTO deployments(id, %s) VALUES (?%s)" % (", ".join(fields), ", ?" * len(fields)),
                            [row_id] + list(fields.values()))
            else:
                con.execute("UPDATE deployments SET %s WHERE id=?" % ", ".join(key + "=?" for key in fields),
                            list(fields.values()) + [row_id])
    finally:
        con.close()


def history_outcome(result):
    """Atlas's convention: an executed installer is 'launched' with its exit code, never 'installed'."""
    if result["state"] == "unknown":
        return "unknown"  # Even after an exit code was read, a later failure leaves the outcome open.
    if "exit_code" in result:
        return "launched"
    return {"copied": "complete", "unknown": "unknown", "running": "running"}.get(result["state"], "failed")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def text(value, label, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid %s" % label)
    return value.strip()


def computer(value):
    value = text(value, "computer name", 64)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) or ".." in value or value.endswith((".", "-")):
        raise ValueError("Use one explicit computer hostname or IPv4 address, without wildcards or paths")
    return value.upper()


def computer_targets(computers, validate=None):
    if not isinstance(computers, list) or not 1 <= len(computers) <= 50:
        raise ValueError("Supply 1 to 50 computer names")
    validate = validate or computer
    return list(dict.fromkeys(validate(value) for value in computers))

def inspection_targets(computers, view, validate=None):
    if view not in ("preflight", "overview", "disks"):
        raise ValueError("Bulk inspection covers preflight, overview or disks; use inspect_computer for services, processes or software")
    return computer_targets(computers, validate)

def service_targets(computers, action, name, validate=None):
    if action not in ("service_start", "service_stop", "service_restart"):
        raise ValueError("Bulk actions cover service_start, service_stop or service_restart")
    return computer_targets(computers, validate), text(name, "service name")



def target_key(value):
    """One lock and guard name per PC, whether it is given short or fully qualified."""
    name = str(value or "").strip().upper().rstrip(".")
    return name if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", name) else name.split(".", 1)[0]


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("%s must be between %d and %d" % (label, low, high))
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid job or snapshot ID")
    return value


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        for attempt in range(20):
            try:
                os.replace(str(temporary), str(path))
                break
            except PermissionError:
                # Windows refuses to replace a file another process is reading,
                # such as Atlas's activity panel or a chat checking this job.
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def linked(path):
    """Reject symlinks and junctions without rejecting OneDrive recall attributes."""
    path = Path(path)
    return path.is_symlink() or getattr(path.lstat(), "st_reparse_tag", 0) == 0xA0000003


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def share(pc, path):
    p = PureWindowsPath(path)
    if p.drive.upper() != "C:" or ".." in p.parts:
        raise ValueError("Only the fixed C: staging paths may be used")
    return Path("\\\\%s\\C$\\%s" % (computer(pc), "\\".join(p.parts[1:])))


def process_alive(pid):
    if type(pid) is not int or pid < 1:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied establishes no outcome; keep the job active.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def target_lock(state_dir, pc):
    """OS-owned locks release on worker exit, including crashes; no stale lock files."""
    path = Path(state_dir) / "locks" / (target_key(computer(pc)) + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another operation is active on " + pc)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


# Atlas's job_service.TERMINAL; any other saved state means the work may still be running.
ATLAS_TERMINAL = {"launched", "complete", "failed", "cancelled", "interrupted", "unknown"}


def atlas_blocking(database, pc):
    """Why Atlas's records forbid work on this PC, or None. Unreadable records never read as clear."""
    key = target_key(pc)
    try:
        con = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "operation_guard" in tables and any(target_key(row[0]) == key for row in con.execute("SELECT target FROM operation_guard")):
                return ("%s has an unresolved Atlas operation. Inspect the PC, then acknowledge it in Atlas's "
                        "Operation recovery." % pc)
            # A job that was running when Atlas stopped is marked interrupted only at Atlas's next start.
            for (body,) in con.execute("SELECT body FROM operation_state WHERE kind='job'") if "operation_state" in tables else ():
                job = json.loads(body)
                if job.get("state") in ATLAS_TERMINAL:
                    continue
                targets = [job.get("target")] + [row.get("target") or row.get("machine")
                                                 for row in job.get("items", job.get("results", [])) if isinstance(row, dict)]
                if any(isinstance(name, str) and target_key(name) == key for name in targets):
                    return ("%s has an Atlas operation that is running, or was running when Atlas stopped. Wait for it, "
                            "or open AA so an interrupted operation is listed in Operation recovery." % pc)
            return None
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError, AttributeError) as error:
        raise RuntimeError("Cannot read Atlas's operation records (%s); no change was started" % error) from None


class ITTools:
    def __init__(self, state_dir, package_repo=None, confirm=None, timeout=3600, atlas_db=None, atlas_history=False):
        self.state = Path(state_dir).expanduser().resolve()
        self.atlas_db = str(atlas_db) if atlas_db else None
        self.atlas_history = bool(atlas_history and self.atlas_db)
        package_repo = package_repo or os.environ.get("AGENT_PACKAGE_REPO") or os.environ.get("WMI_PACKAGE_REPO") or DEFAULT_PACKAGE_REPO
        self.repository = Path(os.path.expandvars(package_repo)).expanduser().resolve()
        self.confirm = confirm or (lambda action: False)
        self.timeout = integer(timeout, "Deployment timeout", 60, 86400)

    def call(self, name, args):
        if os.name != "nt":
            raise RuntimeError("These IT actions require Windows; file and shell tools remain available")
        if not isinstance(args, dict):
            raise ValueError("Arguments must be an object")
        schema = next(t["function"]["parameters"] for t in TOOLS if t["function"]["name"] == name)
        unknown = set(args) - set(schema["properties"])
        missing = set(schema["required"]) - set(args)
        if unknown or missing:
            raise ValueError("Unexpected arguments %s; missing arguments %s" % (sorted(unknown), sorted(missing)))
        return getattr(self, name)(**args)

    def ps(self, request, timeout=60):
        payload = base64.b64encode(json.dumps(request).encode("utf-8")).decode("ascii")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(Path(__file__).with_name("it_windows.ps1")), "-RequestBase64", payload]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = result.stdout.decode("utf-8-sig", "replace").strip()
        if result.returncode:
            raise RuntimeError((result.stderr.decode("utf-8-sig", "replace") or output or "PowerShell failed").strip()[:4000])
        data = json.loads(output)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise RuntimeError("Windows returned an invalid result")
        if request.get("computer") and data.get("computer", "").upper() != request["computer"].upper():
            raise RuntimeError("Windows returned a different computer identity")
        return data

    def inspect_computer(self, computer, view, query="", offset=0, limit=25):
        pc = globals()["computer"](computer)
        if view not in ("preflight", "overview", "disks", "services", "processes", "software"):
            raise ValueError("Unknown inspection view")
        if not isinstance(query, str) or len(query) > 256 or any(ord(c) < 32 for c in query):
            raise ValueError("Invalid query")
        integer(offset, "Offset", 0, 1000000)
        integer(limit, "Limit", 1, 100)
        data = self.ps({"op": "inspect", "computer": pc, "view": view, "query": query,
                        "offset": offset, "limit": limit})
        if view in ("services", "processes"):
            snapshot = uuid.uuid4().hex
            write_json(self.state / "snapshots" / (snapshot + ".json"),
                       {"computer": pc, "view": view, "created": time.time(), "items": data.get("items", [])})
            data["snapshot"] = snapshot
        return data

    def inspect_computers(self, computers, view):
        targets = inspection_targets(computers, view)
        def inspect(pc):
            try:
                data = self.ps({"op": "inspect", "computer": pc, "view": view, "query": "", "offset": 0, "limit": 25})
                return {"computer": pc, "ok": True, "data": data.get("data", data)}
            except Exception as error:
                return {"computer": pc, "ok": False, "error": str(error)[:400]}
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            results = list(pool.map(inspect, targets))
        return {"view": view, "count": len(results), "results": results}

    def root(self):
        if not self.repository.is_dir():
            raise ValueError("Package repository is unavailable: " + str(self.repository))
        return self.repository

    def package(self, name):
        name = text(name, "package", 200)
        if PureWindowsPath(name).name != name or name in (".", "..") or ":" in name or "/" in name:
            raise ValueError("Choose an exact package folder name from find_packages")
        matches = [p for p in self.root().iterdir() if p.name.casefold() == name.casefold()]
        if len(matches) != 1 or not matches[0].is_dir() or linked(matches[0]):
            raise ValueError("Package missing, ambiguous, or linked outside the repository")
        folder = matches[0].resolve()
        if folder.parent != self.root():
            raise ValueError("Package is outside the configured repository")
        return folder

    def scripts(self, folder, action):
        if action not in SUFFIXES:
            raise ValueError("Choose Install, Uninstall or Repair")
        found, count = [], 0
        for base, dirs, files in os.walk(str(folder), followlinks=False):
            for entry in dirs + files:
                path = Path(base) / entry
                count += 1
                if count > 100000:
                    raise ValueError("Package exceeds 100,000 entries; split it into smaller packages")
                if linked(path) or folder not in path.resolve().parents:
                    raise ValueError("Package contains a symlink/junction or an escaping path: " + str(path))
            for entry in files:
                path = Path(base) / entry
                if path.suffix.lower() in (".ps1", ".vbs") and path.stem.lower().endswith(SUFFIXES[action]):
                    found.append(str(path.relative_to(folder)))
        return sorted(found, key=str.casefold)

    def find_packages(self, query="", package=None, action="Install", offset=0):
        integer(offset, "Offset", 0, 1000000)
        if package is not None:
            folder = self.package(package)
            scripts = self.scripts(folder, action)
            return {"package": folder.name, "action": action, "scripts": scripts[offset:offset + 50],
                    "total": len(scripts), "next_offset": offset + 50 if len(scripts) > offset + 50 else None}
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError("Invalid query")
        packages = sorted((p.name for p in self.root().iterdir()
                           if p.is_dir() and not linked(p) and query.casefold() in p.name.casefold()), key=str.casefold)
        result = {"repository": str(self.root()), "packages": packages[offset:offset + 50], "total": len(packages),
                  "next_offset": offset + 50 if len(packages) > offset + 50 else None}
        if len(packages) == 1 and offset == 0:
            folder = self.package(packages[0])
            scripts = self.scripts(folder, action)
            result.update(package=folder.name, action=action, scripts=scripts[:50], script_total=len(scripts),
                          script_next_offset=50 if len(scripts) > 50 else None)
        return result

    def selection(self, package, script, action):
        folder = self.package(package)
        script = text(script, "installer path", 1024)
        requested = PureWindowsPath(script)
        if requested.is_absolute() or requested.drive or ".." in requested.parts:
            raise ValueError("Installer must be a relative path within the selected package")
        normalized = str(Path(*requested.parts))
        matches = [s for s in self.scripts(folder, action) if s.casefold() == normalized.casefold()]
        if len(matches) != 1:
            raise ValueError("Installer does not match the discovered package and action")
        return folder, matches[0], digest(folder / matches[0])

    def jobs(self):
        folder = self.state / "jobs"
        if not folder.exists():
            return []
        return sorted((read_json(p) for p in folder.glob("*.json")), key=lambda j: j["created"], reverse=True)

    def blocking_job(self, pc, exclude=None):
        """The job that is active on this PC or left it with an unacknowledged unknown outcome."""
        key = target_key(pc)
        for job in self.jobs():
            if job["id"] == exclude or key not in {target_key(name) for name in job["computers"]}:
                continue
            if job["state"] in ACTIVE or (job["state"] == "unknown" and not job.get("acknowledged")):
                return job
        return None

    def prune(self):
        """Bound saved state. Never removes a job that is active or has an unacknowledged unknown outcome."""
        finished = [job for job in self.jobs() if job["state"] not in ACTIVE
                    and not (job["state"] == "unknown" and not job.get("acknowledged"))]
        removed = 0
        for job in finished[RETAINED_JOBS:]:
            base = self.state / "jobs" / identifier(job["id"])
            for path in (base.with_suffix(".json"), base.with_suffix(".worker.log")):
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        now = time.time()
        for folder, age in (("snapshots", SNAPSHOT_SECONDS), ("outputs", OUTPUT_SECONDS)):
            for path in (self.state / folder).glob("*") if (self.state / folder).is_dir() else ():
                try:
                    if path.is_file() and now - path.stat().st_mtime > age:
                        path.unlink()
                        removed += 1
                except OSError:
                    pass  # In use or already gone; the next prune retries.
        return removed

    def ensure_available(self, pc, exclude=None):
        job = self.blocking_job(pc, exclude)
        if job:
            raise RuntimeError("%s has an active or unresolved job %s. Inspect it with it_job_status first." % (pc, job["id"]))
        reason = atlas_blocking(self.atlas_db, pc) if self.atlas_db else None
        if reason:
            raise RuntimeError(reason)

    def spawn(self, plan):
        try:
            self.prune()
        except (OSError, ValueError, KeyError) as error:
            sys.stderr.write("Axis state was not pruned: %s\n" % error)  # Never blocks new work.
        job_id = uuid.uuid4().hex
        job = dict(plan, id=job_id, state="queued", created=now(), created_epoch=time.time(),
                   results=[], events=[], worker_pid=None)
        if self.atlas_db:
            job["atlas_db"] = self.atlas_db  # The detached worker rechecks the same guard.
            job["atlas_history"] = self.atlas_history
        path = self.state / "jobs" / (job_id + ".json")
        write_json(path, job)
        try:
            with path.with_suffix(".worker.log").open("ab") as log:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(path)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt")
        except Exception as error:
            job.update(state="failed", error=str(error), finished=now())
            write_json(path, job)
            raise
        message = ("Reboot queued; completion is not yet verified. Progress and boot-time verification: /jobs %s." % job_id
                   if job["kind"] == "reboot" else
                   "Deployment queued; installation is not yet verified. Progress: /jobs %s." % job_id)
        return {"job_id": job_id, "state": "queued", "computers": job["computers"], "message": message}

    def deploy_package(self, computers, package, script, action, mode="full"):
        if not isinstance(computers, list) or not 1 <= len(computers) <= 200:
            raise ValueError("Supply 1 to 200 explicit computer names")
        targets = list(dict.fromkeys(computer(pc) for pc in computers))
        if mode not in ("full", "copy", "execute"):
            raise ValueError("Choose full, copy or execute")
        folder, script, sha = self.selection(package, script, action)
        for pc in targets:
            self.ensure_available(pc)
        detail = "%s %s using %s on %s (mode=%s; source=%s; script SHA256=%s)" % (
            action, folder.name, script, ", ".join(targets), mode, folder, sha)
        if not self.confirm(detail):
            return {"state": "declined", "message": "User declined the deployment; no job started"}
        # Bind approval to the actual installer bytes, then recheck in the worker.
        if self.selection(package, script, action)[2] != sha:
            raise RuntimeError("Installer changed during approval. Discover and approve it again.")
        return self.spawn({"kind": "deploy", "computers": targets, "repository": str(self.root()),
                           "package": folder.name, "script": script, "script_sha256": sha,
                           "action": action, "mode": mode, "timeout": self.timeout})

    def it_job_status(self, job_id=None, wait_seconds=0, acknowledge_unknown=False):
        integer(wait_seconds, "Wait seconds", 0, 10)
        if type(acknowledge_unknown) is not bool:
            raise ValueError("acknowledge_unknown must be boolean")
        if job_id is None:
            if acknowledge_unknown:
                raise ValueError("Select a job to acknowledge")
            return {"jobs": [{k: j.get(k) for k in ("id", "kind", "computers", "state", "created", "acknowledged")}
                             for j in self.jobs()[:50]]}
        path = self.state / "jobs" / (identifier(job_id) + ".json")
        deadline = time.monotonic() + wait_seconds
        while True:
            job = read_json(path)
            if job["state"] not in ACTIVE or time.monotonic() >= deadline:
                break
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        if job["state"] in ACTIVE and time.time() - job["created_epoch"] > 20 and not process_alive(job.get("worker_pid")):
            job.update(state="unknown", error="Worker stopped without a final result. Remote work may still be running. Inspect targets before retrying.", finished=now())
            write_json(path, job)
        if acknowledge_unknown:
            if job["state"] != "unknown":
                raise ValueError("Only an unknown job may be acknowledged")
            if self.confirm("acknowledge that you inspected %s for job %s; release its targets without retrying" % (", ".join(job["computers"]), job_id)):
                job["acknowledged"] = now()
                write_json(path, job)
        result = dict(job)
        result["events"] = job["events"][-20:]
        result["log_file"] = str(path.with_suffix(".worker.log"))
        if job.get("kind") == "deploy":
            result["verification_note"] = "Installer exit codes/logs describe script execution. Application health is not verified by this job."
        return result

    def expected(self, snapshot, pc, view, name=None, pid=None):
        saved = read_json(self.state / "snapshots" / (identifier(snapshot) + ".json"))
        if saved["computer"] != pc or saved["view"] != view or time.time() - saved["created"] > 900:
            raise ValueError("Snapshot expired or belongs to another PC/view; inspect again")
        matches = [r for r in saved["items"] if (str(r.get("Name", "")).casefold() == name.casefold()
                   if name is not None else r.get("ProcessId") == pid)]
        if len(matches) != 1:
            raise ValueError("Choose an exact item from the inspection snapshot")
        return matches[0]

    def computer_action(self, computer, action, name=None, pid=None, snapshot=None):
        pc = globals()["computer"](computer)
        request = {"op": action, "computer": pc}
        if action in ("service_start", "service_stop", "service_restart"):
            name = text(name, "service name")
            request["expected"] = self.expected(snapshot, pc, "services", name=name)
            request["name"] = name
        elif action == "process_stop":
            integer(pid, "PID", 5, 4294967295)
            request["expected"] = self.expected(snapshot, pc, "processes", pid=pid)
            request["pid"] = pid
        elif action not in ("enable_remote_registry", "reboot", "cleanup_packages"):
            raise ValueError("Unknown computer action")
        self.ensure_available(pc)
        if action == "reboot":
            before = self.ps({"op": "inspect", "computer": pc, "view": "overview"})["data"]["LastBootUpTime"]
            if not self.confirm("restart %s; unsaved work may be lost" % pc):
                return {"state": "declined"}
            return self.spawn({"kind": "reboot", "computers": [pc], "before_boot": before, "timeout": 900})
        if not self.confirm("%s on %s%s" % (action, pc, (" " + name) if name else (" PID %s" % pid if pid else ""))):
            return {"state": "declined"}
        with target_lock(self.state, pc):
            self.ensure_available(pc)
            if action == "cleanup_packages":
                import shutil
                folder = share(pc, REMOTE_ROOT + r"\Packages")
                self.check_share_path(folder)
                if folder.exists():
                    shutil.rmtree(str(folder))
                return {"computer": pc, "state": "complete", "verified": not folder.exists(), "folder": str(folder)}
            try:
                return self.ps(request, timeout=90)
            except Exception as error:
                raise UnknownOutcome("%s: %s. Inspect current state before retrying." % (action, error)) from error

    def bulk_service_action(self, computers, action, name):
        pcs, name = service_targets(computers, action, name)
        if not self.confirm("%s %s on %d PCs: %s" % (action, name, len(pcs), ", ".join(pcs))):
            return {"state": "declined"}
        results = []
        for pc in pcs:
            attempted = False
            try:
                self.ensure_available(pc)
                with target_lock(self.state, pc):
                    self.ensure_available(pc)
                    current = self.ps({"op": "inspect", "computer": pc, "view": "services", "query": name,
                                       "offset": 0, "limit": 100})
                    matches = [item for item in current.get("items", []) if str(item.get("Name", "")).casefold() == name.casefold()]
                    if len(matches) != 1:
                        raise ValueError("The exact service was not found; no service was changed")
                    attempted = True
                    data = self.ps({"op": action, "computer": pc, "name": name, "expected": matches[0]}, timeout=90)
                wanted = "Stopped" if action == "service_stop" else "Running"
                state = (data.get("after") or {}).get("State")
                verified = data.get("verified") is True and state == wanted
                row = {"computer": pc, "ok": verified, "verified": verified, "state": state,
                       "outcome": "verified" if verified else "unknown"}
                if not verified:
                    row["error"] = "Service change was not verified. Inspect current state before retrying."
                results.append(row)
            except Exception as error:
                results.append({"computer": pc, "ok": False, "verified": False,
                                "outcome": "unknown" if attempted else "not_started",
                                "error": str(error)[:400] + (". Inspect current state before retrying." if attempted else "")})
        return {"action": action, "name": name, "count": len(results),
                "succeeded": sum(1 for row in results if row["ok"]), "results": results}

    def directory_lookup(self, kind, identity, server=""):
        if kind not in ("user", "computer", "group"):
            raise ValueError("Choose user, computer or group")
        identity = text(identity, "directory identity", 256)
        if server:
            server = computer(server)
        return self.ps({"op": "directory", "kind": kind, "identity": identity, "server": server})

    def open_remote_tool(self, computer, tool):
        pc = globals()["computer"](computer)
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        args = {
            "rdp": [str(system / "mstsc.exe"), "/v:" + pc],
            "remote_assistance": [str(system / "msra.exe"), "/offerra", pc],
            "computer_management": [str(system / "mmc.exe"), "compmgmt.msc", "/computer=" + pc],
            "event_viewer": [str(system / "mmc.exe"), "eventvwr.msc", "/computer=" + pc],
            "admin_share": ["explorer.exe", str(share(pc, "C:\\"))],
            "temp": ["explorer.exe", str(share(pc, r"C:\Temp"))],
            "packages": ["explorer.exe", str(share(pc, REMOTE_ROOT + r"\Packages"))],
        }
        if tool not in args:
            raise ValueError("Unknown remote support tool")
        if not self.confirm("open %s for %s" % (tool, pc)):
            return {"state": "declined"}
        subprocess.Popen(args[tool], stdin=subprocess.DEVNULL)
        return {"state": "opened", "tool": tool, "computer": pc, "message": "Application opened; remote connection is not verified"}

    @staticmethod
    def check_share_path(path):
        # Resolve every existing component; never follow a staging junction.
        for item in [path] + list(path.parents):
            if item.exists() and linked(item):
                raise ValueError("Remote staging contains a symlink/junction: " + str(item))

    def deploy_one(self, job, pc, event):
        launched = False
        result = {"computer": pc, "state": "running", "verified": False}
        try:
            with target_lock(self.state, pc):
                self.ensure_available(pc, exclude=job["id"])
                folder, script, sha = self.selection(job["package"], job["script"], job["action"])
                if sha != job["script_sha256"]:
                    raise RuntimeError("Installer changed after approval; no deployment was started")
                preflight = self.ps({"op": "inspect", "view": "preflight", "computer": pc})["data"]
                if not preflight.get("wmi") or not preflight.get("admin_share"):
                    raise RuntimeError("WMI or administrative share unavailable; check connectivity and account rights")
                destination = REMOTE_ROOT + "\\Packages\\" + folder.name
                remote_script = destination + "\\" + str(PureWindowsPath(script))
                self.check_share_path(share(pc, destination))
                if job["mode"] != "execute":
                    event(pc, "Copying package")
                    copied = subprocess.run(["robocopy.exe", str(folder), str(share(pc, destination)),
                                             "/E", "/XJ", "/MT:8", "/R:1", "/W:1", "/Z", "/FFT", "/COPY:DAT", "/DCOPY:DAT", "/NP", "/NFL", "/NDL"],
                                            stdin=subprocess.DEVNULL, capture_output=True, timeout=job["timeout"],
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    result["robocopy_code"] = copied.returncode
                    if not 0 <= copied.returncode <= 7:
                        raise RuntimeError("Robocopy failed (code %d): %s" % (copied.returncode, (copied.stderr or copied.stdout).decode("utf-8", "replace")[-1500:]))
                self.check_share_path(share(pc, remote_script))
                if digest(share(pc, remote_script)) != sha:
                    raise RuntimeError("Staged installer differs from the approved script; not launched")
                if job["mode"] == "copy":
                    return dict(result, state="copied", verified=True, message="Package copied and installer checksum verified; nothing executed")
                remote_job = REMOTE_ROOT + "\\Jobs\\" + job["id"]
                job_folder = share(pc, remote_job)
                self.check_share_path(job_folder)
                job_folder.mkdir(parents=True, exist_ok=False)
                log = remote_job + "\\output.log"
                exit_file = remote_job + "\\exitcode.txt"
                status_file, result_file = remote_job + "\\status.txt", remote_job + "\\activity.json"
                # The target stops waiting for installer activity early enough to report before monitoring ends.
                payload = remote_payload(remote_script, log, exit_file, max(60, job["timeout"] - 120), status_file, result_file)
                (job_folder / "run.ps1").write_text(payload, encoding="utf-8-sig")
                result.update(remote_log=log, remote_exit_file=exit_file)
                # A transport error after invoking Create can still mean it launched.
                launched = True
                started = self.ps({"op": "launch", "computer": pc, "script": remote_job + "\\run.ps1"})
                result["pid"] = started["pid"]
                event(pc, "Remote installer launched (PID %s); waiting for it and the installers it starts to finish" % started["pid"])
                deadline = time.monotonic() + job["timeout"]
                exit_path, status_path, shown = share(pc, exit_file), share(pc, status_file), None
                while not exit_path.is_file():
                    if time.monotonic() >= deadline:
                        raise UnknownOutcome("Monitoring timed out; remote installer may still be running")
                    try:
                        status = status_path.read_text(encoding="utf-8-sig").strip()[:300]
                    except OSError:
                        status = None
                    if status and status != shown:
                        event(pc, status)
                        shown = status
                    time.sleep(2)
                exit_code = int(exit_path.read_text(encoding="utf-8-sig").strip())
                result["exit_code"] = exit_code
                logfile = share(pc, log)
                if logfile.is_file():
                    result["log_tail"] = tail(logfile)
                result["application_verified"] = False
                activity = read_install_activity(share(pc, result_file))
                if activity:
                    result["installer_activity"] = {key: activity.get(key) for key in (
                        "settled", "waited_seconds", "still_running", "left_running", "windows_installer_busy", "tracking")}
                    if "software" in activity:
                        result["software_changes"] = activity["software"]
                summary = describe_install_activity(activity)
                unfinished = install_unconfirmed(activity)
                if unfinished:
                    return dict(result, state="unknown", inspect_before_retry=True, message=(
                        "Installer script exited with code %d, but %s; check the PC before retrying or verifying" % (exit_code, unfinished)))
                if exit_code == 0:
                    message = "Installer script returned 0"
                    state = "script_succeeded"
                elif exit_code in (3010, 1641):
                    message = "Installer script returned a Windows Installer restart code"
                    state = "reboot_required"
                else:
                    return dict(result, state="failed", message="Installer script failed with exit code %d" % exit_code + ("; " + summary if summary else ""))
                return dict(result, state=state, message=message + ("; " + summary if summary else "") + (
                    "; application health still needs verification" if state == "script_succeeded" else
                    "; verify its log/application before restarting"))
        except Exception as error:
            return dict(result, state="unknown" if launched else "failed", message=str(error),
                        inspect_before_retry=launched)


def tail(path, size=16000):
    with Path(path).open("rb") as source:
        source.seek(0, 2)
        source.seek(max(0, source.tell() - size))
        return source.read().decode("utf-8-sig", "replace")


# Machine-wide and the installing account's uninstall registrations; the ones the software view reads, plus per-user.
UNINSTALL_KEYS = ((r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "Machine"),
                  (r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "Machine32"),
                  (r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall", "User"))

# Runs on the target around the installer script. Many scripts return while the installer they started is still
# working (a setup.exe that hands over to msiexec, an uninstaller that copies itself and exits), so the exit record
# is written only once the processes the script started and Windows Installer have finished, or the time is up.
INSTALL_ACTIVITY = r"""
function Start-InstallTracking {
    # Every process the script starts joins this job object, even after its parent exits.
    try {
        if (-not ('AxisInstallJob' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AxisInstallJob {
    [StructLayout(LayoutKind.Sequential)] struct BasicLimit { public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimit { public BasicLimit Basic; public IoCounters Io; public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed; }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attributes, IntPtr name);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimit info, int size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool QueryInformationJobObject(IntPtr job, int infoClass, IntPtr info, int size, IntPtr returned);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    public static IntPtr Track() {
        IntPtr job = CreateJobObject(IntPtr.Zero, IntPtr.Zero);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        ExtendedLimit info = new ExtendedLimit();
        info.Basic.LimitFlags = 0x800;  // BREAKAWAY_OK: a child that asks to leave the job may; all others stay tracked
        SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(typeof(ExtendedLimit)));
        return AssignProcessToJobObject(job, GetCurrentProcess()) ? job : IntPtr.Zero;
    }
    public static long[] Processes(IntPtr job) {
        int size = 8 + IntPtr.Size * 4096;
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try {
            if (!QueryInformationJobObject(job, 3, buffer, size, IntPtr.Zero)) return new long[0];
            int count = Marshal.ReadInt32(buffer, 4);
            long[] ids = new long[count];
            for (int i = 0; i < count; i++) ids[i] = Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64();
            return ids;
        } finally { Marshal.FreeHGlobal(buffer); }
    }
}
'@
        }
        $job = [AxisInstallJob]::Track()
        if ($job -ne [IntPtr]::Zero) { return $job }
    } catch {}
    return $null
}

function Get-ProcessTable($filter) {
    $options = @{ClassName='Win32_Process'; ErrorAction='Stop'}
    if ($filter) { $options.Filter = $filter }
    if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) { return @(Get-CimInstance @options) }
    $options.Class = $options.ClassName; $options.Remove('ClassName')
    @(Get-WmiObject @options)
}

function Test-WindowsInstallerBusy {
    # The InProgress key exists while an installation runs. The msiexec service itself (/V) idles for minutes afterwards.
    try { if (Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\InProgress') { return $true } } catch {}
    try {
        foreach ($p in (Get-ProcessTable "Name='msiexec.exe'")) { if ([string]$p.CommandLine -notmatch '\s/V\s*$') { return $true } }
    } catch {}
    $false
}

function Get-InstallActivity($tracker) {
    $ids = @()
    if ($tracker) {
        try { $ids = @([AxisInstallJob]::Processes($tracker)) } catch {}
    } else {
        # Without a job object, follow the process tree from this script, remembering every descendant seen so a
        # child is still connected after its parent exits. A hand-off that started and exited unseen is missed, so
        # this tracking never confirms that installation finished.
        try {
            $table = Get-ProcessTable $null
            $grew = $true
            while ($grew) {
                $grew = $false
                foreach ($p in $table) {
                    if (-not $AxisTree.ContainsKey([long]$p.ProcessId) -and $AxisTree.ContainsKey([long]$p.ParentProcessId)) { $AxisTree[[long]$p.ProcessId] = $true; $grew = $true }
                }
            }
            $ids = @($table | Where-Object { $AxisTree.ContainsKey([long]$_.ProcessId) } | ForEach-Object { [long]$_.ProcessId })
        } catch {}
    }
    $running = @()
    foreach ($id in $ids) {
        if ([long]$id -eq $PID) { continue }
        $process = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -ne 'conhost') { $running += $process }
    }
    @{processes=$running; msi=(Test-WindowsInstallerBusy)}
}

function Get-RegisteredSoftware {
    $items = @{}
    foreach ($root in $AxisUninstallKeys) {
        try {
            if (-not (Test-Path -LiteralPath $root.Path)) { continue }
            foreach ($key in @(Get-ChildItem -LiteralPath $root.Path -ErrorAction SilentlyContinue)) {
                $name = [string]$key.GetValue('DisplayName')
                if ($name) { $items[$root.Scope + '\' + $key.PSChildName] = @{name=$name; version=[string]$key.GetValue('DisplayVersion')} }
            }
        } catch {}
    }
    $items
}

function Compare-RegisteredSoftware($before, $after) {
    $added = @(); $removed = @(); $changed = @()
    foreach ($id in $after.Keys) {
        $new = $after[$id]
        if (-not $before.ContainsKey($id)) { $added += [ordered]@{name=$new.name; version=$new.version} }
        elseif ($before[$id].version -ne $new.version -or $before[$id].name -ne $new.name) {
            $changed += [ordered]@{name=$new.name; from=$before[$id].version; to=$new.version}
        }
    }
    foreach ($id in $before.Keys) {
        if (-not $after.ContainsKey($id)) { $removed += [ordered]@{name=$before[$id].name; version=$before[$id].version} }
    }
    [ordered]@{added=@($added | Sort-Object { $_.name } | Select-Object -First 20)
               removed=@($removed | Sort-Object { $_.name } | Select-Object -First 20)
               changed=@($changed | Sort-Object { $_.name } | Select-Object -First 20)}
}

function Complete-InstallActivity($tracker, $before, $deadline, $exitCode, $statusPath, $resultPath) {
    $started = Get-Date; $quiet = 0; $shown = ''; $idleNames = ''; $idleCpu = $null; $idleSince = $null
    $result = [ordered]@{settled=$false; waited_seconds=0; still_running=@(); left_running=@(); windows_installer_busy=$false
                         tracking=$(if ($tracker) { 'job object' } else { 'process tree' })}
    while ($true) {
        $activity = Get-InstallActivity $tracker
        $names = @($activity.processes | ForEach-Object { $_.ProcessName + '.exe' } | Sort-Object -Unique)
        if ($names.Count -eq 0 -and -not $activity.msi) {
            # Confirm once, in case the next step of a chained installer is just starting.
            $quiet++
            if ($quiet -ge 2) { $result.settled = $true; break }
            Start-Sleep -Seconds 2; continue
        }
        $quiet = 0
        # A finished installer can leave its application running. Accept that once Windows Installer is idle, the
        # remaining processes have used under a second of CPU for a minute and the registered software has changed.
        $cpu = 0.0; $measured = $true
        foreach ($p in $activity.processes) { try { $cpu += $p.TotalProcessorTime.TotalSeconds } catch { $measured = $false } }
        $key = $names -join ','
        if (-not $activity.msi -and $measured -and $null -ne $before -and $key -eq $idleNames -and $null -ne $idleCpu -and ($cpu - $idleCpu) -lt 1) {
            if (((Get-Date) - $idleSince).TotalSeconds -ge 60) {
                $changes = Compare-RegisteredSoftware $before (Get-RegisteredSoftware)
                if ($changes.added.Count + $changes.removed.Count + $changes.changed.Count -gt 0) { $result.settled = $true; $result.left_running = $names; break }
            }
        } else { $idleNames = $key; $idleCpu = $cpu; $idleSince = Get-Date }
        if ((Get-Date) -ge $deadline) { $result.still_running = $names; $result.windows_installer_busy = [bool]$activity.msi; break }
        $waiting = @($names)
        if ($activity.msi) { $waiting += 'Windows Installer' }
        $status = 'Script exited with code ' + $exitCode + '; waiting for ' + ($waiting -join ', ') + ' to finish'
        if ($status -ne $shown) { try { Set-Content -LiteralPath $statusPath -Value $status -Encoding utf8 } catch {}; $shown = $status }
        Start-Sleep -Seconds 5
    }
    $result.waited_seconds = [int]((Get-Date) - $started).TotalSeconds
    if ($null -ne $before) { $result.software = Compare-RegisteredSoftware $before (Get-RegisteredSoftware) }
    Set-Content -LiteralPath $resultPath -Value ($result | ConvertTo-Json -Depth 5 -Compress) -Encoding utf8
}
"""


def install_activity_setup(limit):
    """PowerShell that defines the wait and starts tracking; give the wait at most limit seconds from here."""
    keys = ", ".join("@{Path=%s; Scope=%s}" % (quote(path), quote(scope)) for path, scope in UNINSTALL_KEYS)
    return ("$AxisUninstallKeys = @(%s)\n$AxisTree = @{}; $AxisTree[[long]$PID] = $true\n$axisDeadline = (Get-Date).AddSeconds(%d)\n%s\n"
            "$axisTracker = $null; $axisBefore = $null\n"
            "try { $axisTracker = Start-InstallTracking; $axisBefore = Get-RegisteredSoftware } catch {}\n"
            % (keys, int(limit), INSTALL_ACTIVITY.strip()))


def install_activity_finish(exit_code, status_file, result_file, log):
    """PowerShell for the finally block, before the exit record: wait, then record what changed. Never throws."""
    return ("try { Complete-InstallActivity $axisTracker $axisBefore $axisDeadline %s %s %s } catch {\n"
            "    ('Installer activity was not checked: ' + $_) | Out-File -LiteralPath %s -Append -Encoding utf8\n}"
            % (exit_code, quote(status_file), quote(result_file), quote(log)))


def read_install_activity(path):
    """The target's record of the wait, or None when it is missing or unreadable (an older payload, a failed write)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def describe_install_activity(activity):
    """One plain sentence fragment for job messages: how long the wait took and what registered software changed."""
    if not activity:
        return ""
    parts = []
    waited = int(activity.get("waited_seconds") or 0)
    if activity.get("settled") and waited >= 10:
        parts.append("installer activity finished after %s" % duration(waited))
    if activity.get("left_running"):
        parts.append("left running: " + ", ".join(activity["left_running"]))
    software = activity.get("software") or {}
    def names(items, form):
        return ", ".join(form(item) for item in items if isinstance(item, dict))
    for label, key, form in (("newly registered", "added", lambda i: ("%s %s" % (i.get("name"), i.get("version") or "")).strip()),
                             ("no longer registered", "removed", lambda i: str(i.get("name"))),
                             ("version changed", "changed", lambda i: "%s %s -> %s" % (i.get("name"), i.get("from") or "?", i.get("to") or "?"))):
        if software.get(key):
            parts.append("%s: %s" % (label, names(software[key], form)))
    if activity.get("settled") and not any(software.get(key) for key in ("added", "removed", "changed")) and "software" in activity:
        parts.append("no change in registered software")
    return "; ".join(parts)


def install_unconfirmed(activity):
    """Why the target's record does not confirm that the installers the script started have finished, or None."""
    if not activity:
        return "no installer-activity record was written, so installer completion was not checked"
    if not activity.get("settled"):
        running = list(activity.get("still_running") or []) + (["Windows Installer"] if activity.get("windows_installer_busy") else [])
        return "installer activity was still running when monitoring stopped (%s)" % (", ".join(running) or "unknown")
    # A job object on the target (Axis), or Atlas watching the PC's processes and Windows Installer from outside.
    if activity.get("tracking") not in ("job object", "process watch"):
        return "this PC could not track every process the script started, so installer completion is not confirmed"
    return None


def duration(seconds):
    return "%d min %d s" % divmod(seconds, 60) if seconds >= 60 else "%d s" % seconds


def remote_payload(installer, log, exit_file, limit=3480, status_file=None, result_file=None):
    status_file = status_file or exit_file + ".status"
    result_file = result_file or exit_file + ".result.json"
    invoke = "& " + quote(installer)
    if PureWindowsPath(installer).suffix.lower() == ".vbs":
        invoke = "& cscript.exe //B //NoLogo " + quote(installer)
    return """$ErrorActionPreference = 'Stop'
$ec = 1
%s
try {
    Set-Location -LiteralPath %s
    $global:LASTEXITCODE = 0
    %s *>&1 | Out-File -LiteralPath %s -Encoding utf8
    $ec = $global:LASTEXITCODE
} catch {
    $_ | Out-File -LiteralPath %s -Append -Encoding utf8
    $ec = 1
} finally {
    %s
    [string]$ec | Set-Content -LiteralPath %s -Encoding ascii
    Move-Item -LiteralPath %s -Destination %s -Force
}
exit $ec
""" % (install_activity_setup(limit), quote(str(PureWindowsPath(installer).parent)), invoke, quote(log), quote(log),
        install_activity_finish("$ec", status_file, result_file, log),
        quote(exit_file + ".tmp"), quote(exit_file + ".tmp"), quote(exit_file))


def run_worker(path):
    path = Path(path).resolve()
    job = read_json(path)
    if job["state"] != "queued" or path.name != identifier(job["id"]) + ".json":
        raise ValueError("Job is not queued")
    backend = ITTools(path.parent.parent, job.get("repository"), timeout=job["timeout"], atlas_db=job.get("atlas_db"))
    job.update(state="running", worker_pid=os.getpid())
    write_json(path, job)

    def event(pc, message):
        job["events"].append({"at": now(), "computer": pc, "message": message})
        write_json(path, job)

    history = {"failed": False, "open": None}

    def recorded(index, fields, create=False):
        # History is a record of the work, never a reason to stop or fail it.
        if not job.get("atlas_history") or history["failed"]:
            return
        try:
            record_history(job["atlas_db"], "axis-%s-%d" % (job["id"], index), fields, create)
            history["open"] = index if create else None
        except (sqlite3.Error, OSError) as error:
            history["failed"] = True
            event("", "Atlas deployment history was not updated: %s" % error)

    try:
        for index, pc in enumerate(job["computers"]):
            if job["kind"] == "deploy":
                recorded(index, {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "operator": windows_account() + " (Axis)",
                                 "target": pc, "package": job["package"], "action": job["action"], "script": job["script"],
                                 "mode": job["mode"], "state": "running", "payload": json.dumps({
                                     "computer": pc, "folder": str(Path(job["repository"]) / job["package"]),
                                     "script": job["script"], "action": job["action"], "mode": job["mode"]})}, create=True)
                result = backend.deploy_one(job, pc, event)
                recorded(index, {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "state": history_outcome(result),
                                 "exit_code": str(result.get("exit_code", "")), "pid": str(result.get("pid", "")),
                                 "robocopy_code": str(result.get("robocopy_code", "")),
                                 "details": ((result.get("message") or "") + "\n" + (result.get("log_tail") or "")).strip()[-4000:]})
            elif job["kind"] == "reboot":
                result = {"computer": pc, "state": "unknown", "verified": False}
                try:
                    with target_lock(backend.state, pc):
                        backend.ensure_available(pc, exclude=job["id"])
                        backend.ps({"op": "reboot", "computer": pc, "before_boot": job["before_boot"]})
                        event(pc, "Restart request accepted; waiting for a new boot timestamp")
                        deadline = time.monotonic() + job["timeout"]
                        while time.monotonic() < deadline:
                            time.sleep(5)
                            try:
                                boot = backend.ps({"op": "inspect", "view": "overview", "computer": pc}, timeout=30)["data"]["LastBootUpTime"]
                                if boot and boot != job["before_boot"]:
                                    result.update(state="reboot_verified", verified=True, boot=boot)
                                    break
                            except Exception:
                                pass
                        else:
                            result["message"] = "Reboot could not be verified; inspect before retrying"
                except Exception as error:
                    result["message"] = str(error) + "; reboot outcome may be unknown"
            else:
                raise ValueError("Unknown job kind")
            job["results"].append(result)
            event(pc, result.get("message") or result["state"])
        states = {r["state"] for r in job["results"]}
        job["state"] = "unknown" if "unknown" in states else "failed" if "failed" in states else "complete"
    except BaseException as error:
        job.update(state="unknown", error=str(error) + "; inspect target state before retrying")
        if history["open"] is not None:
            recorded(history["open"], {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "state": "unknown",
                                       "details": job["error"]})
    finally:
        job["finished"] = now()
        write_json(path, job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local agent IT job worker")
    parser.add_argument("--worker", required=True)
    run_worker(parser.parse_args().worker)
