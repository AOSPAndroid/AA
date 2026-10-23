#!/usr/bin/env python3
"""Start Axis: prepare the model, start llama-server, then open the assistant.

Double-click "Start Agent.bat", or run:  python start.py [--workdir DIR] [--model KEY] [--cpu]
Needs no internet access. The model parts are picked up from Downloads (or
this folder, or %USERPROFILE%\\local-ai) and joined on first run.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if __package__:
    from .terminal_ui import TerminalUI
else:
    from terminal_ui import TerminalUI

HERE = os.path.dirname(os.path.abspath(__file__))
AA_ROOT = os.path.dirname(HERE)
PART_SIZE = 1900000000
RELEASES = "https://github.com/AOSPAndroid/Axis/releases/tag/"
def in_aa():
    return os.path.isfile(os.path.join(AA_ROOT, "aa_launcher.py"))


def _aa_module(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location("aa_" + name, os.path.join(AA_ROOT, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aa_settings():
    """The state, database and package folder AA's browser chat uses, so both chats share them."""
    config_path = os.path.join(AA_ROOT, "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}
    return {"--state-dir": os.path.join(AA_ROOT, "data", "axis", "state"),
            "--atlas-db": str(_aa_module("runtime_paths").database_path()),
            "--package-repo": str(_aa_module("package_paths").package_repository(config if isinstance(config, dict) else {}, Path(AA_ROOT)))}


def unresolved_jobs(state):
    """Jobs in an earlier terminal state folder that would no longer guard their PCs."""
    folder = os.path.join(state, "jobs")
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                job = json.load(f) if name.endswith(".json") else None
        except (OSError, ValueError):
            continue
        if job and (job.get("state") in ("queued", "running") or job.get("state") == "unknown" and not job.get("acknowledged")):
            found.append(job.get("id", name))
    return found


def load_models():
    """Models in menu order. "parts" are the SHA-256 of each 1.9 GB release part. A model in several
    files lists them under "files"; llama-server is given the first and finds the rest next to it."""
    with open(os.path.join(HERE, "models.json")) as f:
        models = {}
        for m in json.load(f):
            m = dict(m, release=RELEASES + m["tag"])
            files = m.get("files") or [{k: m[k] for k in ("file", "size", "sha256", "parts")}]
            m["files"] = [dict(one, name=m["name"], release=m["release"]) for one in files]
            m.setdefault("file", m["files"][0]["file"])
            models[m["key"]] = m
        return models


MODELS = load_models()
PORT = 8080
HOME = os.path.expanduser("~")
SEARCH_DIRS = [HERE, os.path.dirname(HERE), os.path.join(HOME, "Downloads"), os.path.join(HOME, "local-ai")]
GPU_WORDS = ("nvidia", "radeon", "amd", "intel(r) arc")
MIN_VRAM = 3500000000  # Windows caps the reported value at 4 GB, so this means "4 GB or more"
CHUNK = 8 << 20


def log(msg=""):
    print(msg, flush=True)


# ---- model -----------------------------------------------------------------

def find_file(name, size):
    for d in SEARCH_DIRS:
        path = os.path.join(d, name)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path
    return None


def part_list(m):
    """[(file name, size, sha256)] for each release part of model m."""
    count = len(m["parts"])
    return [("%s.part%03d" % (m["file"], i + 1),
             PART_SIZE if i < count - 1 else m["size"] - PART_SIZE * (count - 1),
             digest) for i, digest in enumerate(m["parts"])]


def sha256(path, label):
    h = hashlib.sha256()
    size, done = os.path.getsize(path), 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
            done += len(block)
            print("\r  %s %3d%%" % (label, 100 * done // max(size, 1)), end="", flush=True)
    log()
    return h.hexdigest()


def join_parts(m):
    """Join verified parts in place (needs only one part of spare disk) and resume if interrupted."""
    parts = part_list(m)
    first_dir = None
    for d in SEARCH_DIRS:
        if os.path.exists(os.path.join(d, m["file"] + ".joining")):
            first_dir = d
    if first_dir is None:
        first = find_file(*parts[0][:2])
        first_dir = os.path.dirname(first)
    target = os.path.join(first_dir, m["file"] + ".joining")
    state_path = target + ".json"
    state = {"appended": 0, "size": 0}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
        log("Resuming the join after part %d." % state["appended"])

    todo = parts[state["appended"]:]
    log("Checking %d model parts (one time only)..." % len(todo))
    paths = []
    for i, (name, size, digest) in enumerate(todo, state["appended"] + 1):
        path = os.path.join(first_dir, name) if i == 1 else find_file(name, size)
        if i == 1 and not os.path.exists(path):
            path = target  # part 1 was already renamed to the join target
        if path is None:
            sys.exit("Error: %s is missing. Download it from %s and rerun." % (name, m["release"]))
        if path != target and sha256(path, "part %d/%d" % (i, len(parts))) != digest:
            sys.exit("Error: %s is damaged. Delete it, download it again and rerun." % path)
        paths.append(path)

    log("Joining...")
    for i, path in enumerate(paths, state["appended"] + 1):
        if i == 1:
            os.replace(path, target)
            path = target
        else:
            with open(target, "r+b") as out:
                out.truncate(state["size"])  # drop a half-written append from an interruption
                out.seek(state["size"])
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, out, CHUNK)
                out.flush()
                os.fsync(out.fileno())
        state = {"appended": i, "size": os.path.getsize(target)}
        with open(state_path, "w") as f:
            json.dump(state, f)
        if path != target:
            os.remove(path)
        print("\r  %3d%%" % (100 * state["size"] // m["size"]), end="", flush=True)
    log()
    if os.path.getsize(target) != m["size"]:
        sys.exit("Error: the joined model has the wrong size. Delete %s and download the parts again." % target)
    final = os.path.join(HERE, m["file"])
    try:
        os.replace(target, final)
    except OSError:  # different drive: leave it where it is
        final = os.path.join(first_dir, m["file"])
        os.replace(target, final)
    os.remove(state_path)
    log("Model ready: %s" % final)
    return final


def parts_status(m):
    found = [find_file(name, size) for name, size, _ in part_list(m)]
    joining = any(os.path.exists(os.path.join(d, m["file"] + ".joining")) for d in SEARCH_DIRS)
    return found, joining


def file_status(f):
    """For one model file: ("ready", path), ("parts", None) when joinable, or ("partial", parts found)."""
    path = find_file(f["file"], f["size"])
    if path:
        return "ready", path
    if not f["parts"]:
        return None, 0  # parts not published yet
    found, joining = parts_status(f)
    if joining or all(found):
        return "parts", None
    return "partial", sum(1 for p in found if p)


def model_status(m):
    """("ready", path), ("parts", None) when joinable, ("partial", found count) or (None, 0)."""
    states = [file_status(f) for f in m["files"]]
    if all(state == "ready" for state, _ in states):
        return "ready", states[0][1]
    if any(state is None for state, _ in states):
        return None, 0
    if all(state in ("ready", "parts") for state, _ in states):
        return "parts", None
    count = sum(len(f["parts"]) if state != "partial" else found for f, (state, found) in zip(m["files"], states))
    return ("partial", count) if count else (None, 0)


def report_missing(m):
    log("%s is not ready yet. Missing or still downloading:" % m["name"])
    for f in m["files"]:
        if find_file(f["file"], f["size"]):
            continue
        found, joining = parts_status(f)
        if joining:
            continue
        for (name, _, _), p in zip(part_list(f), found):
            if not p:
                log("  " + name)
    log("\nDownload them from %s" % m["release"])
    log("(wait until none ends in .crdownload). Looked in:")
    for d in SEARCH_DIRS:
        log("  " + d)


def same_folder(paths):
    """Put the files of a split model next to the first one, where llama-server looks for them."""
    folder = os.path.dirname(paths[0])
    for path in paths[1:]:
        if os.path.normcase(os.path.abspath(os.path.dirname(path))) != os.path.normcase(os.path.abspath(folder)):
            destination = os.path.join(folder, os.path.basename(path))
            if os.path.lexists(destination):
                sys.exit("Error: %s already exists. Resolve the duplicate model file before moving %s there." % (destination, path))
            try:
                os.rename(path, destination)
            except OSError:
                sys.exit("Error: move %s into %s, then start again." % (path, folder))
    return paths[0]


def choose(keys):
    log("Models found:")
    for i, key in enumerate(keys, 1):
        log("  %d) %-30s %s" % (i, MODELS[key]["name"], MODELS[key]["note"]))
    while True:
        try:
            answer = input("Choose a model [1]: ").strip()
        except EOFError:
            answer = ""
        if not answer:
            return keys[0]
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]


def prepare_model(choice=None):
    """Return (model key, path), asking which model to use when several are present."""
    status = {key: model_status(m) for key, m in MODELS.items()}
    if choice:
        key = choice
    else:
        usable = [k for k, (state, _) in status.items() if state in ("ready", "parts")]
        partial = [k for k, (state, _) in status.items() if state == "partial"]
        if not usable:
            if partial:
                report_missing(MODELS[partial[0]])
            else:
                log("No model found. Download all the parts of one of these into Downloads:")
                for m in MODELS.values():
                    log("  %-30s %s" % (m["name"], m["release"]))
            sys.exit(1)
        for k in partial:
            log("Still downloading: %s (%d of %d parts)" % (MODELS[k]["name"], status[k][1],
                                                            sum(len(f["parts"]) for f in MODELS[k]["files"])))
        key = usable[0] if len(usable) == 1 else choose(usable)
    state, _ = status[key]
    if state in ("ready", "parts"):
        paths = [find_file(f["file"], f["size"]) or join_parts(f) for f in MODELS[key]["files"]]
        return key, same_folder(paths)
    if all(f["parts"] for f in MODELS[key]["files"]):
        report_missing(MODELS[key])
    else:
        log("%s has not been published yet: %s" % (MODELS[key]["name"], MODELS[key]["release"]))
    sys.exit(1)


# ---- llama-server ----------------------------------------------------------

def gpus():
    """[(name, memory in bytes)] of the display adapters. Memory is capped at 4 GB."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_VideoController | "
                              "ForEach-Object { '{0}|{1}' -f $_.AdapterRAM, $_.Name }"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    result = []
    for line in out.splitlines():
        ram, _, name = line.strip().partition("|")
        if name:
            result.append((name.strip(), int(ram) if ram.isdigit() else 0))
    return result


def use_gpu(adapters):
    """True when a graphics card with 4 GB or more is present. Smaller cards are slower than the processor here."""
    return any(ram >= MIN_VRAM for name, ram in adapters if any(w in name.lower() for w in GPU_WORDS))


def find_server(folder):
    for base, _, files in os.walk(folder):
        for name in ("llama-server.exe", "llama-server"):
            if name in files:
                return os.path.join(base, name)
    return None


def server_ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:%d/health" % PORT, timeout=5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def start_server(exe, model, ctx, gpu, think=True, alias=None, extra=(), ui=None):
    ui = ui or TerminalUI()
    log_path = os.path.join(HERE, "server.log")
    cmd = [exe, "-m", model, "-c", str(ctx), "--jinja", "--host", "127.0.0.1", "--port", str(PORT),
           # On a graphics card llama.cpp fits as many layers (or, for mixture-of-experts
           # models, the shared layers first) as free memory allows; the rest stays in RAM.
           "-ngl", "auto" if gpu else "0", "--temp", "0.6", "--top-p", "0.95", "--top-k", "20"]
    cmd += ["--alias", alias or os.path.splitext(os.path.basename(model))[0]]
    cmd += list(extra)
    if not think:
        # Some chat templates ignore the per-request switch; a zero budget ends any thinking at once.
        cmd += ["--reasoning", "off", "--reasoning-budget", "0"]
    with open(log_path, "w") as log_file:
        try:
            # Ctrl+C belongs to the chat, not the model server sharing its console.
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=os.path.dirname(exe),
                                    creationflags=flags, start_new_session=os.name != "nt")
        except OSError as e:
            log("  could not start %s: %s" % (exe, e))
            return None
    deadline = time.monotonic() + 600
    try:
        # llama-server does not provide reliable load percentages; show activity only.
        with ui.status("Loading model"):
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    with open(log_path, errors="replace") as f:
                        tail = f.read().splitlines()[-8:]
                    ui.error("llama-server stopped (exit code %s)" % proc.returncode)
                    for line in tail:
                        log("    " + line)
                    return None
                if server_ready():
                    ui.checkpoint("Model ready")
                    return proc
                time.sleep(2)
        proc.kill()
        proc.wait()
        ui.error("Timed out after 10 minutes; see %s" % log_path)
        return None
    except BaseException:
        # Ctrl+C during model loading must not leave an orphan server behind.
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise


def wait_for_agent(command):
    child = subprocess.Popen(command)
    while True:
        try:
            return child.wait()
        except KeyboardInterrupt:
            # The child receives the same console event and cancels its request.
            continue


def server_model():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:%d/v1/models" % PORT, timeout=5) as response:
            entries = json.load(response).get("data", [])
        return entries[0]["id"] if len(entries) == 1 else None
    except (OSError, ValueError, KeyError):
        return None


def main(argv=None):
    p = argparse.ArgumentParser(description="Start llama-server and Axis.")
    p.add_argument("--setup-firecrawl", action="store_true", help="save a Firecrawl API key in your user profile, then exit")
    p.add_argument("--with-atlas", action="store_true", help="start Atlas with this Windows account and share its active database")
    p.add_argument("--atlas-dir", help="Atlas installation folder (also enables --with-atlas)")
    p.add_argument("--atlas-db", help="Atlas database file for standalone Axis; shared startup selects Atlas's active file")
    p.add_argument("--plain", action="store_true", help="disable colour and animation in both startup and chat")
    p.add_argument("--workdir", default=os.path.join(HERE, "workspace"),
                   help="folder the agent works in (default: the workspace folder here)")
    p.add_argument("--ctx", type=int, help="context size in tokens (default: model setting, otherwise 16384)")
    p.add_argument("--model", choices=list(MODELS), help="which model to use (default: ask when several are present)")
    p.add_argument("--temperature", type=float, help="override the model's sampling temperature")
    p.add_argument("--top-p", type=float, help="override the model's nucleus sampling")
    thinking = p.add_mutually_exclusive_group()
    thinking.add_argument("--think", dest="think", action="store_true", default=True,
                          help="enable and display model thinking (default)")
    thinking.add_argument("--no-think", dest="think", action="store_false",
                          help="disable model thinking for faster answers")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cpu", action="store_true", help="always run on the processor")
    g.add_argument("--gpu", action="store_true", help="try the graphics card even if none was detected")
    a, agent_args = p.parse_known_args(argv)

    if a.setup_firecrawl:
        from web_tools import configure_firecrawl
        return configure_firecrawl()

    if in_aa() and (a.with_atlas or a.atlas_dir):
        p.error("AA already includes Atlas. Start AA.bat opens the map; this terminal shares its database, jobs and memory")
    if a.with_atlas or a.atlas_dir:
        if a.atlas_db:
            p.error("--atlas-db is for standalone Axis; shared startup selects Atlas's active database automatically")
        from launch_atlas import AtlasLaunchError, start_atlas
        try:
            a.atlas_db = start_atlas(HERE, a.atlas_dir)
        except (AtlasLaunchError, OSError, subprocess.SubprocessError) as exc:
            log("Could not start Axis with Atlas: %s" % exc)
            return 1
    if a.atlas_db:
        agent_args += ["--atlas-db", a.atlas_db]
    if in_aa():
        # One tool: the terminal uses the jobs, locks, memory, database and packages of AA's browser chat.
        given = {arg.split("=", 1)[0] for arg in agent_args}
        if os.environ.get("AGENT_PACKAGE_REPO"):
            given.add("--package-repo")
        for option, value in aa_settings().items():
            if option not in given:
                agent_args += [option, value]
        legacy = unresolved_jobs(os.path.join(HERE, "state"))
        if legacy and "--state-dir" not in given:
            log("Earlier terminal jobs in axis\\state are still active or unresolved: %s. Inspect those PCs, "
                "then review the jobs with: \"Start Agent.bat\" --state-dir state" % ", ".join(legacy))

    ui = TerminalUI(plain=a.plain)
    if a.plain:
        agent_args.append("--plain")

    key, model = prepare_model(a.model)
    settings = MODELS[key]
    alias = settings["name"]
    ctx = a.ctx if a.ctx is not None else settings.get("ctx", 16384)
    for option, field in (("--temperature", "temperature"), ("--top-p", "top_p")):
        supplied = getattr(a, field)
        value = supplied if supplied is not None else settings.get(field)
        if value is not None:
            agent_args += [option, str(value)]
    log("Model: %s" % os.path.basename(model))
    ui.startup(alias)
    os.makedirs(a.workdir, exist_ok=True)

    proc = None
    if server_ready():
        log("Using the llama-server already running on port %d." % PORT)
        alias = server_model()
        if not alias:
            sys.exit("Cannot identify the running server's model. Close it and restart this launcher, or run agent.py directly with its --model ID.")
    else:
        adapters = gpus()
        log("Graphics: %s" % (", ".join(name for name, _ in adapters) or "unknown"))
        gpu = not a.cpu and (a.gpu or use_gpu(adapters))
        builds = ["vulkan", "cpu"] if gpu else ["cpu"]
        for build in builds:
            exe = find_server(os.path.join(HERE, "llama-" + build))
            if not exe:
                log("No llama-%s folder next to start.py; skipping." % build)
                continue
            where = "graphics card + processor" if build == "vulkan" else "processor"
            log("Starting llama-server (%s), loading the model" % where)
            proc = start_server(exe, model, ctx, build == "vulkan", think=a.think, alias=alias,
                                extra=settings.get("server_args", ()), ui=ui)
            if proc:
                break
            if build == "vulkan":
                log("Falling back to the processor.")
        if not proc:
            sys.exit("Could not start llama-server. Details are in %s" % os.path.join(HERE, "server.log"))

    try:
        log()
        return wait_for_agent([sys.executable, os.path.join(HERE, "agent.py"), "--model", alias,
                               "--workdir", a.workdir, "--ctx", str(ctx),
                               "--think" if a.think else "--no-think"] + agent_args)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStartup cancelled.")
        sys.exit(130)
