<# One-time setup from elevated Atlas. No password, logon trigger, or policy change. #>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$MailUser,
    [Parameter(Mandatory = $true)][string]$PythonPath
)
$ErrorActionPreference = 'Stop'

function Assert-LocalInboxPath([string]$Path) {
    if ($Path.StartsWith('\\') -or $Path.Contains('"')) { throw 'Use a local Atlas folder without quotes in its path.' }
    $probe = [IO.DirectoryInfo]::new($Path)
    while ($null -ne $probe) {
        if ($probe.Exists -and ($probe.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Inbox setup does not follow links or junctions: $($probe.FullName)" }
        $probe = $probe.Parent
    }
}

function Resolve-LinkedPath([string]$Path) {
    # Tool installs often reach Python through a link (for example ...\python3.12\current). Follow
    # junctions and symbolic links once, here, and keep the real folder: it is then checked like any
    # other path, so re-pointing the link later cannot change what the task runs. Other reparse
    # points (cloud placeholders and similar) are left for Assert-LocalInboxPath to refuse.
    $current = [IO.Path]::GetFullPath($Path)
    for ($hop = 0; $hop -lt 32; $hop++) {
        $root = [IO.Path]::GetPathRoot($current)
        $parts = @($current.Substring($root.Length).Split([char[]]@('\', '/'), [StringSplitOptions]::RemoveEmptyEntries))
        $prefix = $root
        $followed = $false
        for ($i = 0; $i -lt $parts.Count; $i++) {
            $prefix = Join-Path $prefix $parts[$i]
            $item = Get-Item -LiteralPath $prefix -Force -ErrorAction SilentlyContinue
            if ($null -eq $item -or -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
            if ($item.LinkType -notin @('Junction', 'SymbolicLink')) { return $current }
            $target = [string](@($item.Target)[0]) -replace '^\\\\\?\\|^\\\?\?\\', ''
            if (-not $target) { return $current }
            if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path (Split-Path -Parent $prefix) $target }
            if ($i + 1 -lt $parts.Count) { $target = Join-Path $target ($parts[($i + 1)..($parts.Count - 1)] -join [IO.Path]::DirectorySeparatorChar) }
            $current = [IO.Path]::GetFullPath($target)
            $followed = $true
            break
        }
        if (-not $followed) { return $current }
    }
    throw "Too many links in $Path"
}

function New-InboxControlAcl($AtlasSid, $MailSid) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($AtlasSid)
    foreach ($sid in @($AtlasSid, [Security.Principal.SecurityIdentifier]'S-1-5-18')) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    if ($MailSid.Value -ne $AtlasSid.Value) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($MailSid, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    return $acl
}

function New-ProtectedInboxDirectory([string]$Path, $Acl) {
    Assert-LocalInboxPath $Path
    if (Test-Path -LiteralPath $Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Expected an inbox directory.' }
        $actual = Get-Acl -LiteralPath $Path
        $sections = [Security.AccessControl.AccessControlSections]'Owner,Access'
        if ($actual.GetSecurityDescriptorSddlForm($sections) -ne $Acl.GetSecurityDescriptorSddlForm($sections)) {
            throw "Existing inbox folder has different permissions; nothing was changed: $Path"
        }
        return
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    Assert-LocalInboxPath $Path
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [IO.FileSystemAclExtensions]::Create([IO.DirectoryInfo]::new($Path), $Acl)
    } else { [IO.Directory]::CreateDirectory($Path, $Acl) | Out-Null }
}

function Write-InboxJson([string]$Path, $Value) {
    if ((Test-Path -LiteralPath $Path) -and ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Inbox configuration must not be a link.' }
    $temp = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temp, ($Value | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp, $Path, $null) }
        else { [IO.File]::Move($temp, $Path) }
    } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp } }
}

function New-InboxTaskDefinition($Service, [string]$MailSid, [string]$Root, [string]$Configuration) {
    $definition = $Service.NewTask(0)
    $definition.RegistrationInfo.Description = 'Atlas Inbox agent: ' + $Root
    $definition.Principal.UserId = $MailSid
    $definition.Principal.LogonType = 3 # InteractiveToken: existing signed-in session, no password.
    $definition.Principal.RunLevel = 0 # Limited: same elevation as Outlook/Teams.
    $definition.Settings.MultipleInstances = 2 # IgnoreNew, plus the agent's queue lock.
    $definition.Settings.ExecutionTimeLimit = 'PT0S'
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.AllowDemandStart = $true
    $definition.Settings.Hidden = $true
    $definition.Settings.RestartCount = 3
    $definition.Settings.RestartInterval = 'PT1M'
    $action = $definition.Actions.Create(0)
    $action.Path = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + (Join-Path $Root 'Run-Inbox-Agent.ps1') + '" -Configuration "' + $Configuration + '"'
    $action.WorkingDirectory = $Root
    return $definition
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))) {
    throw 'Open Atlas from your elevated PowerShell for this one-time setup.'
}
$atlasSid = $identity.User
$mailSid = ([Security.Principal.NTAccount]$MailUser).Translate([Security.Principal.SecurityIdentifier])
if ($mailSid.Value -notlike 'S-1-5-21-*' -or $atlasSid.Value -notlike 'S-1-5-21-*') { throw 'Use named Windows user accounts.' }
$mailAccount = $mailSid.Translate([Security.Principal.NTAccount]).Value
$python = Resolve-LinkedPath ((Resolve-Path -LiteralPath $PythonPath).Path)
if ((Split-Path -Leaf $python) -notin @('python.exe', 'pythonw.exe') -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Select a Python 3.12+ python.exe that the mail account can run.' }
Assert-LocalInboxPath $python
Assert-LocalInboxPath $PSScriptRoot
$hash = [Security.Cryptography.SHA256]::Create()
try { $key = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToLowerInvariant() + '|' + $atlasSid.Value + '|' + $mailSid.Value)))).Replace('-', '').Substring(0, 16).ToLowerInvariant() }
finally { $hash.Dispose() }
$taskName = 'Atlas-Inbox-' + $key
$control = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) ('Atlas\InboxControl\' + $key)
$agentConfig = Join-Path $control 'config.json'
$data = Join-Path $PSScriptRoot 'data'
Assert-LocalInboxPath $data
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$existing = @($folder.GetTasks(1) | Where-Object { $_.Name -eq $taskName })
if ($existing.Count -and $existing[0].Definition.RegistrationInfo.Description -ne ('Atlas Inbox agent: ' + $PSScriptRoot)) { throw 'A different application already owns the inbox task name.' }
if (-not $PSCmdlet.ShouldProcess($mailAccount, 'Prepare private inbox folders and a limited, on-demand interactive task for Atlas')) { return }

if ($mailSid.Value -ne $atlasSid.Value) {
    $bridge = & (Join-Path $PSScriptRoot 'Configure-Outlook-Bridge.ps1') -MailUser $mailAccount -AtlasUser $identity.Name 6>$null
    $directory = $bridge.Directory
} else {
    $directory = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) ('Atlas\OutlookBridge\' + $mailSid.Value)
    New-ProtectedInboxDirectory $directory (New-InboxControlAcl $atlasSid $mailSid)
}
New-ProtectedInboxDirectory $control (New-InboxControlAcl $atlasSid $mailSid)
$config = [ordered]@{version = 1; directory = $directory; control_directory = $control; mail_user = $mailAccount; mail_sid = $mailSid.Value; atlas_user = $identity.Name; atlas_sid = $atlasSid.Value; task_name = $taskName; python = $python}
Write-InboxJson $agentConfig $config
if (-not (Test-Path -LiteralPath (Join-Path $control 'desired.json'))) {
    Write-InboxJson (Join-Path $control 'desired.json') @{running = $false; outlook = $true; notifications = $true; outlook_previews = $false}
}
$definition = New-InboxTaskDefinition $service $mailSid.Value $PSScriptRoot $agentConfig
$sddl = 'D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;' + $atlasSid.Value + ')'
if ($mailSid.Value -ne $atlasSid.Value) { $sddl += '(A;;GRGX;;;' + $mailSid.Value + ')' }
$folder.RegisterTaskDefinition($taskName, $definition, 6, $mailSid.Value, $null, 3, $sddl) | Out-Null
[IO.Directory]::CreateDirectory($data) | Out-Null
Write-InboxJson (Join-Path $data 'inbox-integration.json') $config
Write-Output 'Inbox connected. Start collectors in Atlas; notification package installation and consent belong to the normal mail account.'
