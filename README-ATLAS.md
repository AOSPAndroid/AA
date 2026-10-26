> **Atlas reference for AA:** This is the imported standalone Atlas guide. Use
> [AA's launch instructions](README.md#start) and [AA's update guide](docs/updating-atlas.md)
> for this combined application. The standalone launch, updater and hosted Preview
> instructions below do not replace AA's workflow; `Update-Atlas.bat` is disabled here.

## Live Inbox with Outlook and Teams

**[Live Inbox setup](docs/inbox-integration.md)** connects incoming Outlook emails and Teams/Outlook notification previews to the existing Atlas GUI, sender lookup and linked machines. Configure the normal mail account once in Atlas Admin > Live Inbox. All local Start BAT files then launch the collectors through its limited interactive Windows task; Stop BAT files request graceful shutdown. Start/Stop, source switches and listener settings are also in the GUI.

Run **[Install-Inbox-Collectors.bat](Install-Inbox-Collectors.bat)** once in the normal mail account with an approved signed notification package. Windows notification consent is still required. The repo includes the build source, a compiled development folder and an unsigned MSIX for the approved signing process. Demo and Preview never receive email or notification data.

## Launch Admin, Demo and Preview

Double-click **[Start-All-Atlas.bat](Start-All-Atlas.bat)** to start the local services once and open three browser tabs: Admin, Demo and the hosted Preview (which needs internet access).

**[Stop-All-Atlas.bat](Stop-All-Atlas.bat)** stops both local servers. Finish active jobs first. It leaves browser tabs open and does not unpublish hosted Preview.

## Quick start and stop

| Start Admin + Demo | Stop local services |
| --- | --- |
| [Start-Office-Atlas.bat](Start-Office-Atlas.bat) | [Stop-All-Atlas.bat](Stop-All-Atlas.bat) |

Start runs Admin and Demo. Stop stops both; finish queue jobs first. Hosted Preview stays online. (The optional Desktop layout with a dock and draggable windows was removed; old Desktop shortcuts open normal Atlas.)

**[Database update guide](docs/database-update-guide.md)** covers imports, backups, recovery, seating and hosted Preview updates.

**[Update-Atlas.bat](Update-Atlas.bat)** updates this installation from GitHub while preserving its data and settings. Install Git for Windows once, finish active jobs, then run it from your existing Atlas folder. [Update instructions](docs/updating-atlas.md) cover ZIP installations, backups and checks.

**[Latest code audit](docs/code-audit-2026-10-06.md)** records the confirmed fixes, regression coverage and large-directory measurements.

# Atlas 7.0.0

**One workspace to find people, locate equipment and get IT work done.**

Atlas is a self-hosted Windows IT support and administration tool with a browser interface. It connects interactive office floor plans, directory users, machine inventory, application deployment and remote administration. Start with a colleague, a computer or a desk, then follow the links to the information and actions you need.

The **map** helps you explore floors and seating in 2D or 3D. The **IT console** brings user lookup, linked machines, health checks and deployment into one workspace. Both share the same command palette, package catalogue and detail panels. A separate **read-only demo/viewer** now includes the full IT console alongside maps, people and stored machine details.

## What Atlas can do

**Live Inbox:** emails and Teams/Outlook notification previews, matched sender records and linked machines inside the main Atlas GUI. Start/Stop collectors, choose sources and open listener settings from the same screen. The message comes first with the machines and people it names highlighted; people named in the email ("DUPONT Marie", emails, account IDs) are matched to Atlas with their desk and PCs. Their record, health, performance (with End process), AD groups with "same access as" comparison, deployment, software, services, articles, MSRA/C$ and reboot run in a tools column beside the message, and anyone else is one lookup away, without leaving Live Inbox. See [the message and its people](docs/inbox-integration.md#the-message-and-the-people-in-it) and [request tools](docs/inbox-integration.md#request-tools-everything-beside-the-message). Suggested fixes are not yet included.

**New to the performance tools?** Read the [Remote Admin performance guide](docs/REMOTE_ADMIN_PERFORMANCE.md) for what each CPU, GPU, Memory and Overview button does, how to interpret the results, and a practical slowness investigation workflow. All scans require an explicit button click.

**Atlas Companion:** a small tray app you run in your normal Windows account (Atlas Admin stays elevated). It sends every clipboard copy to the clipboard history, even with Atlas closed, skipping copies password managers mark private, and reads classic Outlook mail for Live Inbox when Email watcher is on. Run **Install-Atlas-Companion.bat** once as yourself; then it starts at sign-in or with **Start-Atlas-Companion.bat**. [Details](docs/companion.md).

**Clipboard history:** the **Clipboard** button in the header keeps what you copy into Atlas (Capture clipboard, Ctrl+V on any page outside text boxes, the Live Inbox clipboard reader and, when the browser allows the clipboard, automatically as you come back to Atlas). Each item is enriched from the database: machines with their user, model and inventory status, people (by email, account or unique name), desks with their occupant, ticket numbers and IP addresses, plus copied names Atlas does not know. Coloured chips summarise each item; its tables give **Select**, **Open** and a right-click menu with the usual tools, and bulk actions for lists: **Bulk deploy**, **Run a script**, **Ping all**, copy names/users/emails. Copying the same text again moves it to the top. The last 300 items are kept in `data/clipboard-history.json` (or the database folder); **Delete** or **Clear** removes them.

**Retry and re-queue deployments:** every deployment now saves its full request (package, script, action, fresh copy, threads). A failed run shows **Retry**, **Add to queue** and **Copy log** under its progress in the Deploy panel; **Add to queue** and **Open queue** sit under the Install button; failed cards in the Deployments drawer and failed rows in **History** have **Retry**, and any single deployment can be queued again with its original options.

**Read from screen and clipboard:** at the top of Live Inbox, **Clipboard** reads copied text or a Win+Shift+S screenshot (text recognition) through the browser, and **Ctrl+V** on the page does the same with no permission. Run **Allow-Atlas-Clipboard.bat** once, as yourself, so Edge and Chrome stop asking. [Details](docs/inbox-integration.md#read-from-screen).

**Live floor plan:** Point **Manage Database > Live floor plan** at the folder holding the assistants' desk-plan Excel (for example the OneDrive-synced `02_Current_plan`). Atlas reads boxes such as `Christophe Duriez 02R015079`, `Credit Sales 02R016079` or `Open 03R016079` every minute, links names to directory people, fixes codes missing their leading zero, and updates official seating with a backup; Admin and Demo maps refresh on their own. Large or unclear changes wait for review. [Details](docs/database-update-guide.md#live-floor-plan-the-assistants-excel).

**Scripts:** Open **Scripts** in the IT console sidebar to run PowerShell scripts against a list of machines. The page opens on **Online check** and runs nothing until clicked. Paste the machines (from Excel, comma or line separated), pick a script, review its values and click **Run**; each result line shows green (OK), red (failed) or amber (warning) with a count at the top. Built-ins: stop and disable services, enable and start services, check services, stop processes by name, online check, uptime, disk space, who is logged on, find installed software, Group Policy update and restart. Service and software names start blank and must be supplied explicitly. **Duplicate** a built-in, or use **New script** / **Import .ps1**, to save your own; saved scripts live in `data/scripts.json` (or the configured database folder). **Download .ps1** includes the helper functions: built-ins accept `-Computers` and their task parameters, while custom scripts retain their own parameter blocks and normal PowerShell prompts. Atlas adds the machines as `$Computers` (and `Read-Host` answers with them inside Atlas), checks every machine name first, and asks before running built-ins that change machines or custom scripts marked **Changes machines**. Scripts run on the Atlas host with the Atlas account's rights, up to 30 minutes.

**PsTools terminal:** Open **Scripts → PsTools commands** in the admin IT console for 72 templates covering PsExec and the adjacent Sysinternals tools, including Excel, sessions, diagnostics, networking, services, printing and repairs. Select a target and click **Run** to see live output and exit status in Atlas. Remote Command Prompt supports typed follow-up commands. Runs use the Atlas host account and your existing PsExec in `C:\Data`; repairs require target confirmation. Includes Stop, recent transcripts, favourites and optional command copying. Nothing starts automatically. [Setup, terminal controls and PsExec commands](docs/PSEXEC.md).

| Area | Capabilities |
| --- | --- |
| **Office maps** | Explore multiple floors in 2D and 3D, search desks and rooms, locate colleagues, and manage seating and directory links. |
| **People and machines** | Search directory and inventory exports; inspect accounts, organisation details, assigned machines, last recorded users and original export fields. |
| **Remote administration** | Check machine health and specifications, inspect software and resource usage, manage processes, list and start/stop/restart Windows services, and open Windows support tools. Remote actions use the host account's existing permissions. |
| **Application deployment** | Browse a package catalogue, select install/repair/uninstall scripts, deploy to individual targets or a bulk queue, and follow progress, logs and history. |
| **Data management** | Preview and apply directory imports, review export-column coverage, maintain seating records, and back up or restore the database. |
| **Shared viewer** | Host a separate read-only interface on the local network for maps, people lookup and stored inventory. Editing, deployment and elevated remote operations stay in the admin tool. |

Atlas runs from Python source with FastAPI and SQLite; the interface uses HTML, CSS and JavaScript. The Windows launcher starts the local admin service and shared viewer together. Runtime records live in a persistent database, while deployment packages stay in your configured package repository.

## Atlas 7: Admin, Demo and private preview

All three versions share the current map and full console: Workspace, Remote Admin, Bulk Deploy, History, PsExec and the package catalogue. Demo and the owner-private preview let you explore every console page, select stored machines, switch between Overview/CPU/GPU/Memory, and prepare or copy any of the 72 PsTools commands.

**Deployment, live metrics/health, remote tools and PsExec execution are greyed out** with an explanation: use Atlas Admin from an elevated Windows account. Demo remains read-only even if its host is elevated; its server has no remote execution routes and rejects all writes. The hosted preview has no Windows backend. Neither starts scans or commands when browsing. Real metrics, package-share contents, deployment history and terminal transcripts are not fabricated or copied into the preview.

Admin and Demo use the same console source. The hosted preview receives those same assets while retaining its private directory snapshot and existing owner-only access.

## Map previews

These are screenshots of the Atlas renderer using **entirely fictional floors and sample desks**, with name tags disabled. They contain no real names, accounts, hostnames, IP addresses, seating assignments or office-plan geometry. The layouts illustrate the interface and are not the actual office floors.

| 2D floor navigation | 3D floor exploration |
| --- | --- |
| ![Atlas 2D map with a fictional floor, sample desks and name tags disabled](docs/images/atlas-map-2d.jpg) | ![Atlas 3D map with a fictional floor, sample desks and name tags disabled](docs/images/atlas-map-3d.jpg) |

[How the screenshots are produced](docs/images/README.md) · [How to run Atlas](#how-to-run-windows) · [Configuration and updates](#configuration-and-updates)

## How to run (Windows)

### First-time setup

1. On this GitHub repository, select the **main** branch, then **Code → Download ZIP**.
2. Right-click the downloaded ZIP and choose **Extract All**. Open the extracted folder containing `Install_Dependencies.bat` and `Start-Office-Atlas.bat`. Keep all files and subfolders together and run the scripts from the extracted folder.
3. Install **Python 3.12** if it is not already installed, including the Python launcher (`py`). `Python_Settings.bat` detects it through `py -3.12`. If your organisation provides Python elsewhere, set `WMI_PYTHON` to that interpreter's full executable path.
4. Double-click **`Install_Dependencies.bat`**. Wait for **Dependencies installed** and press a key to close the window. This installs the Python packages listed in `requirements.txt` and needs access to your configured Python package index.
5. Double-click **`Start-Office-Atlas.bat`**. It starts both the admin tool and the read-only viewer, then opens two browser tabs.

**Normal startup: `Start-Office-Atlas.bat`.** Dependency installation is needed for the first setup, after changing Python, or when an update changes `requirements.txt`.

Git and Node.js are not needed to run the downloaded application. Git for Windows is required to use `Update-Atlas.bat` for future updates. The download includes the application, maps and initial directory database. Application installers used for deployment stay in your separate package repository. Atlas automatically looks for the synced **EPP_PACKAGE_REPO_BetaPackages - BetaPackages** SharePoint folder in business OneDrive; no repository setting is needed when that folder is available. Sync the SharePoint shortcut through OneDrive before deploying.

This is a normal project tree containing Python source, browser assets, floor plans, templates and tests. No TXT-to-Python extraction is needed.

If you already use Atlas, follow [Configuration and updates](#configuration-and-updates) to retain your live database and settings when updating.

After updating and restarting Atlas, refresh any open browser tabs. Console scripts and styles use versioned URLs, and admin pages revalidate cached files so an older console script cannot keep adding removed interface sections. API responses are not cached.

### Open and share Atlas

| Interface | Address | Access |
| --- | --- | --- |
| Your admin tool | `http://127.0.0.1:8770` | Local computer only; existing editing and IT operations |
| Shared read-only viewer | `http://YOUR-IP:8771` | People on your reachable network; full console, maps and stored directory lookup; execution disabled |

Use the host computer's Wi-Fi/Ethernet IPv4 address in place of `YOUR-IP`. The launcher prints candidate addresses and saves them in `data/share-addresses.txt`. Share the address belonging to the network your colleagues use. The viewer requires only a browser, not Python or Windows elevation on their computers.

**`Stop-All-Atlas.bat` stops both servers.** Finish active deployments before stopping. Starting again reuses this folder's running servers. Occupied ports fail with an error rather than attaching to another installation. Closing a browser tab does not stop hosting.

To change ports, set `ATLAS_ADMIN_PORT` and `ATLAS_VIEWER_PORT` before launching; they must be different. Logs are in `logs/admin-startup.log` and `logs/viewer-startup.log`.

### If startup fails

- **Python 3.12 not found:** install Python 3.12 with the launcher, or configure `WMI_PYTHON` as described above.
- **Dependency installation failed / Dependencies missing:** rerun `Install_Dependencies.bat` and check its error message; dependencies must be installed for the same Python that starts Atlas.
- **Startup failed / port occupied:** check the startup log named in the error. If this folder has an unresponsive Atlas server, run `Stop-All-Atlas.bat` before starting again. If another application uses the port, choose different Atlas ports.
- **Browser tabs did not open:** try `http://127.0.0.1:8770` for admin or `http://127.0.0.1:8771` for the viewer after a successful startup.

## One command palette across Atlas, the IT console and the shared viewer

Press **Ctrl+K** (or **Cmd+K** on a Mac browser), or click **Search Atlas** in either header. Search people, machines, desk codes, teams and admin views in one place. Use arrow keys and Enter to open a result, and Escape to close.

Use `person:`, `machine:`, `desk:` or `>` to narrow results. In the IT console, person results open their details and linked machines in the Workspace, even when they have assigned desks; name searches prioritize directory people over desk matches. Explicit desk results open the map. From the map, people with a single mapped desk open there; multiple locations offer a choice. Unmapped people and machines open selected in the existing IT console. Name-only desk matches are identified as unconfirmed. Actions open the existing admin interface and keep its review/confirmation flow. Both admin views load the same component, isolated stylesheet and command catalogue. Commands belonging to the other view navigate there; selected machines carry across where available. Deployment, file-access and remote-operation commands open their existing controls for review. The shared viewer uses the same component, styling, keyboard controls and animation setting, with console navigation enabled and privileged commands shown greyed out. Its person and machine results stay inside the read-only viewer.

## Site information

Click the circled **i** near the lower-right edge of the map for the site VLAN reference and useful phone contacts. The panel has **VLANs** and **Contacts** tabs, with phone-number copying and call links. Search **VLAN** or **Contacts** in the shared command palette to open the corresponding tab from Admin, Demo or the private preview. In the IT console, the same panel opens without leaving the console. These are stored reference details; opening the panel makes no remote checks.

## Shared viewer

- Explore the same ten-floor 2D/3D map, search seating, inspect desk records, and export the displayed records.
- Use **Ctrl+K / Search Atlas** or **User lookup** to search the Europe-wide directory by name, account, email, BRID or machine name. Open a person to see their linked machines and mapped desks. Inspect a machine to see stored inventory, assignment/logon relationships, linked people and recorded desks; copy its stored report when needed.
- Both processes read the same runtime database (`data/office_atlas.db` by default). **Refresh records** reloads seating changes made in the admin interface; directory queries read the current database on each request.
- Read-only means no seating edits, imports, settings changes or deployment actions. Live remote health/software checks that use the host's privileges are unavailable. Stored inventory details remain visible.

The viewer is a separate FastAPI application with only explicitly registered read routes. It does not import or register the admin backend. SQLite is opened with `mode=ro` and `query_only`; mutation requests receive HTTP 403. Administrative GET endpoints, full-database downloads and server files are not served. The admin interface retains its loopback and same-origin checks. Browser controls are hidden for clarity; the server enforces the restrictions.

The host must remain awake and network-reachable. Windows Firewall or your organisation's firewall must allow inbound TCP on the viewer port (8771 by default). If colleagues cannot connect, check that rule and the selected network/IP; changing the admin bind address is unnecessary. The launcher does not change firewall policy. This is an unauthenticated internal viewer: anyone who can reach its port can read the displayed directory and maps.

## Machine details

The console, map and shared viewer use the same Atlas header, blue eagle branding and sidebar dimensions. The console keeps its Workspace, Remote Admin, Bulk Deploy and History navigation below the header. Map import, export and database backup actions are grouped under **More**. **History** colours each run by state, counts failures, filters by machine, package or state, and opens a machine in Workspace when you click its name.

Workspace keeps user/machine lookup and compact health on the left, with deployment on the right. Active Directory has its own navigation entry, searchable group list and comparison. Controls stay in their normal layout. Open the package selector to search or choose a favourite/recent package; Escape restores the previous selection. **Install / Repair / Uninstall** choose the action. **Advanced** contains threads, fresh copy, alternative execution modes and package checks. The left column scrolls on shorter screens; on phones, the columns stack and the **Deployment · hostname** control toggles deployment. Selection is retained when minimized, and clearing the target hides the panel. A job's compact status and expandable log appear only for its original target; failures open the log automatically.

**Package catalogue** opens the same dialog within the console or map, without navigating away. Browse packages, inspect scripts and edit display names or versions. Closing it returns to your current view and preserves the selected target and deployment form.

**Machines outside inventory.** Search a hostname (or `machine:HOSTNAME`). If no directory record matches, choose **Use hostname as target** in Search. Atlas selects the entered hostname and opens deployment tools without creating an inventory record or starting a deployment. Normal package/script checks and Windows permissions still apply. Demo and Preview allow selection while keeping execution disabled.

**Loading and responsiveness.** Bulk Deploy loads its independent package list when first opened, avoiding a duplicate catalogue scan during Workspace startup. Unchanged deployment and sidebar summaries do not redraw their controls.

**Quick health on machine selection.** Clicking a machine in the map or IT console refreshes ping, C$ access, C: storage/free space, last boot and Windows uptime. A short delay skips targets passed over quickly; clicking the same machine again refreshes these readings after the current check finishes. Automatically displaying a user's only linked machine does not start checks until you select it. **Scan health / Refresh health** explicitly collects the full health readings; specifications also wait for Scan health. CPU, GPU, memory, process/thread and slowness scans remain manual, with no periodic refresh. Demo and hosted preview keep live checks disabled.

The fixed **Current selection** sidebar keeps the selected user's name, account, email, team and office visible across console pages, including Knowledge Base. The device card shows its model, asset tag, inventory badges, existing connectivity/storage/uptime readings and check times. **Scan health** retrieves CPU, memory and Windows specifications manually; switching pages makes no additional machine requests. Click a user or device heading to return to its Workspace details. Phones show inventory information without Windows checks. On small screens the summary starts collapsed and retains the selected names; expand it for details. Demo and Preview keep live scans disabled. Navigation and deployment/queue controls share matching SVG icons.

Right-click a linked machine to refresh health, open Remote Desktop, Computer Management or Event Viewer, or use the existing copy, remote assistance, file, deployment and inventory actions. Actions use the right-clicked machine. The menu stays within the screen and scrolls when needed; use the mouse wheel or arrow keys, Home/End to reach the first/last option, and Escape to close it. Remote tools use the host computer's current account and existing access permissions.

Expand **Machine details** in the IT console, admin map or shared viewer to inspect the machine's stored export fields. Identity shows infrastructure category, manufacturer, model, serial number, correlation ID, record class and description when supplied. Ownership distinguishes the assigned person from the inventory's last logged-on user. Discovery shows the inventory status, discovery source and the discovery/update timestamps. Machine reports use the same fields.

Empty optional fields are omitted. An absent assignment or last user is labelled **Not supplied**. **Operational** is an inventory status, not proof that the machine is online; last logged-on user does not identify a current session. The current computers export does not supply CPU, disk capacity/free space, BIOS, Citrix registration or maintenance state. Available live specifications remain in the admin health/specifications tools.

## Use every directory export column

The included export supplies **14 person columns and 14 machine columns**. All are mapped to the directory database. Person details show **Department**, **Business unit** and **Organisation** separately. Excel serial values in **Last login time** display as readable dates and times; no timezone is inferred from the export.

Open **User details → All export fields**, or **Machine details → All export fields**, to inspect, filter and copy every field for that record. Original column headings, empty values and zero values remain inspectable. When an original value differs from Atlas's formatted or normalized value, both are shown. Fields are fetched only when this inspector opens, so ordinary searches and map animations do not download the source archive.

**User details** groups useful information into Organisation and Account activity. It shows the most precise recorded login, removes duplicate account/date values and omits empty fields. **Find manager**, **Same department** and **Same office** open a prefilled search in the shared palette; your current person remains selected until you choose a result. These shortcuts and the grouped details work in the console, map and demo. The console retains its domain-account display and copy action.

**Domain account** follows the confirmed Windows-login convention: an exported `G` followed entirely by digits uses `x` with the same digits for its login (for example, `G00123456` → `INTRANET\x00123456`). Other usernames and existing domain prefixes are preserved. The console, map and demo show the same derived login; console copies and support reports use it too. Searches accept either the original G identifier or the X login, including domain-qualified logins. The imported Account, Employee ID, original export values and stored relationships remain unchanged. If separate G and X records exist, Atlas asks you to select a result.

Search the console, shared command palette or viewer lookup using field prefixes:

| Find | Examples |
| --- | --- |
| Equipment identifiers | `serial:ABC123`, `asset:12345` (correlation ID); exact serial/correlation IDs also work without a prefix |
| Hardware and inventory | `manufacturer:Dell`, `model:Z2`, `class:computer`, `infrastructure:desktop`, `status:Operational`, `source:discovery` |
| Ownership | `assigned:account`, `last_user:account` (recorded inventory values) |
| Organisation | `team:Support`, `business:Technology`, `organisation:Operations`, `location:Paris`, `manager:Name` |
| Person details | `title:Engineer`, `worker:Permanent`, `start_date:2026`, `last_login:2026-09` |

The underlying directory field names and source column names also work as prefixes. Searches are case-insensitive, limited to 100 results, and treat `%` and `_` literally. Narrow broad searches for more specific results.

**Manage Database → Directory column coverage** shows each column, its populated row count and where it is used. The import preview includes the incoming coverage and warns when columns disappear. **Download all directory fields (.ndjson)** exports the complete stored snapshot, including additional worksheets and rows without a usable identity. NDJSON contains one JSON object per line, starting with the column inventory.

Directory imports now retain the original cell values, worksheet names, row numbers and column headings alongside the existing operational tables. Additional columns and worksheets are retained automatically. Duplicate or blank headings are preserved by column position; two headings that map to the same operational field are rejected to avoid overwriting a value. The archive preserves exported values, not Excel formatting or executable formulas; formula cells contribute their saved cached value. Existing databases without an archive still expose all stored fields and explicitly say that original cells require a directory refresh.

Archive replacement is part of the same database transaction as a directory refresh. Backups retain it. Restoring a pre-archive directory clears the newer archive so it cannot be mistaken for the restored snapshot. Seating records, history and deployment data keep their existing refresh protections.

The demo shares the person/machine inspector, date display and field searches. It serves the established 28 directory fields; newly encountered columns and the full archive remain in the local admin interface until their intended shared use is defined.

## Package states and ownership

Open **Packages** in the console, command palette or with `Alt+6`. Upload the ServiceNow CSV in **Database > Package data**. See [the package data guide](docs/packages.md) for headers, matching and update behavior.

## Configuration and updates

The default package repository is the synced **EPP_PACKAGE_REPO_BetaPackages - BetaPackages** SharePoint folder, inside **Shortcuts** or directly inside business OneDrive. Atlas checks `OneDriveCommercial`, the current account's registered business OneDrive folders, and the standard business OneDrive location. When running under a separate admin account, it can use the exact package folder from a loaded Windows profile if only one accessible match exists. It does not guess between multiple users' package folders.

Leave `package_repository` blank in `config.json` (as in `config.example.json`), or omit `config.json`, to use automatic detection. An explicit repository saved through admin **Settings** takes precedence; `WMI_PACKAGE_REPO` overrides both. These defaults do not sign in to SharePoint or create its OneDrive shortcut. Local configuration, logs, process records and SQLite journal files are ignored by Git.

To update application code, finish active jobs and run **[Update-Atlas.bat](Update-Atlas.bat)** from this existing folder. It backs up the installation, preserves local data/configuration, and converts a downloaded ZIP folder into a Git checkout on its first run. Later updates require a clean tracked source tree and fast-forward history. Install Git for Windows and verify access to the GitHub repository first; no user/device reimport is needed. [Updating Atlas](docs/updating-atlas.md) explains the process and `--check` / `--no-start` options.

The launcher copies the distributed `office_atlas.db` seed into ignored `data/office_atlas.db` only once, using SQLite backup. Subsequent launches keep the runtime database. Set `ATLAS_DB_PATH` to use another existing Atlas database. Preserve the entire `data/` directory, backups and `config.json` if moving to another checkout; never replace live records with the repository seed. Use the admin database manager for supported directory refreshes.

See [IT operations and imports](docs/operations.md) for deployment modes, software repair/uninstall, directory replacement, seating Excel sync and backup workflows.

## Development

```powershell
py -3.12 -m pip install -r requirements-dev.txt
npm ci
py -3.12 -X utf8 tests/run_all.py
py -3.12 launcher.py run --no-browser
py -3.12 launcher.py stop
```

`backend/main.py` hosts admin routes; `backend/viewer.py` hosts shared read routes; `directory_lookup.py` shares database-only lookup queries; `atlas/official-app.js` renders the common map; `atlas/viewer.js` provides read-only user and machine inspection.

The test runner uses disposable database copies, starts isolated UI fixtures on ports 8892/8893, and runs the Python regressions plus eighteen Node DOM suites. Remote operations are simulated. `npm run format:check` verifies formatting of the maintained browser sources.

The source tree also retains inputs and maintenance tools that are needed to reproduce or import data:

- `directory_workbook.py` provides the workbook parser and schema used by directory imports, seating sync and desk moves.
- `database040926.xlsx`, `atlas/data.json` and `atlas/visual-seating-matches.json` support the initial directory and previous-seating migration. The Excel templates remain available from Manage Database.
- `tools/build_official_3d.py` extracts geometry into `atlas/official-data.json`; `tools/build_studio_plans.py` generates the current `atlas/studio-floor-*.svg` backgrounds from the retained official PDFs. These optional build tools require PyMuPDF and rewrite their outputs; normal startup does not run them.
- The [floor-plan review](FLOOR_PLAN_AUDIT.md) covers all ten original plans, the reviewed furniture/stair/amenity corrections, source-coordinate checks and remaining physical-layout uncertainties. Run the correction generators after rebuilding the base geometry; normal startup loads their checked-in results without parsing PDFs.
- `scripts/serve_documentation_preview.py` generates the fictional map used for the [documentation screenshots](docs/images/README.md).

## Optimization changes

- The IT console is split into shared state, directory, deployment, shell, and software modules. One shell initializer and one shared command catalogue replace the accumulated version overrides and duplicate shortcut definitions.
- `client.js` owns session tokens, stale request cancellation, and job polling with bounded retries. Palette searches revalidate a compact desk index instead of downloading the full map state.
- Shared person cards and dialog styling keep the console, map, and viewer consistent. Shared database-only desk resolution preserves confirmed versus suggested links.
- Official custom locations retain their layout across save, reload, and export. Queues pause, resume, and cancel using the same server queue ID.
- Worker admission, deployment execution, and remote inventory concurrency are bounded. Inventory no longer holds the global directory-mutation gate while querying a remote machine.
- Job snapshots survive restarts. Interrupted work is never replayed automatically. Open **Operation recovery** from either admin palette, inspect the named target, then acknowledge its exact hostname before retrying. Unresolved-target guards survive event retention; deployment history remains available.
- The runtime retains up to 200 completed job snapshots and 200 completed queue snapshots, with 200 events per job. Active work is retained until terminal.
- Workbook shared strings belong to each workbook operation; imports release connections and temporary resources. Static assets revalidate through normal browser caching while API responses remain uncached.
- Removed the unused previous-map renderer and superseded stylesheet; historical seating data and import support remain available.

## Motion and map navigation

**Left-drag moves the map; right-drag rotates and tilts it in 3D.** Rotation stays anchored around the spot you grab. **Shift + left-drag** is an alternative for trackpads. Scroll to zoom, or use the rotation and reset buttons. A simple left-click selects a desk; a right-click without dragging opens its admin menu (or inspects the desk in the read-only viewer). Left-drag moves the map in both 2D and 3D, following the pointer at any zoom level. Admin and demo share these controls.

Search or select a person to glide to their desk with a brief location highlight. Longer moves pull back slightly before closing in, so the destination stays in context. Search groups are framed smoothly; zoom buttons, cursor-anchored wheel zoom, reset, and rotation share the same camera controller. Switching to 3D tilts the map into place, while floor changes fade in briefly.

Palettes, dialogs, person cards, console pages, and drawers use the same short motion timings. Both the admin map and shared viewer receive the map effects. Dragging immediately cancels automatic movement; repeated searches replace the previous destination. The **Animations On/Off** switch is available beside the map view controls; use **Ctrl+K → Toggle animations** in the IT console. **Off** disables map movement and interface animations immediately; **On** enables them. Before you make a choice, Atlas follows your system reduced-motion preference. Your choice is saved for that browser and Atlas address; the viewer has its own preference. Changes apply immediately, including during a camera flight.

No frontend runtime library was added. Camera movement shares the existing render loop and stops when settled. Cached geometry is reused throughout animations. Regression checks cover rapid selection, manual interruption, cursor anchoring, reduced motion, and rendering after the animation ends.

With **Animations On**, selecting a user or machine brings their details or deployment panel up with a quick slide and soft settle. A brief blue outline marks a selected machine; dialogs and the command palette lift into view. Machine, person and health cards appear in a short cascade while scrolling, with at most six effects per batch and 160 ms of stagger. Buttons also give a small press response. Admin, Demo and the private preview share these effects.

Movement and fades use transforms and opacity; there is no idle animation loop, extra library or remote scan. The IT workspace uses a faster profile: panels settle in 280 ms, cards use 180 ms with no stagger delay, and page transitions use 240 ms. The map keeps the richer motion. A panel entrance replaces any card effects inside it, rapid selections replace unfinished entrances, and leaving the tab cancels running effects. Completed effects leave no permanent transforms behind. **Animations Off** and **Citrix / remote** skip these decorative effects immediately. Content stays readable before observation and throughout the stagger.

The map renderer, camera controller, animation switch, person cards, dialog styles and palette are shared source files across admin and viewer. Viewer commands use the common command catalogue and clearly mark unavailable operations; permissions continue to be enforced by the separate read-only server.

Remote Admin shows up to 100 processes sorted by CPU, GPU or memory, with the full process count alongside. Right-click a row, press Shift+F10, or use its **•••** button to **Kill process**, copy its PID or copy its details. Killing a row confirms its name, PID and machine, rechecks the process creation time, reports Windows' result, and refreshes after success. Core Windows processes are blocked. The manual PID/name field also confirms before terminating; a name targets every matching instance. GPU usage reports the busiest engine per process and requires counters exposed by the remote graphics driver; unavailable counters produce an explicit message. These remote operations remain available only in the local admin version.

## Troubleshooting performance in Remote Admin

### Citrix and remote display mode

Choose **Display → Citrix / remote** in the shared header on the map, console or demo. This browser preference is remembered and synchronized between tabs on the same origin; choose it separately in the demo or another browser when needed. It does not start scans or change permissions.

In this mode, map drawing is capped at 30 rendered frames per second. Camera transitions take at most 280 ms and skip the panoramic zoom detour. While moving, the 3D buffer uses 75% width and height (about 44% fewer pixels) and only the selected person's name label remains visible. Full resolution and nearby labels return when movement settles; all desks remain selectable. Decorative CSS animations, scroll reveals, locator pulses and backdrop blur are disabled. The existing Animations Off setting still makes camera transitions immediate. Standard mode retains the normal presentation.

There is no continuous idle rendering or background performance probe. Lower render resolution is a standard [WebGL performance technique](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices#consider_rendering_to_a_smaller_back_buffer), but actual Citrix smoothness also depends on the session and connection; validate on the affected desktop.

If WebGL initialization fails, Atlas reports the available error and lets you retry by switching 3D on again. A lost graphics context falls back to 2D; after restoration, manually enable 3D to rebuild the graphics resources. The display mode cannot enable WebGL when the browser or enterprise configuration blocks it.

### Manual performance capture

Click **Scan for slowness** while the user reproduces the problem. Opening Remote Admin, selecting a machine or waiting on the page never starts a scan. Each click starts a light capture: at most six samples over 60 seconds, with at least 10 seconds of rest after each completed check. It highlights busy CPU consumers, individual logical-processor saturation, memory pressure with paging activity, elevated disk response during I/O and commit headroom. Each finding includes measured evidence and a next check. Repeated evidence requires at least three matching observations spanning eight seconds and 60% of the available samples; brief spikes and limited evidence remain labelled separately. These thresholds guide investigation and do not establish a root cause.

To limit overhead, the capture requests selected WMI properties and excludes GPU engine enumeration, individual thread enumeration and volume inventory. Those deeper checks remain available through **GPU**, **Disk** and **Inspect CPU threads**. Only one performance collection runs at a time per Atlas server, with a server-enforced pause between diagnostic samples for the same machine. The collector has a 15-second timeout. The browser rests 20 seconds if CPU is at least 90%, RAM is at least 95% or a check takes at least five seconds; it stops after a failed request, a check lasting at least 10 seconds, or elevated WMI provider CPU (5% of the machine or the equivalent of 50% of one logical processor). WMI provider activity can come from other monitoring software; this does not attribute its load to Atlas. Fewer samples can miss brief spikes. Monitoring still has a cost: [Microsoft documents WMI performance issues from large or frequent queries](https://learn.microsoft.com/en-us/troubleshoot/windows-server/system-management-components/scenario-guide-troubleshoot-wmi-performance-issues), so zero impact cannot be guaranteed.

**Copy findings** produces a ticket-ready report with the timeline, check durations, coverage and collection failures. Captures also stop when cancelled, when the tab is hidden or when leaving Remote Admin, and are kept only in the current page. An already-started remote WMI query may finish after cancellation or the collector timeout. Changing the target clears the capture. The process list selects consumers across CPU, RAM and I/O, plus up to 20 Excel and 20 WMI provider instances, while preserving process identity checks. No workbook is opened or modified, and no process is terminated automatically.

WMI cannot identify a particular slow formula, add-in, Citrix session delay or hypervisor scheduling problem from these counters. The report explicitly lists those gaps; **Cause not established** is a valid result. For deeper investigation, use [Microsoft's Excel calculation guidance](https://learn.microsoft.com/en-us/office/vba/excel/concepts/excel-performance/excel-improving-calculation-performance), [Citrix session performance](https://docs.citrix.com/en-us/citrix-virtual-apps-desktops/director/troubleshoot-deployments/user-issues/session-performance) and host-side VMware metrics where applicable. Diagnostics remain administrator-only.

Enter a machine, select **Overview**, **CPU**, **GPU** or **Memory**, then click that view's **Scan** button. Switching views never starts a scan. Each view keeps its own last result for the current machine; **Refresh** takes another sample and shows percentage-point changes since its previous scan. A failed refresh keeps the previous result with a failure message and its original timestamp. Changing the machine clears all four results. **Copy report** copies only the selected view's readings and process list.

| View | What it collects and displays |
| --- | --- |
| Overview | CPU, GPU, RAM, commit, paging and disk pressure; CPU-ranked processes and expandable disk/processor details. |
| CPU | Machine and logical-processor CPU, queue, total threads and context switches; CPU-ranked processes with manual thread inspection. No GPU, memory or disk providers. |
| GPU | GPU engines and GPU-ranked processes with reported counters, with the busiest engine identified for each process. No CPU, memory or disk providers. Processes with no GPU counters are omitted from this list. Missing GPU counters stay unknown, not 0%. GPU memory is not collected. |
| Memory | Used/available RAM, committed memory and limit, paging reads; resident-memory-ranked processes with RAM percentage, private commit, page faults and handles. No CPU, GPU or disk providers. |

All four scans project only the WMI fields they need. The simulated-provider regression checks 14 queries for Overview, 8 for CPU, 3 for GPU and 6 for Memory; these counts do not measure execution cost. The light slowness capture remains at 12 queries per sample. Nothing polls outside an explicitly started, bounded capture and no collector is installed on the target. The interface prevents overlapping resource scans; the server also enforces its collection limit. Ping, C$ and Disk utility results do not replace the selected performance view.

- CPU, memory and GPU rings show overall usage versus remaining capacity in the relevant view. RAM shows both a percentage of usable physical memory and readable KiB/MiB/GiB sizes. Each process table contains only that view's metrics.
- In Overview, expand **Processor activity & disks** for logical-processor activity, physical-disk read/write latency and queue depth, and volume free space. CPU and GPU views show their processor/engine breakdown directly. Each view has its own measurement guide.
- From CPU or Overview, click a thread count or choose **Inspect CPU threads** from the process menu. Two raw samples, at least one second apart, show each thread's usage of one logical CPU and of the whole machine, context switches, priority, state and wait reason. Process identity is checked before and after collection; new or reused thread IDs have no fabricated CPU rate. The busiest 200 threads are shown with the total thread count.
- Red process values start at 25% machine CPU, 80% GPU or 20% of usable RAM; amber starts at 10% CPU/RAM or 50% GPU. A count of 500+ threads is amber only. These are visible investigation thresholds, not proof of a leak, fault or excessive thread creation. Repeat samples to check whether pressure persists.
- Missing providers produce partial results and explicit warnings. GPU counters depend on Windows, the driver and the Citrix environment. These host-privileged diagnostics remain unavailable in the shared read-only viewer.

CPU and disk rates use differences between raw counters and the target provider's timestamps. Thread wait states are instantaneous observations, not call stacks or a measurement of blocked time; see [Microsoft's thread counter reference](https://learn.microsoft.com/en-us/previous-versions/aa394279(v=vs.85)). GPU summaries follow the busiest-engine principle described in [Microsoft's Task Manager explanation](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/). Per-process GPU values and resident working sets must not be summed into a capacity pie: engines and memory pages can be shared. The charts instead use machine-level totals. High I/O or page-fault rates alone do not establish disk trouble, and these WMI snapshots cannot measure end-to-end network or Citrix session latency.

### Floor framing and machine filters

The map fits the complete current floor into its available canvas on opening, floor changes and **Fit floor**. While fitted, it adapts to window resizing. Finding a person uses a short, modest zoom that keeps surrounding desks visible; manual pan and zoom remain available. Both 2D and 3D use the same framing in admin and demo, including Citrix display mode.

Linked-machine lists in the map, IT Console and demo offer **All**, **Dedicated desktops**, **VDI**, **Kiosks** and **Other** filters with counts. Select several types to combine them, or choose All to clear the filters. Assigned machines stay first and filtering never changes the selected deployment target or starts a scan. Kiosks follow the `PWMK` naming pattern after any three-letter region prefix (including `GBR`, `PAR` and `NYK`); `PWMF` identifies dedicated desktops, and hostnames containing `VDI` identify VDI machines. Other names stay accessible under Other rather than being guessed from the country code.

The map uses a compact white arrow with a rounded dark outline, changing to Barclays blue over interactive items. Both admin and demo use native browser cursor images with standard fallbacks, a grabbing hand while dragging and a crosshair for desk placement. There is no cursor animation loop or extra remote traffic.

### Enable Remote Registry

Search **Enable Remote Registry** in the palette or right-click a machine in the map or IT console. The action shows the hostname before you click **Enable Remote Registry**. Atlas starts the fixed `RemoteRegistry` service over WMI, changes Disabled startup to Manual only when necessary, verifies Running, and reports failures. It requires remote administrator rights and runs only on explicit request. No reboot or automatic startup is added. Demo and hosted preview disable the action.

### Deployment launch status

Copy & execute shows **Launched** as soon as Windows confirms the remote process started. Monitoring then waits for the script and every installer it starts, including ones handed off after the script returns, and for Windows Installer, before reading the exit code. The deployment's activity shows what it is waiting for, and the history records the uninstall registrations that were added, removed or changed. Installers still running at the deployment timeout hold the PC for Operation recovery. Script exit codes do not turn that status into Failed or imply installation success. Output and exit codes remain in the log/history; copy or process-start errors still fail. Background log collection retains the target lock while the process runs. Demo and hosted Preview remain read-only.

### Reboot checks in Queue

The Reboot button captures the selected hostname, requests the reboot once, then opens a live ping terminal in the floating Queue drawer. Windows must accept the request. Two consecutive missed IPv4 echo replies followed by two consecutive replies mark the check complete; replies before the offline transition never count as a completed reboot. This confirms network reachability, not that sign-in or applications are ready.

Ping checks run about every two seconds, stop immediately on confirmed return, and completed cards disappear after ten seconds. Stop monitoring ends only the ping checks, not a reboot already requested. A fifteen-minute timeout leaves a visible unconfirmed result for dismissal. At most eight machines can be watched simultaneously; duplicate watches are rejected. Closing the drawer or refreshing the browser leaves the server watch running; stopping Atlas ends it. Demo and Preview display the shared interface but cannot reboot or ping machines.

### Activity widgets in Queue

The floating Queue now includes live widgets for deployments and batches, deployment queues, reboot checks, PsExec sessions, software inventory/actions, CPU/GPU/memory and process scans, health checks, Remote Registry, cleanup, remote tools and database imports. Widgets show the original target, state and available output. The badge combines active widgets with waiting local deployments and reboot checks, without counting child jobs twice.

The activity feed reads existing server state; it never starts a remote scan. Slowness capture has a Stop capture control; PsExec can stop its local session; deployment queues can pause after the current item, resume or cancel waiting items. Ordinary running requests and installers are not given a misleading Cancel button. Completed widgets clear after ten seconds; failed or uncertain results remain briefly for inspection or dismissal. Opening Queue does not repeat an action. Demo and Preview show the shared layout but make no live activity requests.

### Moving the databases to another drive

Run **Stop-All-Atlas.bat**, then **Move-Databases.bat**. It moves the Atlas database and the Knowledge Base database to `F:\Atlas\DB` (or to a folder you give it, for example `Move-Databases.bat G:\AtlasData`) and records the folder as `database_folder` in `config.json`. Each copy must pass an integrity check and match the original's row counts before Atlas switches to it; existing files are never overwritten, and the old files are kept in `data\backups\before-database-move-...` until you delete them. If the drive is missing when Atlas starts, Atlas stops with a message instead of opening an empty database. To go back, remove `database_folder` from `config.json` and return the files to `data`.

### Deployment kits in Queue

Queue the packages you usually deploy together, type a name under **Deployment kits** and click **Save queue as kit**. Later, select any machine and click **Add for MACHINE** to queue every package in the kit for it, with the same script, action and copy options. Adding a kit only fills the queue; nothing deploys until you click **Start queue**. Saving with an existing name replaces that kit. Kits are kept in this browser's storage. Demo shows them read-only.

### Windows features and DISM through PsExec

The Windows features & DISM category provides Enable .NET Framework 3.5, check NetFx3 status, enable Microsoft Print to PDF, list optional features, CheckHealth, ScanHealth, RestoreHealth, AnalyzeComponentStore, and list Windows servicing packages. These templates run DISM on the selected remote machine as SYSTEM (`-s`) using the configured local PsExec path (default `C:\Data\PsExec.exe`).

Feature changes and repair retain the existing typed-hostname confirmation and use `/NoRestart`. Exit 3010 is reported as completed with a restart required, not failure. Long DISM commands have a bounded one-hour terminal timeout, with output in the PsExec terminal and Queue activity widget. Stopping the local session does not guarantee a remote DISM operation stops. Preview/Demo keep execution disabled.

NetFx3 enable applies to Windows 10 and Windows 11 through 25H2. Windows 11 26H1 and later need the standalone .NET 3.5 installer. Component availability and downloads depend on Windows edition and the organisation's repair-source policy. CheckHealth reports known corruption; ScanHealth performs a scan; RestoreHealth repairs; AnalyzeComponentStore only reports usage. See Microsoft: https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/repair-a-windows-image and https://learn.microsoft.com/en-us/dotnet/framework/install/dotnet-35-windows-11.

### Package deployment flow

Workspace package selection applies immediately: clicking elsewhere, switching machines or refreshing filtered results keeps the chosen package. Workspace and Bulk deploy use the same Install / Repair / Uninstall switch and load the corresponding scripts. The launch button names the action and target (or bulk machine count). Bulk submissions are blocked while scripts load or a request is being submitted, and each request captures its package, action and targets. Demo and hosted preview show the controls with execution disabled.

### Knowledge Base: articles, search everything and diagrams

The Knowledge Base opens on **Articles**: written runbooks in Markdown. **Diagrams** (the tab beside it) is the Draw.io editor described below; Atlas remembers which one you used last.

- **New article…** starts from a template (software install, slow PC, Outlook, VPN, printer, locked account, blank). The editor has a formatting toolbar, a live preview and Ctrl+S to save. Tables, checklists, code and links work as usual in Markdown; a ` ```mermaid ` block draws a flowchart (the **Diagram** button inserts one). Mermaid loads only for articles that contain a diagram.
- Add **tags** to group articles (the tag chips filter the list), and tick the issue types under **Suggest in Live Inbox for**: matching requests then show the article first under Knowledge Base on the request card.
- **Search** finds words in any form ("freezes" finds "freezing", accents ignored) and highlights them. Tick **Everything** to also search past Live Inbox requests, deployment history and diagram notes: a request opens in Live Inbox, a deployment shows its details with **Select this machine in Workspace**.
- Articles are saved in `knowledge.sqlite3` (next to the diagrams) with the same revision check. The search index `search-index.sqlite3` beside it is a cache that Atlas rebuilds by itself; it is safe to delete. Articles stay in Admin: in the Demo viewer and Preview the Articles tab only shows a note, and the Diagrams tab works as before.
- Markdown is rendered with marked 18.0.14 and cleaned by DOMPurify 3.4.16; diagrams use Mermaid 12.0.0. All three are bundled in `frontend/assets` with their licences (`python tools/vendor_frontend.py` refreshes them from `node_modules`).

#### Diagrams (Draw.io)

Use Map / Workspace / Knowledge Base in the header, then **Diagrams**. Atlas embeds the actual open-source Draw.io 31.5.3 editor, bundled under `frontend/drawio` with licenses and provenance. It loads only when opened. No external diagram or AI service is used; the editor blocks external network connections.

- **Documents** and **Notes** toggle docked panels beside the editor. Notes starts closed to leave room for the diagram; narrow windows also start with Documents closed. **Focus editor** temporarily hides both panels and the Operations sidebar, then restores their previous state. These controls resize the existing editor without reopening the document or clearing its draft. The canvas uses the available window height, including inside Atlas Desktop.
- Native Draw.io shapes, connectors, pages, layers, formatting, undo/redo and zoom, with incident-triage and network templates.
- Notes to diagram converts steps, indented bullets and `A -> B` connections into editable shapes. `Check ping? -> [Yes] Check application` creates a decision and labelled connection. Conversion is deterministic and local, not AI interpretation. Review the result. Existing diagrams are kept separately.
- Admin auto-saves to `data/knowledge.sqlite3`. Revision checks prevent silent overwrites between windows. Back up this database, or export documents.
- Demo and Preview provide the same editor with downloadable drafts. Download Atlas JSON to retain notes and diagrams before closing. Admin documents are never included in preview builds or exposed through the LAN viewer.
- Open `.drawio`, `.xml` and Atlas JSON. Export Atlas JSON, Draw.io XML, SVG or PNG. Only Atlas JSON includes accompanying notes.
- Search `drawio` in the palette for documents, notes conversion, shapes, connecting two selected shapes, layers, formatting, duplicate/delete, undo/redo, zoom, save, import/export and templates. Ctrl K works inside the editor.

Restart Atlas after updating to register editor and document routes. Remote-administration permissions remain unchanged.

### PsTools suite

The **PsTools** page (formerly PsExec) now includes a tool selector, searchable templates, command previews and the existing embedded terminal. Search Ctrl+K for PsTools or a utility name. Extract Microsoft's PsTools into `C:\Data` on the **Atlas host**, then start Atlas from an elevated account. The PsExec path determines the folder: `C:\Data\PsExec.exe` selects the adjacent tool executables; a PsExec64 path selects their 64-bit names. Each tool must be present on the Atlas host. PsExec and direct PsTools commands include `-accepteula`: clicking Run or executing a copied command accepts the [Microsoft Sysinternals licence terms](https://learn.microsoft.com/en-us/sysinternals/license-terms) for that tool under the Windows account executing it. Browsing, preparing and copying commands do not launch a tool or accept a licence. Atlas uses your existing tool installation and does not require a previous licence-acceptance registry entry.

| Tool | Included functions |
| --- | --- |
| PsExec | Existing remote commands, interactive command prompt and DISM templates |
| PsFile | List shared open files; close one file ID with confirmation |
| PsGetSid | Computer SID; account/SID lookup |
| PsInfo | System information/uptime, volumes/free space, software, hotfixes |
| PsPing | Ten ICMP pings or TCP connection attempts from the Atlas host |
| PsList | Process snapshot/tree; PID memory and thread details |
| PsKill | Terminate a confirmed PID |
| PsLoggedOn | Profile/share logons or local logons only |
| PsLogList | Recent System/Application events; seven days of restart evidence |
| PsService | Query/configuration/dependencies; start/stop/restart/pause/resume |
| PsShutdown | Restart/shutdown countdown; cancel pending shutdown |
| PsSuspend | Suspend/resume one confirmed PID |
| PsPasswd | Local help only; password changes are deliberately not sent through Atlas's recorded terminal |

PsUptime is incorporated into PsInfo. No alternate credentials are collected by these templates. Review current process/file IDs immediately before a change; they can be reused. Changes require typing the target hostname. Direct tools run with argument arrays without a command shell; they include the common `-accepteula` flag, without inheriting PsExec-specific connection or elevation flags. Terminal completion describes the command process, not proof a reboot or application operation has finished. Some tools have nonstandard exit codes (PsInfo can return the service-pack number); inspect their output. Stopping a local session does not undo a remote operation.

Admin is required for execution; Demo and hosted Preview show the same catalogue with execution blocked. PsInfo and some logon queries require permitted Remote Registry access; Atlas does not enable it implicitly. PsPing tests the path **from the Atlas host**, not the target's historical or outbound internet connectivity. PsPasswd passwords can appear in process arguments, and omitting its new-password argument applies a NULL password, so use your approved password-management workflow.

Sources: [Microsoft PsTools](https://learn.microsoft.com/en-us/sysinternals/downloads/pstools), [PsPasswd](https://learn.microsoft.com/en-us/sysinternals/downloads/pspasswd), [PsPing](https://learn.microsoft.com/en-us/sysinternals/downloads/psping), [PsInfo](https://learn.microsoft.com/en-us/sysinternals/downloads/psinfo). Other utility references are available from the Microsoft suite page.

### Active Directory lookup

Open **Active Directory**, or search Ctrl+K for **AD**, **groups** or **OU**. User-name shortcuts and machine context actions open the separate directory page. Workspace selection does not query AD automatically. AD failures do not prevent deployment to a selected hostname. Choose User or Computer, enter an exact account/machine name (users also support UPN and DOMAIN\account), optionally specify a domain/controller, then click **Look up AD**. **Use selected machine** copies the current target without querying. Selection loads memberships once in local Admin; filters use those results without further queries. **AD lookup** also supports an explicit account/controller lookup or refresh. Queries are read-only through the Windows account running local Admin. No passwords are collected and no AD objects are changed.

Results show OU/parent container, full distinguished and canonical names, SID, enabled status, creation/change dates, approximate replicated last-logon date and password timestamps. Users also show lockout, expiration, department, title and manager DN; computers show DNS hostname and OS details. Filter group names with contains, starts/ends with, equals or excludes. Expand a group row for the full description, directory path, scope and category. Results include direct, primary and discovered nested memberships; partial resolution and traversal limits remain visible under lookup evidence. Membership is not proof of effective permissions. Replicated logon timestamps are not precise recent activity records.

Install the RSAT **Active Directory PowerShell** module on the Atlas host using your approved software process. Domain connectivity and permission to read the objects are required. The optional server field selects a domain/controller. Failures report missing RSAT, lookup errors or the 35-second timeout. Atlas does not install RSAT or enable services automatically. Demo and hosted Preview show the page with lookups disabled; live AD results are not added to the hosted snapshot. Classic and Desktop share the feature.

Microsoft references: [Get-ADUser](https://learn.microsoft.com/en-us/powershell/module/activedirectory/get-aduser), [Get-ADComputer](https://learn.microsoft.com/en-us/powershell/module/activedirectory/get-adcomputer), [Get-ADGroup](https://learn.microsoft.com/en-us/powershell/module/activedirectory/get-adgroup).

### Compact interface and loading feedback

Atlas uses tight shared spacing: small controls, 12px console panels, narrower sidebars and compact headers. Touchscreen controls keep larger targets. Knowledge Base navigation and tools have SVG icons, and the editor uses the available window height. Slow foreground requests show a small loading indicator after 180ms; it clears on success or error, including concurrent requests. Background watcher polls stay silent. Draw.io has its own loading indicator and timeout message. Indicators respect Animations Off, reduced motion and Citrix mode; they never show invented percentages.



### AD group inspection and comparison
Right-click a user or machine and choose **See groups** to query its exact account in local Admin. **Compare groups** takes up to five colleagues or machines at once (comma separated) and shows one colour-coded column per person: green ✓ member (teal nested, indigo primary), red ✗ missing. Groups the first person is missing come first, with a count of who has them; coloured counters (missing, only them, partly shared, everyone has) filter the list, and **Copy missing groups** copies the missing names for an access request. Built for directories with hundreds of groups: a comparison opens on **Differences only** (with a count of the shared groups hidden and a **Show them** link), and lists of 40 or more groups fold into sections by name prefix (APP-, FS-, VPN-…) with per-section coloured counts, sorted so the sections with missing groups come first; **Collapse all** / **Expand all** and the **Group by prefix** switch control them. The list also supports case-insensitive name filters: contains, starts with, ends with, equals and excludes. **Export CSV** downloads the filtered rows, object identities and each object's membership type; spreadsheet formula-like values are escaped. Command palette: See user groups, See machine groups, Compare AD groups, Filter AD group names, Export AD groups to CSV.

Queries use the Windows account running Atlas and require RSAT/domain connectivity. Results cover direct, primary and discovered nested membership in the queried directory scope, not effective permissions. Any lookup warnings or membership limits still apply to comparisons. Demo and Preview expose navigation but never run live AD queries.


Performance and machine views use dense layouts: compact process rows with inline PID/session, small metric charts, expandable logical-processor detail, and compact machine facts. Long process lists scroll inside the list with sticky column headings; full records remain available. Touch devices retain larger action targets.




### AD health and comparison

AD lookup shows compact read-only user/machine health, OU, machine password change, and replicated (approximate) last logon. User password expiry uses the directory-computed expiry attribute. Unknown values remain unknown.

Group lookup traverses parents of direct and primary groups, detects cycles, and labels discovered memberships Nested. Traversal is bounded to 1,000 visited groups and a 20-second work budget (the existing 35-second process timeout still applies). Failed resolution or limits produce partial-result warnings. This is scoped directory evidence, not a complete cross-domain authorization calculation or proof of effective access.

Compare users or computers above the group list; expand **Account health & properties** for both health cards and a property matrix with differences highlighted. Existing group filters and CSV export include nested memberships. Copy support summary (also in the palette) includes every compared object, query times, returned properties, group memberships, differences and warnings. No AD changes or additional remote health scans are performed.

References: https://learn.microsoft.com/en-us/powershell/module/activedirectory/get-adgroup and https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-adts/f9e9b7e2-c7ac-4db6-ba38-71d9696981e9


### AD identity lookup troubleshooting
Atlas first resolves an exact logon name, SID or GUID. If a user account is not found, it checks exact account, UPN, mail, employeeID and employeeNumber values in the selected domain/controller (maximum two matches; ambiguous matches are rejected). Access errors do not trigger fallback. Use Domain / controller to match the server displayed in AD Users and Computers. No cross-domain guessing or directory changes are performed. Structured errors replace raw PowerShell CLIXML. Restart Atlas after updating the Python backend.

Identity semantics: https://learn.microsoft.com/en-us/powershell/module/activedirectory/about/about_activedirectory_identity

User identifiers from reports with B, G or X followed only by digits are normalized to X plus the same digits before AD lookup, including DOMAIN\account and numeric UPN local parts. Leading zeroes are preserved. This applies to user lookup and comparison, not computer objects or other usernames.


### Read-only AD browser and complete group display
See groups returns direct, primary and discovered nested memberships for users and computers. Windows PowerShell 5.1 group records are converted to objects before deduplication, avoiding the single-row hashtable sorting bug. All direct membership DNs remain visible even when enrichment times out; nested traversal limits and directory-scope failures are explicitly reported.

Expand **Directory browser** below the Workspace group list, or search AD directory browser in the command palette. Choose a domain/controller, browse OU/container children, search within the current container, filter object type, inspect properties and direct group members, or open user/computer memberships by GUID. Back, Parent OU and Domain root support navigation. Load more increases the result window up to 5,000; beyond that narrow the search/OU. No AD data changes or automatic background queries. Demo/Preview expose the interface but disable live browsing.

Tests include Windows PowerShell 5.1 and PowerShell 7 membership fixtures, escaped LDAP search, API token enforcement, navigation and read-only guards. Live bank-domain results require verification on the domain-connected Admin host.

AD memberships use a compact table with group name, full wrapped AD description and membership type. Comparison rows include presence and both membership types. Directory paths are expandable. CSV and support summaries include descriptions; unresolved details are distinguished from an empty AD description. Directory-browser results also show descriptions.


### Compact machine health
Workspace shows four small readings for the selected machine: ping, C$ access, C: free storage and uptime. **Full health readings** expands the existing readings, errors and check times; **Scan health** explicitly retrieves the remaining metrics. Clicking a machine retains the existing delayed quick check, with no polling or automatic CPU/RAM/GPU scan. Demo and Preview show the same layout with live AD, health and deployment disabled.
AD group rows provide Copy (group name) and See members. Left-click a group name or use its right-click menu to open members; users/computers in the member list have See groups, and nested groups can be explored recursively. Links retain the result domain/controller and exact object DN/GUID. Browser Back returns to the previous directory listing. Clipboard failures offer a selectable name. Demo/Preview keep live navigation disabled.


### Workspace Terminal and PowerShell ISE-style editor
Open Terminal in the Workspace sidebar or search Terminal / ISE in the command palette. Commands run on the Atlas host with the Windows account running Atlas, not automatically on the selected machine. Choose PowerShell or CMD, or use the PowerShell script editor to open/save .ps1 files and run a script or selected text. Ctrl+Enter runs the editor contents. Each run starts a fresh, noninteractive process; variables and working-directory changes do not persist between runs. Interactive applications and password prompts are not supported.

Output streams into the embedded terminal with an exit code, Copy output and Stop. Terminal and PsTools output is shown in a real terminal view (xterm.js 6, bundled, loaded the first time either page opens): colours from tools are displayed, long output scrolls quickly, and the **Find in output** box (Enter for the next match, Shift+Enter for the previous one) searches it. The plain text stays underneath for Copy and screen readers; if the terminal view cannot load, the plain output is shown as before. One local command runs at a time, with a 15-minute limit and bounded, in-memory output. Stop ends the local shell; child or remote processes may require separate inspection. No execution-policy bypass is added. Execution requires elevated local Admin and a session token; Demo/Preview allow editing and downloading scripts only. Script contents are not saved to browser storage.


### Atlas visual system
The shared UI uses a blue/slate palette, Windows 11 Segoe UI Variable type, a light sidebar with a raised pill for the current page, white cards with hairline borders and soft shadows, sentence-case labels and table headers, soft focus rings and consistent table, form, dialog and terminal styling. **Dark mode** follows the Windows light/dark setting; the moon/sun button in the header switches it and the choice is remembered per browser. The floor plan, Knowledge Base articles, diagrams, menus and the search box all have dark versions. The final rules live in frontend/assets/design-system.css; the command palette mirrors them inside its shadow root. Map, Workspace, AD, Packages, Remote Admin, Bulk Deploy, History, Terminal, PsTools, Knowledge Base and database management share these rules. Dense row/control geometry, semantic warning colours, map labels and the Draw.io canvas remain intact. The refresh adds no animation loops, remote fonts, image dependencies or JavaScript runtime work.

### shadcn UI components

Workspace launch cards and Packages badges, buttons, empty states and loading skeletons use official shadcn source in frontend/react/components/ui. The CLI configuration is components.json (Radix, JavaScript, prefixed Tailwind). Rebuild with npm run build:ui. Atlas semantic colours and compact geometry remain in the shared design system; reduced motion also disables skeleton animation. No CDN or browser-time component downloads are used.
