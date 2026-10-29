[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Configuration)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
if ($config.version -ne 1 -or $config.task_name -notmatch '^Atlas-Inbox-[a-f0-9]{16}$') { throw 'Invalid Atlas inbox configuration.' }
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$task = $service.GetFolder('\').GetTask($config.task_name)
$taskUser = $task.Definition.Principal.UserId
$taskSid = if ($taskUser -like 'S-1-*') { $taskUser } else { ([Security.Principal.NTAccount]$taskUser).Translate([Security.Principal.SecurityIdentifier]).Value }
if ($taskSid -ne $config.mail_sid -or $task.Definition.Principal.LogonType -ne 3 -or $task.Definition.Principal.RunLevel -ne 0) {
    throw 'The inbox task must use the configured mail account, InteractiveToken and Limited privileges. Reconnect it in Atlas.'
}
if (-not $task.Enabled) { throw 'The Atlas inbox task is disabled in Task Scheduler.' }
$task.Run($null) | Out-Null
# Cover a Start overlapping the previous agent's final cooperative Stop.
Start-Sleep -Milliseconds 750
if ($folder = $service.GetFolder('\')) {
    $task = $folder.GetTask($config.task_name)
    if ($task.State -ne 4) { $task.Run($null) | Out-Null }
}
Write-Output 'Collector task requested. The mail user must be signed in on this PC.'
