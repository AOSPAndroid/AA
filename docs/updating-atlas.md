# Update AA

Download the [latest AA release](https://github.com/AOSPAndroid/AA/releases/latest).
Verify `aa-windows.zip.sha256` before extracting into a new installation folder.
`BUNDLE-COMMIT.txt` identifies the source; `BUNDLE-MANIFEST.json` lists the shipped files
and their SHA-256 digests. Release tags identify immutable source commits.

1. Finish deployments, queues, imports and terminal jobs. Save open articles.
2. Run **Stop AA.bat** from the old installation. Confirm it stopped successfully.
3. Keep your existing workspace and model files. Copy `config.json` to the new installation.
4. Set `runtime_folder` in the new config (or `AA_DATA_HOME`) to the existing workspace.
5. Run **Start AA.bat** from the new installation. Check your directory, desks,
   knowledge articles, saved chats and packages before removing the old installation.

The distributed database contains fictional examples. Never replace your live database
with the root `office_atlas.db` from a release.

## Moving or backing up the workspace

While AA is stopped:

```sh
python runtime_workspace.py export F:\Backups\aa-workspace.zip
python runtime_workspace.py import F:\Backups\aa-workspace.zip --dest F:\AA-Workspace
```

Use the same environment/configuration for export as for starting AA. Export snapshots
SQLite databases consistently, includes chats/memory/skills and working files, and omits
logs, process records and locks. Restore requires a new destination folder. Set
`runtime_folder` to that destination before starting the new copy. Keep the backup private.
Models and the installation's `config.json` are separate; keep them alongside the backup.
An explicit `ATLAS_DB_PATH` database is included as `office_atlas.db` in the export, even
when it is outside the runtime folder. After restoring, clear the old override to use that
restored database. Export does not collect unrelated external folders or account-specific
collector queues automatically.

## Migrating an installation from before runtime-folder support

Earlier versions split state between the configured `database_folder` and the old
installation's `data/axis`. After stopping the old version, make a workspace backup and:

- Keep the active database, `knowledge.sqlite3`, `scripts.json`, clipboard/companion files,
  seating/import settings and backups from the existing database folder.
- Copy the old `data/axis` into the workspace's `axis` folder, including `state`, `chats`,
  `workspace` and custom `skills`. Copy older installation-level `axis/state` into workspace `axis/legacy-state` so its
  unresolved jobs keep blocking targets until acknowledged.
- Copy `data/inbox-integration.json` into the workspace if collectors are configured.
  Its explicitly configured cross-account mail folder stays where it is; preserve its ACLs.
- Do not copy `server.json`, `viewer-server.json`, `model-process.json` or lock files.
- Preserve existing mail queues from their configured folder. New, unconfigured collectors
  use the workspace's `mail` folder. An existing default profile queue remains discoverable
  until you explicitly migrate it.

`AA_DATA_HOME` takes precedence over `runtime_folder`, then the legacy `database_folder`.
Without these, `ATLAS_DB_PATH` supplies the workspace's parent, or AA uses `data` beside
its installation. `ATLAS_DB_PATH` can still override only the main database file. The
health endpoint reports resolved locations for checking configuration.

The retired Atlas updater cannot replace AA. Compatibility start/stop shortcuts forward
to AA. No AA change deploys over standalone Atlas, standalone Axis or the hosted Preview.
