"""Optional shared Windows startup; ordinary Axis never imports this module."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request


class AtlasLaunchError(RuntimeError):
    pass


def _folder(value):
    return Path(str(value).strip().strip('"')).expanduser().resolve()


def _is_atlas(path):
    return all((path / name).is_file() for name in
               ("Start-Office-Atlas.bat", "Python_Settings.bat", "launcher.py"))


def _saved_folder():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Axis" / "atlas-folder.txt"


def find_atlas(here, directory=None):
    selected = directory or os.environ.get("ATLAS_HOME")
    if selected:
        root = _folder(selected)
        if not _is_atlas(root):
            raise AtlasLaunchError("Atlas launcher files were not found in %s. Use --atlas-dir with your Atlas installation folder." % root)
        return root
    try:
        saved = _saved_folder().read_text(encoding="utf-8").strip()
        if saved and _is_atlas(_folder(saved)):
            return _folder(saved)
    except (OSError, ValueError):
        pass

    here = Path(here).resolve()
    candidates = {path.resolve() for path in
                  (here / "Atlas", here.parent / "Atlas", here.parent.parent / "Atlas", Path(r"F:\Atlas"))
                  if _is_atlas(path)}
    if len(candidates) == 1:
        return candidates.pop()
    print("Atlas folder (the folder containing Start-Office-Atlas.bat). Saved after successful startup.")
    try:
        selected = input("Atlas folder > ").strip()
    except EOFError:
        selected = ""
    if not selected:
        raise AtlasLaunchError("Set --atlas-dir to your Atlas installation folder, or use Start Agent.bat for Axis alone.")
    return find_atlas(here, selected)


def _get_json(port, route):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d%s" % (port, route), timeout=5) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("Invalid Atlas response")
    return value


def _active_port(root, identity, required=False):
    try:
        record = json.loads((root / "data" / "server.json").read_text(encoding="utf-8"))
        port = record["port"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid Atlas port")
        health = _get_json(port, "/api/health")
    except (OSError, ValueError, KeyError, TypeError):
        if not required:
            return None  # Atlas's own launcher handles stale records and occupied ports.
        raise AtlasLaunchError("Cannot verify Atlas startup. Check Atlas's logs\\admin-startup.log.") from None
    if (health.get("application") != "Office Atlas" or health.get("mode") != "admin"
            or not record.get("instance_id") or health.get("instance_id") != record["instance_id"]
            or not record.get("root") or _folder(record["root"]) != root
            or not health.get("instance_root") or _folder(health["instance_root"]) != root):
        raise AtlasLaunchError("The running Atlas instance does not match this folder. Use its Stop-All-Atlas.bat, then retry.")
    if str(health.get("identity", "")).strip().casefold() != identity.casefold():
        raise AtlasLaunchError("Atlas is running under a different or unknown Windows account. Stop it with its existing launcher, then run this launcher under your DSK account.")
    return port


def start_atlas(here, directory=None):
    """Run Atlas's launcher under our account and return its active database file."""
    if sys.platform != "win32":
        raise AtlasLaunchError("The shared Atlas launcher requires Windows. Start Agent.bat still runs Axis on its own.")
    root = find_atlas(here, directory)
    identity = subprocess.run(["whoami.exe"], capture_output=True, text=True, check=True).stdout.strip()
    if not identity:
        raise AtlasLaunchError("Cannot identify this window's Windows account.")
    _active_port(root, identity)  # Reject another account before Atlas starts its collectors.
    env = os.environ.copy()
    if not env.get("WMI_PYTHON") and sys.version_info >= (3, 12):
        env["WMI_PYTHON"] = sys.executable
    env["AXIS_ATLAS_LAUNCHER"] = str(root / "Start-Office-Atlas.bat")
    command = '"%s" /d /v:off /s /c ""%%AXIS_ATLAS_LAUNCHER%%""' % os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
    print("Starting Atlas as %s..." % identity, flush=True)
    # A fixed environment placeholder avoids interpreting folder names as shell code.
    result = subprocess.run(command, cwd=str(root), env=env)
    if result.returncode:
        raise AtlasLaunchError("Atlas startup failed (exit %d). Resolve the message above and retry, or use Start Agent.bat for Axis alone." % result.returncode)
    port = _active_port(root, identity, required=True)
    try:
        status = _get_json(port, "/api/master/status")
        if status.get("available") is not True or not isinstance(status.get("path"), str) or not status["path"]:
            raise ValueError("Database unavailable")
        path = Path(status["path"]).expanduser()
        database = (path if path.is_absolute() else root / path).resolve()
        if not database.is_file():
            raise ValueError("Database file missing")
    except (OSError, ValueError):
        raise AtlasLaunchError("Atlas's active database is unavailable. Check its database settings; Axis has not selected a different file.") from None
    try:
        saved = _saved_folder()
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(str(root), encoding="utf-8")
    except OSError:
        print("Could not remember the Atlas folder; use --atlas-dir next time.", flush=True)
    print("Atlas database (read-only for Axis): %s" % database, flush=True)
    return str(database)
