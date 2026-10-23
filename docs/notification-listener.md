# Teams and Outlook notifications in Atlas

Atlas Admin's **Workspace > Live Inbox** combines full emails from the Outlook
watcher with **Teams preview** and optional **Outlook preview** records. Each
entry uses the same sender lookup and linked-machine view. Notification titles
are treated as possible display names: exact matches are marked for verification,
ambiguous matches require selecting a candidate, and chat/group titles are never
split into guessed identities. Opening a person in Workspace is an explicit action.

The Windows companion runs as the normal Teams/Outlook user. Atlas reads its local
SQLite queue; it never launches it using the elevated Atlas account. Mail and
notification processes operate independently. Email, notification text and queue
status are unavailable to Demo and the hosted Preview.

## Your two-account setup

The recommended workflow is now [Connect collectors inside Atlas](inbox-integration.md).
It saves both accounts and the queue, registers an interactive limited task, and
connects all Atlas launchers and the Live Inbox controls. The manual environment
assignments below are only needed for standalone use without that setup.

| Component | Windows account |
| --- | --- |
| Teams, Outlook, Outlook watcher, notification listener | `x01426046`, normal session |
| Atlas Admin | `x01426046_dsk`, elevated PowerShell |

Use the protected folder already created by `Configure-Outlook-Bridge.ps1`.
Set the same printed `ATLAS_MAIL_DIR` assignment in both PowerShell windows before
launching the relevant components. See [the account bridge instructions](outlook-watcher.md).
The normal user can write the queue; the Atlas account has read access. Collectors
do not store passwords or pass executable commands across the account boundary.

## Install and start on the work PC

Requires 64-bit Windows 10 version 2004 or later, .NET Framework 4.8, and a registered
Atlas Notification Listener package. The ZIP contains a compiled development
folder and a validated **unsigned** MSIX; the same files are in the repository's
`notification-listener` folder. An unsigned MSIX is not installable as a
production package. Use your organization's signing/deployment route for the
work PC; the package publisher must match its signing certificate.

1. Install the **signed** MSIX for `x01426046`. From a normal Windows PowerShell:
   `./Install-Notification-Listener.ps1 -PackagePath C:\Approved\Atlas-Notification-Listener.msix`
2. Set `ATLAS_MAIL_DIR` to the existing bridge folder, then run
   **Start-Notification-Listener.bat** (or `./Start-Notification-Listener.ps1`).
3. In the listener window, choose **Allow access and start**, and grant the Windows
   notification permission. Only Teams sources are saved initially. Enable
   **Also capture Outlook notification previews** if needed; the Outlook watcher
   already collects complete email, so enabling both can show two separate records.
4. Generate a **Test notification** in Teams notification settings, then receive a
   real incoming Teams message. Check the listener's source list and Atlas Live Inbox.
   A test notification may have a generic title and therefore no directory match.
   If Windows reports a different Teams app ID, explicitly select that app and
   choose **Use selected app as Teams**.
5. Minimize the listener to the tray to keep collecting. With integrated setup,
   Atlas starts it in the tray after consent has been granted. Use Atlas's source
   switches or Stop collectors to pause it persistently; closing the companion
   alone may cause the supervisor to restart it. Standalone mode has no startup
   task. The source settings and queue location are remembered.

Atlas shows separate Outlook and notification status, including permission denial,
retrying, stopped and stale heartbeat states. **Collectors and alerts > Connection details** contains setup
reminders and the last successful checks. The browser and Windows listener poll
every two seconds.

## What is captured

The listener uses Windows `UserNotificationListener`, with its declared manifest
capability and Windows consent. It reads current notification snapshots and stores
only selected Teams/Outlook sources. It does not read notification databases,
browser profiles, Teams caches or screenshots; dismiss notifications; send replies;
mark messages read; or execute message content. Browser-wide capture is excluded
because one browser can carry notifications from unrelated sites.

Only text supplied in the Windows notification is available. It may omit email
addresses, include a chat/group name instead of a sender, hide text, or truncate a
long message. Atlas always labels it as a preview. Notifications dismissed between
polls, already cleared while the listener was stopped, or never published to
Windows cannot be recovered this way. Teams app-only banners are not supported by
this connector. **Listening** confirms Windows access, not complete Teams coverage.

On the first successful start, collection begins at that time. Restarts resume
from that boundary and deduplicate snapshots that remain in Notification Center.
A changed preview is retained as another entry; it is not asserted to be a distinct
chat message. Windows notification IDs can be reused, so creation time and content
also participate in deduplication. Existing Outlook history and checkpoints are
preserved during the additive queue migration.

## Build and deployment

`Build-Notification-Listener.ps1` compiles the .NET Framework companion with
the Windows C# compiler. Its only build download is Microsoft's pinned
`Microsoft.Windows.SDK.Contracts` 10.0.19041.2 NuGet package. The target PC needs
neither Python for this listener nor a new .NET runtime; Atlas and the separate
Outlook watcher retain their existing Python requirements.

```powershell
./Build-Notification-Listener.ps1 -IncludeTests `
  -Publisher 'CN=Your approved package publisher' `
  -MakeAppxPath 'C:\Path\To\WindowsSDK\x64\makeappx.exe'
```

This creates `output/Atlas-Notification-Listener` and an unsigned MSIX. Sign the
MSIX with the matching approved certificate using the Windows SDK SignTool, then
install it for the normal user. The build does not install certificates, change
Windows policy, register the package, grant consent or read notifications.

For a development PC **already configured for Developer Mode**, running
`Install-Notification-Listener.ps1` without `-PackagePath` registers the compiled
folder. Keep that folder in place. The script does not enable Developer Mode or
bypass an organization's installation policy. For production use the signed MSIX.

Validation performed locally: compilation and MSIX manifest validation; real
Windows SQLite writer interoperating with Python; legacy history migration;
source filtering; deduplication and notification-ID reuse; matching and pagination;
permission/stale status rendering; safe text display and private viewer boundary.
Live Windows consent and actual Teams/Outlook banner delivery must be verified in
the intended account on the work PC. No fix-suggestion engine is included in this
integration.

References: [Windows notification listener](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/notification-listener),
[Teams notifications](https://support.microsoft.com/en-us/teams/notifications-settings/manage-notifications-in-microsoft-teams),
[development package registration](https://learn.microsoft.com/en-us/windows/apps/develop/testing/loose-file-registration).
