window.AtlasPsExecCatalogue = [
  {
    "id": "identity",
    "category": "Diagnostics",
    "title": "Check execution identity",
    "description": "See the account and groups used on the remote machine.",
    "args": [
      "whoami.exe",
      "/all"
    ],
    "insight": "Use this to confirm the execution context before investigating an access problem.",
    "fields": []
  },
  {
    "id": "sessions",
    "category": "Sessions & Excel",
    "title": "Logged-on sessions",
    "description": "List session IDs, users and active/disconnected state.",
    "args": [
      "query.exe",
      "user"
    ],
    "insight": "Session IDs identify Windows sessions. Disconnected does not mean safe to log off.",
    "fields": []
  },
  {
    "id": "session-detail",
    "category": "Sessions & Excel",
    "title": "Session connection states",
    "description": "Inspect console and remote session names and states.",
    "args": [
      "query.exe",
      "session"
    ],
    "insight": "Useful alongside logged-on sessions when checking the machine hosting a Citrix desktop.",
    "fields": []
  },
  {
    "id": "excel",
    "category": "Sessions & Excel",
    "title": "Excel process snapshot",
    "description": "List Excel instances, sessions, resident RAM, CPU time and thread counts.",
    "script": "Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Select-Object Id,SessionId,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},@{n='CPU_seconds';e={$_.CPU}},@{n='Threads';e={$_.Threads.Count}},Responding | Format-Table -AutoSize",
    "insight": "CPU seconds are cumulative, not CPU utilization. Use Remote Admin CPU for a sampled percentage. Responding is not a diagnosis of workbook health.",
    "fields": []
  },
  {
    "id": "processes",
    "category": "Diagnostics",
    "title": "Processes and session owners",
    "description": "List running processes with session, user and memory information.",
    "args": [
      "tasklist.exe",
      "/v",
      "/fo",
      "table"
    ],
    "insight": "Tasklist is a snapshot; it does not provide current CPU or GPU utilization.",
    "fields": []
  },
  {
    "id": "memory",
    "category": "Diagnostics",
    "title": "Largest memory consumers",
    "description": "Show the 20 largest resident working sets with private memory and handles.",
    "script": "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 Name,Id,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},@{n='Private_MB';e={[math]::Round($_.PrivateMemorySize64/1MB,1)}},Handles | Format-Table -AutoSize",
    "insight": "Shared memory can appear in several processes. Do not add working sets to calculate total RAM usage.",
    "fields": []
  },
  {
    "id": "uptime",
    "category": "Diagnostics",
    "title": "Windows boot time and uptime",
    "description": "Get the last boot time, OS version and elapsed uptime.",
    "script": "$os=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Windows=$os.Caption;Version=$os.Version;LastBoot=$os.LastBootUpTime;Uptime=((Get-Date)-$os.LastBootUpTime).ToString()} | Format-List",
    "insight": "This executes one local CIM query on the target after PsExec connects.",
    "fields": []
  },
  {
    "id": "space",
    "category": "Diagnostics",
    "title": "Disk free space",
    "description": "Show fixed volumes, capacity and free space in GiB.",
    "script": "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,VolumeName,@{n='Size_GiB';e={[math]::Round($_.Size/1GB,1)}},@{n='Free_GiB';e={[math]::Round($_.FreeSpace/1GB,1)}} | Format-Table -AutoSize",
    "insight": "Capacity is not disk latency. Use Overview in Remote Admin for sampled disk response times.",
    "fields": []
  },
  {
    "id": "app-errors",
    "category": "Diagnostics",
    "title": "Recent application errors",
    "description": "Read the latest 30 application errors from the last 24 hours.",
    "script": "Get-WinEvent -FilterHashtable @{LogName='Application';Level=1,2;StartTime=(Get-Date).AddDays(-1)} -MaxEvents 30 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName,Message | Format-List",
    "insight": "Event messages may include workbook paths or user details. Review output before sharing a ticket.",
    "fields": []
  },
  {
    "id": "system-errors",
    "category": "Diagnostics",
    "title": "Recent system errors",
    "description": "Read the latest 30 system errors from the last 24 hours.",
    "script": "Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2;StartTime=(Get-Date).AddDays(-1)} -MaxEvents 30 -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName,Message | Format-List",
    "insight": "Match timestamps to the reported issue; an old error may be unrelated.",
    "fields": []
  },
  {
    "id": "ip",
    "category": "Networking",
    "title": "IP and DNS configuration",
    "description": "Inspect adapters, IP addresses, DNS servers and DHCP configuration.",
    "args": [
      "ipconfig.exe",
      "/all"
    ],
    "insight": "Shows the remote machine configuration, not the local kiosk configuration.",
    "fields": []
  },
  {
    "id": "dns",
    "category": "Networking",
    "title": "Resolve a hostname from the target",
    "description": "Check DNS resolution from the remote machine.",
    "fields": [
      {
        "key": "destination",
        "label": "Destination hostname or IPv4",
        "placeholder": "SERVER01",
        "pattern": "^(?![-.])(?!.*\\.\\.)[A-Za-z0-9_.-]{1,253}$"
      }
    ],
    "args": [
      "nslookup.exe",
      "{destination}"
    ],
    "insight": "Compare the answer with the affected application destination."
  },
  {
    "id": "tcp",
    "category": "Networking",
    "title": "Test a destination TCP port",
    "description": "Test one TCP connection from the target, for example to a file server.",
    "fields": [
      {
        "key": "destination",
        "label": "Destination hostname or IPv4",
        "placeholder": "SERVER01",
        "pattern": "^(?![-.])(?!.*\\.\\.)[A-Za-z0-9_.-]{1,253}$"
      },
      {
        "key": "port",
        "label": "TCP port",
        "placeholder": "445",
        "pattern": "^[0-9]{1,5}$"
      }
    ],
    "script": "Test-NetConnection -ComputerName '{destination}' -Port {port} -InformationLevel Detailed",
    "insight": "A successful TCP connection does not prove application performance. Test duration depends on the network timeout."
  },
  {
    "id": "connections",
    "category": "Networking",
    "title": "Connections and listening ports",
    "description": "Show current TCP/UDP endpoints and their process IDs.",
    "args": [
      "netstat.exe",
      "-ano"
    ],
    "insight": "Match the PID with the process list. Listening ports alone do not establish a problem.",
    "fields": []
  },
  {
    "id": "routes",
    "category": "Networking",
    "title": "Routing table",
    "description": "Inspect routes and interfaces used by the remote machine.",
    "args": [
      "route.exe",
      "print"
    ],
    "insight": "Useful when a destination is reached through an unexpected interface or gateway.",
    "fields": []
  },
  {
    "id": "services",
    "category": "Services",
    "title": "List services",
    "description": "List service names, display names and current state.",
    "script": "Get-Service | Sort-Object Status,Name | Format-Table Status,Name,DisplayName -AutoSize",
    "insight": "Use the service name, not its display name, in the service-specific templates.",
    "fields": []
  },
  {
    "id": "service",
    "category": "Services",
    "title": "Inspect one service",
    "description": "Read status, start mode, executable, account and PID for a named service.",
    "fields": [
      {
        "key": "service",
        "label": "Service name (not display name)",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_.$-]{1,128}$"
      }
    ],
    "script": "Get-CimInstance Win32_Service -Filter 'Name=''{service}''' | Select-Object Name,DisplayName,State,StartMode,StartName,ProcessId,PathName | Format-List",
    "insight": "The configured service account is not necessarily the identity running this diagnostic."
  },
  {
    "id": "dns-flush",
    "category": "Repairs",
    "title": "Flush the DNS cache",
    "description": "Clear cached DNS answers on the target.",
    "args": [
      "ipconfig.exe",
      "/flushdns"
    ],
    "change": true,
    "insight": "Changes the target DNS cache. Applications may need to resolve names again; this does not change DNS server settings.",
    "fields": []
  },
  {
    "id": "restart-service",
    "category": "Repairs",
    "title": "Restart one service",
    "description": "Stop and start a specific service after reviewing its dependencies.",
    "fields": [
      {
        "key": "service",
        "label": "Service name (not display name)",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_.$-]{1,128}$"
      }
    ],
    "script": "Restart-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize",
    "change": true,
    "insight": "Interrupts clients of the selected service. Does not force dependent services to stop. Agree the interruption with the affected users first."
  },
  {
    "id": "policy",
    "category": "Repairs",
    "title": "Refresh computer Group Policy",
    "description": "Reapply computer policy and wait up to 60 seconds for its status.",
    "args": [
      "gpupdate.exe",
      "/target:computer",
      "/force",
      "/wait:60"
    ],
    "change": true,
    "insight": "Reapplies policy on the target and can affect active work. It does not request an automatic reboot or logoff; some policies may still require one later.",
    "fields": []
  },
  {
    "id": "excel-stop",
    "category": "Repairs",
    "title": "End one Excel process",
    "description": "Stop only a reviewed Excel PID, without targeting all Excel instances.",
    "fields": [
      {
        "key": "pid",
        "label": "Excel process ID",
        "placeholder": "1234",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "script": "$p=Get-Process -Id {pid} -ErrorAction Stop; if($p.ProcessName -ne 'EXCEL'){throw 'This PID is not Excel'}; Stop-Process -InputObject $p -Confirm:$false",
    "change": true,
    "insight": "Can lose unsaved work. Recheck the PID before running and confirm in the terminal. For stronger creation-time identity checks, use Kill process in Remote Admin."
  },
  {
    "id": "shell",
    "category": "Terminal",
    "title": "Open a remote Command Prompt",
    "description": "Start an interactive Command Prompt in a selected Windows session, with input and output here.",
    "args": [
      "cmd.exe"
    ],
    "insight": "Uses PsExec -i with the session ID you enter. A console window may also appear on that remote desktop. Type exit to finish; commands run as the Atlas account and can change the target.",
    "interactive": true,
    "fields": [
      {
        "key": "session",
        "label": "Windows session ID (from Logged-on sessions)",
        "placeholder": "1",
        "pattern": "^[0-9]{1,5}$"
      }
    ]
  },
  {
    "id": "time-sync",
    "category": "Networking",
    "title": "Time synchronization status",
    "description": "Check Windows Time source and synchronization status.",
    "args": [
      "w32tm.exe",
      "/query",
      "/status"
    ],
    "insight": "Clock skew can affect authentication; this query does not change the clock."
  },
  {
    "id": "drivers",
    "category": "Diagnostics",
    "title": "Installed drivers",
    "description": "List installed driver names, types and status.",
    "args": [
      "driverquery.exe",
      "/fo",
      "table"
    ],
    "insight": "Compare relevant driver versions with your supported workstation baseline."
  },
  {
    "id": "updates",
    "category": "Diagnostics",
    "title": "Recent Windows hotfixes",
    "description": "List the 20 latest hotfix records exposed by Windows.",
    "script": "Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 20 HotFixID,Description,InstalledOn | Format-Table -AutoSize",
    "insight": "Get-HotFix does not list every update or application patch."
  },
  {
    "id": "tasks",
    "category": "Diagnostics",
    "title": "Scheduled task states",
    "description": "List scheduled tasks and current state.",
    "script": "Get-ScheduledTask | Select-Object TaskPath,TaskName,State | Format-Table -AutoSize",
    "insight": "This inspects tasks without starting or changing them."
  },
  {
    "id": "printers",
    "category": "Services",
    "title": "Configured printers",
    "description": "List printer queues, drivers, ports and status.",
    "script": "Get-Printer | Select-Object Name,DriverName,PortName,PrinterStatus | Format-Table -AutoSize",
    "insight": "Requires the PrintManagement module; user-specific printer visibility depends on execution context."
  },
  {
    "id": "print-jobs",
    "category": "Services",
    "title": "Pending print jobs",
    "description": "Show jobs in queues visible to the execution account.",
    "script": "Get-Printer | ForEach-Object { Get-PrintJob -PrinterName $_.Name -ErrorAction Continue } | Select-Object PrinterName,ID,UserName,JobStatus,SubmittedTime | Format-Table -AutoSize",
    "insight": "Lists jobs only; it does not clear queues or delete documents."
  },
  {
    "id": "start-service",
    "category": "Repairs",
    "title": "Start one service",
    "description": "Start a named Windows service.",
    "fields": [
      {
        "key": "service",
        "label": "Service name (not display name)",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_.$-]{1,128}$"
      }
    ],
    "script": "Start-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize",
    "change": true,
    "insight": "Starts the selected service and any required dependencies."
  },
  {
    "id": "stop-service",
    "category": "Repairs",
    "title": "Stop one service",
    "description": "Stop a named Windows service without forcing dependencies.",
    "fields": [
      {
        "key": "service",
        "label": "Service name (not display name)",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_.$-]{1,128}$"
      }
    ],
    "script": "Stop-Service -Name '{service}' -ErrorAction Stop; Get-Service -Name '{service}' | Format-Table Status,Name,DisplayName -AutoSize",
    "change": true,
    "insight": "Interrupts users of the service. Does not force dependent services to stop."
  },
  {
    "id": "netfx3-enable",
    "category": "Windows features & DISM",
    "title": "Enable .NET Framework 3.5",
    "description": "Enable the NetFx3 Windows feature and its dependencies.",
    "args": [
      "dism.exe",
      "/Online",
      "/Enable-Feature",
      "/FeatureName:NetFx3",
      "/All",
      "/NoRestart"
    ],
    "system": true,
    "change": true,
    "timeout_seconds": 3600,
    "success_exit_codes": [
      0,
      3010
    ],
    "insight": "Runs as SYSTEM (-s). Uses the target Windows repair source or Windows Update as permitted by policy. For Windows 10 and Windows 11 through 25H2; Windows 11 26H1 and later require the standalone installer. A restart may still be required.",
    "fields": []
  },
  {
    "id": "netfx3-status",
    "category": "Windows features & DISM",
    "title": "Check .NET Framework 3.5 status",
    "description": "Show whether the NetFx3 optional feature is enabled.",
    "args": [
      "dism.exe",
      "/Online",
      "/Get-FeatureInfo",
      "/FeatureName:NetFx3"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 180,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). NetFx3 is not a Windows feature on Windows 11 26H1 and later; check its standalone installation there.",
    "fields": []
  },
  {
    "id": "dism-features",
    "category": "Windows features & DISM",
    "title": "List Windows optional features",
    "description": "List feature names and their enabled or disabled state.",
    "args": [
      "dism.exe",
      "/Online",
      "/Get-Features",
      "/Format:Table"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 180,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). Available features vary by Windows version and edition. Use this list before planning a feature change.",
    "fields": []
  },
  {
    "id": "print-pdf-enable",
    "category": "Windows features & DISM",
    "title": "Enable Microsoft Print to PDF",
    "description": "Enable the built-in PDF printing feature where available.",
    "args": [
      "dism.exe",
      "/Online",
      "/Enable-Feature",
      "/FeatureName:Printing-PrintToPDFServices-Features",
      "/All",
      "/NoRestart"
    ],
    "system": true,
    "change": true,
    "timeout_seconds": 3600,
    "success_exit_codes": [
      0,
      3010
    ],
    "insight": "Runs as SYSTEM (-s). Availability depends on the target Windows edition and component source. No automatic restart is requested.",
    "fields": []
  },
  {
    "id": "dism-checkhealth",
    "category": "Windows features & DISM",
    "title": "DISM: quick health status",
    "description": "Check whether component-store corruption has already been flagged.",
    "args": [
      "dism.exe",
      "/Online",
      "/Cleanup-Image",
      "/CheckHealth"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 180,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). This reads the recorded corruption status; it does not perform a fresh full scan or repair.",
    "fields": []
  },
  {
    "id": "dism-scanhealth",
    "category": "Windows features & DISM",
    "title": "DISM: scan Windows image",
    "description": "Run a fresh component-store corruption scan.",
    "args": [
      "dism.exe",
      "/Online",
      "/Cleanup-Image",
      "/ScanHealth"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 3600,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). This can take several minutes and use CPU and disk. It diagnoses corruption without repairing it.",
    "fields": []
  },
  {
    "id": "dism-restorehealth",
    "category": "Windows features & DISM",
    "title": "DISM: repair Windows image",
    "description": "Scan and repair the running Windows component store.",
    "args": [
      "dism.exe",
      "/Online",
      "/Cleanup-Image",
      "/RestoreHealth",
      "/NoRestart"
    ],
    "system": true,
    "change": true,
    "timeout_seconds": 3600,
    "success_exit_codes": [
      0,
      3010
    ],
    "insight": "Runs as SYSTEM (-s). Uses the target repair source or Windows Update as permitted by policy. Can take a long time; stopping local PsExec does not guarantee the remote repair stops.",
    "fields": []
  },
  {
    "id": "dism-analyze-store",
    "category": "Windows features & DISM",
    "title": "DISM: analyse component store",
    "description": "Report component-store usage and whether cleanup is recommended.",
    "args": [
      "dism.exe",
      "/Online",
      "/Cleanup-Image",
      "/AnalyzeComponentStore"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 3600,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). Analysis only: this command does not delete packages or perform component cleanup.",
    "fields": []
  },
  {
    "id": "dism-packages",
    "category": "Windows features & DISM",
    "title": "List installed Windows packages",
    "description": "Show Windows servicing packages and their state.",
    "args": [
      "dism.exe",
      "/Online",
      "/Get-Packages",
      "/Format:Table"
    ],
    "system": true,
    "change": false,
    "timeout_seconds": 180,
    "success_exit_codes": [
      0
    ],
    "insight": "Runs as SYSTEM (-s). These are Windows servicing packages, not the full installed-applications inventory.",
    "fields": []
  },
  {
    "id": "pst-files",
    "tool": "PsFile",
    "category": "PsFile",
    "title": "List open shared files",
    "description": "Show files opened through network shares, not every local file handle.",
    "insight": "Show files opened through network shares, not every local file handle.",
    "args": [
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-file-close",
    "tool": "PsFile",
    "category": "PsFile",
    "title": "Close one shared file",
    "description": "Closes one file ID from PsFile. Unsaved writes may be lost; refresh the file list before choosing its ID.",
    "insight": "Closes one file ID from PsFile. Unsaved writes may be lost; refresh the file list before choosing its ID.",
    "args": [
      "{unc}",
      "{fileid}",
      "-c"
    ],
    "fields": [
      {
        "key": "fileid",
        "label": "Open file ID",
        "placeholder": "123",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-sid",
    "tool": "PsGetSid",
    "category": "PsGetSid",
    "title": "Computer SID",
    "description": "Resolve the selected computer SID.",
    "insight": "Resolve the selected computer SID.",
    "args": [
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-account-sid",
    "tool": "PsGetSid",
    "category": "PsGetSid",
    "title": "Resolve account or SID",
    "description": "Translate an account or SID on the selected machine.",
    "insight": "Translate an account or SID on the selected machine.",
    "args": [
      "{unc}",
      "{account}"
    ],
    "fields": [
      {
        "key": "account",
        "label": "Account or SID",
        "placeholder": "DOMAIN\\account",
        "pattern": "^[A-Za-z0-9_][A-Za-z0-9_.\\\\@-]{0,127}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-info",
    "tool": "PsInfo",
    "category": "PsInfo",
    "title": "System information and uptime",
    "description": "System summary including uptime. Requires permitted Remote Registry access. PsUptime is incorporated into PsInfo.",
    "insight": "System summary including uptime. Requires permitted Remote Registry access. PsUptime is incorporated into PsInfo.",
    "args": [
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-disks",
    "tool": "PsInfo",
    "category": "PsInfo",
    "title": "Disk volumes and free space",
    "description": "Show volume size and free space through PsInfo; Remote Registry access is required.",
    "insight": "Show volume size and free space through PsInfo; Remote Registry access is required.",
    "args": [
      "{unc}",
      "-d"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-software",
    "tool": "PsInfo",
    "category": "PsInfo",
    "title": "Installed software",
    "description": "Read registered software inventory; this may not include every per-user or packaged app.",
    "insight": "Read registered software inventory; this may not include every per-user or packaged app.",
    "args": [
      "{unc}",
      "-s"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-hotfixes",
    "tool": "PsInfo",
    "category": "PsInfo",
    "title": "Installed hotfixes",
    "description": "Show hotfix records reported by PsInfo.",
    "insight": "Show hotfix records reported by PsInfo.",
    "args": [
      "{unc}",
      "-h"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-ping",
    "tool": "PsPing",
    "category": "PsPing",
    "title": "Ping machine ten times",
    "description": "Measure connectivity from the Atlas host to this machine. This does not test the machine\u2019s outbound internet.",
    "insight": "Measure connectivity from the Atlas host to this machine. This does not test the machine\u2019s outbound internet.",
    "args": [
      "-n",
      "10",
      "{target}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-tcp",
    "tool": "PsPing",
    "category": "PsPing",
    "title": "TCP connection check",
    "description": "Test ten TCP connections from the Atlas host to the selected machine and port.",
    "insight": "Test ten TCP connections from the Atlas host to the selected machine and port.",
    "args": [
      "-n",
      "10",
      "{target}:{port}"
    ],
    "fields": [
      {
        "key": "port",
        "label": "TCP port",
        "placeholder": "443",
        "pattern": "^[0-9]{1,5}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-list",
    "tool": "PsList",
    "category": "PsList",
    "title": "Process snapshot",
    "description": "List process statistics using remote performance counters.",
    "insight": "List process statistics using remote performance counters.",
    "args": [
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-tree",
    "tool": "PsList",
    "category": "PsList",
    "title": "Process tree",
    "description": "Show parent and child processes.",
    "insight": "Show parent and child processes.",
    "args": [
      "{unc}",
      "-t"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-detail",
    "tool": "PsList",
    "category": "PsList",
    "title": "Process memory and threads",
    "description": "Inspect a single PID. PID values can be reused; check the current process first.",
    "insight": "Inspect a single PID. PID values can be reused; check the current process first.",
    "args": [
      "{unc}",
      "-x",
      "{pid}"
    ],
    "fields": [
      {
        "key": "pid",
        "label": "Process ID",
        "placeholder": "1234",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-kill",
    "tool": "PsKill",
    "category": "PsKill",
    "title": "Terminate one process",
    "description": "Terminates the selected PID. Unsaved work can be lost. Verify the PID immediately before running.",
    "insight": "Terminates the selected PID. Unsaved work can be lost. Verify the PID immediately before running.",
    "args": [
      "{unc}",
      "{pid}"
    ],
    "fields": [
      {
        "key": "pid",
        "label": "Process ID",
        "placeholder": "1234",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-loggedon",
    "tool": "PsLoggedOn",
    "category": "PsLoggedOn",
    "title": "Logged-on users and shares",
    "description": "Lists loaded user profiles and resource-share logons. Your own query can appear as a share logon.",
    "insight": "Lists loaded user profiles and resource-share logons. Your own query can appear as a share logon.",
    "args": [
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-local-logons",
    "tool": "PsLoggedOn",
    "category": "PsLoggedOn",
    "title": "Local logons only",
    "description": "Lists users with loaded profiles; this does not prove they are actively using the machine.",
    "insight": "Lists users with loaded profiles; this does not prove they are actively using the machine.",
    "args": [
      "-l",
      "{unc}"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-events",
    "tool": "PsLogList",
    "category": "PsLogList",
    "title": "Recent System events",
    "description": "Read the latest 100 System events without clearing the log.",
    "insight": "Read the latest 100 System events without clearing the log.",
    "args": [
      "{unc}",
      "-n",
      "100",
      "System"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-restart-events",
    "tool": "PsLogList",
    "category": "PsLogList",
    "title": "Restart and shutdown evidence",
    "description": "Read the last seven days of restart-related events. Interpret the messages together; an unexpected shutdown event alone does not establish its cause.",
    "insight": "Read the last seven days of restart-related events. Interpret the messages together; an unexpected shutdown event alone does not establish its cause.",
    "args": [
      "{unc}",
      "-d",
      "7",
      "-i",
      "41,1074,6005,6006,6008",
      "System"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-application-events",
    "tool": "PsLogList",
    "category": "PsLogList",
    "title": "Recent Application events",
    "description": "Read the latest 100 Application events without clearing the log.",
    "insight": "Read the latest 100 Application events without clearing the log.",
    "args": [
      "{unc}",
      "-n",
      "100",
      "Application"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-password-help",
    "tool": "PsPasswd",
    "category": "PsPasswd",
    "title": "Password tool help (local only)",
    "description": "Shows local PsPasswd usage only. Atlas does not collect or execute password changes. Use your approved password-management workflow; omitting NewPassword in PsPasswd applies a NULL password.",
    "insight": "Shows local PsPasswd usage only. Atlas does not collect or execute password changes. Use your approved password-management workflow; omitting NewPassword in PsPasswd applies a NULL password.",
    "args": [
      "-?"
    ],
    "fields": [],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-service-query",
    "tool": "PsService",
    "category": "PsService",
    "title": "Query service",
    "description": "Inspect the named service on the selected machine.",
    "insight": "Inspect the named service on the selected machine.",
    "args": [
      "{unc}",
      "query",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-service-config",
    "tool": "PsService",
    "category": "PsService",
    "title": "Config service",
    "description": "Inspect the named service on the selected machine.",
    "insight": "Inspect the named service on the selected machine.",
    "args": [
      "{unc}",
      "config",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-service-depend",
    "tool": "PsService",
    "category": "PsService",
    "title": "Depend service",
    "description": "Inspect the named service on the selected machine.",
    "insight": "Inspect the named service on the selected machine.",
    "args": [
      "{unc}",
      "depend",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": false,
    "direct": true
  },
  {
    "id": "pst-service-start",
    "tool": "PsService",
    "category": "PsService",
    "title": "Start service",
    "description": "Changes the selected service; dependent applications can be interrupted.",
    "insight": "Changes the selected service; dependent applications can be interrupted.",
    "args": [
      "{unc}",
      "start",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-service-stop",
    "tool": "PsService",
    "category": "PsService",
    "title": "Stop service",
    "description": "Changes the selected service; dependent applications can be interrupted.",
    "insight": "Changes the selected service; dependent applications can be interrupted.",
    "args": [
      "{unc}",
      "stop",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-service-restart",
    "tool": "PsService",
    "category": "PsService",
    "title": "Restart service",
    "description": "Changes the selected service; dependent applications can be interrupted.",
    "insight": "Changes the selected service; dependent applications can be interrupted.",
    "args": [
      "{unc}",
      "restart",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-service-pause",
    "tool": "PsService",
    "category": "PsService",
    "title": "Pause service",
    "description": "Changes the selected service; dependent applications can be interrupted.",
    "insight": "Changes the selected service; dependent applications can be interrupted.",
    "args": [
      "{unc}",
      "pause",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-service-cont",
    "tool": "PsService",
    "category": "PsService",
    "title": "Resume service",
    "description": "Changes the selected service; dependent applications can be interrupted.",
    "insight": "Changes the selected service; dependent applications can be interrupted.",
    "args": [
      "{unc}",
      "cont",
      "{service}"
    ],
    "fields": [
      {
        "key": "service",
        "label": "Service name",
        "placeholder": "Spooler",
        "pattern": "^[A-Za-z0-9_$.-]{1,128}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-reboot",
    "tool": "PsShutdown",
    "category": "PsShutdown",
    "title": "Restart with 60-second countdown",
    "description": "Requests restart in 60 seconds without forced application closure. Command completion is not proof the machine has rebooted.",
    "insight": "Requests restart in 60 seconds without forced application closure. Command completion is not proof the machine has rebooted.",
    "args": [
      "{unc}",
      "-r",
      "-t",
      "60"
    ],
    "fields": [],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-shutdown",
    "tool": "PsShutdown",
    "category": "PsShutdown",
    "title": "Shut down with 60-second countdown",
    "description": "Requests shutdown in 60 seconds without forced application closure. Ensure the user has saved their work.",
    "insight": "Requests shutdown in 60 seconds without forced application closure. Ensure the user has saved their work.",
    "args": [
      "{unc}",
      "-s",
      "-t",
      "60"
    ],
    "fields": [],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-abort",
    "tool": "PsShutdown",
    "category": "PsShutdown",
    "title": "Cancel pending shutdown",
    "description": "Attempts to cancel a pending shutdown on this machine.",
    "insight": "Attempts to cancel a pending shutdown on this machine.",
    "args": [
      "{unc}",
      "-a"
    ],
    "fields": [],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-suspend",
    "tool": "PsSuspend",
    "category": "PsSuspend",
    "title": "Suspend one process",
    "description": "Pauses a process; its locks and resources remain held. Do not suspend Windows or security processes. Use Resume for the same PID.",
    "insight": "Pauses a process; its locks and resources remain held. Do not suspend Windows or security processes. Use Resume for the same PID.",
    "args": [
      "{unc}",
      "{pid}"
    ],
    "fields": [
      {
        "key": "pid",
        "label": "Process ID",
        "placeholder": "1234",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "change": true,
    "direct": true
  },
  {
    "id": "pst-resume",
    "tool": "PsSuspend",
    "category": "PsSuspend",
    "title": "Resume one process",
    "description": "Resumes a previously suspended PID. Check that it still identifies the intended process.",
    "insight": "Resumes a previously suspended PID. Check that it still identifies the intended process.",
    "args": [
      "-r",
      "{unc}",
      "{pid}"
    ],
    "fields": [
      {
        "key": "pid",
        "label": "Process ID",
        "placeholder": "1234",
        "pattern": "^[1-9][0-9]{0,9}$"
      }
    ],
    "change": true,
    "direct": true
  }
];
