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

The download includes the upstream Atlas seed data. Configure `ATLAS_DB_PATH` or
`database_folder` in `config.json` to use your current Atlas database instead.
Keep existing models, configuration and runtime data when updating. No model
weights or API credentials are bundled.

Use **Stop AA.bat** to stop AA's local services. Accepted remote deployment jobs
are independent of the browser chat and must be checked before retrying.

`BUNDLE-COMMIT.txt` identifies the source commit. The companion
`aa-windows.zip.sha256` verifies the download.
