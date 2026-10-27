# Updating Atlas databases

Admin and the local Demo share one local database. Import once to update both. Hosted Preview uses a separately published snapshot.

## Updating AA itself

Download the new AA release ZIP into a new folder. Finish Atlas and Axis jobs, back up the database in Admin, and run **Stop AA.bat** before moving configuration or runtime files. Reuse your model and `config.json`, and point `database_folder` at the existing runtime folder; `ATLAS_DB_PATH` overrides the main database path when set. The inherited `Update-Atlas.bat` is disabled in AA.

See [Updating AA](updating-atlas.md) for the complete steps, including preserving Knowledge Base, backups and optional Axis job/output history. Do not copy the old installation's process ownership records. You do not need to reimport directory or package data for an application update; the import instructions below change database content separately.

## Data locations

- Live database: `data/office_atlas.db` after first launch. `ATLAS_DB_PATH` overrides this when configured.
- Root `office_atlas.db`: distributed seed, copied only on first launch. Replacing it does not refresh an existing runtime database.
- Automatic import backups: `backups/` beside the active database, normally `data/backups/`.
- Calendar, Notes and Reminders: browser-local storage, separate from SQLite.

## Easiest: the import folder

Save the exports in **`C:\AtlasXL`** and Atlas imports them by itself within a minute. No upload, preview or `APPLY` is needed for a normal update.

| Export | Example file | Import |
| --- | --- | --- |
| Users | `sys_user.csv` | Users & devices, together with the devices export |
| Devices | `alm_asset.csv` | Users & devices, together with the users export |
| Citrix VDIs | `SingleSessionMachines.csv` (or `.xlsx`) | Citrix VDI data, default mode: VDIs in the file are replaced, others kept |
| Packages | `u_cmdb_software_package.csv` | Package data: rows are added or updated, none removed |

- Atlas recognises each file by its columns, so names such as `SingleSessionMachines (1).csv` work. When several files are the same kind, the newest one is used. Other files in the folder are listed and left alone.
- Each import is the same as the matching Manage Database section, with the same backup in `backups/` and the same import history and restore. Users and devices go first, so Citrix links match the new directory.
- **Users and devices are a complete snapshot**, as described below: people and devices missing from the exports disappear from directory search. With **Ask before large removals** on (the default), a snapshot that removes more than 10% of the users or devices waits in **Manage Database > Import folder** with its counts and warnings; choose **Back up and apply** or **Skip these files**. Atlas also waits while deployments or queue jobs run, and for a file saved less than 30 seconds ago.
- A file Atlas cannot import is shown with the reason and is not read again until you save it again. **Check now** retries straight away.
- Imported files are read again only once they change. Overwrite the files with new exports, or add new ones; you do not need to delete anything.
- Change the folder, or turn the folder off, in **Manage Database > Import folder**. The setting is kept in `import-folder.json` beside the database. Demo and hosted Preview never import.

## Recommended: Admin import

After updating Atlas, restart local Admin and Demo before importing so both load the current workbook support.

1. Obtain the **complete intended directory snapshot** from your approved ServiceNow exports. Export all intended rows, not just the visible page. Keep the agreed location and machine filters consistent. A partial extract can remove other accounts from directory search.
2. Keep the two exports as they are: the **users** file and the **devices** file, `.xlsx` or `.csv`. You can select both together in step 4 (Ctrl-click, or drag them onto the Users & devices card); Atlas works out which is which from the headers and combines them itself. One `.xlsx` with worksheets named **users** and **devices** (or **Users** and **computers**) still works too. Names are case-insensitive; use one user sheet and one device sheet. Keep the original headers, columns and rows: no duplicate cleanup is required. Users require `user_name`, `name` and `email`; devices include `ci` or `name`. If both CI and name columns are present, Atlas prefers the CI and uses a nonempty name when the CI is blank. Other aliases use the first nonempty column.
3. Finish active deployments and queue jobs. Open local **Admin**, then **Manage Database**. Demo and hosted Preview cannot import.
4. Select both exports (or the workbook) and click **Validate and preview**. This creates a separate candidate without changing the live directory.
5. Review added/removed users, machines and assignments, automatic duplicate handling, column coverage warnings, and missing desk accounts. Unexpected large removals usually indicate incomplete exports or changed filters. Discard the preview if necessary.
6. Tick **This is the complete intended directory snapshot, and I have reviewed the removals**, type `APPLY`, then click **Back up and apply**. Atlas creates a full backup first.
7. Search known people and machines, verify assignments, and review missing desk links. Reload or use **Refresh records** in both local layouts and Demo.

The directory is a full snapshot replacement, not an incremental import. Accounts absent from it disappear from directory search. Desk positions, edited labels, confirmed account links, package catalogue and operation history stay in place. Retained desk links to missing accounts need review.

The devices export accepts `ci` as hostname and `model` as model; `assigned_to` and `serial_number` already match. The user headers `u_organisational_unit`, `u_business_unit`, `u_start_date`, `manager`, `location`, `title`, `u_job_type` and `employee_number` are supported unchanged. Atlas retains every original column, including device `asset_tag`, `model_category`, `cmp_last_used`, `install_status`, `assigned`, `display_name` and `location`, in the directory and export details. Compact device badges show Laptop, Desktop or iPhone, Assigned/Unassigned, asset state and Last used when supplied. `assigned` is the assignment date; `cmp_last_used` is the recorded usage date. Numeric Excel dates are converted, while the original cells remain in the archive. Asset state is not substituted for operational status or proof that a device is online.

Phones are searchable inventory and can link to their assigned users. Generic or blank CI labels such as `iPhone` do not merge separate phones: Atlas uses the CMDB `sys_id` when supplied, otherwise serial number, asset tag, or a meaningful CI. These identifiers have separate inventory namespaces, independent of the device category; changing a phone's category does not create another asset. They are inventory IDs, not invented Windows hostnames. With no identifier, each mobile row receives a separate source-row ID scoped to that extract. Row IDs can change with a new extract, so include serial numbers or asset tags when available. The original CI remains searchable (also using `source_ci:`), appears in device details, and is retained with the model, asset tag, serial number and location in export details. Atlas disables PC deployment, health and Windows remote actions for recognized phones/tablets/Macs, including when their original CI is entered manually. Laptops and unassigned Windows computers remain usable as PC targets. This does not provide iPhone management or MDM deployment.

Duplicate accounts and device identities are consolidated automatically. When values differ, the row with the newest `sys_updated_on`/`updated_on` timestamp wins; otherwise the last row wins. The winning row replaces the record as a whole, including blank assignments, rather than carrying forward stale values from an older duplicate. All original rows and columns remain in the source archive. Export details open the selected row and show the number of retained source rows. The preview reports reconciliation counts and examples; duplicate names belonging to different user accounts remain separate and ambiguous name references are not linked automatically.

Blank `assigned_to` does not discard a named device. References match a unique user account, email, employee number or full name. Windows device rows without a `ci`/`name` hostname are retained in the source archive and reported in the preview, but do not create remote targets. Atlas does not invent a Windows hostname from an asset tag or serial number. Keep a Computers export's discovery and last-logon columns if those details are required; fields absent from a replacement snapshot are not carried forward.

## Matching users and machines

Exact accounts, email addresses and employee identifiers take priority over display names. A supplied account domain is respected: an account in `CLIENT` is not automatically linked to a known account in `INTRANET`. The existing G-number/X-number convention remains supported, but separately exported accounts remain separate when an alias could refer to either person. Duplicate names and ambiguous identifiers offer a choice instead of selecting someone automatically. Search prefixes such as `email:`, `name:` and `brid:` restrict the corresponding field.

Assignment records can use a unique full name when no exact identifier matches. Inventory last-logon references use the same identifier priority and may fall back to a unique exact full name for compatibility with historical exports. Ambiguous names remain unlinked, and domain-qualified accounts or email references never fall back to display names. Workspace device cards identify assignment, Citrix assignment and inventory last-logon relationships separately. These exports describe recorded relationships, not live sessions.

A unique short hostname can find its exported fully qualified hostname, including an optional trailing dot. If multiple exported machines share that short name, choose the intended machine first; Atlas does not choose a Windows target for you. Machines without assigned users remain searchable and usable when they have a supported, unambiguous Windows hostname. Shared Citrix VDIs appear on each uniquely matched assigned user's profile.

Users without a login or email use their supplied source ID or employee number. With neither available, Atlas preserves each row under an extract-scoped key instead of merging people by name or reusing a row number across extracts. Placeholder values such as `(empty)`, `null`, `unassigned` and `-` do not become identifiers.

After this matching update, restarting Admin refreshes derived account aliases and imported relationships once while preserving source records and confirmed desk links. If an older import already consolidated distinct people or assets, reimport the original workbook once to recover those separate records. An ordinary code update does not require a new import.

Validation covers the original directory template and the users/devices export, source-column retention, unique assignment matching, duplicate identities/aliases, preview/apply/backup guards and Demo restrictions. A synthetic scale check imported 300,000 named devices plus one archived device without a hostname; it does not establish performance for a particular production export. The Admin preview was also checked at 390, 768 and 1366 px. The hosted read-only snapshot is separate and unchanged by importer updates.

## Standalone refresh

Finish active jobs, then drag the intended new `.xlsx` workbook, or the users and devices exports together, onto **windows\Refresh-Directory.bat**. It stops both local services, validates the file, displays counts and asks for `APPLY`. A full backup is saved beside the active database in `backups/`, normally `data/backups/`. Start either edition again afterwards, even if you cancelled the import.

Always supply the new file. With no file argument, this script uses the older bundled `database040926.xlsx`.

For validation only, run from the repository root:

```powershell
py -3.12 refresh_directory.py --source "C:\Data\Europe-export.xlsx" --check-only
```

This does not apply changes. Do not run a direct CLI refresh concurrently with servers using the same database.

## Restore and back up

In **Manage Database > Import history**, choose **Restore directory before this import** and review the staged comparison before applying. This restores the directory while preserving current seating and deployment history; it is not a full application rollback.

**Back up .db** downloads a consistent SQLite snapshot. Keep one before updating AA or changing application files. Preserve the runtime database folder, `knowledge.sqlite3`, its backups, any older installation-level `backups/` directory and local configuration. Reusing that folder through `database_folder` keeps the data in place. If moving files, stop AA first and follow [Updating AA](updating-atlas.md); do not carry `data/server.json`, `data/viewer-server.json` or model process ownership records into another installation. Never replace your runtime database with the distributed seed or copy a running SQLite database as an ordinary file.

## Live floor plan (the assistants' Excel)

**Manage Database > Live floor plan** links official seating to the desk plan the administrative assistants keep in Excel. Enter the folder once, for example the OneDrive-synced `...\PA-IT_shared\02_Current_plan` (quotes from "Copy as path" are fine), tick **Live link on** and click **Save**.

- Atlas checks the folder every minute and uses the newest `.xlsx` with a tab per floor (`R+2`, `+3`, `Floor 4`…) that contains desk codes; without such a workbook, the newest one with desk codes. Other workbooks in the folder (New Joiners, Headcount files) are skipped. A file saved less than 30 seconds ago is read on the next check.
- Every visible tab is read; hidden tabs (older copies of a floor) are skipped. When a desk appears on several tabs, the tab for its floor wins (`R+4 (FINAL)` for `04R…` desks), then tabs that name no floor (`Desk Mapping (FINAL)`), and tabs named old, draft, copy or v2 come last. Only two tabs of the same standing that disagree hold the update. List tabs are read row by row: a header such as **Desk** / **Desk number** with a person column (**Name**, **Person assigned**, **Assigned to**, **Employee**…) or a **Team** column; without headers, the cell beside a desk code. A code on another floor's tab (`02R…` on `R+4`) is listed for checking.
- Each box with a desk code becomes a desk: a name that matches exactly one directory person (word order, case and accents ignored) is linked to that person and their machines. Atlas also accepts shorter names that identify one person, uses the Paris location to resolve duplicate names where possible, and recognises close spelling matches among Paris staff when there is no close second match. These matches are listed for checking. "Open" or "Vacant" written in the box frees the desk. A desk code with nothing written beside it is left as it is and listed. Anything else ("Credit Sales", "Private Office (209) … GCAS (…)", someone not in the directory) is shown exactly as written. A code typed without its leading zero (`2R017069`) is corrected to `02R017069` and listed.
- **The Excel is the authority.** What it says is applied as written, with a backup, and open maps (Admin and Demo) refresh within a minute. Nothing in the plan blocks an update: a person on two desks is shown on both, a name Atlas cannot link to one account is kept as written, a person the plan places elsewhere leaves desks the plan does not mention, and each case is listed under **notes** on the card. The map footer names the plan and its time.
- **Ask before large changes** (on by default): a save that changes more than the greater of 40 desks and 15% of the plan, or puts two different names on the same desk, waits for review first. Turn it off and every save reaches the map straight away. The card lists the changes; click **Apply these changes**, or correct the Excel and Atlas reads it again. Approval applies only to the proposal you reviewed; if it has changed, Atlas asks you to review it again.
- Desks the plan does not mention are left as they are. Desk codes not on the map are skipped and listed.
- The card lists **people on more than one desk now**, read from the database each time it refreshes (or says there are none). When the plan places someone, any other desk holding their account, or only their name, is freed; what remains is where the Excel itself lists a person twice.
- The card shows what was read: the tabs and how many desks each gave, hidden tabs skipped, corrected codes, names not matched to one person, unknown codes and bare codes. The ten most recent live-plan backups are kept in `backups/`.
- **Undo** next to a recent live update restores the names, teams, occupancy and account links of the desks it changed, with a new backup. Newer desk details such as notes, equipment and map positions are kept. If restoring an older update would duplicate a person after a later move, Atlas leaves the data unchanged and asks you to resolve the seating conflict. Atlas then leaves the map alone until the plan is saved again; click **Check now** to read the current plan straight away.
- After an Atlas update that changes how plans are read, the current plan is read again on the next check.

## Seating updates

Use the separate seating Excel or Desk moves tools in Manage Database. A directory import does not automatically remap desk assignments. See [IT operations and imports](operations.md) for templates and preview steps.

## Hosted Preview

Local imports update local Admin and Demo in **both editions**, but do not automatically update hosted Preview. Its snapshot must be deliberately exported, reviewed for the intended audience and republished through the preview deployment workflow. Both hosted layouts use that same snapshot.

Do not upload the complete live `.db` to the public site or commit runtime databases and backups to GitHub. The Preview shortcut opens the hosted site; it does not synchronize local data.
