# AA — Atlas + Axis

Atlas's map and tools, with Axis chat in the same application.

**[Download AA for Windows](https://github.com/AOSPAndroid/AA/releases/download/aa-windows/aa-windows.zip)**

## Start

1. Extract `aa-windows.zip`.
2. Put your existing full GGUF model in the `AA` folder or its `axis` folder.
   The model files remain separate; you do not need to download them again.
3. Run **Start AA.bat** under your DSK account.
4. Use the Atlas map and the **Axis** chat panel in the same browser window.

Python 3.12 and Atlas's existing Python dependencies are required. The launcher
prefers `C:\devhome\tools\python3.12\current\python.exe`. If this Python does not
have Atlas's packages, run `Install_Dependencies.bat` once. The Windows download
includes CPU and Vulkan llama.cpp runtimes, but no model weights or API keys.

Use **Stop AA.bat** to stop this installation and the model it started. A model
server already running when AA starts stays under its original owner's control.
If the model is missing, the map still opens and chat explains how to start it.

## One workspace

- **Map first:** the Atlas map stays on the homepage; the chat panel can be closed
  to return to the desk inspector.
- **Shared directory:** Axis reads the database Atlas is actually using and uses
  the same configured package repository.
- **Selected desk:** explicitly attach a desk to the chat when useful. Selection
  gives Axis context; changes still require approval.
- **Chat on every page:** the **Axis** button opens the same chat on the console
  pages. On Workspace, **Use current target** attaches the target PC.
- **Clipboard page:** the Clipboard sits beside Workspace and Live Inbox. Each
  capture lists the machines, people, desks, tickets and IP addresses Atlas
  recognises, with their actions.
- **Ask Axis about a request or capture:** **Ask Axis** on a Live Inbox message or
  a clipboard capture attaches it to the chat. The Admin backend reads it by ID
  and gives it to Axis as a tool result: private, untrusted evidence, never your
  instructions. Axis can also list and read recent requests and captures itself.
  Once such text is in a conversation, every web lookup (shown in full), shell
  command and PC outside Atlas needs your approval, so the text cannot leave
  through a search or a DNS lookup.
- **Desks from chat:** ask where someone sits or which desk a PC is at. Axis
  reads the floor-plan seating (stored plan, not who is in today), and each desk
  it finds has a **Show on map** button that selects it without leaving the chat.
- **Visible work:** answers, thinking and tool activity stream into the panel.
  Actions display an approval with the actual command or target.
- **Background jobs:** accepted deployments and reboots keep running if the chat
  is closed. Use `/jobs` or `/jobs ID` in chat to inspect Axis jobs. They also
  appear in Atlas's activity panel.
- **One operations guard:** Atlas and Axis take the same per-PC lock, so they
  never change the same PC at once. An unknown outcome in either app blocks the
  PC in both until it is acknowledged where it happened: Atlas's Operation
  recovery, or by asking Axis after you inspect the PC. Atlas's package cleanup
  clears both apps' staging folders and keeps Axis's job logs.
- **One history and audit:** Axis deployments appear in Atlas's deployment
  history (marked Axis, with the Windows account), where Retry and Queue use
  Atlas's deployment. Every Axis approval decision is appended to
  `data/axis/state/audit.jsonl` before the change runs.
- **Memory:** ask Axis to remember a fact (or forget one). After your approval it
  saves a line in `data/axis/state/MEMORY.md`, shared by the browser chat and the
  Axis terminal; open chats receive changes with their next request. The chat's
  **Memory** panel lists facts and forgets one after confirmation; `/memory`
  shows the file, which you can also edit. Lines that look like passwords, keys
  or tokens are refused.
- **Chats come back:** the latest chat reappears after a page reload or an AA
  restart and continues where it stopped. The local Admin backend keeps the 20
  most recent chats in `data/axis/chats`; nothing is stored in the browser.
  Decisions show as history, so a saved approval can never be answered again.
- **Viewer stays read-only:** Axis execution is available only on the local
  Admin interface, not the LAN Viewer.

The Axis terminal, `axis\Start Agent.bat`, shares the same database, package
repository, jobs, locks and memory as the browser chat.

AA is a separate merged version. Existing Atlas and Axis installations remain
usable. The imported Atlas guide is [README-ATLAS.md](README-ATLAS.md), and the
Axis terminal guide is [axis/README.md](axis/README.md).

## Existing data and configuration

AA uses Atlas's usual database settings: `ATLAS_DB_PATH` takes precedence over
`database_folder` in `config.json`. To use your current database, point these
settings at that existing file/folder before starting AA. The imported Atlas
seed remains available for first-run setup. Runtime databases, logs, chat tool
outputs and model state stay outside the Git source files.

The selected database is also Atlas's writable database; Axis's directory lookup
and its check of Atlas's unresolved operations use read-only connections. Axis
writes only its own deployment rows into Atlas's deployment history. Keep your
normal Atlas backup process when moving or updating a database.

Optional Firecrawl setup remains available in `axis/Configure Firecrawl.bat`.
The key stays in your Windows profile. Public web tools retain Axis's restrictions
on sending private directory data to external sites.

## Updates

Download the new AA ZIP and extract it into a new folder. Stop the old AA first,
then reuse your model and `config.json`, and point the new copy at your existing
runtime database. Copy `data/axis/state` and `data/axis/workspace` only after
stopping AA if you want to retain saved jobs, memory, tool outputs and working files;
copy `data/axis/chats` to keep recent chats.
Keep the old folder until the new copy works. See [Updating AA](docs/updating-atlas.md).
The inherited Atlas updater is disabled for AA so it cannot replace the combined
app with standalone Atlas.

## Development

```sh
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
python tests/run_all.py
python -m unittest discover -s axis/tests -v
```

Tests use disposable databases and simulated Windows operations. See
[SOURCES.md](SOURCES.md) for the imported commits. The release includes
`BUNDLE-COMMIT.txt` and a SHA-256 checksum to identify and verify its source.
