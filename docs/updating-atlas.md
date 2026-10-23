# Update AA

Use the [AA Windows download](https://github.com/AOSPAndroid/AA/releases/download/aa-windows/aa-windows.zip). Extract each release into a **new folder** and keep the previous folder until the new copy works. The inherited `Update-Atlas.bat` is disabled in AA because it updates standalone Atlas, not the combined application.

1. Finish active Atlas and Axis work: deployments, queues, imports, terminal commands and background jobs. Save open documents and drafts.
2. In Atlas Admin, use **Manage Database > Back up .db** to save a consistent SQLite snapshot. Keep the existing runtime folder, its `knowledge.sqlite3`, backups and local configuration.
3. Run **Stop AA.bat** from the old AA folder and check that shutdown succeeded before copying runtime files.
4. Extract the new ZIP. Copy your `config.json` and reuse your full GGUF model in the new `AA` or `AA/axis` folder. Model weights do not need to be downloaded again.
5. Set `database_folder` in the new `config.json` to the **existing runtime database folder**, using its full path. This also keeps Knowledge Base and other folder-based data together. `ATLAS_DB_PATH`, if set, overrides the main database path; check that it still names the intended file. Keep the old runtime folder at that path.
6. If you want saved Axis jobs and tool outputs, copy `data/axis` from the stopped installation. Do not copy `model-process.json` or process lock files. Chat conversations are held in memory and do not survive a restart.
7. Run **Start AA.bat** in the new folder under your DSK account. Check familiar people, desks, packages and Knowledge Base records, then open Axis chat. Keep the previous folder and backups until these checks succeed.

Do not copy `data/server.json` or `data/viewer-server.json` into the new installation. They identify processes owned by the old folder; the new launcher creates its own records. Preserve older installation-level `backups/` directories too. If you choose to move runtime data instead of reusing its folder, do so only after shutdown and update its configured path.

Never replace the live database with the root `office_atlas.db` distributed in the ZIP. That file is a first-run seed. Application updates do not require reimporting users, devices, packages or Citrix VDI records.

If startup fails, keep the error and startup log, stop the new copy, and retain both folders and backups while resolving it. [Database update and recovery](database-update-guide.md) covers imports and consistent backups. AA updates do not publish or replace Atlas's separate hosted Preview.
