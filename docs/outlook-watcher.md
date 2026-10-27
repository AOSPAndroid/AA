# Local Outlook inbox watcher

Atlas Live Inbox also supports [Teams and Outlook notification previews](notification-listener.md)
through an optional Windows listener. Both collectors use the same protected
queue and run independently under the normal Teams/Outlook account.

The optional watcher runs as a background Python process on the Windows PC
where classic Outlook (`OUTLOOK.EXE`) is open. It attaches to the existing
signed-in session through pywin32 and polls one selected Inbox every 5 seconds.
It does not need a Graph application registration or a separate Microsoft login.
Company Outlook programmatic-access settings still apply and may display an
access prompt; the watcher does not change those settings.

## Start and stop

For the integrated GUI and automatic BAT startup, use the
[Live Inbox setup guide](inbox-integration.md). The steps below are the standalone
workflow; the main GUI supervises the same watcher after integration is configured.

1. Run **windows\Install-Inbox-Collectors.bat** once on the Outlook PC. This installs the
   optional pywin32 dependency into the Python selected by `Python_Settings.bat`
   (Teams notifications are skipped without a package; email still works).
2. Open classic Outlook normally and allow the mailbox to synchronize.
3. Run `py -3.12 outlook_watcher.py start` from the Atlas folder, under the same
   Windows account and elevation level as Outlook. The process keeps running after
   the window closes.
4. `py -3.12 outlook_watcher.py status` shows whether it is watching, waiting for
   Outlook, retrying a read, or stopped, and how many messages it saved.
5. `py -3.12 outlook_watcher.py stop` requests a cooperative stop. If Outlook is
   displaying an access prompt, finish that prompt so the outstanding call can return.

Without integrated setup, this helper is independent of Atlas Admin/Demo.
With setup saved, every local Atlas launcher starts its normal-user supervisor,
and the Atlas stop scripts request collector shutdown. It is not a Windows
service and does not automatically start at Windows login.

## Collected data

Collection starts at the first run, without importing older Inbox history by
default. Later runs resume the checkpoint and catch up on messages received while
the watcher or Outlook was closed, provided they remain in the selected folder.

Each new mail item contributes its Outlook ID, thread ID, received time, sender,
subject, and plain-text body (at most 100,000 characters, with a truncation flag).
The watcher does not change read/unread state, move mail, send replies or run fixes.
Attachments and external links are not opened or downloaded.

By default, data stays in the current user's `%LOCALAPPDATA%\Atlas\OutlookWatcher`.
The two-account setup below uses a protected local shared folder instead. Both
locations contain:

- `inbox.sqlite3`: messages and collection checkpoints.
- `status.json`: process status, counts and last successful check, without email content.
- `watcher.lock` and `stop.json`: process/stop coordination.

This database is separate from Atlas's directory and knowledge databases.
Atlas Admin exposes read-only message views to the local browser. Mail is never
served by the LAN viewer or hosted Preview, or included in their builds/exports.

## Live Inbox in Atlas

Open **Workspace → Live Inbox** in Atlas Admin, or navigate to
`http://127.0.0.1:8770/installer?command=inbox`. The page checks the local queue
every two seconds while visible. The separate watcher continues collecting when
the page is closed. New rows appear without changing the message you are reading;
**Show newest** selects the latest arrival. Older messages remain accessible with
**Load older messages**.

Atlas matches the sender's SMTP email against stored emails and UPN aliases first.
If none match, it uses the exact full name. A name-only match is visibly marked for
verification. Duplicate names or addresses require choosing a candidate; machines
from different candidates are never combined. Machines come from the current
Atlas physical-device and VDI relationships, including separately labelled assigned
and historical logon links. These are stored inventory facts, not live device health.

Select **Open in Workspace** to continue with that person in the existing Atlas
tools. Receiving or selecting a message never runs remote diagnostics or repairs.
The mail body is rendered as plain text; links, HTML, scripts and attachments are
not executed. Suggested fixes and automatic replies are not part of this view.

The watcher always runs in Outlook's Windows account and at Outlook's elevation
level. Atlas can run under a different account using the local bridge below.
Without a bridge or `ATLAS_MAIL_DIR`, each account uses its own Local AppData,
so Atlas would otherwise see a different, empty inbox.

## Normal Outlook account and separate elevated Atlas account

For the described workstation:

| Process | Windows account | Role |
| --- | --- | --- |
| Outlook and the Python watcher | `x01426046` | Reads the signed-in `dallil.redouane@barclays.com` mailbox and writes the local queue |
| Elevated Atlas | `x01426046_dsk` | Reads the queue and matches senders against the Atlas database |

On that workstation, from the **elevated PowerShell used for Atlas**, run:

```powershell
$bridge = .\Configure-Outlook-Bridge.ps1 -MailUser 'x01426046' -AtlasUser 'x01426046_dsk'
$env:ATLAS_MAIL_DIR = $bridge.Directory
```

If Windows cannot resolve an account, use its `DOMAIN\username` value from
`whoami` in the corresponding account's PowerShell. The script resolves the
actual Windows SIDs and requires the current elevated identity to match
`-AtlasUser`. `-WhatIf` displays the plan without creating the bridge.

Setup creates a new queue folder beneath `%ProgramData%\Atlas\OutlookBridge`,
identified by the mail user's SID. Its ACL grants Modify to the mail account,
Read and Execute to the Atlas account, and Full Control to SYSTEM. Inherited
permissions are removed on that queue folder. There is no network share,
credential storage, service account login, or Outlook access by the admin account.
An existing folder with different permissions is rejected without changing it.

The script prints the exact `$env:ATLAS_MAIL_DIR = '...'` line. Copy that line
into a **normal PowerShell as `x01426046`**, then run:

```powershell
.\Install-Inbox-Collectors.bat  # once, using Python available to this account
py -3.12 outlook_watcher.py start
```

Keep classic Outlook open normally. In the elevated window, restart Atlas using
its usual launcher after setting `ATLAS_MAIL_DIR`. Open **Live Inbox**. Both
processes now use the same queue, while the watcher stays in the mailbox session.

Run watcher status and stop commands in the normal window. Environment settings
above apply to those PowerShell windows and their children: set the same value
again in a new window before launching. Do not start the watcher from an
Explorer process that has not inherited that setting. `--data-dir` overrides the
watcher's environment only; Atlas must still point to the matching directory.

Existing messages in the old per-user queue are not migrated automatically. Stop
the watcher before changing folders. A new bridge starts a new collection; use
`--lookback-hours 24` on its first start if yesterday's retained Inbox messages
should be collected. Live access across the two corporate accounts still needs
verification on the actual work PC.

## Inbox selection and options

List available stores in the running Outlook profile:

```powershell
py -3.12 outlook_watcher.py inboxes
```

The default is Outlook's primary Inbox. To choose another accessible store, use
its exact displayed name. Subfolders are relative to that store's Inbox; separate
nested folder names with `/`.

```powershell
py -3.12 outlook_watcher.py start --mailbox "IT Support" --subfolder "Incidents" --data-dir "$env:LOCALAPPDATA\Atlas\SupportWatcher"
py -3.12 outlook_watcher.py status --data-dir "$env:LOCALAPPDATA\Atlas\SupportWatcher"
py -3.12 outlook_watcher.py stop --data-dir "$env:LOCALAPPDATA\Atlas\SupportWatcher"
```

The folder identity and Outlook profile are pinned after the first connection.
Later starts with the same data folder reuse those settings. Use a different
`--data-dir` for a different inbox. Two processes cannot use the same data folder.

Optional first-time history import and a slower poll interval:

```powershell
py -3.12 outlook_watcher.py start --lookback-hours 24 --interval 30
```

`--lookback-hours` only applies to a new data folder; it does not reset an existing
collection. Maximum initial lookback: 720 hours. For one foreground attempt:

```powershell
py -3.12 outlook_watcher.py run --once
```

Exit 0 means a completed pass, 2 means Outlook unavailable/a failed COM read, and
1 means a configuration/startup error. A one-shot attempt exits, so its status
correctly reports `running: false` even if that pass completed.

## Recovery and limits

The watcher attaches without launching Outlook. It waits and retries when Outlook
is closed. Each pass checks a five-minute overlap; every fifteen minutes it
reconciles mail received since collection began to find late synchronization.
Table scans batch IDs and read bodies only for items not already stored. These
periodic scans can grow with a long-running collection.

Each message is committed separately. An unreadable item does not block collection
of other readable mail. A failed/interrupted pass does not advance the checkpoint;
retries do not duplicate saved IDs. Saved mail is retained until
the local database is removed while stopped; automatic retention is not implemented.

Only the selected folder is monitored. Rules that move messages out before a scan
can make them unavailable; select their destination folder when using such rules.
New Outlook is unsupported. The PC must be awake and the user logged in. Live
mailbox operation must be verified on the actual PC with its Outlook access policy.

Microsoft references: [running Outlook instances](https://learn.microsoft.com/en-us/office/client-developer/outlook/pia/how-to-get-and-log-on-to-an-instance-of-outlook),
[date filters and UTC](https://learn.microsoft.com/en-us/office/vba/outlook/how-to/search-and-filter/filtering-items-using-a-date-time-comparison),
[new-mail event limitations](https://learn.microsoft.com/en-us/office/vba/api/outlook.application.newmailex).
