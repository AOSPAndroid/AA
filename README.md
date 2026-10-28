# AA — Atlas + Axis

Atlas's map and tools, with Axis chat in the same application.

**[Download AA for Windows](https://github.com/AOSPAndroid/AA/releases/download/aa-windows/aa-windows.zip)**

## Start

1. Extract `aa-windows.zip`.
2. Put your existing full GGUF model in the `AA` folder or its `axis` folder.
   The model files remain separate; you do not need to download them again.
3. Run **Start AA.bat** under your DSK account.
4. Use the Atlas map, and **Ask Axis** (bottom right) for chat, in the same browser window.

Python 3.12 and Atlas's existing Python dependencies are required. The launcher
prefers `C:\devhome\tools\python3.12\current\python.exe`. If this Python does not
have Atlas's packages, run `windows\Install_Dependencies.bat` once. The Windows download
includes CPU and Vulkan llama.cpp runtimes, but no model weights or API keys.

The model catalogue also includes `flash-abliterated`. Select it with
`"Start AA.bat" --model flash-abliterated` after supplying its model files.
The launcher reuses Flash's byte-identical second GGUF, linking it under the
variant's filename when possible and copying it if linking is unavailable.
The [variant release](https://github.com/AOSPAndroid/Axis/releases/tag/qwen3.8-flash-next-gsq-rco-abliterated-q2-0)
contains the first file's 21 parts; its second file comes from the original
[Flash release](https://github.com/AOSPAndroid/Axis/releases/tag/qwen3.8-flash-next-gsq-rco-q2-0).

Use **Stop AA.bat** to stop this installation and the model it started. A model
server already running when AA starts stays under its original owner's control.
If the model is missing, the map still opens and chat explains how to start it.

## One workspace

- **Map first:** the Atlas map and desk inspector open on the homepage. The chat
  opens from **Ask Axis** and can be closed to return to the inspector.
- **Shared directory:** Axis reads the database Atlas is actually using and uses
  the same configured package repository.
- **Selected desk:** explicitly attach a desk to the chat when useful. Selection
  gives Axis context; changes still require approval.
- **Chat on every page:** the floating **Ask Axis** button in the bottom-right
  corner opens the same chat on the map and every console page. On Workspace,
  **Use current target** attaches the target PC.
- **New joiners and personas:** each desk's access requests come from the
  requests workbook in `C:\AtlasXL`; each persona adds the software that role
  needs. **New joiners** turns them into one checklist per person: the requests
  to raise in the portal, ticked off by ticket number, and the software installed
  on their machine in one click (also from Personas or the Workspace panel).
- **Clipboard page:** the Clipboard sits beside Workspace and Live Inbox. Each
  capture lists the machines, people, desks, tickets and IP addresses Atlas
  recognises, with their actions.
- **Ask Axis about a request or capture:** **Ask Axis** on a Live Inbox message or
  a clipboard capture attaches it to the chat. The Admin backend reads it by ID
  and gives it to Axis as a tool result: private, untrusted evidence, never your
  instructions. Axis can also list and read recent requests and captures itself.
  Once such text is in a conversation, every web lookup (shown in full), shell
  command, and PC or directory server outside Atlas needs your approval, so the
  text cannot leave through a search or a DNS lookup.
- **Desks from chat:** ask where someone sits or which desk a PC is at. Axis
  reads the floor-plan seating (stored plan, not who is in today), and each desk
  it finds has a **Show on map** button that selects it without leaving the chat.
- **Visible work:** answers and tool activity stream into the panel; each tool
  call collapses to one line you can expand for its full request and result.
  Actions display an approval with the actual command or target. **Thinking** is
  off by default for quick, quiet answers; the header toggle shows the model's
  reasoning for a hard problem and resets off with each new chat.
- **One engine:** Axis's Windows work is Atlas's own work. A deployment Axis
  starts is an Atlas deployment, with Atlas's checks, per-PC lock and
  unknown-outcome guard. It appears in the Deployments drawer and in history,
  both marked Axis, where Retry and Queue work as usual. Reboots use Atlas's
  reboot monitor. Service and process changes use Atlas's identity-checked
  actions, bound to the list Axis showed you. Inspections, packages, AD lookups
  and support tools use Atlas's own code too. Axis still asks for your approval
  first.
- **From chat to Atlas:** work Axis starts has **Show in Deployments** or **Show
  reboot monitor**, and PCs in its results have **Select in Workspace**.
  Accepted work keeps running if the chat is closed; `/jobs` lists Atlas's
  deployments and reboots.
- **One guard:** an unknown outcome blocks the PC until it is acknowledged after
  inspection, in Atlas's Operation recovery or by asking Axis. Jobs from earlier
  Axis versions keep blocking their PCs until acknowledged the same way.
- **One audit:** every Axis approval decision, from the map, a console page or
  the terminal, is appended to `data/axis/state/audit.jsonl` before the change
  runs.
- **Memory:** ask Axis to remember a fact (or forget one). After your approval it
  saves a line in `data/axis/state/MEMORY.md`, shared by the browser chat and the
  Axis terminal; open chats receive changes with their next request. The chat's
  **Memory** panel lists facts and forgets one after confirmation; `/memory`
  shows the file, which you can also edit. Lines that look like passwords, keys
  or tokens are refused.
- **Skills:** Axis has ten reusable workflows based on Atlas: people/PC lookup,
  desks, PC health, performance triage, deployments, services/processes, AD access,
  inbox/clipboard triage, job recovery and Knowledge Base drafts. `/skills` lists
  them; `/skills pc-health` reads a guide. Ask naturally, for example "Use
  pc-health to check this PC." Axis reads the relevant guide before using its
  existing tools. See [Axis skills](docs/axis-skills.md) to add your own.
- **Chats come back:** the latest chat reappears after a page reload or an AA
  restart and continues where it stopped. The local Admin backend keeps the 20
  most recent chats in `data/axis/chats`; nothing is stored in the browser.
  Decisions show as history, so a saved approval can never be answered again.
- **Import folder:** save the users, devices, Citrix and package exports in
  `C:\AtlasXL` and Atlas updates its database within a minute, with a backup
  first. A users and devices snapshot that would remove more than 10% waits for
  your review in Manage Database. See the [database update guide](docs/database-update-guide.md#easiest-the-import-folder).
- **Demo is Admin, greyed out:** the LAN Viewer (Demo) shows the same map,
  inspector, menus and console pages as Admin. Changes, live checks, deployment,
  Clipboard, Live Inbox collection and **Ask Axis** are visible but disabled;
  Axis execution is available only on the local Admin interface.

The Axis terminal, `axis\Start Agent.bat`, is another window onto the same
Axis: start AA first, and the terminal streams the Admin backend's chat, answers
approvals in the window and runs nothing itself. `--resume` continues the
latest chat, including one started on the map.

AA is a separate merged version. Existing Atlas and Axis installations remain
usable. The imported Atlas guide is [README-ATLAS.md](docs/README-ATLAS.md), and the
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
Copy `data/axis/skills` to retain custom workflow guides.
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
[SOURCES.md](docs/SOURCES.md) for the imported commits. The release includes
`BUNDLE-COMMIT.txt` and a SHA-256 checksum to identify and verify its source.
