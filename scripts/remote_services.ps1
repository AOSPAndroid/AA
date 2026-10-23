param(
    [Parameter(Mandatory = $true)][string]$Computer,
    [ValidateSet('list', 'stop', 'start', 'restart')][string]$Action = 'list',
    [string]$Name = '',
    [string]$ExpectedIdentity = ''
)
$ErrorActionPreference = 'Stop'

function Get-ServiceIdentity($Service) {
    # Detect a replaced/reconfigured service before issuing control commands.
    $value = [string]$Service.Name + "`n" + [string]$Service.PathName + "`n" + [string]$Service.ServiceType + "`n" + [string]$Service.StartName + "`n" + [string]$Service.StartMode
    $hash = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}
function Get-StopReason($Service) {
    if ($Service.Name -in @('RpcSs', 'DcomLaunch', 'RpcEptMapper', 'Winmgmt', 'WinRM', 'LanmanServer', 'EventLog')) {
        return 'Required for Windows or remote administration'
    }
    if ($Service.State -notin @('Running', 'Paused')) { return 'Service is not running or paused' }
    if (-not $Service.AcceptStop) { return 'Windows does not allow this service to be stopped' }
    return ''
}
function Get-StartReason($Service) {
    if ($Service.StartMode -eq 'Disabled') { return 'Startup is disabled; Atlas does not change the startup type' }
    if ($Service.State -ne 'Stopped') { return 'Service is not stopped' }
    return ''
}
function Get-RestartReason($Service) {
    $reason = Get-StopReason $Service
    if ($reason) { return $reason }
    if ($Service.StartMode -eq 'Disabled') { return 'Startup is disabled; restart would leave the service stopped' }
    return ''
}
function Get-ServiceItem($Service) {
    $stopReason = Get-StopReason $Service
    $startReason = Get-StartReason $Service
    $restartReason = Get-RestartReason $Service
    return @{name = [string]$Service.Name; display_name = [string]$Service.DisplayName; state = [string]$Service.State; start_mode = [string]$Service.StartMode; pid = [long]$Service.ProcessId; can_stop = (-not $stopReason); stop_reason = $stopReason; can_start = (-not $startReason); start_reason = $startReason; can_restart = (-not $restartReason); restart_reason = $restartReason; identity = (Get-ServiceIdentity $Service)}
}
function Write-ServiceResult($Outcome, $Service, $Message, $Code = $null, $Phase = '') {
    $item = $(if ($Service) { Get-ServiceItem $Service } else { $null })
    @{ok = $true; computer = $Computer; name = $Name; action = $Action; outcome = $Outcome; state = $(if ($Service) { [string]$Service.State } else { '' }); message = $Message; code = $Code; phase = $Phase; item = $item} | ConvertTo-Json -Depth 4 -Compress
}
function Read-Service($Service) {
    try { $null = $Service.Get() }
    catch {
        # WMI may remove a service between inventory and a refresh. Other failures remain unknown.
        $exception = $_.Exception
        while ($exception) {
            if ([string]$exception.ErrorCode -eq 'NotFound' -or $exception.HResult -eq -2147217406) { return 'gone' }
            $exception = $exception.InnerException
        }
        throw
    }
    if ((Get-ServiceIdentity $Service) -cne $ExpectedIdentity) { return 'changed' }
    return ''
}
function Write-ReadFailure($Issue, $Service, $Phase) {
    if ($Issue -eq 'gone') { Write-ServiceResult 'gone' $null 'Service is no longer installed. Refresh services; its final state could not be verified.' $null $Phase }
    else { Write-ServiceResult 'changed' $Service 'Service configuration changed. No further control was issued; refresh services to check the current state.' $null $Phase }
}
function Get-ControlMessage($Code, $Verb) {
    $messages = @{1 = 'Control is not supported'; 2 = 'Access denied'; 3 = 'Dependent services are running; they were not stopped'; 4 = 'Invalid service control'; 5 = 'Service cannot accept control'; 7 = 'Windows service control timed out'; 8 = 'Unknown Windows service failure'; 9 = 'Service executable was not found'; 11 = 'Service database is locked'; 12 = 'Service dependency was deleted'; 13 = 'Service dependency failed'; 14 = 'Startup is disabled'; 15 = 'Service logon failed'; 16 = 'Service is marked for deletion'; 22 = 'Service account is invalid'}
    $message = $messages[$Code]
    if (-not $message) { $message = "Windows rejected the $Verb request (code $Code)" }
    return $message
}
try {
    # Exact name comparison avoids building WQL from service names.
    $services = @(Get-WmiObject -ComputerName $Computer -Class Win32_Service -ErrorAction Stop)
    if ($Action -eq 'list') {
        $items = @($services | Sort-Object DisplayName, Name | ForEach-Object {
            Get-ServiceItem $_
        })
        @{ok = $true; computer = $Computer; collected_at = [DateTime]::UtcNow.ToString('o'); items = $items} | ConvertTo-Json -Depth 4 -Compress
        return
    }
    if (-not $Name -or $ExpectedIdentity -cnotmatch '^[a-f0-9]{64}$') { throw 'Refresh services before choosing a service to control' }
    $service = $services | Where-Object { $_.Name -ieq $Name } | Select-Object -First 1
    if (-not $service) { Write-ServiceResult 'gone' $null 'Service is no longer installed. Refresh services.'; return }
    $issue = Read-Service $service
    if ($issue) { Write-ReadFailure $issue $service 'before_control'; return }
    if ($Action -eq 'start') {
        if ($service.State -eq 'Running') { Write-ServiceResult 'already_running' $service 'Service is already running.'; return }
        $reason = Get-StartReason $service
    } elseif ($Action -eq 'restart') {
        $reason = Get-RestartReason $service
    } else {
        # Core services remain protected even if already stopped.
        if ($service.Name -in @('RpcSs', 'DcomLaunch', 'RpcEptMapper', 'Winmgmt', 'WinRM', 'LanmanServer', 'EventLog')) {
            Write-ServiceResult 'blocked' $service 'Required for Windows or remote administration'; return
        }
        if ($service.State -eq 'Stopped') { Write-ServiceResult 'already_stopped' $service 'Service is already stopped.'; return }
        $reason = Get-StopReason $service
    }
    if ($reason) { Write-ServiceResult 'blocked' $service $reason; return }
    if ($Action -in @('stop', 'restart')) {
        # Control only the selected service: no dependent stops, force, or shared-host termination.
        $code = [int]$service.StopService().ReturnValue
        if ($code -notin @(0, 6)) {
            $issue = Read-Service $service
            if ($issue) { Write-ReadFailure $issue $service 'stop'; return }
            Write-ServiceResult 'failed' $service (Get-ControlMessage $code 'stop') $code 'stop'; return
        }
        $stopped = $false
        for ($i = 0; $i -lt 40; $i++) {
            $issue = Read-Service $service
            if ($issue) { Write-ReadFailure $issue $service 'stop'; return }
            if ($service.State -eq 'Stopped') { $stopped = $true; break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $stopped) { Write-ServiceResult 'pending' $service 'Stop was accepted, but Stopped was not verified. No start was issued; refresh services to check the current state.' $code 'stop'; return }
        if ($Action -eq 'stop') { Write-ServiceResult 'stopped' $service 'Service stopped.' $code 'stop'; return }
        # Restart must observe the same stopped service again immediately before StartService.
        $issue = Read-Service $service
        if ($issue) { Write-ReadFailure $issue $service 'before_start'; return }
        $reason = Get-StartReason $service
        if ($reason) { Write-ServiceResult 'blocked' $service ("Restart did not start the service: $reason. Current state: $($service.State). Refresh services.") $null 'before_start'; return }
    }
    $code = [int]$service.StartService().ReturnValue
    if ($code -notin @(0, 10)) {
        $issue = Read-Service $service
        if ($issue) { Write-ReadFailure $issue $service 'start'; return }
        Write-ServiceResult 'failed' $service ((Get-ControlMessage $code 'start') + ". Running was not verified; current state: $($service.State). Refresh services before retrying.") $code 'start'; return
    }
    for ($i = 0; $i -lt 40; $i++) {
        $issue = Read-Service $service
        if ($issue) { Write-ReadFailure $issue $service 'start'; return }
        if ($service.State -eq 'Running') {
            $outcome = $(if ($Action -eq 'restart') { 'restarted' } else { 'started' })
            Write-ServiceResult $outcome $service 'Service is running.' $code 'start'; return
        }
        Start-Sleep -Milliseconds 250
    }
    Write-ServiceResult 'pending' $service 'Start was accepted, but Running was not verified. No retry was issued; refresh services to check the current state.' $code 'start'
} catch {
    @{ok = $false; computer = $Computer; error = $_.Exception.Message} | ConvertTo-Json -Compress
}
