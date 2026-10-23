param(
    [string]$Computer,
    [ValidateSet('list', 'kill')][string]$Action = 'list',
    [ValidateSet('cpu', 'memory', 'gpu')][string]$Kind = 'cpu',
    [string]$Value = '',
    [ValidateSet('exact', 'contains')][string]$Match = 'exact',
    [string]$ExpectedCreated = '',
    [string]$ExpectedName = ''
)
$ErrorActionPreference = 'Stop'

function Get-BlockReason($Record) {
    if ([long]$Record.ProcessId -le 4 -or $Record.Name -in @(
        'System', 'Idle', 'Registry', 'Secure System', 'smss.exe', 'csrss.exe',
        'wininit.exe', 'services.exe', 'lsass.exe', 'winlogon.exe'
    )) { return 'Core Windows process' }
    if (-not $Record.CreationDate) { return 'Process identity unavailable; refresh the list' }
    return ''
}

try {
    if ($Action -eq 'kill') {
        if ($Match -eq 'contains') {
            $records = @(Get-WmiObject -ComputerName $Computer -Class Win32_Process -ErrorAction Stop |
                Where-Object { ([string]$_.Name).IndexOf($Value, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        } else {
            $filter = if ($Value -match '^\d+$') { "ProcessId=$Value" } else { "Name='$Value'" }
            $records = @(Get-WmiObject -ComputerName $Computer -Class Win32_Process -Filter $filter -ErrorAction Stop)
        }
        $results = @(
            foreach ($record in $records) {
                $reason = Get-BlockReason $record
                $state = 'blocked'
                if ($ExpectedCreated -and ($record.CreationDate -cne $ExpectedCreated -or $record.Name -ine $ExpectedName)) {
                    $reason = 'Process changed since this list was loaded. Refresh before trying again.'
                    $state = 'changed'
                }
                if (-not $reason) {
                    try {
                        $current = Get-WmiObject -ComputerName $Computer -Class Win32_Process -Filter "ProcessId=$($record.ProcessId)" -ErrorAction Stop
                        if (-not $current) {
                            $state = 'gone'; $reason = 'Process no longer exists'
                        } elseif ($current.CreationDate -cne $record.CreationDate -or $current.Name -ine $record.Name) {
                            $state = 'changed'; $reason = 'Process changed during termination. Review the target before trying again.'
                        } else {
                            $reason = Get-BlockReason $current
                            if (-not $reason) {
                                $code = $current.Terminate(1).ReturnValue
                                if ($null -eq $code) { throw 'Windows returned no termination result; refresh to check the process.' }
                                $state = if ($code -eq 0) { 'terminated' } else { 'failed' }
                                $reason = switch ([long]$code) {
                                    0 { 'Terminated' }
                                    2 { 'Access denied' }
                                    3 { 'Insufficient privilege' }
                                    8 { 'Windows reported an unknown failure' }
                                    9 { 'Process no longer exists' }
                                    21 { 'Windows rejected the process parameter' }
                                    default { "Windows returned error $code" }
                                }
                            }
                        }
                    } catch { $state = 'failed'; $reason = $_.Exception.Message }
                }
                [pscustomobject]@{ PID = [long]$record.ProcessId; Process = [string]$record.Name; state = $state; message = $reason }
            }
        )
        [pscustomobject]@{
            ok = $true
            count = @($results | Where-Object state -eq 'terminated').Count
            failed = @($results | Where-Object state -ne 'terminated').Count
            results = $results
        } | ConvertTo-Json -Depth 5 -Compress
        return
    }

    $processes = @(Get-WmiObject -ComputerName $Computer -Class Win32_Process -ErrorAction Stop)
    $metrics = @{}
    if ($Kind -eq 'cpu') {
        $cores = [math]::Max(1, (Get-WmiObject -ComputerName $Computer -Class Win32_ComputerSystem -ErrorAction Stop).NumberOfLogicalProcessors)
        foreach ($metric in (Get-WmiObject -ComputerName $Computer -Class Win32_PerfFormattedData_PerfProc_Process -ErrorAction Stop)) {
            if ($metric.IDProcess -gt 0) { $metrics[[long]$metric.IDProcess] = $metric }
        }
    } elseif ($Kind -eq 'gpu') {
        try {
            $engines = @(Get-WmiObject -ComputerName $Computer -Class Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop)
        } catch {
            throw "GPU counters are unavailable on $Computer. The driver or Citrix session may not expose them. $($_.Exception.Message)"
        }
        if (-not $engines.Count) { throw "No GPU counters are exposed on $Computer. CPU and Memory remain available." }
        foreach ($engine in $engines) {
            if ($engine.Name -match '^pid_(\d+)_') {
                $processId = [long]$Matches[1]
                if (-not $metrics.ContainsKey($processId) -or $engine.UtilizationPercentage -gt $metrics[$processId].UtilizationPercentage) {
                    $metrics[$processId] = $engine
                }
            }
        }
    }
    $rows = @(
        foreach ($record in $processes) {
            if ($record.ProcessId -eq 0) { continue }
            $processId = [long]$record.ProcessId
            if ($Kind -ne 'memory' -and -not $metrics.ContainsKey($processId)) { continue }
            $blocked = Get-BlockReason $record
            $row = [ordered]@{
                PID = $processId; Process = [string]$record.Name
                MemoryMB = [math]::Round([double]$record.WorkingSetSize / 1MB, 1)
                CreatedAt = [string]$record.CreationDate; SessionId = [long]$record.SessionId
                CommandLine = [string]$record.CommandLine
                CanTerminate = -not [bool]$blocked; BlockReason = $blocked
            }
            if ($Kind -eq 'cpu') { $row.CPU = [math]::Round([math]::Min(100, [double]$metrics[$processId].PercentProcessorTime / $cores), 1) }
            if ($Kind -eq 'gpu') {
                $row.GPU = [math]::Round([math]::Min(100, [double]$metrics[$processId].UtilizationPercentage), 1)
                $row.Engine = ($metrics[$processId].Name -split '_engtype_', 2)[-1]
            }
            [pscustomobject]$row
        }
    )
    $sort = switch ($Kind) { 'cpu' { 'CPU' }; 'gpu' { 'GPU' }; default { 'MemoryMB' } }
    [pscustomobject]@{ ok = $true; items = @($rows | Sort-Object $sort -Descending | Select-Object -First 30) } | ConvertTo-Json -Depth 5 -Compress
} catch {
    [pscustomobject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
