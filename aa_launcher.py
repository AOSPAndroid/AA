"""Launch the Atlas map and Axis chat together under this Windows account."""
import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request
import webbrowser

import launcher as atlas
from axis import start as axis
from axis.it_tools import target_lock
from axis.launch_atlas import _active_port

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "axis"


def _read(path):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid launcher record: " + str(path))
    return value


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _identity():
    identity = subprocess.run(["whoami.exe"], capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()
    if not identity:
        raise RuntimeError("Cannot identify this Windows account.")
    return identity


class _WindowsProcess:
    """Keep one kernel handle open from identity verification through termination.

    A PID can be recycled between a metadata query and Stop-Process. A retained
    handle always refers to the original process, even if it has since exited.
    """
    def __init__(self, pid, terminate=False):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE, optionally TERMINATE.
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000 | int(terminate), False, pid)
        if not self.handle:
            if ctypes.get_last_error() == 87:
                raise ProcessLookupError(pid)
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = pid

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kernel.CloseHandle(self.handle)

    def metadata(self):
        from ctypes import wintypes
        if self.kernel.WaitForSingleObject(self.handle, 0) == 0:
            raise ProcessLookupError(self.pid)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        created = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        return {"pid": self.pid, "created": created, "executable": path.value}

    def stop(self):
        if self.kernel.WaitForSingleObject(self.handle, 0) == 0:
            return
        if not self.kernel.TerminateProcess(self.handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.kernel.WaitForSingleObject(self.handle, 10000) != 0:
            raise RuntimeError("The model process did not exit within 10 seconds.")


def _same_path(left, right):
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _listener_pid():
    # Verify the new child's socket, not just an unrelated server's /health.
    script = ("$ErrorActionPreference='Stop';"
              "$p=@(Get-NetTCPConnection -State Listen -LocalPort 8080 | "
              "Select-Object -ExpandProperty OwningProcess -Unique);"
              "if($p.Count -ne 1){throw 'Cannot identify model listener'};[Console]::Write($p[0])")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, check=True, timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return int(result.stdout.strip())


def _owned_record(child, executable, alias):
    with _WindowsProcess(child.pid) as process:
        record = process.metadata()
        if (child.poll() is not None or not _same_path(record["executable"], executable)
                or _listener_pid() != child.pid or axis.server_model() != alias):
            raise RuntimeError("Cannot verify ownership of the newly started model server.")
    return dict(record, root=str(ROOT), model=alias)


def _stop_model():
    path = STATE / "model-process.json"
    record = _read(path)
    if not record:
        print("No AA-owned model server to stop. Reused servers are left running.")
        return
    if (not isinstance(record.get("root"), str) or not _same_path(record["root"], ROOT)
            or type(record.get("pid")) is not int or record["pid"] <= 0
            or not isinstance(record.get("created"), str) or not record["created"].isdigit()
            or not isinstance(record.get("executable"), str) or not record["executable"]):
        raise RuntimeError("Invalid model ownership record; retained for inspection: " + str(path))
    try:
        with _WindowsProcess(record["pid"], terminate=True) as process:
            actual = process.metadata()
            if (actual["created"] != record["created"]
                    or not _same_path(actual["executable"], record["executable"])):
                raise RuntimeError("Model PID now belongs to another process. It was not stopped; ownership record retained.")
            process.stop()
    except ProcessLookupError:
        pass
    path.unlink()
    print("AA model server stopped.")


def _discard_exited_record():
    path = STATE / "model-process.json"
    record = _read(path)
    if not record:
        return
    if type(record.get("pid")) is not int or record["pid"] <= 0:
        raise RuntimeError("Invalid model ownership record. Check " + str(path))
    try:
        with _WindowsProcess(record["pid"]) as process:
            process.metadata()
    except ProcessLookupError:
        path.unlink()
        return
    raise RuntimeError("A recorded AA model is still running but not ready. Run Stop AA.bat before restarting.")


def _port_busy():
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", axis.PORT))
        except OSError:
            return True
    return False


def _running_context(alias):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8080/props", timeout=3) as response:
            value = json.load(response)["default_generation_settings"]["n_ctx"]
        if type(value) is int and 4096 <= value <= 131072:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # A conservative history budget when an external server does not expose it.
    return 4096


def _settings(alias, ctx, managed):
    catalog = next((m for m in axis.MODELS.values() if m["name"] == alias), {})
    return {"model": alias, "ctx": ctx, "think": True, "managed": managed,
            "sampling": {key: catalog[key] for key in ("temperature", "top_p") if key in catalog}}


def _start_model(args):
    if axis.server_ready():
        alias = axis.server_model()
        if not isinstance(alias, str) or not alias:
            raise RuntimeError("The server on port 8080 does not identify a single model; chat cannot use it.")
        if args.model and axis.MODELS[args.model]["name"] != alias:
            raise RuntimeError("Port 8080 already serves %s. Stop that server before selecting another model." % alias)
        ctx = _running_context(alias)
        _write(STATE / "model-settings.json", _settings(alias, ctx, False))
        print("Axis ready: using %s on port 8080 (existing server left under its original owner)." % alias)
        if args.ctx or args.cpu or args.gpu:
            print("Startup options apply to new model servers; the existing server was not reconfigured.")
        return
    if _port_busy():
        raise RuntimeError("Port 8080 is busy or the model is still loading. No second model was started.")
    _discard_exited_record()
    try:
        key, model = axis.prepare_model(args.model)
    except SystemExit as error:
        raise RuntimeError("Model files are not ready. Put your complete GGUF in the AA or axis folder, then run Start AA.bat again.") from error
    catalog = axis.MODELS[key]
    alias = catalog["name"]
    ctx = args.ctx or catalog.get("ctx", 16384)
    gpu = not args.cpu and (args.gpu or axis.use_gpu(axis.gpus()))
    ui = axis.TerminalUI(plain=args.plain)
    child = None
    for build in (["vulkan", "cpu"] if gpu else ["cpu"]):
        executable = axis.find_server(str(ROOT / "axis" / ("llama-" + build)))
        if not executable:
            continue
        print("Starting %s with llama-%s..." % (alias, build), flush=True)
        child = axis.start_server(executable, model, ctx, build == "vulkan", think=True,
                                  alias=alias, extra=catalog.get("server_args", ()), ui=ui)
        if child:
            break
    if not child:
        raise RuntimeError("Model startup failed. Use the AA Windows bundle with its llama-cpu/llama-vulkan folders; see axis/server.log.")
    try:
        record = _owned_record(child, executable, alias)
        _write(STATE / "model-process.json", record)
        _write(STATE / "model-settings.json", _settings(alias, ctx, True))
    except BaseException:
        # This Popen is ours even if writing its persistent record fails.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
        raise
    print("Axis ready: %s. Thinking is enabled." % alias)


def start(args):
    identity = _identity()
    _active_port(ROOT, identity)  # Reject another account before collectors start.
    print("Starting AA as %s..." % identity, flush=True)
    if atlas.run(open_browser=False):
        return 1
    port = _active_port(ROOT, identity, required=True)
    try:
        _start_model(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Map ready; Axis chat is not ready: %s" % error, flush=True)
    if not args.no_browser:
        webbrowser.open("http://127.0.0.1:%d/" % port)
    print("AA map: http://127.0.0.1:%d/\nUse Stop AA.bat to stop this AA installation." % port)
    return 0


def stop():
    # Atlas's own launcher verifies instance records. Refuse foreign roots first.
    for mode in ("admin", "viewer"):
        record = atlas.read_record(mode)
        if record and (not record.get("root") or not _same_path(record["root"], ROOT)):
            raise RuntimeError("The %s record belongs to another installation; nothing was stopped." % mode)
    failed = 0
    try:
        _stop_model()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Model was not stopped: %s" % error)
        failed = 1
    return int(bool(atlas.stop() or failed))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"), nargs="?", default="start")
    parser.add_argument("--model", choices=list(axis.MODELS))
    parser.add_argument("--ctx", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--plain", action="store_true")
    gpu = parser.add_mutually_exclusive_group()
    gpu.add_argument("--cpu", action="store_true")
    gpu.add_argument("--gpu", action="store_true")
    args = parser.parse_args(argv)
    if args.ctx is not None and not 4096 <= args.ctx <= 131072:
        parser.error("--ctx must be between 4096 and 131072")
    if sys.platform != "win32" or sys.version_info < (3, 12):
        print("AA needs Windows and Python 3.12+. Use Start AA.bat.")
        return 1
    try:
        with target_lock(STATE, "AA-LAUNCHER"):
            return start(args) if args.action == "start" else stop()
    except KeyboardInterrupt:
        print("\nStartup cancelled. The map may still be running; use Stop AA.bat to stop AA.")
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("AA: %s" % error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
