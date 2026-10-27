# Live Inbox in the main Atlas GUI

Use **Atlas Admin > Workspace > Live Inbox**. Incoming
Outlook email and Teams/Outlook notification previews share one local feed,
sender lookup, candidate selection and linked-machine panel. Open in Workspace
selects the matched person in the existing Atlas tools. Messages never launch
diagnostics, deployments or fixes automatically.

## The message, and the people in it

The selected message comes first: subject, sender and the email itself (long emails
are folded; **Show the whole message** opens them). Machines and people Atlas finds in
it are highlighted: click a PC to check it, or a person to open their record.

**People** shows the sender and everyone **named in the message**, found in the
newest part of the email (quoted earlier replies are ignored):

- full names as people write them: "Marie Dupont", "DUPONT Marie", "Dupont, Marie",
  "Marie Dupont's laptop", "Bonjour Marie Dupont";
- email addresses and account IDs (X01426046).

Only names that exist in the Atlas directory are listed, with their account,
department, desk and PCs. A name shared by several people shows each of them to
choose from. The sender (their signature) and you (the Windows account running
Atlas, with or without its `_dsk` suffix) are left out. The PCs of the people named
are offered in the Request card's **Machine** list after the sender's, labelled with
their owner, so "install Visio for Marie" can go to Marie's laptop.

## Request tools: everything beside the message

**Details**, **Select**, **Health**, **Groups**, the **Suggested checks**, the package
buttons, Knowledge Base articles and the highlights open a third column next to the
message, so the email, the people and the results stay on screen. The PC there
becomes Atlas's current target (Workspace and Remote Admin follow it).

- **In this request**: the sender, the people named and every PC mentioned or linked,
  one click each. A PC brings its owner; a person brings their own PC.
- **Look up anyone**: name, account, email or PC name, for requests about someone
  who is not in the email.
- **Person**: the directory record (account, email, department, job role, location,
  manager, start date, last login), the desk from the floor plan, and every device
  with **Health**, **Performance** and **Deploy** for each PC. **Copy summary** copies
  it all.
- **Health**: ping, C$, WMI, CPU, RAM, GPU, C: space and uptime. **Select** runs the
  quick checks; **Health** scans everything.
- **Performance**: one sample of CPU, memory, C: free space, disk latency and
  uptime, what stands out, and the 12 busiest processes by CPU or memory.
  **End…** stops a process after you confirm. **Remote Admin ↗** opens the full
  view (threads, GPU).
- **PC groups** and **User groups**: the AD account first (disabled, locked out,
  password or account expired), then the groups, direct before primary before
  nested, with a filter and **Copy names**. **Compare with** a colleague (the other
  people in the request are offered, or type an account) lists the groups they have
  and this person lacks, ready to copy: "same access as…" requests in one step.
- **Deploy**: the Workspace deployment panel itself (package, Install, Repair or
  Uninstall, script, Advanced, Add to queue, progress and log). It goes back to
  Workspace when you close the tools or leave Live Inbox, with your choices kept.
- **Knowledge**: Knowledge Base articles suggested for the request (or under Seen
  before) open here, formatted, with **Copy text**. Diagrams open in the diagram
  viewer.
- **MSRA**, **C$**, **Remote Desktop**, **Computer Management**, **Software…**
  (installed applications, uninstall and repair), **Services…** (start, stop,
  restart), **Specs** and **Reboot…** (with its confirmation) at the top;
  **Workspace ↗** opens the person and PC there.

When a Live Inbox button opens another page (a diagram, Workspace, Active
Directory, Remote Admin), a **Back to Live Inbox** button appears at the bottom.
On screens narrower than 1280 pixels the message list hides while the tools are
open; close them (×) to see it again.

## Acting on a message

Each selected message shows a **Request** card and buttons on every machine:

- **Request type.** Atlas reads the subject and the newest part of the body
  (quoted earlier replies are ignored) in English or French. *Software request*
  means words like install, uninstall, reinstall or "can I have"; *Issue* lists
  recognised categories such as slow PC, application error, Outlook, Teams,
  network/VPN, printing, password or locked account, access, disk space and
  peripherals. These are keyword suggestions; check them before acting.
- **Machine.** Machines written in the message (for example `GBRPWMK20881521`)
  are checked against inventory and listed first, even when they are not linked
  to the sender. Otherwise the sender's linked Windows machines are offered.
  Phones and other inventory-only devices get no Windows actions.
- **Packages.** Product names in the message are matched against the package
  catalogue. **Install… / Uninstall… / Repair…** opens **Deploy** in the request
  tools beside the message with the machine, package, action and script selected;
  click the deploy button there.
  **Add to queue** adds it to the deployment queue, which still needs
  **Start queue**. If nothing matches, **Search catalogue** opens the package
  picker with the words after "install". Saved deployment kits can be added too.
- **Other names and typos.** Each catalogue package is linked to the same product
  in an offline copy of the Windows Package Manager index (`resources/winget_aliases.json.gz`,
  from github.com/microsoft/winget-pkgs, MIT), so "powerbi", "acrobat reader" or
  "visual studio code" find your packages even when their folder names differ.
  Close spellings ("acrobat reder") are matched with RapidFuzz. The card says why
  a package was suggested. Rebuild the alias file with
  `python tools/build_winget_aliases.py` (downloads about 20 MB).
- **Suggested checks** depend on the issue: performance scan, health check,
  reboot (with the usual confirmation), and the user's or machine's AD groups.
  They run in the request tools, without leaving Live Inbox (below).
- **Knowledge Base** shows articles and diagrams whose title or text mention the
  matched words. Articles tagged for the request's issue type (see **Suggest in
  Live Inbox for** in the article editor) come first.
- **Seen before** lists earlier requests and articles that share at least two
  distinctive words with this one (greetings, signatures, disclaimers found in
  most mail, hostnames and ticket numbers are ignored). Click a request to open
  it, or an article to read the fix you wrote last time. It uses the local search
  index (`search-index.sqlite3`), which picks up new mail by itself.
- **Machine buttons** (Select, Health, Groups, Reboot…) work on any listed machine.

The package list is read from the repository at most every two minutes. If the
package share or Knowledge Base is unavailable, the message still opens and the
card says which suggestions are missing.

**Ask Axis** (AA Admin only) opens the Axis chat with the message attached and a
suggested triage question. The Admin backend reads the message by ID and gives
it to Axis as untrusted evidence, never as your instructions; any change Axis
proposes still needs your approval. The LAN Viewer has no Ask Axis.

## Read from screen

For requests that arrive another way (a ServiceNow ticket, a Teams chat, a
phone call you typed up), use **Read from screen** at the top of Live Inbox:

- **Window in 3 s**: click it, then bring the ticket or chat to the front.
  After three seconds Atlas reads the text of the window in front.
- **Whole screen in 3 s**: the same for all monitors.
- **Clipboard**: reads the whole clipboard, no countdown: copied text (a
  hostname, an email, a Teams or Outlook message, copied as rich text too) or a
  screenshot copied with **Win+Shift+S**, which is read with text recognition.
  The browser reads it from your own session, so it works even though Atlas
  runs under another account. Edge asks once ("see text and images copied to
  the clipboard"); choose **Allow**. The badge next to the button shows
  *Clipboard allowed* (green) or *Clipboard blocked* (red). If it is blocked,
  Atlas falls back to reading the clipboard of the account it runs under.
- **Ctrl+V** anywhere on the Live Inbox page (outside a text box) does the
  same with whatever you paste: text or a screenshot. It needs no permission.

To stop the browser asking at all, double-click **windows\Allow-Atlas-Clipboard.bat**
as yourself (the account you browse with, not "Run as administrator" with
another account) and restart Edge. It adds `http://127.0.0.1:8770` and
`http://localhost:8770` to the per-user `ClipboardAllowedForUrls` policy of Edge
and Chrome, keeping any entries already there; `windows\Allow-Atlas-Clipboard.bat remove`
undoes it. If your company sets that policy for the whole PC, its setting wins.

The text is read with Windows' built-in text recognition (Windows.Media.Ocr),
so nothing is installed. Atlas then works out the person (email addresses in
the text first, then a name in the window title such as
`Chat | Alex Morgan | Microsoft Teams`), the machines and the request, exactly
as for an email, with the same Request card and machine buttons. Correct any
misread words in the text box and click **Analyse again**; if several people
share a name, choose the right one.

- It reads only your own Windows session: the account and desktop where Atlas
  Admin runs. It never captures another person's PC.
- The screenshot is a temporary file deleted straight after recognition. Text
  is analysed in memory and not saved. Demo and Preview do not offer it.
- If Atlas itself is still in front when the countdown ends, nothing is read;
  switch windows sooner and retry. Very small text reads better after zooming in.
- Recognition uses the languages installed for your Windows account.
- Text recognition can confuse look-alike characters in hostnames (0/O, 1/I/l,
  5/S, 8/B, 2/Z). If a machine name is not found exactly, Atlas retries with
  those characters treated as equal and shows "read as …" next to the machine
  it found. Only machines that exist in inventory are offered; check the name
  before acting. The same applies to mistyped names in emails.

> **Simpler option:** the [Atlas Companion](companion.md) reads classic Outlook from your normal
> account without the Windows task and shared folders below. Once it has connected, Live Inbox's
> Email watcher switch controls it. Teams notifications still use the listener described here.

## One-time setup on the work PC

1. Keep the Atlas checkout in a local folder readable by both Windows accounts.
   Use Python 3.12+ that the normal account can run. A Python installed only under
   the elevated account's private profile may not be accessible.
2. In the normal Outlook/Teams account (`x01426046`), run
   `windows\Install-Inbox-Collectors.bat "C:\Approved\Atlas.NotificationListener.msix"`
   with your approved, signed package. This installs pywin32 for classic Outlook
   and registers the notification package for that Windows account. Run without a package,
   `windows\Install-Inbox-Collectors.bat` sets up email and reports Teams notifications as
   skipped; add the package later to enable them.
   `WMI_PYTHON` can select the Python used by these BAT files.
3. Open Atlas from the usual elevated PowerShell (`x01426046_dsk`). In Live Inbox,
   the **Collectors and alerts** section opens by itself until collectors are connected. Enter the normal Windows account as
   `DOMAIN\x01426046` (use `whoami` in the normal session for the actual domain),
   and set the same Python executable used in step 2. Click **Connect and start collectors**.
   A path pasted with quotes is fine. If that Python is reached through a link or
   junction (for example `C:\devhome\tools\python3.12\current`), setup saves the real
   folder it points to, so the collectors keep running that exact Python. After a
   Python update replaces that folder, run this setup again.
4. Click **Listener settings**. Its window opens in the normal user's session.
   Select **Allow access and start** to grant Windows notification permission.
   Generate a Teams test notification and check the source list; select the
   installed Teams app if its ID differs from the built-in defaults.
5. Open classic Outlook normally for full emails. The watcher waits while it is
   closed. Both collectors continue when you switch Atlas pages or close its tab.

Setup creates an on-demand, limited Windows task using the normal account's
existing interactive sign-in. That account must be signed in on the same PC.
It does not store a password, create a Windows service, add a login trigger,
change notification permissions, enable Developer Mode, or trust certificates.
If workstation policy blocks task registration or package installation, Atlas
shows the error; the rest of the GUI remains available.

## Normal use

- `Start-Office-Atlas.bat` and `Start-All-Atlas.bat` use the same startup hook. After setup, they request collector startup once;
  repeated launches reuse the task and collector locks. Preview-only launchers
  do not start any local process.
- **Email watcher** and **Notification watcher** are always visible above the
  feed. Switches apply immediately and persist for the next Atlas launch. Email
  controls full classic Outlook messages; notifications controls Teams and the
  optionally selected Outlook previews. Turning on a switch after Stop starts
  only that source. Turning off the last source shuts down the supervisor.
- **Start collectors** and **Stop collectors** control the shared normal-user
  supervisor while retaining source preferences. The switches show Off while
  stopped. On means requested; the status badges above confirm actual readiness,
  waiting for Outlook, missing permission or errors. With email still on,
  notification Off pauses capture; the companion may remain in the tray.
- **Collectors and alerts** (folded away once collectors run; the watcher switches stay
  visible above it) holds Start/Stop, Listener settings, the optional Outlook preview
  setting, desktop alerts and connection details.
- **Listener settings** opens Windows consent and notification-source selection
  even when preview capture is disabled. Enabling Outlook previews alongside
  full emails can show both forms of the same incoming message.
- Every `Stop-*-Atlas.bat` requests cooperative collector shutdown before
  stopping the shared servers. A pending Outlook access prompt may delay its
  shutdown; finish that prompt in Outlook. Atlas never kills Outlook or Teams.
- Standalone watcher start/stop/status and notification start scripts also use
  the saved queue after setup. While the supervisor is running, use the GUI to
  stop a source; otherwise its saved preference may restart it.

An existing manually configured collector can still work without integrated
setup through `ATLAS_MAIL_DIR`. The integrated setup takes precedence once saved.
It does not move or delete any older queue. For the same accounts, an existing
bridge is reused only if its exact permissions match.

## Install Atlas as an app (PWA)

1. Start Atlas with the normal BAT launcher. Open **http://127.0.0.1:8770/installer**
   in Edge or Chrome under your normal Windows account. Keep using the same
   address and port; `localhost` is a different browser origin.
2. In **Live Inbox**, click **Install Atlas app**, then confirm the browser's
   installation dialog. If it is unavailable, use Edge's Apps menu or its address
   bar install icon. Organization policy may disable web-app installation.
3. Use **Atlas desktop alerts** to opt in to Windows notifications and accept the
   browser prompt. This is separate from the notification watcher, which reads
   selected Teams/Outlook notifications with the native companion's permission.

The installed app uses the same GUI. It gives
Atlas its own window and taskbar entry; it does not install or start the Python
server. Keep using the elevated Atlas launcher (`x01426046_dsk`) and the normal
mail user's collector task (`x01426046`). If the server is stopped, the app shows
startup instructions and a Retry link. A PWA cannot read another app's Windows
notifications or replace the native collectors.

Alerts poll a count-only local endpoint every five seconds while an Atlas window
is open, including minimized. Browser suspension, Do Not Disturb and organization
settings can delay or silence delivery. Closing all Atlas windows stops app
alerts; collector capture can continue until Stop Atlas. There is no cloud push
provider or closed-app background polling in this release.

The alert shows a new-item count, without names or message bodies. Clicking it
focuses Atlas and opens Live Inbox. Old items are skipped when enabling or opening
alerts. Concurrent windows in the same browser profile share a lock and cursor
to avoid duplicate alerts. Different browser profiles/origins have independent
settings. The service worker stores no UI, mail or API response cache; browser
storage contains only the alert preference and numeric cursor. Demo/Preview do
not expose the app capability or arrival-count endpoint.

OpenFin is a possible later wrapper if the workstation already has an approved
OpenFin deployment. Its runtime and Notification Center integration are separate
from a PWA; neither wrapper grants access to Outlook or Teams. No OpenFin runtime
or dependency is included here.

References: [Edge PWA installation](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/),
[Edge app notifications](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/notifications-badges),
[OpenFin Notification Center](https://developer.openfin.co/docs/services/notifications/stable/api/index.html).

## Accounts, data and control

`data/inbox-integration.json` stores local account names, paths and the task name;
it is ignored by Git and preserved by `Update-Atlas.bat`. No per-PC values are
committed. After moving the checkout, stop collectors and reconnect from the new
path to update the task action. Reconfiguration is allowed once its agent exits.

For different accounts, `%ProgramData%\Atlas\OutlookBridge\<mail-SID>` gives the
normal account Modify, the Atlas account ReadAndExecute, and SYSTEM FullControl.
Atlas's API opens SQLite read-only. A separate protected
`%ProgramData%\Atlas\InboxControl\<installation-id>` lets Atlas write desired
source states while the normal user has read access. The normal-user supervisor
accepts only start/stop/show and source preferences; it writes its own heartbeat
and bounded listener commands to the queue. No command field can name an
executable, script, recipient or remote machine.

Demo and hosted Preview show an Admin-only explanation and never request mail,
collector status or control APIs. Admin's loopback, host and origin checks apply
to these routes. Mail and notification text are never included in preview sync,
source uploads or the notification package.

## Installation package and troubleshooting

The repository includes a compiled development folder under
`notification-listener/package` and a validated **unsigned** MSIX under
`notification-listener`. The unsigned MSIX needs your organization's approved
signing/deployment process before production installation. Its publisher must
match the signing certificate. The installer can register the development
folder only where Developer Mode is already enabled.

To rebuild, run `Build-Notification-Listener.ps1`; add `-MakeAppxPath` pointing to
the Windows SDK's x64 `makeappx.exe` to create the unsigned MSIX in `output`.
Use `-Publisher` for your signing identity and `-IncludeTests` for native writer
tests. Build output is ignored by Git. The checked-in package has a SHA-256
manifest tying it to the listener sources.
After rebuilding both the loose folder and MSIX, run
`py -3.12 scripts/package_notification_listener.py` to refresh those distributable
files and their manifest. `tests/test_inbox_package.py` rejects stale packages.

- **Task never connects:** confirm the normal account is signed in, the configured
  Python and Atlas folder are readable by it, and inspect the saved
  `Atlas-Inbox-...` task's Last Run Result in Task Scheduler.
- **pywin32 missing:** install `requirements-outlook.txt` using the exact Python
  selected in Live Inbox, under the normal account.
- **Package missing / permission required:** install the signed package in the
  normal account, then use Listener settings. Subsequent Atlas starts reuse an
  existing grant and run the listener in the tray.
- **No Teams previews:** only notifications actually exposed to Windows are
  available. Hidden previews, app-only banners and notifications cleared between
  polls cannot supply complete messages. This is not a full Teams connector.
- **Changing accounts/Python:** Stop collectors, wait for shutdown, then use
  **Collectors and alerts > Change connection**. The equivalent script is
  `Configure-Inbox-Integration.ps1 -MailUser 'DOMAIN\user' -PythonPath 'C:\Python312\python.exe'`
  from the elevated Atlas account and relaunch Atlas. Old queues are retained.

Validation covers queue migration, sender matching, NTFS read-only handoff,
control/task definitions, duplicate starts, cooperative stop, source failures,
compiled GUI controls and simulated notifications. Actual work-PC policies,
the two domain accounts and notification consent still require on-device testing.
