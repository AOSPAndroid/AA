#!/usr/bin/env python3
"""One-step setup for Axis on Windows (Python 3.8+, standard library only).

Downloads and verifies the Qwen3.8-9B model, downloads llama.cpp for your GPU,
fetches the agent, and writes start-server.bat and agent.bat into one folder.
Safe to re-run: finished steps are skipped and interrupted downloads resume.

    python setup_local.py                  # installs into %USERPROFILE%\\local-ai
    python setup_local.py --dir D:\\ai      # somewhere else
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

MODEL = "Qwen3.8-9B-Q4_K_M.gguf"
MODEL_SIZE = 5780090176
MODEL_SHA256 = "df13d66021cef676f82be74053220fd75af6bf2a6a7fb77f5222ab9e50744a7a"
RELEASE = os.environ.get(
    "SETUP_RELEASE_URL",
    "https://github.com/AOSPAndroid/Axis/releases/download/qwen3.8-9b-q4-k-m")
AGENT_URL = os.environ.get(
    "SETUP_AGENT_URL",
    "https://raw.githubusercontent.com/AOSPAndroid/Axis/main/agent/agent.py")
LLAMA_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=50"
LLAMA_RELEASES = "https://github.com/ggml-org/llama.cpp/releases"
CHUNK = 1 << 20


def log(msg):
    print(msg, flush=True)


def fetch(url, accept=None):
    headers = {"User-Agent": "local-agent-setup"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read()


def download(url, dest):
    """Download url to dest, resuming a partial file if one exists."""
    tmp = dest + ".partial"
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    headers = {"User-Agent": "local-agent-setup"}
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 416:  # 416: the partial file is already complete
            raise
        os.replace(tmp, dest)
        return
    with resp:
        if have and resp.status != 206:
            have = 0  # server ignored the range; start over
        total = have + int(resp.headers.get("Content-Length") or 0)
        name = os.path.basename(dest)
        with open(tmp, "ab" if have else "wb") as f:
            done = have
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                f.write(block)
                done += len(block)
                if total:
                    print("\r  %s  %5.1f%%  %d / %d MB" % (name, 100.0 * done / total, done >> 20, total >> 20),
                          end="", flush=True)
        print(flush=True)
    os.replace(tmp, dest)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK * 8), b""):
            h.update(block)
    return h.hexdigest()


# ---- model -----------------------------------------------------------------

def setup_model(root):
    model = os.path.join(root, MODEL)
    if os.path.exists(model) and os.path.getsize(model) == MODEL_SIZE:
        log("Checking existing model...")
        if sha256(model) == MODEL_SHA256:
            log("Model OK, skipping download.")
            return model
        log("Existing model is corrupt; downloading again.")
        os.remove(model)

    free = shutil.disk_usage(root).free
    if free < 12 * 10**9:
        log("Warning: only %.1f GB free; about 12 GB is needed while the parts are joined." % (free / 1e9))

    sums = {}
    for line in fetch(RELEASE + "/PARTS-SHA256SUMS.txt").decode().splitlines():
        if line.strip():
            digest, name = line.split()
            sums[name.lstrip("*")] = digest
    parts = sorted(sums)

    log("Downloading model (%d parts, %.2f GB)..." % (len(parts), MODEL_SIZE / 1e9))
    for name in parts:
        path = os.path.join(root, name)
        if os.path.exists(path) and sha256(path) == sums[name]:
            continue
        if os.path.exists(path):
            os.remove(path)
        download(RELEASE + "/" + name, path)
        if sha256(path) != sums[name]:
            os.remove(path)
            sys.exit("Error: %s failed its checksum. Run setup again to retry." % name)

    log("Joining parts and verifying...")
    h = hashlib.sha256()
    tmp = model + ".joining"
    with open(tmp, "wb") as out:
        for name in parts:
            with open(os.path.join(root, name), "rb") as f:
                for block in iter(lambda: f.read(CHUNK * 8), b""):
                    h.update(block)
                    out.write(block)
    if h.hexdigest() != MODEL_SHA256:
        os.remove(tmp)
        sys.exit("Error: joined model failed its checksum. Delete the .part files and run setup again.")
    os.replace(tmp, model)
    for name in parts:
        os.remove(os.path.join(root, name))
    log("Model OK.")
    return model


# ---- llama.cpp -------------------------------------------------------------

def nvidia_cuda_version():
    """CUDA version the NVIDIA driver supports, e.g. (12, 8), or None without an NVIDIA GPU."""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def cuda_of(name):
    m = re.search(r"cuda-?(\d+)\.(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def pick_llama_assets(assets, driver_cuda):
    """Choose the llama.cpp zip(s) to install. Returns (label, [assets])."""
    zips = [a for a in assets if a["name"].endswith(".zip") and "x64" in a["name"]]
    main = [a for a in zips if "bin-win" in a["name"] and not a["name"].startswith("cudart")]

    if driver_cuda:
        cuda = [a for a in main if cuda_of(a["name"]) and cuda_of(a["name"]) <= driver_cuda]
        if cuda:
            best = max(cuda, key=lambda a: cuda_of(a["name"]))
            ver = cuda_of(best["name"])
            runtime = [a for a in zips if a["name"].startswith("cudart") and cuda_of(a["name"]) == ver]
            return "CUDA %d.%d (NVIDIA)" % ver, [best] + runtime[:1]

    for kind, label in (("vulkan", "Vulkan (AMD / Intel / NVIDIA)"), ("cpu", "CPU only")):
        found = [a for a in main if "-%s-" % kind in a["name"]]
        if found:
            return label, found[:1]
    return None, []


def find_server(folder):
    for base, _, files in os.walk(folder):
        if "llama-server.exe" in files:
            return os.path.join(base, "llama-server.exe")
    return None


def setup_llama(root, gpu):
    folder = os.path.join(root, "llama.cpp")
    server = find_server(folder) if os.path.isdir(folder) else None
    if server:
        log("llama.cpp already installed, skipping. Delete %s to update it." % folder)
        return server

    driver_cuda = None if gpu in ("vulkan", "cpu") else nvidia_cuda_version()
    # The "latest" release is not always a binary one; take the newest with a Windows build.
    label, chosen, release = None, [], {}
    for release in json.loads(fetch(LLAMA_API, "application/vnd.github+json")):
        assets = release.get("assets", [])
        if gpu in ("vulkan", "cpu"):
            assets = [a for a in assets if "cuda" not in a["name"]]
            if gpu == "cpu":
                assets = [a for a in assets if "vulkan" not in a["name"]]
        label, chosen = pick_llama_assets(assets, driver_cuda)
        if chosen and not release.get("draft"):
            break
    if not chosen:
        sys.exit("Error: no recent llama.cpp release has a matching Windows build. Download one from %s, extract it to %s and run setup again."
                 % (LLAMA_RELEASES, folder))

    log("Installing llama.cpp %s, %s build..." % (release.get("tag_name"), label))
    os.makedirs(folder, exist_ok=True)
    for asset in chosen:
        zpath = os.path.join(root, asset["name"])
        download(asset["browser_download_url"], zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(folder)
        os.remove(zpath)

    server = find_server(folder)
    if not server:
        sys.exit("Error: llama-server.exe not found after extracting %s." % ", ".join(a["name"] for a in chosen))
    return server


# ---- agent and launchers -----------------------------------------------------

def setup_agent(root):
    for name in ("agent.py", "it_tools.py", "it_windows.ps1", "terminal_ui.py", "web_tools.py", "atlas_db.py"):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        dest = os.path.join(root, name)
        if os.path.exists(here):
            if os.path.abspath(here) != os.path.abspath(dest):
                shutil.copyfile(here, dest)
        else:
            url = AGENT_URL if name == "agent.py" else AGENT_URL.rsplit("/", 1)[0] + "/" + name
            with open(dest, "wb") as f:
                f.write(fetch(url))
    return os.path.join(root, "agent.py")


def write_launchers(root, server, model):
    start = os.path.join(root, "start-server.bat")
    with open(start, "w", newline="\r\n") as f:
        f.write('@echo off\n'
                'rem Starts the model server for the agent. Set CTX=8192 first if 16384 does not fit.\n'
                'if "%%CTX%%"=="" set CTX=16384\n'
                '"%s" -m "%s" -ngl 99 -c %%CTX%% --jinja --host 127.0.0.1 --port 8080 '
                '--temp 0.6 --top-p 0.95 --top-k 20\n' % (server, model))
    agent = os.path.join(root, "agent.bat")
    with open(agent, "w", newline="\r\n") as f:
        f.write('@echo off\n'
                'title Axis\n'
                'rem Runs Axis in the current folder. Extra options are passed through.\n'
                'if "%%CTX%%"=="" set CTX=16384\n'
                '"%s" "%s" --workdir "%%CD%%" --ctx %%CTX%% %%*\n' % (sys.executable, os.path.join(root, "agent.py")))
    return start, agent


def main():
    p = argparse.ArgumentParser(description="Set up the local Qwen agent.")
    p.add_argument("--dir", default=os.path.join(os.path.expanduser("~"), "local-ai"), help="install folder")
    p.add_argument("--gpu", choices=["auto", "vulkan", "cpu"], default="auto",
                   help="llama.cpp build: auto picks CUDA for NVIDIA cards, otherwise Vulkan")
    a = p.parse_args()
    if os.name != "nt":
        sys.exit("This setup script is for Windows. On Linux or macOS, follow agent/README.md.")

    root = os.path.abspath(a.dir)
    os.makedirs(root, exist_ok=True)
    log("Installing into %s\n" % root)
    try:
        model = setup_model(root)
        server = setup_llama(root, a.gpu)
        setup_agent(root)
    except (urllib.error.URLError, OSError) as e:
        sys.exit("\nError: %s\nRun setup again to resume." % e)
    start, agent = write_launchers(root, server, model)

    log("\nDone. To use it:\n"
        "  1. Double-click %s and leave that window open.\n"
        "  2. In another terminal, cd to a project folder and run:\n"
        "       \"%s\"\n"
        "     (add %s to your PATH to type just 'agent')." % (start, agent, root))


if __name__ == "__main__":
    main()
