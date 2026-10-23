# Simulated Win32_Service objects. No real provider or service control is used.
$ErrorActionPreference = 'Stop'
class AtlasFixtureNotFoundException : System.Exception {
    [string]$ErrorCode = 'NotFound'
    AtlasFixtureNotFoundException() : base('Simulated removed service') {}
}
$global:AtlasServiceCalls = [System.Collections.Generic.List[string]]::new()
function New-TestService($Name, $State = 'Running', $Options = @{}) {
    $s = [pscustomobject]@{Name = $Name; DisplayName = "Display $Name"; State = $State; StartMode = 'Auto'; ProcessId = $(if ($State -eq 'Stopped') { 0 } else { 1234 }); AcceptStop = ($State -in @('Running', 'Paused')); PathName = 'C:\Test\service.exe'; ServiceType = 'Own Process'; StartName = 'LocalSystem'; StopCode = 0; StartCode = 0; StopPending = $false; StartPending = $false; Phase = ''; PhaseReads = 0; Reads = 0; ChangeAtRead = 0; DisableAtRead = 0; GoneAtRead = 0; RunAtRead = 0}
    foreach ($key in $Options.Keys) { $s.$key = $Options[$key] }
    $s | Add-Member ScriptMethod Get {
        $this.Reads++
        if ($this.GoneAtRead -and $this.Reads -ge $this.GoneAtRead) { throw [AtlasFixtureNotFoundException]::new() }
        if ($this.ChangeAtRead -and $this.Reads -ge $this.ChangeAtRead) { $this.PathName = 'C:\Test\replacement.exe' }
        if ($this.DisableAtRead -and $this.Reads -ge $this.DisableAtRead) { $this.StartMode = 'Disabled' }
        if ($this.Phase) {
            $this.PhaseReads++
            $pending = $(if ($this.Phase -eq 'stop') { $this.StopPending } else { $this.StartPending })
            if (-not $pending -and $this.PhaseReads -ge 2) {
                if ($this.Phase -eq 'stop') { $this.State = 'Stopped'; $this.ProcessId = 0; $this.AcceptStop = $false }
                else { $this.State = 'Running'; $this.ProcessId = 9000; $this.AcceptStop = $true }
                $this.Phase = ''
            }
        }
        if ($this.RunAtRead -and $this.Reads -ge $this.RunAtRead) { $this.State = 'Running'; $this.AcceptStop = $true; $this.ProcessId = 9100 }
    }
    $s | Add-Member ScriptMethod StopService {
        $global:AtlasServiceCalls.Add("stop:$($this.Name):$($this.State)")
        if ($this.StopCode -eq 0) { $this.Phase = 'stop'; $this.PhaseReads = 0; $this.State = 'Stop Pending' }
        elseif ($this.StopCode -eq 6) { $this.State = 'Stopped'; $this.ProcessId = 0; $this.AcceptStop = $false }
        return [pscustomobject]@{ReturnValue = $this.StopCode}
    }
    $s | Add-Member ScriptMethod StartService {
        if ($this.State -ne 'Stopped') { throw 'Fixture: StartService was called before Stopped was verified' }
        if ($this.StartMode -eq 'Disabled') { throw 'Fixture: startup type was overridden or disabled service was started' }
        $global:AtlasServiceCalls.Add("start:$($this.Name):$($this.State)")
        if ($this.StartCode -eq 0) { $this.Phase = 'start'; $this.PhaseReads = 0; $this.State = 'Start Pending' }
        elseif ($this.StartCode -eq 10) { $this.State = 'Running'; $this.ProcessId = 9200; $this.AcceptStop = $true }
        return [pscustomobject]@{ReturnValue = $this.StartCode}
    }
    return $s
}
function Get-WmiObject {
    param($ComputerName, $Class, $ErrorAction)
    if ($ComputerName -ne 'TESTPC' -or $Class -ne 'Win32_Service') { throw 'Unexpected service provider query' }
    return $global:AtlasServices
}
function Start-Sleep { param($Milliseconds) } # Bounded polling is instantaneous in this fixture.
$scriptPath = Join-Path $PSScriptRoot '../scripts/remote_services.ps1'
$global:AtlasServices = @(
    foreach ($n in 1..155) { New-TestService "Unrelated$n" }
    New-TestService TestService
    New-TestService RestartSuccess
    New-TestService PausedService 'Paused'
    New-TestService RpcSs
    New-TestService Winmgmt
    New-TestService CannotStop 'Running' @{AcceptStop = $false}
    New-TestService AlreadyStopped 'Stopped'
    New-TestService DisabledStopped 'Stopped' @{StartMode = 'Disabled'}
    New-TestService DisabledRunning 'Running' @{StartMode = 'Disabled'}
    New-TestService ChangedBeforeControl 'Stopped' @{ChangeAtRead = 1}
    New-TestService ChangedDuringStop 'Running' @{ChangeAtRead = 2}
    New-TestService ChangedBeforeStart 'Running' @{ChangeAtRead = 4}
    New-TestService ChangedDuringStart 'Running' @{ChangeAtRead = 5}
    New-TestService DisabledBeforeStart 'Running' @{DisableAtRead = 4}
    New-TestService RunningBeforeStart 'Running' @{RunAtRead = 4}
    New-TestService GoneDuringStop 'Running' @{GoneAtRead = 2}
    New-TestService GoneBeforeStart 'Running' @{GoneAtRead = 4}
    New-TestService GoneDuringStart 'Stopped' @{GoneAtRead = 2}
    New-TestService HasDependents 'Running' @{StopCode = 3}
    New-TestService AccessDenied 'Running' @{StopCode = 2}
    New-TestService PendingStop 'Running' @{StopPending = $true}
    New-TestService PendingStart 'Stopped' @{StartPending = $true}
    New-TestService RestartPendingStart 'Running' @{StartPending = $true}
    New-TestService RestartStartDenied 'Running' @{StartCode = 2}
    New-TestService StartDependencyFailed 'Stopped' @{StartCode = 13}
    New-TestService StopCodeSix 'Running' @{StopCode = 6}
    New-TestService StartCodeTen 'Stopped' @{StartCode = 10}
    New-TestService 'a180-service'
    foreach ($state in @('Start Pending', 'Stop Pending', 'Continue Pending', 'Pause Pending')) { New-TestService ("Transition-" + $state.Replace(' ', '')) $state }
)
$list = (& $scriptPath -Computer TESTPC -Action list) | ConvertFrom-Json
if (-not $list.ok -or $list.items.Count -ne $global:AtlasServices.Count) { throw 'Service list omitted records' }
foreach ($name in @('RpcSs', 'Winmgmt', 'CannotStop', 'AlreadyStopped')) {
    $item = $list.items | Where-Object name -eq $name
    if ($item.can_stop -or $item.can_restart) { throw "$name should not allow Stop/Restart" }
}
if (-not ($list.items | Where-Object name -eq 'AlreadyStopped').can_start) { throw 'Stopped service omitted Start capability' }
if (($list.items | Where-Object name -eq 'DisabledStopped').can_start -or ($list.items | Where-Object name -eq 'DisabledRunning').can_restart) { throw 'Disabled startup was not reflected in capabilities' }
function Invoke-Control($Name, $Action = 'stop', $Identity = '') {
    if (-not $Identity) { $Identity = ($list.items | Where-Object name -eq $Name).identity }
    return (& $scriptPath -Computer TESTPC -Action $Action -Name $Name -ExpectedIdentity $Identity) | ConvertFrom-Json
}
function Assert-Outcome($Result, $Outcome, $State) {
    if (-not $Result.ok -or $Result.outcome -ne $Outcome -or $Result.state -ne $State) { throw "Unexpected result: $($Result | ConvertTo-Json -Compress)" }
    if ($Outcome -eq 'gone') { if ($null -ne $Result.item) { throw 'Gone service retained an actionable snapshot' } }
    elseif ($Result.item.state -ne $State -or $Result.item.name -ine $Result.name) { throw 'Result snapshot does not reflect the observed service' }
}
$success = Invoke-Control TestService
Assert-Outcome $success stopped Stopped
if (-not $success.item.can_start -or $success.item.can_stop -or $success.item.pid -ne 0) { throw 'Stop did not expose a fresh Start capability' }
$count = $global:AtlasServiceCalls.Count
Assert-Outcome (Invoke-Control TestService) already_stopped Stopped
if ($global:AtlasServiceCalls.Count -ne $count) { throw 'Already stopped service was controlled again' }
$started = Invoke-Control TestService start $success.item.identity
Assert-Outcome $started started Running
if ($started.item.can_start -or -not $started.item.can_stop -or -not $started.item.can_restart -or $started.item.pid -ne 9000) { throw 'Start did not expose refreshed Stop/Restart capabilities' }
$count = $global:AtlasServiceCalls.Count
Assert-Outcome (Invoke-Control TestService start $started.item.identity) already_running Running
if ($global:AtlasServiceCalls.Count -ne $count) { throw 'Already running service was started again' }
foreach ($name in @('RpcSs', 'Winmgmt', 'CannotStop')) {
    foreach ($action in @('stop', 'restart')) { Assert-Outcome (Invoke-Control $name $action) blocked Running }
}
Assert-Outcome (Invoke-Control DisabledStopped start) blocked Stopped
Assert-Outcome (Invoke-Control DisabledRunning restart) blocked Running
Assert-Outcome (Invoke-Control DisabledRunning start) already_running Running
if ($global:AtlasServiceCalls.Count -ne $count) { throw 'Protected/disabled services were controlled' }
Assert-Outcome (Invoke-Control RestartSuccess restart) restarted Running
Assert-Outcome (Invoke-Control PausedService restart) restarted Running
foreach ($name in @('RestartSuccess', 'PausedService')) {
    $calls = @($global:AtlasServiceCalls | Where-Object { $_ -like "*:${name}:*" })
    if ($calls.Count -ne 2 -or $calls[0] -notlike 'stop:*' -or $calls[1] -ne "start:${name}:Stopped") { throw 'Restart did not stop, verify Stopped, then start the exact service' }
}
$count = $global:AtlasServiceCalls.Count
Assert-Outcome (Invoke-Control ChangedBeforeControl start) changed Stopped
Assert-Outcome (Invoke-Control CannotStop stop ('a' * 64)) changed Running
foreach ($state in @('Start Pending', 'Stop Pending', 'Continue Pending', 'Pause Pending')) {
    foreach ($action in @('start', 'stop', 'restart')) { Assert-Outcome (Invoke-Control ("Transition-" + $state.Replace(' ', '')) $action) blocked $state }
}
if ($global:AtlasServiceCalls.Count -ne $count) { throw 'Changed/transitional service received an unintended control' }
Assert-Outcome (Invoke-Control ChangedDuringStop restart) changed 'Stop Pending'
Assert-Outcome (Invoke-Control ChangedBeforeStart restart) changed Stopped
Assert-Outcome (Invoke-Control ChangedDuringStart restart) changed 'Start Pending'
Assert-Outcome (Invoke-Control DisabledBeforeStart restart) changed Stopped
Assert-Outcome (Invoke-Control RunningBeforeStart restart) blocked Running
foreach ($name in @('ChangedDuringStop', 'ChangedBeforeStart', 'DisabledBeforeStart', 'RunningBeforeStart')) {
    if (@($global:AtlasServiceCalls | Where-Object { $_ -like "start:${name}:*" }).Count) { throw 'Restart started after identity, startup or state changed' }
}
Assert-Outcome (Invoke-Control GoneDuringStop restart) gone ''
Assert-Outcome (Invoke-Control GoneBeforeStart restart) gone ''
Assert-Outcome (Invoke-Control GoneDuringStart start) gone ''
$dependents = Invoke-Control HasDependents restart
Assert-Outcome $dependents failed Running
if ($dependents.message -notlike '*Dependent services*' -or @($global:AtlasServiceCalls | Where-Object { $_ -like 'start:HasDependents:*' }).Count) { throw 'Dependency stop failure was ignored' }
Assert-Outcome (Invoke-Control AccessDenied stop) failed Running
$pending = Invoke-Control PendingStop restart
Assert-Outcome $pending pending 'Stop Pending'
if ($pending.phase -ne 'stop' -or @($global:AtlasServiceCalls | Where-Object { $_ -like 'start:PendingStop:*' }).Count) { throw 'Restart started without a verified stop' }
Assert-Outcome (Invoke-Control PendingStart start) pending 'Start Pending'
$pendingStart = Invoke-Control RestartPendingStart restart
Assert-Outcome $pendingStart pending 'Start Pending'
if ($pendingStart.phase -ne 'start' -or @($global:AtlasServiceCalls | Where-Object { $_ -like 'start:RestartPendingStart:*' }).Count -ne 1) { throw 'Pending restart was retried or its phase hidden' }
$denied = Invoke-Control RestartStartDenied restart
Assert-Outcome $denied failed Stopped
if ($denied.message -notlike '*current state: Stopped*' -or -not $denied.item.can_start -or @($global:AtlasServiceCalls | Where-Object { $_ -like 'start:RestartStartDenied:*' }).Count -ne 1) { throw 'Failed restart hid the stopped state or started repeatedly' }
Assert-Outcome (Invoke-Control StartDependencyFailed start) failed Stopped
Assert-Outcome (Invoke-Control StopCodeSix stop) stopped Stopped
Assert-Outcome (Invoke-Control StartCodeTen start) started Running
$global:AtlasServices = @($global:AtlasServices | Where-Object Name -ne 'a180-service')
Assert-Outcome (Invoke-Control 'a180-service') gone ''
if (@($global:AtlasServiceCalls | Where-Object { $_ -like '*:Unrelated*' -or $_ -like '*:RpcSs:*' -or $_ -like '*:Winmgmt:*' -or $_ -like '*:DisabledStopped:*' -or $_ -like '*:DisabledRunning:*' }).Count) { throw 'An unrelated, core or disabled service was controlled' }
$global:AtlasServices = @()
$empty = (& $scriptPath -Computer TESTPC -Action list) | ConvertFrom-Json
if (-not $empty.ok -or $empty.items.Count -ne 0) { throw 'Empty service list was not an array' }
Write-Output 'PASS: exact Start/Stop/Restart, refreshed capabilities, idempotence, stop-before-start ordering, disabled/core protection, dependencies, pending/failed phases, identity/absence checks and no unintended controls'
