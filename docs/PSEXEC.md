# PsExec terminal and command workbench

Open **IT Console → PsTools**, below **History**. Atlas runs commands through your existing PsExec and adjacent PsTools executables and displays live output in the embedded terminal. There are **72 templates** across the tool families. Nothing starts when you open the page, select a machine or browse commands: click **Run on target** explicitly.

## Run a command

1. Select a machine in Workspace, or enter a hostname in PsExec. **Follow selected target** follows Workspace; manually entering another hostname does not change the deployment target.
2. Set your executable path, normally `C:\Data\PsExec.exe` or `C:\Data\PsExec64.exe`. It must exist on the computer hosting Atlas.
3. Choose a template, fill in its required fields and review **Command on target**. **Full PsExec command** shows the generated invocation; the server independently rebuilds the command from the same catalogue.
4. Click **Run on target**. A command marked **Changes target** asks you to type the target hostname before it starts.
5. Watch **Terminal** for output, state and exit code. **Follow output** scrolls with new output; disable it to inspect earlier lines. **Copy output** copies the transcript for a ticket.

The process inherits the account running Atlas. The terminal shows that account and whether the Atlas host process is elevated. Starting Atlas from elevated PowerShell does not guarantee that the account has remote permissions on every target. The optional **Use elevated token (-h)** requests an available elevated token on the target; it does not grant rights or switch accounts.

## Type commands directly

Choose **Open a remote Command Prompt**. Enter the Windows session ID shown by **Logged-on sessions**, then click Run. This uses PsExec's interactive-session option; a console window may also appear on that remote desktop. Type subsequent commands in the terminal input and press **Send** or Enter. Type `exit` to finish normally.

This is a line-oriented Command Prompt, not a full terminal emulator. Full-screen applications and interactive keystroke shortcuts are not supported. Commands typed in this session run with the Atlas account's permissions and can change the target. Template confirmation applies to repair templates; free-form commands execute when you explicitly send them. See [Microsoft's PsExec usage reference](https://learn.microsoft.com/en-us/sysinternals/downloads/psexec) for interactive sessions and account behavior.

## Session controls and limits

- **Stop session** ends the local PsExec process. It does not guarantee the remote command stopped; inspect the target before retrying.
- One PsExec session runs at a time per Atlas server. Ordinary commands have a three-minute limit; interactive sessions have a fifteen-minute limit. The PsExec connection attempt has its own ten-second limit.
- Changing the target or template does not redirect a running session. Its terminal retains the original hostname and command.
- **Refresh sessions** reconnects after a page reload or connection problem. **Recent sessions** opens retained transcripts. Start requests use unique run IDs to prevent duplicate starts after an uncertain response; Atlas does not automatically rerun a command.
- The latest 20 sessions are retained in memory, with up to 262,144 output characters each. Older output is trimmed and labelled. Transcripts are not written into deployment History and clear when Atlas restarts. A remote command could outlive that restart.
- Polling reads the local PsExec output only while a session is active. It does not create repeated WMI scans. Closing the tab does not cancel an already running session.

## First run and troubleshooting

Atlas checks that the selected tool exists on the Atlas host and that Atlas is running elevated. PsExec and all direct PsTools commands include `-accepteula`, including copied PowerShell/Command Prompt commands. Clicking **Run**, or executing a copied command, accepts the [Microsoft Sysinternals licence terms](https://learn.microsoft.com/en-us/sysinternals/license-terms) for that tool under the Windows account executing it. Opening the page, selecting a target, preparing or copying a command does not launch a tool or change licence acceptance. Atlas does not require a pre-existing acceptance registry entry or write that entry itself; the Microsoft executable handles first use. Atlas uses your existing tools and Windows account.

PsExec uses remote administrative connectivity and starts a service on the target. Access denied means checking account permissions, elevation and target policy. Connection errors call for checking hostname resolution, administrative shares and service-control connectivity. A command's nonzero exit status is shown in the terminal; it is not a successful run.

Repair commands can interrupt work. Ending Excel can lose unsaved changes; that template checks the process name, while Remote Admin's process action also performs creation-time identity checks. CPU time in Excel snapshots is cumulative seconds, not a utilization percentage. For sampled CPU/GPU activity, use [Remote Admin performance](REMOTE_ADMIN_PERFORMANCE.md).

## Copying and favourites

Copy remains available for a separate PowerShell or Command Prompt window. **Copy format** changes the clipboard syntax, not the server's execution method. PowerShell scripts use an encoded UTF-16LE payload to preserve quoting; the readable script is always displayed for review. Copied repair commands execute when you run them in your terminal; the Atlas Run confirmation does not apply outside Atlas.

Favourites, executable path and copy format are remembered in this browser. The target, command parameters and elevation choice are not saved as preferences. Elevation resets when selecting another template. In Atlas 7, Demo and the private preview show the entire command workbench: search templates, enter a target and parameters, review and copy commands. Run, Stop and terminal input are greyed out and require elevated Atlas Admin. Execution and transcripts are Admin-only; Demo and the private read-only preview expose none of these endpoints.

## Original PsExec templates

| Template | Required input beyond the target | Purpose |
| --- | --- | --- |
| **Check execution identity** | None | See the account and groups used on the remote machine. |
| **Logged-on sessions** | None | List session IDs, users and active/disconnected state. |
| **Session connection states** | None | Inspect console and remote session names and states. |
| **Excel process snapshot** | None | List Excel instances, sessions, resident RAM, CPU time and thread counts. |
| **Processes and session owners** | None | List running processes with session, user and memory information. |
| **Largest memory consumers** | None | Show the 20 largest resident working sets with private memory and handles. |
| **Windows boot time and uptime** | None | Get the last boot time, OS version and elapsed uptime. |
| **Disk free space** | None | Show fixed volumes, capacity and free space in GiB. |
| **Recent application errors** | None | Read the latest 30 application errors from the last 24 hours. |
| **Recent system errors** | None | Read the latest 30 system errors from the last 24 hours. |
| **IP and DNS configuration** | None | Inspect adapters, IP addresses, DNS servers and DHCP configuration. |
| **Resolve a hostname from the target** | Destination hostname or IPv4 | Check DNS resolution from the remote machine. |
| **Test a destination TCP port** | Destination hostname or IPv4; TCP port | Test one TCP connection from the target, for example to a file server. |
| **Connections and listening ports** | None | Show current TCP/UDP endpoints and their process IDs. |
| **Routing table** | None | Inspect routes and interfaces used by the remote machine. |
| **List services** | None | List service names, display names and current state. |
| **Inspect one service** | Service name (not display name) | Read status, start mode, executable, account and PID for a named service. |
| **Flush the DNS cache** | None | Clear cached DNS answers on the target. **Changes target.** |
| **Restart one service** | Service name (not display name) | Stop and start a specific service after reviewing its dependencies. **Changes target.** |
| **Refresh computer Group Policy** | None | Reapply computer policy and wait up to 60 seconds for its status. **Changes target.** |
| **End one Excel process** | Excel process ID | Stop only a reviewed Excel PID, without targeting all Excel instances. **Changes target.** |
| **Open a remote Command Prompt** | Windows session ID (from Logged-on sessions) | Start an interactive Command Prompt in a selected Windows session, with input and output here. |
| **Time synchronization status** | None | Check Windows Time source and synchronization status. |
| **Installed drivers** | None | List installed driver names, types and status. |
| **Recent Windows hotfixes** | None | List the 20 latest hotfix records exposed by Windows. |
| **Scheduled task states** | None | List scheduled tasks and current state. |
| **Configured printers** | None | List printer queues, drivers, ports and status. |
| **Pending print jobs** | None | Show jobs in queues visible to the execution account. |
| **Start one service** | Service name (not display name) | Start a named Windows service. **Changes target.** |
| **Stop one service** | Service name (not display name) | Stop a named Windows service without forcing dependencies. **Changes target.** |

## Complete command reference

These are commands or readable PowerShell payloads for the target, not complete local PsExec invocations. Generate the full invocation in Atlas. `{service}`, `{destination}`, `{port}` and `{pid}` below are filled from validated form fields. Interactive Command Prompt also requires the session ID for its PsExec `-i` option.

### Check execution identity

Diagnostics

See the account and groups used on the remote machine.

```bat
whoami.exe /all
```

Use this to confirm the execution context before investigating an access problem.

### Logged-on sessions

Sessions & Excel

List session IDs, users and active/disconnected state.

```bat
query.exe user
```

Session IDs identify Windows sessions. Disconnected does not mean safe to log off.

### Session connection states

Sessions & Excel

Inspect console and remote session names and states.

```bat
query.exe session
```

Useful alongside logged-on sessions when checking the machine hosting a Citrix desktop.

### Excel process snapshot

Sessions & Excel

List Excel instances, sessions, resident RAM, CPU time and thread counts.

```powershell
Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Select-Object Id,SessionId,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},@{n='CPU_seconds';e={$_.CPU}},@{n='Threads';e={$_.Threads.Count}},Responding | Format-Table -AutoSize
```

CPU seconds are cumulative, not CPU utilization. Use Remote Admin CPU for a sampled percentage. Responding is not a diagnosis of workbook health.

### Processes and session owners

Diagnostics

List running processes with session, user and memory information.

```bat
tasklist.exe /v /fo table
```

Tasklist is a snapshot; it does not provide current CPU or GPU utilization.

### Largest memory consumers

Diagnostics

Show the 20 largest resident working sets with private memory and handles.

```powershell
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 Name,Id,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},@{n='Private_MB';e={[math]::Round($_.PrivateMemorySize64/1MB,1)}},Handles | Format-Table -AutoSize
```

Shared memory can appear in several processes. Do not add working sets to calculate total RAM usage.

### Windows boot time and uptime

Diagnostics

Get the last boot time, OS version and elapsed uptime.

```powershell
$os=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Windows=$os.Caption;Version=$os.Version;LastBoot=$os.LastBootUpTime;Uptime=((Get-Date)-$os.LastBootUpTime).ToString()} | Format-List
```

This executes one local CIM query on the target after PsExec connects.

### Disk free space

Diagnostics

Show fixed volumes, capacity and free space in GiB.

```powershell
Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,VolumeName,@{n='Size_GiB';e={[math]::Round($_.Size/1GB,1)}},@{n='Free_GiB';e={[math]::Round($_.FreeSpace/1GB,1)}} | Format-Table -AutoSize
```

Capacity is not disk latency. Use Overview in Remote Admin for sampled disk response times.

### Recent application errors

Diagnostics

Read the latest 30 application errors from the last 24 hours.

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application';Level=1,2;StartTime=(Get-Date).AddDays(-1)} -MaxEvents 30 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName,Message | Format-List
```

Event messages may include workbook paths or user details. Review output before sharing a ticket.

### Recent system errors

Diagnostics

Read the latest 30 system errors from the last 24 hours.

```powershell
Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2;StartTime=(Get-Date).AddDays(-1)} -MaxEvents 30 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName,Message | Format-List
```

Match timestamps to the reported issue; an old error may be unrelated.

### IP and DNS configuration

Networking

Inspect adapters, IP addresses, DNS servers and DHCP configuration.

```bat
ipconfig.exe /all
```

Shows the remote machine configuration, not the local kiosk configuration.

### Resolve a hostname from the target

Networking

Check DNS resolution from the remote machine.

```bat
nslookup.exe {destination}
```

Compare the answer with the affected application destination.

### Test a destination TCP port

Networking

Test one TCP connection from the target, for example to a file server.

```powershell
Test-NetConnection -ComputerName '{destination}' -Port {port} -InformationLevel Detailed
```

A successful TCP connection does not prove application performance. Test duration depends on the network timeout.

### Connections and listening ports

Networking

Show current TCP/UDP endpoints and their process IDs.

```bat
netstat.exe -ano
```

Match the PID with the process list. Listening ports alone do not establish a problem.

### Routing table

Networking

Inspect routes and interfaces used by the remote machine.

```bat
route.exe print
```

Useful when a destination is reached through an unexpected interface or gateway.

### List services

Services

List service names, display names and current state.

```powershell
Get-Service | Sort-Object Status,Name | Format-Table Status,Name,DisplayName -AutoSize
```

Use the service name, not its display name, in the service-specific templates.

### Inspect one service

Services

Read status, start mode, executable, account and PID for a named service.

```powershell
Get-CimInstance Win32_Service -Filter 'Name=''{service}''' | Select-Object Name,DisplayName,State,StartMode,StartName,ProcessId,PathName | Format-List
```

The configured service account is not necessarily the identity running this diagnostic.

### Flush the DNS cache

Repairs · **Changes target**

Clear cached DNS answers on the target.

```bat
ipconfig.exe /flushdns
```

Changes the target DNS cache. Applications may need to resolve names again; this does not change DNS server settings.

### Restart one service

Repairs · **Changes target**

Stop and start a specific service after reviewing its dependencies.

```powershell
Restart-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize
```

Interrupts clients of the selected service. Does not force dependent services to stop. Agree the interruption with the affected users first.

### Refresh computer Group Policy

Repairs · **Changes target**

Reapply computer policy and wait up to 60 seconds for its status.

```bat
gpupdate.exe /target:computer /force /wait:60
```

Reapplies policy on the target and can affect active work. It does not request an automatic reboot or logoff; some policies may still require one later.

### End one Excel process

Repairs · **Changes target**

Stop only a reviewed Excel PID, without targeting all Excel instances.

```powershell
$p=Get-Process -Id {pid} -ErrorAction Stop; if($p.ProcessName -ne 'EXCEL'){throw 'This PID is not Excel'}; Stop-Process -InputObject $p -Confirm:$false
```

Can lose unsaved work. Recheck the PID before running and confirm in the terminal. For stronger creation-time identity checks, use Kill process in Remote Admin.

### Open a remote Command Prompt

Terminal

Start an interactive Command Prompt in a selected Windows session, with input and output here.

```bat
cmd.exe
```

Uses PsExec -i with the session ID you enter. A console window may also appear on that remote desktop. Type exit to finish; commands run as the Atlas account and can change the target.

### Time synchronization status

Networking

Check Windows Time source and synchronization status.

```bat
w32tm.exe /query /status
```

Clock skew can affect authentication; this query does not change the clock.

### Installed drivers

Diagnostics

List installed driver names, types and status.

```bat
driverquery.exe /fo table
```

Compare relevant driver versions with your supported workstation baseline.

### Recent Windows hotfixes

Diagnostics

List the 20 latest hotfix records exposed by Windows.

```powershell
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 20 HotFixID,Description,InstalledOn | Format-Table -AutoSize
```

Get-HotFix does not list every update or application patch.

### Scheduled task states

Diagnostics

List scheduled tasks and current state.

```powershell
Get-ScheduledTask | Select-Object TaskPath,TaskName,State | Format-Table -AutoSize
```

This inspects tasks without starting or changing them.

### Configured printers

Services

List printer queues, drivers, ports and status.

```powershell
Get-Printer | Select-Object Name,DriverName,PortName,PrinterStatus | Format-Table -AutoSize
```

Requires the PrintManagement module; user-specific printer visibility depends on execution context.

### Pending print jobs

Services

Show jobs in queues visible to the execution account.

```powershell
Get-Printer | ForEach-Object { Get-PrintJob -PrinterName $_.Name -ErrorAction Continue } | Select-Object PrinterName,ID,UserName,JobStatus,SubmittedTime | Format-Table -AutoSize
```

Lists jobs only; it does not clear queues or delete documents.

### Start one service

Repairs · **Changes target**

Start a named Windows service.

```powershell
Start-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize
```

Starts the selected service and any required dependencies.

### Stop one service

Repairs · **Changes target**

Stop a named Windows service without forcing dependencies.

```powershell
Stop-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize
```

Interrupts users of the service. Does not force dependent services to stop.

## Maintaining the catalogue

`psexec_catalogue.json` is the shared source for the server and browser. After editing it, run `py -3.12 tools/build_psexec_catalogue.py` to regenerate the browser asset. Tests verify that the generated catalogue matches the server definitions. The backend accepts template IDs and validated parameters, never a client-supplied script for a template run.
