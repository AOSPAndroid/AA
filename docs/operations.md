# IT operations and imports

See [the main README](../README.md) for installation, startup, sharing, configuration and updates. This reference covers the workflows that change machines or stored records. Remote actions use the Atlas host account's existing Windows permissions.

## From a desk to a deployment

Select a desk, review its directory identity and choose one linked machine. A name match is a suggestion until the account link is confirmed. Use **Match to directory** to search by name, login or email, inspect the account, then choose the intended person. Linking updates the desk label and stable directory link with history; it does not rename the source directory user or verify physical presence.

Choose the package, action and script. **View script** displays the repository file as text. **Copy only** transfers files without installing, **Copy & execute** transfers and runs the selected script, and **Execute existing** uses the remote copy already present. Review the target and execution mode before starting. Copy success, process launch and installation completion are different outcomes; inspect the recorded result, exit code and logs. Atlas waits for installers the script starts, even ones it hands off before returning, then records which software registrations changed.

Desk deployment history and the Console's history refer to the same shared database. Closing an inspector does not cancel its deployment. Stopping Atlas stops monitoring; an already launched remote installer can continue. Interrupted jobs are not automatically replayed. Use **Operation recovery** to inspect unresolved work and acknowledge the exact target after checking its actual state.

## Package repository and catalogue

Atlas normally finds the synced **EPP_PACKAGE_REPO_BetaPackages - BetaPackages** SharePoint folder in business OneDrive. For offline deployment, mark the required package folders **Always keep on this device** and let synchronization finish. Repository inspection does not download cloud-only files or verify every external script dependency.

Package subfolders contain installation scripts ending in `_i.ps1` or `_i.vbs`, uninstallation scripts ending in `_u.ps1` or `_u.vbs`, and repair scripts ending in `_r.ps1` or `_r.vbs`. The catalogue can store display names and versions without renaming the original folders or scripts. Missing versions are not guessed. See [configuration and updates](../README.md#configuration-and-updates) for repository overrides.

## Installed software, repair and uninstall

Open **Installed software** from Remote Admin or **Software inventory** from a machine menu. Right-click an application, use the keyboard context-menu key or choose **Actions**. Review the application, version, target, scope and exact proposed command, then type the target hostname to execute. Plans expire after 15 minutes, and refreshing inventory invalidates previous plans for that target. Registration is checked again remotely before execution.

MSI uninstall uses the registered ProductCode; MSI repair uses `/fomus`. MSI actions request quiet execution, no automatic restart and a verbose log. EXE actions require a registered silent command or explicitly supplied vendor-documented silent arguments; generic switches are not guessed. Appx reset is not offered as repair. See Microsoft's [Windows Installer command reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/msiexec).

Inventory includes machine registry views and classic per-user entries for loaded profiles. Another user's classic applications need that user's execution context; Atlas does not impersonate users or load their registry hives automatically. Optional MSIX/Store discovery supports removal of the selected installed user registration, not provisioned packages or every user's copy. Unsupported or non-removable registrations explain why an action is unavailable.

**Read MSI cache names** reads cache metadata only, with a limit of 1,500 files or 90 seconds. Cache-only entries are informational, not uninstall targets. Atlas does not query `Win32_Product` for discovery. **Clean cache** remains unavailable until application-specific disposable folders are defined; Windows Installer cache files are never deleted by this feature.

Remote software operations require WMI process creation, the administrative share, Windows PowerShell and permitted script execution on the target. Operation files and logs are written to a unique AtlasSoftware folder below the target Windows Temp directory. A target lock prevents overlapping deployment/software workers. Jobs appear in history and the monitor; a successful process launch is not successful uninstallation. Refresh inventory after completion and inspect unknown outcomes before retrying.

## Directory imports replace a complete snapshot

Use **Manage Database → Users and devices import** for the complete intended directory export, with `users` and `devices` worksheets. Original device headers `ci` (hostname), `model`, `assigned_to` and `serial_number` are accepted; the existing `Users` and `computers` format remains supported. Choose **Validate and preview**, review additions, removals, changes and devices without hostnames, confirm the complete snapshot, type `APPLY`, then choose **Back up and apply**. Missing rows are removed from the directory, so a filtered list or one edited user is not a complete import.

Duplicate identities, duplicate machine names and empty required sheets are rejected. Original source columns and values are retained alongside operational fields. Prefer the normal richer export when extra fields must remain populated. Import the directory before a seating sheet that refers to newly added accounts.

Directory replacement preserves seating, equipment, confirmed canonical account links, seating history, deployment history and catalogue metadata. An account missing from the new export leaves its desk link available for review; Atlas does not silently bind it to another person. Relevant active jobs block imports. Each applied import creates a full database backup and an import-history entry. **Restore directory before this import** stages a preview from the saved backup while preserving current seating and operational history.

## Excel seating templates and synchronization

Manage Database provides an **Official desk template**, **Previous seating template** and **Directory template**. Preserve worksheet names and column headers. The blank templates contain no sample people or machines; the desk reference reflects bundled desks. Use **Download current users and desks** when including locations added later.

For **Users and desks · Excel sync**, maintain `Desk ID`, `Name`, `Team`, `Account` and `Status`, one row per desk. Account accepts an existing directory login, email or BRID and preserves identity across name changes. Names without accounts remain unconfirmed. This workbook changes seating, not Windows accounts or the Europe directory.

Upload the `.xlsx`, choose **Detect changes**, review the preview and type `APPLY` before **Back up and apply seating changes**. Compatible sheets require Desk ID and Name; Team, Account and Status are optional. Use a `Users and desks` or `Seating` worksheet, or a single-sheet workbook.

Omitted desks are unchanged by default, except the previous locations of recognised moves. **Complete layout snapshot** instead vacates desks omitted from the entire selected layout. Clear Name and Account and set Status to `vacant` to explicitly vacate a desk. With Status omitted, a nonempty Name or Account means assigned; both blank means vacant. Vacating seating does not delete the person's directory account.

Unknown desk IDs, unknown or ambiguous supplied accounts, duplicate desk rows and formula/error cells block the import. Duplicate occupants follow the Excel: a person the sheet places on two desks is placed on both and listed as a warning, and a person the sheet places is freed from any other desk the sheet does not mention (including a desk holding only their name). Distinct accounts distinguish namesakes. Changes after a preview invalidate it; previews also expire after one hour or replacement. Applying creates a backup and desk history. Reimporting unchanged data produces no changes.

Recognised moves and swaps carry occupants and account links. Desk geometry, equipment and notes remain at each physical desk, and changed seating loses its previous physical-verification flag. New physical desks must exist on the map first. The separate **Desk moves** workflow exports a workbook where only **Move to desk** should be edited; review **Preview desk moves**, then type `MOVE` to apply.

## Backups, seating imports and standalone directory refresh

**Back up .db** downloads a consistent snapshot of the shared database. The map's record JSON export/import covers seating records only. **Import previous seating .db** brings matching records and seating history from a supported Atlas backup; it does not restore the complete shared app or replace the directory. Reimporting the same seating backup is ignored.

For a normal update, finish active jobs, stop both servers and preserve `data/office_atlas.db`, the rest of the `data` directory and `config.json`, as described in the main README. Keep a separate backup before replacing an installation. The root `office_atlas.db` is the distributed seed; normal launches use the persistent runtime database.

**Refresh-Directory.bat** is the standalone directory recovery/import path. Finish all jobs, then drag a complete `.xlsx` export onto it. The script stops this installation's servers before preparing the refresh. With no supplied file it uses the bundled `database040926.xlsx`. Review user, machine and relationship counts; type `APPLY` only for the intended complete export. A full backup is created in the active database's adjacent `backups/` directory (normally `data/backups/`) before replacement. Start Atlas again afterwards. Do not run a direct CLI refresh concurrently with a server using the same database.

For validation without applying an import:

```powershell
py -3.12 refresh_directory.py --source "Europe-export.xlsx" --check-only
```

This prepares a temporary candidate and displays counts; it does not change the live directory.
