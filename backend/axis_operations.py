"""Axis's Windows tools on Atlas's own operations.

Inside AA, Axis has no second engine. A deployment Axis starts is an Atlas deployment: the same
validation, per-PC lock, unknown-outcome guard, job list, history, retry and queue. Atlas's reboot
monitor watches its reboots, and Atlas's identity-checked actions change services and processes.
Axis asks for approval first, as it always has; Atlas's own checks then apply as for any operator.

Axis job files from earlier versions stay readable, and an unknown one can still be acknowledged,
so no PC they protect is released silently.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import os
import threading
import time
import uuid
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException

from axis.it_tools import OUTPUT_SECONDS, linked, target_key, inspection_targets, service_targets

STRING = {"type": "string"}
ACTIONS = ["Install", "Uninstall", "Repair"]
VIEWS = ["preflight", "overview", "disks", "services", "processes", "software"]
SNAPSHOT_SECONDS = 900  # how long a services/processes listing may back a change
WAIT_SECONDS = 10
MAX_TARGETS = 25        # well inside Atlas's 32 admitted operations, so the operator's own work still starts
TERMINAL = {"launched", "complete", "failed", "cancelled", "interrupted", "unknown"}
REBOOT_ACTIVE = {"requesting", "waiting_offline", "waiting_online"}  # reboot_monitor.ACTIVE
SOFTWARE_FIELDS = ("Name", "Version", "Publisher", "Kind", "Scope", "Architecture")
TOOLS_OPENED = {"rdp": "rdp", "remote_assistance": "msra", "computer_management": "compmgmt",
                "event_viewer": "eventvwr", "admin_share": "cshare", "temp": "temp", "packages": "packages",
                "quick_assist": "quickassist", "remote_help": "remotehelp"}


def _tool(name, description, properties, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}}


TOOLS = [
    _tool("inspect_computer", "Read a Windows PC with Atlas's checks: preflight (ping, C$ share, WMI), overview, disks, services, processes (top CPU users) or software (installed programs). Services and processes return a snapshot ID needed for changes. Use query and offset to narrow or page results.", {
        "computer": STRING, "view": {"type": "string", "enum": VIEWS}, "query": STRING,
        "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        ["computer", "view"]),
    _tool("inspect_computers", "Read up to 50 explicit Windows PCs with Atlas's preflight, overview or disk checks. Uses at most eight readers, preserves target order and reports each PC's result or error. Read-only; use inspect_computer for services, processes or software.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50},
        "view": {"type": "string", "enum": ["preflight", "overview", "disks"]}}, ["computers", "view"]),
    _tool("bulk_service_action", "Start, stop or restart one named service on up to 50 explicit PCs after one approval listing every PC. Uses Atlas's per-PC locks, protected-service checks, current service identity and outcome verification. Each PC reports its own result; an unverified change is not success. No external snapshot is needed.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": 50},
        "action": {"type": "string", "enum": ["service_start", "service_stop", "service_restart"]},
        "name": STRING}, ["computers", "action", "name"]),
    _tool("find_packages", "Search Atlas's package repository. A single match includes its action-specific scripts; reuse them without another lookup. Multiple matches require choosing an exact package. Supply package and offset for more script pages. Never guess a package or script.", {
        "query": STRING, "package": STRING, "action": {"type": "string", "enum": ACTIONS},
        "offset": {"type": "integer", "minimum": 0}}),
    _tool("deploy_package", "After approval, start Atlas deployments to explicit PCs: one Atlas job per PC, shown in Atlas's Deployments and history. Atlas checks the target, copies the package with Robocopy, checks the staged script is the approved one, launches it, waits for it and the installers it starts (and Windows Installer) to finish, then records its exit code and registered-software changes. Returns queued job IDs, NOT installation success. Never retry an unknown outcome automatically.", {
        "computers": {"type": "array", "items": STRING, "minItems": 1, "maxItems": MAX_TARGETS},
        "package": STRING, "script": STRING, "action": {"type": "string", "enum": ACTIONS},
        "mode": {"type": "string", "enum": ["full", "copy", "execute"]}},
        ["computers", "package", "script", "action"]),
    _tool("it_job_status", "List recent Atlas deployments and reboots, or read one job's events, exit code and log. When the user asks to wait, use wait_seconds=10 for a bounded wait. acknowledge_unknown releases a PC whose outcome is unknown, after the operator confirms they inspected it; it never retries or stops remote work.", {
        "job_id": STRING, "wait_seconds": {"type": "integer", "minimum": 0, "maximum": WAIT_SECONDS},
        "acknowledge_unknown": {"type": "boolean"}}),
    _tool("computer_action", "Change a Windows PC through Atlas after approval. service_start/stop/restart need name and the services snapshot ID; process_stop needs pid and the processes snapshot ID. Atlas rechecks identity and verifies the result. reboot returns a job watched by Atlas's reboot monitor, which follows ping only. cleanup_packages deletes the package staging folders Atlas deploys into.", {
        "computer": STRING, "action": {"type": "string", "enum": ["service_start", "service_stop", "service_restart", "process_stop",
                                                                  "enable_remote_registry", "reboot", "cleanup_packages"]},
        "name": STRING, "pid": {"type": "integer", "minimum": 5}, "snapshot": STRING}, ["computer", "action"]),
    _tool("directory_lookup", "Read an exact Active Directory user or computer, with group membership, or find groups by name. Uses Atlas's read-only AD lookup (RSAT). Does not change accounts or groups.", {
        "kind": {"type": "string", "enum": ["user", "computer", "group"]}, "identity": STRING, "server": STRING},
        ["kind", "identity"]),
    _tool("open_remote_tool", "Open a Windows support application for an explicit PC after approval, as Atlas's Workspace does. Opens the application only; does not establish or automate a remote session.", {
        "computer": STRING, "tool": {"type": "string", "enum": sorted(TOOLS_OPENED)}}, ["computer", "tool"]),
]
NAMES = {tool["function"]["name"] for tool in TOOLS}

GUIDANCE = """- inspect_computer, find_packages, deploy_package, computer_action, directory_lookup and open_remote_tool run Atlas's own operations, with its checks and locks. Use them for supported work and never bypass a blocked one with run_command.
- Use inspect_computers for a quick read of preflight, overview or disks across an explicit list of up to 50 PCs. Each PC keeps its own readings or error; services, processes and software use inspect_computer.
- Use bulk_service_action for a requested start, stop or restart of one named service across explicit PCs. One approval lists every target; Atlas checks and verifies each independently. Pending, failed or unknown results are not success; inspect before retrying an uncertain change.
- Package repository: {package_repo}. Saved tool output: {state_dir}.
- Resolve the exact package and action-specific script with find_packages before deployment. A unique search match can include its scripts; reuse them without a second discovery call. Multiple scripts still require an unambiguous selection. Use only explicit PCs supplied by the user or found in notes/directory results.
- If several versions match and neither the user nor a known runbook selects one, immediately ask one short version question with a few exact returned names. Do not inspect targets, browse repository folders or read scripts to guess the preferred version. Results are sorted by name, not version/date, and may be paginated.
- Read only state needed for the decision. Atlas's deployment checks the target itself, and computer_action verifies its own result: do not add duplicate preflight or post-change inspections unless a needed check is missing, failed, uncertain or requested. For raw commands, inspect current state before a change and verify its result before claiming success.
- Service/process changes require a recent inspect_computer snapshot. If identity changed or the snapshot expired, inspect again. A tool result must explicitly support a success claim; distinguish accepted, verified, failed and unknown.
- A deployment or reboot job ID means queued, not complete; it appears in Atlas's Deployments or reboot monitor. Report the job ID, then return unless the user asked to wait or verify. When waiting, use it_job_status with wait_seconds=10 instead of rapid polls.
- Report a deployment from it_job_status's outcome field. "launched" with an exit code means the script ran: exit 0 is not proof the application works; 3010 or 1641 means a restart is required; other codes are failures. "launched" with recovery_required or without an exit code, and "interrupted", mean the outcome is unknown: never retry automatically; inspect the target first, and only acknowledging it releases the PC. "complete" is a finished copy-only run.
- Atlas's reboot monitor follows ping only: "complete" means the PC stopped answering and answered again, not that it restarted. Before saying it restarted, compare the boot time from inspect_computer overview. "timeout" or "failed" means the restart is not confirmed.
- Full tool results are saved. Read omitted sections only when needed, using read_tool_output with the returned output_id and character offset."""


def _error(error):
    """Atlas's HTTP errors as the plain exceptions Axis reports to the model."""
    if isinstance(error, HTTPException):
        return (ValueError if error.status_code < 500 else RuntimeError)(str(error.detail))
    return error


def _page(items, query, offset, limit, fields):
    if not isinstance(query, str) or len(query) > 256 or any(ord(c) < 32 for c in query):
        raise ValueError("Invalid query")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Use offset >= 0 and limit from 1 to 100")
    wanted = query.casefold().strip()
    rows = [item for item in items if not wanted or any(wanted in str(item.get(f, "")).casefold() for f in fields)]
    return {"items": rows[offset:offset + limit], "total": len(rows),
            "next_offset": offset + limit if len(rows) > offset + limit else None}


def outcome(result):
    """What an Atlas deployment's state and exit code mean, in the words Axis should report."""
    state, code = result.get("state"), str(result.get("exit_code") or "").strip()
    if state in ("queued", "running", "monitoring", "paused"):
        return "in progress"
    if state == "complete":
        return "copied; nothing was run"
    if state == "launched" and code.lstrip("-").isdigit() and not result.get("recovery_required"):
        meaning = {"0": "the script ran and returned 0; the application itself is not verified",
                   "3010": "a restart is required", "1641": "a restart was started by the installer"}
        return "launched, exit code %s: %s" % (code, meaning.get(code, "the script reported a failure"))
    if state in ("launched", "unknown", "interrupted"):
        return ("unknown: the script may have run but its result was not read. Inspect the PC before any retry; "
                "acknowledging releases the PC")
    return "failed before the script ran" if state == "failed" else str(state)


class AtlasOperations:
    """The IT tools of an Agent running inside AA. confirm is the Agent's approval and audit."""
    TOOLS = TOOLS
    NAMES = NAMES
    guidance = GUIDANCE

    def __init__(self, wmi, confirm, legacy_state=None, outputs=None):
        self.wmi = wmi
        self.confirm = confirm
        self.outputs = Path(outputs) if outputs else None  # Axis's saved tool output, which can hold private text
        folders = legacy_state if isinstance(legacy_state, (list, tuple)) else [legacy_state] if legacy_state else []
        self.legacy_states = [Path(folder) for folder in folders]
        self.snapshots = {}
        self.reboots = {}  # last row seen per reboot job: Atlas drops a finished row after 10 seconds
        self.lock = threading.Lock()

    @property
    def repository(self):
        return Path(self.wmi.REPO)

    def prune(self):
        cutoff = time.time() - SNAPSHOT_SECONDS
        with self.lock:
            old = [key for key, value in self.snapshots.items() if value["created"] < cutoff]
            for key in old:
                del self.snapshots[key]
        removed = len(old)
        for path in self.outputs.glob("*") if self.outputs is not None and self.outputs.is_dir() else ():
            try:
                if path.is_file() and time.time() - path.stat().st_mtime > OUTPUT_SECONDS:
                    path.unlink()
                    removed += 1
            except OSError:
                pass  # In use or already gone; the next prune retries.
        return removed

    def call(self, name, args):
        if name not in NAMES or not isinstance(args, dict):
            raise ValueError("Unknown Windows tool or invalid arguments")
        schema = next(t["function"]["parameters"] for t in TOOLS if t["function"]["name"] == name)
        unknown, missing = set(args) - set(schema["properties"]), set(schema["required"]) - set(args)
        if unknown or missing:
            raise ValueError("Unexpected arguments %s; missing arguments %s" % (sorted(unknown), sorted(missing)))
        try:
            return getattr(self, name)(**args)
        except HTTPException as error:
            raise _error(error) from None

    # ---- reading ---------------------------------------------------------

    def pc(self, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise ValueError("Use one explicit computer name")
        return self.wmi.validate_pc(value.strip())

    def ready(self, pc):
        """Refuse a PC that Atlas, its reboot monitor or an earlier Axis job is working on or left unresolved,
        however the name is written (short or fully qualified)."""
        wmi, key = self.wmi, target_key(pc)
        wmi.job_service.target_ready(pc)
        if any(target_key(name) == key for name in list(wmi.job_service.unresolved)):
            raise ValueError("%s has an earlier operation with an unknown outcome. Inspect it, then acknowledge it "
                             "in Atlas's Operation recovery or with it_job_status." % pc)
        with wmi.lock:
            pools = [dict(wmi.jobs), dict(getattr(wmi, "queue_jobs", {}))]
        for pool in pools:
            for job_id, job in pool.items():
                names = [job.get("target")] + list(job.get("targets") or [])
                names += [row.get("target") or row.get("machine") for row in job.get("items", job.get("results", []))
                          if isinstance(row, dict)]
                if job.get("state") not in TERMINAL and any(isinstance(n, str) and target_key(n) == key for n in names):
                    raise ValueError("Atlas is working on %s (operation %s, %s). Wait for it to finish." %
                                     (pc, job_id, job.get("state")))
        for row in wmi.reboot_monitor.snapshot()["reboots"]:
            if row.get("state") in REBOOT_ACTIVE and target_key(row.get("target")) == key:
                raise ValueError("%s is rebooting under Atlas's reboot monitor (%s)." % (pc, row.get("id")))
        for legacy in self.legacy():
            job = legacy.blocking_job(pc)
            if job:
                raise ValueError("%s has an active or unresolved earlier Axis job %s. Review it with it_job_status "
                                 "before changing this PC." % (pc, job["id"]))

    @contextmanager
    def held(self, pc):
        """Atlas's per-PC lock for a direct change, and the same checks again now that approval is given."""
        guard = self.wmi.target_lock(pc)
        if not guard.acquire(blocking=False):
            raise ValueError("Another Atlas operation is active on %s; wait for it to finish." % pc)
        try:
            self.ready(pc)
            yield
        finally:
            guard.release()

    def snapshot(self, pc, view, items):
        self.prune()
        key = uuid.uuid4().hex
        with self.lock:
            self.snapshots[key] = {"computer": pc, "view": view, "created": time.time(), "items": copy.deepcopy(items)}
        return key

    def inspect_computer(self, computer, view, query="", offset=0, limit=25):
        if view not in VIEWS:
            raise ValueError("Unknown inspection view")
        pc = self.pc(computer)
        wmi = self.wmi
        if view == "preflight":
            return {"computer": pc, "view": view, "checks": wmi.preflight(pc)}
        if view == "overview":
            return {"computer": pc, "view": view, "overview": wmi.overview(pc)}
        if view == "disks":
            return {"computer": pc, "view": view, "disks": wmi.disk(pc)}
        if view == "services":
            import service_actions
            items = service_actions.list_services(wmi, pc)["items"]
            page = _page(items, query, offset, limit, ("name", "display_name", "state"))
            page["items"] = [{k: v for k, v in item.items() if k != "identity"} for item in page["items"]]
            return dict(page, computer=pc, view=view, snapshot=self.snapshot(pc, view, items))
        if view == "processes":
            import remote_processes
            items = remote_processes.list_processes(wmi, pc, "cpu")
            page = _page(items, query, offset, limit, ("Process", "PID", "CommandLine"))
            page["items"] = [dict(item, CommandLine=str(item.get("CommandLine") or "")[:200]) for item in page["items"]]
            return dict(page, computer=pc, view=view, snapshot=self.snapshot(pc, view, items),
                        note="The 30 processes using the most CPU.")
        import remote_software
        if not wmi.job_service.inventory.acquire(blocking=False):
            raise RuntimeError("Three software inventories are running; try again shortly")
        try:
            data = remote_software.remote_call(wmi, pc)
        finally:
            wmi.job_service.inventory.release()
        items = data.get("software") or []
        items = [items] if isinstance(items, dict) else items
        items = [{k: item.get(k) for k in SOFTWARE_FIELDS if item.get(k) not in (None, "")} for item in items if isinstance(item, dict)]
        page = _page(items, query, offset, limit, ("Name", "Publisher", "Version"))
        return dict(page, computer=pc, view=view, warnings=data.get("warnings") or [])

    def inspect_computers(self, computers, view):
        targets = inspection_targets(computers, view, self.pc)
        def inspect(pc):
            try:
                return {"computer": pc, "ok": True, "data": self.inspect_computer(pc, view)}
            except Exception as error:
                return {"computer": pc, "ok": False, "error": str(error)[:400]}
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            results = list(pool.map(inspect, targets))
        return {"view": view, "count": len(results), "results": results}

    @staticmethod
    def package_name(name):
        """A package is a folder name in the repository, never a path: a path could reach another host."""
        if (not isinstance(name, str) or not name.strip() or len(name) > 200 or PureWindowsPath(name).name != name
                or "/" in name or ":" in name or name in (".", "..") or any(ord(c) < 32 for c in name)):
            raise ValueError("Choose an exact package folder name returned by find_packages")
        return name

    def find_packages(self, query="", package=None, action="Install", offset=0):
        if action not in ACTIONS:
            raise ValueError("Choose Install, Uninstall or Repair")
        if type(offset) is not int or offset < 0:
            raise ValueError("Offset must be 0 or more")
        if package is not None:
            package = self.package_name(package)
            scripts = self.wmi.scripts(package, action)["scripts"]
            name = self.wmi.package_root(package).name
            return {"package": name, "action": action, "scripts": scripts[offset:offset + 50], "total": len(scripts),
                    "next_offset": offset + 50 if len(scripts) > offset + 50 else None}
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError("Invalid query")
        repository = self.repository
        try:
            names = sorted((p.name for p in repository.iterdir()
                            if p.is_dir() and not linked(p) and query.casefold() in p.name.casefold()), key=str.casefold)
        except OSError as error:
            raise RuntimeError("Package repository is unavailable (%s). Check Settings and OneDrive sync." % error) from None
        result = {"repository": str(repository), "packages": names[offset:offset + 50],
                  "total": len(names), "next_offset": offset + 50 if len(names) > offset + 50 else None}
        if len(names) == 1 and offset == 0:
            scripts = self.wmi.scripts(names[0], action)["scripts"]
            result.update(package=names[0], action=action, scripts=scripts[:50], script_total=len(scripts),
                          script_next_offset=50 if len(scripts) > 50 else None)
        return result

    # ---- changes -------------------------------------------------------

    def unlinked(self, folder, limit=100000):
        """Refuse a package holding a link or junction: Robocopy would copy whatever it points at."""
        count = 0
        for base, dirs, files in os.walk(str(folder), followlinks=False):
            for entry in dirs + files:
                count += 1
                if count > limit:
                    raise ValueError("Package exceeds 100,000 entries; split it into smaller packages")
                if linked(Path(base) / entry):
                    raise ValueError("Package contains a link or junction: %s" % (Path(base) / entry))

    def digest(self, package, script):
        h = hashlib.sha256()
        with (self.wmi.package_root(package) / script).open("rb") as source:
            for block in iter(lambda: source.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    def deploy_package(self, computers, package, script, action, mode="full"):
        if not isinstance(computers, list) or not 1 <= len(computers) <= MAX_TARGETS:
            raise ValueError("Supply 1 to %d explicit computer names" % MAX_TARGETS)
        if action not in ACTIONS or mode not in ("full", "copy", "execute"):
            raise ValueError("Choose a supported action and mode")
        wmi = self.wmi
        package = self.package_name(package)
        targets = list(dict.fromkeys(self.pc(name) for name in computers))
        requests = []
        for pc in targets:
            request = wmi.validate_deployment(wmi.Deploy(computer=pc, folder=package, script=script, action=action, mode=mode))
            self.ready(request.computer)  # Refuse before asking, as Atlas would after.
            requests.append(request)
        folder = Path(requests[0].folder)
        self.unlinked(folder)
        sha = self.digest(folder.name, script)
        detail = "%s %s using %s on %s (mode=%s; Atlas deployment; script SHA256=%s)" % (
            action, folder.name, script, ", ".join(targets), mode, sha)
        if not self.confirm(detail):
            return {"state": "declined", "message": "User declined the deployment; no job started"}
        if self.digest(folder.name, script) != sha:
            raise RuntimeError("Installer changed during approval. Find the package and approve it again.")
        jobs = []
        for request in requests:
            # Atlas runs exactly the approved script: it checks this digest before copying and before launching.
            request.sha256 = sha
            try:
                self.ready(request.computer)  # The PC may have changed while approval was pending.
                started = wmi.deploy(request)
            except (HTTPException, ValueError) as error:
                jobs.append({"computer": request.computer, "state": "not started",
                             "message": str(getattr(error, "detail", error))})
                continue
            job = started["job"]
            with wmi.lock:
                if job in wmi.jobs:
                    wmi.jobs[job]["requested_by"] = "Axis"
            try:
                wmi.history_update(job, operator="%s (Axis)" % wmi.identity())
            except Exception:
                pass  # The history row already names the operator; the mark is a convenience.
            jobs.append({"computer": request.computer, "job_id": job, "state": "queued"})
        return {"jobs": jobs, "message": "Atlas deployments queued; installation is not yet verified. "
                                         "They appear in Atlas's Deployments. Progress: it_job_status with a job_id."}

    def services_item(self, pc, snapshot, name=None, pid=None, view="services"):
        if not isinstance(snapshot, str):
            raise ValueError("Inspect the PC first and use the snapshot ID it returns")
        with self.lock:
            saved = self.snapshots.get(snapshot)
        if (not saved or saved["computer"] != pc or saved["view"] != view
                or time.time() - saved["created"] > SNAPSHOT_SECONDS):
            raise ValueError("Snapshot expired or belongs to another PC or view; inspect again")
        if view == "services":
            matches = [i for i in saved["items"] if str(i.get("name", "")).casefold() == str(name).casefold()]
        else:
            matches = [i for i in saved["items"] if i.get("PID") == pid]
        if len(matches) != 1:
            raise ValueError("Choose an exact item from the inspection snapshot")
        return matches[0]

    def computer_action(self, computer, action, name=None, pid=None, snapshot=None):
        wmi = self.wmi
        pc = self.pc(computer)
        verbs = {"service_start": "start", "service_stop": "stop", "service_restart": "restart"}
        if action in verbs:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Name the service to change")
            item = self.services_item(pc, snapshot, name=name.strip())
            reason = item.get(verbs[action] + "_reason")
            if item.get("can_" + verbs[action]) is False:
                raise ValueError("Atlas will not %s %s: %s" % (verbs[action], item["name"], reason or "not allowed"))
            self.ready(pc)
            if not self.confirm("%s service %s (%s) on %s" % (verbs[action], item["name"], item.get("display_name", ""), pc)):
                return {"state": "declined"}
            import service_actions
            request = wmi.ServiceControl(computer=pc, name=item["name"], expected_identity=item["identity"])
            with self.held(pc):
                return getattr(service_actions, verbs[action] + "_service")(wmi, request)
        if action == "process_stop":
            if type(pid) is not int:
                raise ValueError("Give the PID from the processes snapshot")
            item = self.services_item(pc, snapshot, pid=pid, view="processes")
            if item.get("CanTerminate") is False:
                raise ValueError("Atlas will not stop %s: %s" % (item.get("Process"), item.get("BlockReason") or "protected"))
            self.ready(pc)
            if not self.confirm("stop process %s (PID %s) on %s" % (item.get("Process"), pid, pc)):
                return {"state": "declined"}
            import remote_processes
            with self.held(pc):
                return remote_processes.terminate(wmi, wmi.Kill(computer=pc, value=str(pid), created=item.get("CreatedAt"),
                                                                name=item.get("Process")))
        if action not in ("enable_remote_registry", "reboot", "cleanup_packages"):
            raise ValueError("Unknown computer action")
        self.ready(pc)
        prompt = {"enable_remote_registry": "enable and start Remote Registry on %s",
                  "reboot": "restart %s; unsaved work may be lost",
                  "cleanup_packages": "delete the package staging folders on %s"}[action] % pc
        if not self.confirm(prompt):
            return {"state": "declined"}
        if action == "cleanup_packages":
            self.ready(pc)
            return wmi.cleanup_package_folder(pc)  # Takes Atlas's per-PC lock itself.
        with self.held(pc):
            if action == "enable_remote_registry":
                import service_actions
                return service_actions.enable_remote_registry(wmi, pc)
            started = wmi.reboot(wmi.Machine(computer=pc))
        with self.lock:
            self.reboots[started["job"]] = {"id": started["job"], "target": pc, "state": "requesting"}
        return dict(started, state="requested", job_id=started["job"], message=(
            "Reboot requested. Atlas's reboot monitor follows ping only; before saying the PC restarted, compare its "
            "boot time with inspect_computer overview. Progress: it_job_status with this job_id."))

    def bulk_service_action(self, computers, action, name):
        pcs, name = service_targets(computers, action, name, self.pc)
        if not self.confirm("%s %s on %d PCs: %s" % (action, name, len(pcs), ", ".join(pcs))):
            return {"state": "declined"}
        import service_actions
        verb = {"service_start": "start", "service_stop": "stop", "service_restart": "restart"}[action]
        outcomes = {"service_start": {"started", "already_running"}, "service_stop": {"stopped", "already_stopped"},
                    "service_restart": {"restarted"}}
        results = []
        for pc in pcs:
            attempted = False
            try:
                with self.held(pc):
                    items = service_actions.list_services(self.wmi, pc)["items"]
                    matches = [item for item in items if str(item.get("name", "")).casefold() == name.casefold()]
                    if len(matches) != 1:
                        raise ValueError("The exact service was not found; no service was changed")
                    item = matches[0]
                    if item.get("can_" + verb) is False:
                        raise ValueError("Atlas will not %s %s: %s" % (verb, item["name"], item.get(verb + "_reason") or "not allowed"))
                    request = self.wmi.ServiceControl(computer=pc, name=item["name"], expected_identity=item["identity"])
                    attempted = True
                    data = getattr(service_actions, verb + "_service")(self.wmi, request)
                wanted = "Stopped" if action == "service_stop" else "Running"
                verified = data.get("outcome") in outcomes[action] and data.get("state") == wanted
                row = {"computer": pc, "ok": verified, "verified": verified,
                       "outcome": data.get("outcome"), "state": data.get("state"), "data": data}
                if not verified:
                    row["error"] = data.get("message") or "Service change was not verified. Inspect current state before retrying."
                results.append(row)
            except Exception as error:
                detail = str(error.detail) if isinstance(error, HTTPException) else str(error)
                results.append({"computer": pc, "ok": False, "verified": False,
                                "outcome": "unknown" if attempted else "not_started",
                                "error": detail[:400] + (". Inspect current state before retrying." if attempted else "")})
        return {"action": action, "name": name, "count": len(results),
                "succeeded": sum(1 for row in results if row["ok"]), "results": results}

    def directory_lookup(self, kind, identity, server=""):
        import active_directory
        if kind == "group":
            found = active_directory.browse(active_directory.Browse(operation="search", kind="group", query=identity,
                                                                    server=server or "", limit=25), self.wmi.ps)
            return {"kind": "group", "query": identity, "items": found.get("items", [])[:25]}
        if kind not in ("user", "computer"):
            raise ValueError("Choose user, computer or group")
        return active_directory.lookup(active_directory.Lookup(kind=kind, identity=identity, server=server or ""),
                                       self.wmi.ps)

    def open_remote_tool(self, computer, tool):
        if tool not in TOOLS_OPENED:
            raise ValueError("Unknown support tool")
        pc = self.pc(computer)
        if not self.confirm("open %s for %s" % (tool.replace("_", " "), pc)):
            return {"state": "declined"}
        return dict(self.wmi.open_target_tool(TOOLS_OPENED[tool], pc),
                    message="Application opened; a remote connection is not verified")

    # ---- jobs ----------------------------------------------------------

    def legacy(self):
        """Earlier Axis job folders that still hold jobs, each read as Axis's own engine reads it."""
        from axis.it_tools import ITTools
        return [ITTools(folder, confirm=self.confirm) for folder in self.legacy_states if (folder / "jobs").is_dir()]

    def find_job(self, prefix):
        """A full job ID from the start of one, among Atlas's jobs, its reboots and earlier Axis jobs."""
        if not isinstance(prefix, str) or not prefix.isalnum() or not 4 <= len(prefix) <= 64:
            raise ValueError("Use a job ID shown by Axis or Atlas (at least its first 4 characters)")
        with self.wmi.lock:
            candidates = set(self.wmi.jobs)
        candidates |= {row.get("id") for row in self.wmi.reboot_monitor.snapshot()["reboots"]}
        for legacy in self.legacy():
            candidates |= {path.stem for path in (legacy.state / "jobs").glob("*.json")}
        matches = sorted(c for c in candidates if isinstance(c, str) and c.startswith(prefix))
        if len(matches) != 1:
            raise ValueError("No single job starts with %s; use more of its ID" % prefix)
        return matches[0]

    def deployment(self, job_id):
        wmi = self.wmi
        job = wmi.job_service.snapshot(wmi.jobs, job_id)
        events = job.get("events", [])
        exit_codes = [e["exit_code"] for e in events if "exit_code" in e]
        log = next((e["log"] for e in reversed(events) if e.get("log")), [])
        result = {"job_id": job_id, "kind": "deployment", "state": job.get("state"), "target": job.get("target"),
                  "package": job.get("package"), "action": job.get("action"), "script": job.get("script"),
                  "events": [e.get("message") for e in events[-20:]], "exit_code": exit_codes[-1] if exit_codes else None,
                  "log_tail": log[-40:] if isinstance(log, list) else log,
                  "requested_by": job.get("requested_by", "Atlas")}
        install = next((e["install"] for e in reversed(events) if isinstance(e.get("install"), dict)), None)
        if install:
            # What the target waited for after the script returned, and what registered software changed.
            result["installer_activity"] = {key: install.get(key) for key in (
                "settled", "waited_seconds", "still_running", "left_running", "windows_installer_busy")}
            if "software" in install:
                result["software_changes"] = install["software"]
        if job.get("recovery_required") or job.get("state") in ("unknown", "interrupted"):
            result["recovery_required"] = not job.get("recovery_acknowledged")
        result["outcome"] = outcome(result)
        return result

    def reboot_row(self, job_id):
        row = next((row for row in self.wmi.reboot_monitor.snapshot()["reboots"] if row.get("id") == job_id), None)
        with self.lock:
            if row is not None:
                self.reboots[job_id] = copy.deepcopy(row)
                return row
            seen = self.reboots.get(job_id)
        if seen is None:
            return None
        if seen.get("state") not in REBOOT_ACTIVE:
            return seen
        return dict(seen, state="no longer listed", message=(
            "Atlas's reboot monitor no longer lists this reboot. It removes a completed or cancelled reboot after "
            "10 seconds; confirm the new boot time with inspect_computer overview before reporting success."))

    def it_job_status(self, job_id=None, wait_seconds=0, acknowledge_unknown=False):
        wmi = self.wmi
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= WAIT_SECONDS:
            raise ValueError("wait_seconds must be between 0 and %d" % WAIT_SECONDS)
        if type(acknowledge_unknown) is not bool:
            raise ValueError("acknowledge_unknown must be boolean")
        if job_id is None:
            if acknowledge_unknown:
                raise ValueError("Select a job to acknowledge")
            recent = wmi.recent_deployments()
            rows = [{"job_id": d["id"], "kind": "deployment", "state": d.get("state"), "target": d.get("target"),
                     "package": d.get("package"), "action": d.get("action"), "last": d.get("last_message")}
                    for d in (recent if isinstance(recent, list) else recent.get("deployments", []))]
            rows += [{"job_id": r.get("id"), "kind": "reboot", "state": r.get("state"), "target": r.get("target"),
                      "last": r.get("message")} for r in wmi.reboot_monitor.snapshot()["reboots"]]
            for legacy in self.legacy():
                rows += [dict({k: j.get(k) for k in ("kind", "computers", "state", "created", "acknowledged")},
                              job_id=j["id"], source="earlier Axis job") for j in legacy.jobs()[:20]]
            return {"jobs": rows, "unresolved_targets": sorted(wmi.job_service.unresolved)}
        if not isinstance(job_id, str) or len(job_id) > 64:
            raise ValueError("Use a job ID returned by Axis or shown in Atlas")
        deadline = time.monotonic() + wait_seconds
        while True:
            with wmi.lock:
                known = job_id in wmi.jobs
            if known:
                result = self.deployment(job_id)
                done = result["state"] in TERMINAL
            else:
                row = self.reboot_row(job_id)
                if row is None:
                    for legacy in self.legacy():
                        if (legacy.state / "jobs" / (job_id + ".json")).is_file():
                            return dict(legacy.it_job_status(job_id, wait_seconds, acknowledge_unknown), source="earlier Axis job")
                    raise ValueError("No Atlas deployment or reboot has this job ID; check Atlas's history")
                result = dict(copy.deepcopy(row), job_id=job_id, kind="reboot")
                done = row.get("state") not in REBOOT_ACTIVE
            if done or time.monotonic() >= deadline:
                break
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        if acknowledge_unknown:
            target = result.get("target")
            if not result.get("recovery_required") or target not in wmi.job_service.unresolved:
                raise ValueError("Only a job whose outcome is unknown, and whose PC is still held, can be acknowledged")
            if self.confirm("acknowledge that you inspected %s for job %s; release it in Atlas's Operation recovery "
                            "without retrying" % (target, job_id)):
                wmi.acknowledge_recovery(target, {"confirmation": target})
                result = self.deployment(job_id)
        if result.get("kind") == "deployment":
            result["verification_note"] = "An exit code describes the script run; application health is not verified by this job."
        return result
