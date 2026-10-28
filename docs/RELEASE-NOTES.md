# AA for Windows

Atlas's map and Axis chat in one application.

**Personas.** Save the software a role needs as a persona (for example *New
starter* or *Trader*) on the new **Personas** page, then install every package
on a machine in one click: from that page, or from **Install a persona** in the
Workspace deployment panel for the selected machine. Atlas checks the machine
and every package first and starts nothing if any is missing, then installs them
one after another through the queue with the usual locks, history and recovery;
follow or stop the run under Ongoing actions. Personas are saved in Atlas beside
saved scripts, not in the browser. Kits saved in this browser by earlier versions
can be imported once. The queue can still be saved as a persona. Demo shows the
page greyed out.

**Review fixes.** Model joins verify the existing prefix after an interruption,
recover their checkpoint and check the complete GGUF checksum before reporting
success. The import folder now waits for saved or locked files, retries
temporary read failures, ignores generic Name-only lists and refuses exports
that change while being read. Oversized exports are reported without stopping
the other imports. Shared model-join fixes also ship in standalone Axis.

**Bulk PC checks.** Axis can inspect preflight, overview or disks for up to 50
explicit PCs, using at most eight readers and reporting each PC's result or
error. AA uses Atlas's own checks. Every target is validated before any read;
private inbox or clipboard context still requires approval for outside targets.
The bundled PC-health skill covers this in both AA and standalone Axis.

**Bulk service actions.** Start, stop or restart one named service on up to 50
explicit PCs after one approval listing every target. Each PC keeps its own
lock, service-identity and protected-service checks. Pending or unknown changes
are reported separately and never counted as successes. AA uses Atlas's service
controls; the same workflow and regression coverage ship in standalone Axis.

**Import folder.** Save the users, devices, Citrix and package exports in
`C:\AtlasXL` and Atlas imports them within a minute, each with its usual backup.
Files are recognised by their columns. A users and devices snapshot that would
remove more than 10% waits for review in Manage Database > Import folder.

**Quieter Axis chat.** Each tool call now collapses to a one-line summary you can
expand for its full request and result, and **Thinking** is off by default with a
header toggle (it resets off for each new chat). Turn it on for a hard problem.
Existing saved chats keep their history when upgrading or changing this toggle.
Collapsed tool cards show errors and batch results without opening their details.

**Admin and Demo match.** Demo now shows the same map, desk inspector, menus and
console pages as Admin, with changes greyed out instead of hidden or replaced.
The top left reads **Atlas**, and **Ask Axis** is a floating button in the
bottom-right corner of every page (greyed out in Demo). The chat opens when you
ask Axis; the map opens on the desk inspector.

Download **aa-windows.zip**, extract it, place your existing full model in `AA`
or `AA/axis`, then run **Start AA.bat** under your DSK account. Python 3.12 and
Atlas's existing dependencies are required; use `windows\Install_Dependencies.bat` if
they are missing. CPU and Vulkan llama.cpp runtimes are included.

The local Admin map and console pages include Axis chat with streamed tool
activity and action approvals, and optional model reasoning. Axis works on Atlas's own operations: its
deployments are Atlas deployments, shown in Deployments and history and marked
Axis; its reboots use Atlas's reboot monitor; and Atlas's own checks and per-PC
guard apply. Axis reads Atlas's active database and package repository,
remembers approved facts, finds desks on the map and keeps recent chats.
**Ask Axis** on a Live Inbox message or a clipboard capture attaches it as
untrusted evidence. The Clipboard has its own page. `axis\Start Agent.bat` opens
a terminal onto the same Axis while AA runs. The LAN Viewer remains read-only.

Axis includes ten reusable Atlas workflows for directory/desk lookup, PC health,
performance triage, deployments, services/processes, AD access, inbox/clipboard
triage, job recovery and Knowledge Base drafts. Use `/skills` to list them or
`/skills pc-health` to read a guide. Custom guides live in `data/axis/skills`;
see `docs/axis-skills.md`. Skills retain the existing approvals and PC guards.

This release also includes the Live Inbox first-click expansion fix and the
shared Axis model/launcher improvements: `flash-abliterated`, verified model
parts and reuse of the original Flash model's identical second GGUF. Select a
model at AA startup; the browser and terminal then use that same model.

The download includes the upstream Atlas seed data. Configure `ATLAS_DB_PATH` or
`database_folder` in `config.json` to use your current Atlas database instead.
Keep existing models, configuration and runtime data when updating. No model
weights or API credentials are bundled.

Deployments now wait for the installers a script starts, including ones it hands off before returning, and for Windows Installer, before reporting. The deployment shows what it is waiting for and then lists the software that was newly registered, removed or updated. More Qwen3.8 models can be selected in Axis: `35b-distill`, `27b-iq3`, `27b-abliterated`, and the 27B at 8 or 16 bits (`27b-q8`, `27b-bf16`) for PCs with a large graphics card or plenty of memory.

`axis\Join Model.bat` joins a model's downloaded parts on its own, without starting AA. It checks every part, and names any that are missing, still downloading, renamed by the browser or the wrong size.

Use **Stop AA.bat** to stop AA's local services. Accepted remote deployment jobs
are independent of the browser chat and must be checked before retrying.

`BUNDLE-COMMIT.txt` identifies the source commit. The companion
`aa-windows.zip.sha256` verifies the download.
