# Inspect setup using real ACL and Task Scheduler definition objects. Never register a task.
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$path = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows\Configure-Inbox-Integration.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($name in @('New-InboxControlAcl', 'New-InboxTaskDefinition')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$atlas = [Security.Principal.WindowsIdentity]::GetCurrent().User
$mail = [Security.Principal.SecurityIdentifier]'S-1-5-21-100-200-300-9999'
$acl = New-InboxControlAcl $atlas $mail
$rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 3) { throw 'Control folder must have three protected grants.' }
$mailRule = @($rules | Where-Object { $_.IdentityReference.Value -eq $mail.Value })[0]
if ($mailRule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Write) { throw 'Normal user must not change privileged controller settings.' }
if (@($rules | Where-Object { $_.IdentityReference.Value -in @('S-1-1-0','S-1-5-11','S-1-5-32-545','S-1-5-32-544') }).Count) { throw 'Unexpected broad grant.' }
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$task = New-InboxTaskDefinition $service $atlas.Value 'C:\Atlas Folder' 'C:\Atlas Control\config.json'
$actualUser = $task.Principal.UserId
$actualSid = if ($actualUser -like 'S-1-*') { $actualUser } else { ([Security.Principal.NTAccount]$actualUser).Translate([Security.Principal.SecurityIdentifier]).Value }
if ($task.Principal.LogonType -ne 3 -or $task.Principal.RunLevel -ne 0 -or $actualSid -ne $atlas.Value) { throw 'Task must use the mail user, InteractiveToken and Limited.' }
if ($task.Triggers.Count -ne 0 -or $task.Settings.MultipleInstances -ne 2) { throw 'Task must be on-demand and ignore duplicate starts.' }
if ($task.Actions.Item(1).Arguments -notmatch '-WindowStyle Hidden' -or $task.Actions.Item(1).Arguments -match 'Bypass') { throw 'Unexpected task command.' }
if ($task.Actions.Item(1).Arguments -notmatch '"C:\\Atlas Folder\\windows\\Run-Inbox-Agent.ps1"') { throw 'Paths with spaces must stay quoted.' }
Write-Output 'PASS: private control ACL, interactive limited task, no logon trigger, duplicate start prevention, quoted hidden launch. No task registered.'
