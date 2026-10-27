# AA for Windows

Atlas's map and Axis chat in one application.

Download **aa-windows.zip**, extract it, place your existing full model in `AA`
or `AA/axis`, then run **Start AA.bat** under your DSK account. Python 3.12 and
Atlas's existing dependencies are required; use `Install_Dependencies.bat` if
they are missing. CPU and Vulkan llama.cpp runtimes are included.

The local Admin map and console pages include Axis chat with visible thinking,
tool activity and action approvals. Axis works on Atlas's own operations: its
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

**Manage Database → Data folder** keeps users, devices, Citrix VDI and package data current from the exports you save in `C:\AtlasXL` (or `C:\AxisXL`), with no setup. Atlas recognises each file by its columns, imports new saves at start and every 15 minutes (or with **Check now**) with the usual checks and backups, and asks before a users-and-devices export that would remove many records.

The live floor plan follows the team's OneDrive-synced `PA-IT_shared\02_Current_plan` folder without setup. Both folders are built in, so nothing needs re-entering after an update; a folder saved on the card still takes precedence.

Use **Stop AA.bat** to stop AA's local services. Accepted remote deployment jobs
are independent of the browser chat and must be checked before retrying.

`BUNDLE-COMMIT.txt` identifies the source commit. The companion
`aa-windows.zip.sha256` verifies the download.
