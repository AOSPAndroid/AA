# AA — Atlas + Axis

Atlas's office map and Windows tools, with local Axis chat in the same application.

**[Download AA for Windows](https://github.com/AOSPAndroid/AA/releases/latest/download/aa-windows.zip)**

## Start

1. Verify the release checksum and extract the ZIP.
2. Install Python 3.12 and, if necessary, run `windows\Install_Dependencies.bat`.
3. Put your existing full GGUF model in the AA or `axis` folder.
4. Run **Start AA.bat** under your DSK account. Use **Ask Axis** on the map or console.
5. Run **Stop AA.bat** to stop this installation. Finish accepted remote jobs first.

Model weights and API keys are not included. CPU/Vulkan llama.cpp runtimes are bundled.
AA can reuse an existing model server; it stops only a model process it owns. If a model
is missing, the map remains usable and chat reports the missing connection.
`axis\Join Model.bat` joins downloaded model parts with checkpoint and checksum checks.
`"Start AA.bat" --model flash-abliterated` selects a supplied model variant; see
`axis/models.json` for all model definitions.

## Your workspace

The distributed database and seating names are **fictional examples**. Import your own
reviewed directory, package/VDI exports and seating through **Manage Database**.
Existing installations keep their existing data; no startup replaces it with the demo.

Choose one stable workspace folder in `config.json`:

```json
{"runtime_folder": "F:\\AA-Workspace", "share_viewer": false}
```

`AA_DATA_HOME` overrides that folder. Legacy `database_folder` is still supported;
`ATLAS_DB_PATH` overrides the main database file. The default workspace is `data` beside
AA. Databases, chats, memory, skills, clipboard/companion state and logs use the resolved
workspace. Explicit collector folders remain supported for cross-account integrations.
The health endpoint reports resolved paths.

Both Admin and Viewer bind locally by default. To share the **read-only directory** on
your network, set `share_viewer` to `true` or `AA_SHARE_VIEWER=1`. Sharing has no built-in
user authentication; use your normal authenticated network boundary where needed.
Axis, private inbox/clipboard collection and mutations stay in local Admin.

## Working in AA

- The map remains the homepage; desk selection supplies context, not permission.
- Axis and direct Admin changes share operation locks, identity checks and durable
  unknown-outcome guards. Inspect a target and acknowledge recovery before retrying
  an uncertain change. A reboot monitor observes ping, not application health.
- Tool activity and approvals stay visible. Thinking is off by default.
- Axis jobs remain visible in Atlas activity/deployments; accepted jobs outlive the chat.
- Browser and `axis\Start Agent.bat` use the same Admin-backed conversation engine.
- Approved memory, custom workflows and the latest 20 chats stay in the workspace.
- Knowledge Base holds Markdown support articles with sanitized previews and optional
  Mermaid diagrams. The unused Draw.io editor has been removed. Existing saved diagram
  data is preserved in your knowledge database and in workspace exports.
- Live Inbox, clipboard capture, AD, packages and Windows tools retain their existing
  explicit controls. Collectors running under another account retain their configured
  folder and permissions.
- The import folder stages exports and backs up the active database. Large removals
  require review. See the [database guide](docs/database-update-guide.md).

Mail storage defaults to 90 days / 10,000 messages. Normal reconciliation checks a
seven-day window. Set `AA_MAIL_RETENTION_DAYS`, `AA_MAIL_MAX_MESSAGES` and
`AA_MAIL_RECONCILE_DAYS` for your desired bounds. A stopped watcher can run once with
`python outlook_watcher.py run --once --repair` to reconcile its full retained history.
The search cache drops messages removed by retention at its next synchronization.

## Updating and recovery

Use a verified release ZIP and retain your workspace/model. Releases are immutable and
carry source and file manifests. See [Updating AA](docs/updating-atlas.md) for workspace
export/import and the one-time migration from older split data locations.

Historical Git commits and previously published ZIPs are separate from the sanitized
current source. Their audience/removal must be handled in GitHub administration.
AA remains separate from the original Atlas/Axis installations and hosted Preview.
Sources and shared Axis provenance are in [SOURCES.md](docs/SOURCES.md).

## Development

```sh
python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run vendor:sync
npm run build:ui
npm run format:check
python tools/run_checks.py
python tests/run_all.py
python -m unittest discover -s axis/tests -v
```

The supported server entry point is `python -m uvicorn backend.factory:create_app --factory
--host 127.0.0.1 --port 8770 --no-proxy-headers` (one line). It prepares the runtime and
runs migrations during lifespan startup. Importing the routes never writes the source
seed. Tests use disposable databases and simulated Windows transports.

CI rebuilds browser assets, checks their committed parity, format/lint/distribution policy,
then tests Linux and Windows, including an extracted-bundle smoke test. The release builder
reads `resources/runtime-manifest.json`; add runtime files explicitly when introducing them.
Rebuild fictional seed fixtures with `python tools/build_demo_seed.py NEW_FILE.db`.
