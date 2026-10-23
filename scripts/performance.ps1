param(
    [string]$Computer,
    [ValidateSet('overview', 'cpu', 'gpu', 'memory', 'threads', 'diagnose')][string]$Kind = 'cpu',
    [long]$ProcessId = 0,
    [string]$ExpectedCreated = '',
    [string]$ExpectedName = ''
)
$ErrorActionPreference = 'Stop'
$warnings = [System.Collections.Generic.List[string]]::new()
$queryCount = 0
# Each explicit scan requests only its providers and fields. No wildcard reads.
$includeCpu = $Kind -in @('overview', 'cpu', 'diagnose')
$includeMemory = $Kind -in @('overview', 'memory', 'diagnose')
$includeGpu = $Kind -in @('overview', 'gpu')
$includeDisk = $Kind -in @('overview', 'diagnose')
$queryProperties = @{
    Win32_ComputerSystem = @('NumberOfLogicalProcessors', 'Model')
    Win32_Process = @('ProcessId', 'Name', 'CreationDate', 'WorkingSetSize', 'ThreadCount', 'HandleCount', 'SessionId')
    Win32_PerfRawData_PerfProc_Process = @('IDProcess', 'ElapsedTime', 'PercentProcessorTime', 'Timestamp_Sys100NS', 'Timestamp_PerfTime', 'Frequency_PerfTime', 'IODataBytesPersec', 'PageFaultsPersec', 'PrivateBytes')
    Win32_PerfRawData_PerfOS_Processor = @('Name', 'PercentProcessorTime', 'Timestamp_Sys100NS')
    Win32_PerfRawData_PerfDisk_PhysicalDisk = @('Name', 'Timestamp_PerfTime', 'Frequency_PerfTime', 'AvgDisksecPerRead', 'AvgDisksecPerRead_Base', 'AvgDisksecPerWrite', 'AvgDisksecPerWrite_Base', 'CurrentDiskQueueLength', 'DiskReadBytesPersec', 'DiskWriteBytesPersec')
    Win32_OperatingSystem = @('TotalVisibleMemorySize', 'FreePhysicalMemory', 'Caption', 'LastBootUpTime', 'LocalDateTime')
    Win32_PerfFormattedData_PerfOS_Memory = @('CommittedBytes', 'CommitLimit', 'PageReadsPersec')
    Win32_PerfFormattedData_PerfOS_System = @('ProcessorQueueLength', 'ContextSwitchesPersec', 'Threads')
    Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine = @('Name', 'UtilizationPercentage')
    Win32_LogicalDisk = @('DeviceID', 'Size', 'FreeSpace')
    Win32_PerfRawData_PerfProc_Thread = @('IDProcess', 'IDThread', 'ElapsedTime', 'Timestamp_Sys100NS', 'Timestamp_PerfTime', 'Frequency_PerfTime', 'PercentProcessorTime', 'ContextSwitchesPersec', 'ThreadState', 'ThreadWaitReason', 'PriorityCurrent')
}
if ($Kind -ne 'diagnose') {
    $queryProperties.Win32_Process = @('ProcessId', 'Name', 'CreationDate', 'SessionId', 'CommandLine')
    $queryProperties.Win32_PerfRawData_PerfProc_Process = @('IDProcess', 'ElapsedTime', 'Timestamp_PerfTime', 'Frequency_PerfTime')
    if ($includeCpu) {
        $queryProperties.Win32_Process += 'ThreadCount'
        $queryProperties.Win32_PerfRawData_PerfProc_Process += @('PercentProcessorTime', 'Timestamp_Sys100NS')
    }
    if ($includeMemory) {
        $queryProperties.Win32_Process += @('WorkingSetSize', 'HandleCount')
        $queryProperties.Win32_PerfRawData_PerfProc_Process += @('PrivateBytes', 'PageFaultsPersec')
    }
    if ($includeDisk) { $queryProperties.Win32_PerfRawData_PerfProc_Process += 'IODataBytesPersec' }
    if ($Kind -eq 'overview') { $queryProperties.Win32_ComputerSystem += 'UserName' }
    if ($Kind -in @('cpu', 'threads')) { $queryProperties.Win32_ComputerSystem = @('NumberOfLogicalProcessors') }
    if ($Kind -eq 'memory') { $queryProperties.Win32_OperatingSystem = @('TotalVisibleMemorySize', 'FreePhysicalMemory') }
}
function Query($Class, $Filter = '', [switch]$Required, [string[]]$Properties = @()) {
    try {
        $args = @{ComputerName = $Computer; Class = $Class; ErrorAction = 'Stop'}
        if ($Filter) { $args.Filter = $Filter }
        if (-not $Properties.Count) { $Properties = $queryProperties[$Class] }
        if (-not $Properties.Count) { throw 'This provider is not part of the selected scan' }
        $args.Property = $Properties
        $script:queryCount++
        $data = @(Get-WmiObject @args)
        if (-not $data.Count) { throw 'No counters returned' }
        return $data
    } catch {
        if ($Required) { throw }
        $message = "${Class}: $($_.Exception.Message)"
        if (-not $warnings.Contains($message)) { $warnings.Add($message) }
    }
}
function Index($Records, $Key) {
    $table = @{}
    foreach ($record in $Records) { $table[[string]$record.$Key] = $record }
    return $table
}
function Number($Value) {
    if ($null -ne $Value) { return [double]$Value }
    return $null
}
function Percent($Part, $Total) {
    if ($null -eq $Part -or $null -eq $Total -or $Total -le 0) { return $null }
    return [math]::Round([math]::Max([double]0, [math]::Min([double]100, 100 * [double]$Part / [double]$Total)), 1)
}
# Raw values must be differenced using the provider's timestamps, not wall time.
function Rate($Before, $After, $Field, [switch]$Cpu, [switch]$Inverse) {
    if (-not $Before -or -not $After -or $null -eq $Before.$Field -or $null -eq $After.$Field) { return $null }
    $clock = if ($Cpu) { 'Timestamp_Sys100NS' } else { 'Timestamp_PerfTime' }
    if ($null -eq $Before.$clock -or $null -eq $After.$clock) { return $null }
    $elapsed = [decimal]$After.$clock - [decimal]$Before.$clock
    $delta = [decimal]$After.$Field - [decimal]$Before.$Field
    if ($elapsed -le 0 -or $delta -lt 0) { return $null }
    if ($Cpu) {
        $value = 100 * $delta / $elapsed
        if ($Inverse) { $value = 100 - $value }
        return [double]$value
    }
    if ($After.Frequency_PerfTime -le 0) { return $null }
    return [double]($delta * [decimal]$After.Frequency_PerfTime / $elapsed)
}
function Latency($Before, $After, $Field) {
    $base = $Field + '_Base'
    if (-not $Before -or -not $After -or $null -eq $Before.$Field -or $null -eq $After.$Field -or $null -eq $Before.$base -or $null -eq $After.$base -or $After.Frequency_PerfTime -le 0) { return $null }
    $count = [decimal]$After.$base - [decimal]$Before.$base
    $delta = [decimal]$After.$Field - [decimal]$Before.$Field
    if ($count -lt 0 -or $delta -lt 0) { return $null }
    if ($count -eq 0) { return 0 }
    return [math]::Round([double](1000 * $delta / [decimal]$After.Frequency_PerfTime / $count), 2)
}
function Check-Identity($Record) {
    if (-not $Record -or $Record.CreationDate -cne $ExpectedCreated -or $Record.Name -ine $ExpectedName) {
        throw 'Process exited or changed since the list was loaded. Refresh and select it again.'
    }
}
try {
    $computerInfo = $null
    if ($includeCpu -or $Kind -eq 'threads') { $computerInfo = Query Win32_ComputerSystem }
    $cores = Number $computerInfo.NumberOfLogicalProcessors
    if ($Kind -eq 'threads') {
        Check-Identity (Query Win32_Process "ProcessId=$ProcessId" -Required)
        $before = Index @(Query Win32_PerfRawData_PerfProc_Thread "IDProcess=$ProcessId" -Required) 'IDThread'
        Start-Sleep -Milliseconds 1000
        $after = @(Query Win32_PerfRawData_PerfProc_Thread "IDProcess=$ProcessId" -Required)
        Check-Identity (Query Win32_Process "ProcessId=$ProcessId" -Required)
        $states = @('Initialized', 'Ready', 'Running', 'Standby', 'Terminated', 'Waiting', 'Transition', 'Unknown')
        $waits = @('Executive', 'Free page', 'Page in', 'Pool allocation', 'Execution delay', 'Suspended', 'User request', 'Executive', 'Free page', 'Page in', 'Pool allocation', 'Execution delay', 'Suspended', 'User request', 'Event pair high', 'Event pair low', 'LPC receive', 'LPC reply', 'Virtual memory', 'Page out')
        $rows = @(foreach ($thread in $after) {
            $old = $before[[string]$thread.IDThread]
            if (-not $old -or $null -eq $old.ElapsedTime -or $old.ElapsedTime -ne $thread.ElapsedTime) { $old = $null }
            $coreCpu = Rate $old $thread PercentProcessorTime -Cpu
            $state = Number $thread.ThreadState
            $wait = Number $thread.ThreadWaitReason
            [pscustomobject]@{
                TID = [long]$thread.IDThread
                CoreCPU = $(if ($null -ne $coreCpu) { Percent $coreCpu 100 } else { $null })
                CPU = $(if ($null -ne $coreCpu -and $cores -gt 0) { [math]::Round($coreCpu / $cores, 2) } else { $null })
                ContextSwitches = Rate $old $thread ContextSwitchesPersec
                State = $(if ($null -ne $state -and $state -lt $states.Count) { $states[$state] } else { 'Unknown' })
                WaitReason = $(if ($state -eq 5 -and $null -ne $wait) { if ($wait -lt $waits.Count) { $waits[$wait] } else { "Other ($wait)" } } else { $null })
                Priority = Number $thread.PriorityCurrent
            }
        })
        [pscustomobject]@{ok = $true; computer = $Computer; pid = $ProcessId; name = $ExpectedName; checked_at = [datetime]::UtcNow.ToString('o'); logical_processors = $cores; total_threads = $after.Count; limit = 200; items = @($rows | Sort-Object CoreCPU -Descending | Select-Object -First 200); warnings = @($warnings)} | ConvertTo-Json -Depth 7 -Compress
        return
    }
    $identities = Index @(Query Win32_Process -Required -Properties @('ProcessId', 'CreationDate')) 'ProcessId'
    $first = @{}; $last = @{}; $firstCpu = @{}; $lastCpu = @(); $firstDisk = @{}; $lastDisk = @()
    if ($includeCpu -or $includeMemory) { $first = Index @(Query Win32_PerfRawData_PerfProc_Process) 'IDProcess' }
    if ($includeCpu) { $firstCpu = Index @(Query Win32_PerfRawData_PerfOS_Processor) 'Name' }
    if ($includeDisk) { $firstDisk = Index @(Query Win32_PerfRawData_PerfDisk_PhysicalDisk) 'Name' }
    if ($includeCpu -or $includeMemory) { Start-Sleep -Milliseconds 1000 }
    if ($includeCpu -or $includeMemory) { $last = Index @(Query Win32_PerfRawData_PerfProc_Process) 'IDProcess' }
    if ($includeCpu) { $lastCpu = @(Query Win32_PerfRawData_PerfOS_Processor) }
    if ($includeDisk) { $lastDisk = @(Query Win32_PerfRawData_PerfDisk_PhysicalDisk) }
    $engines = @()
    if ($includeGpu) { $engines = @(Query Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine) }
    $processes = @(Query Win32_Process -Required)
    $os = $null; $memory = $null; $system = $null
    if ($includeMemory) {
        $os = Query Win32_OperatingSystem
        $memory = Query Win32_PerfFormattedData_PerfOS_Memory
    }
    if ($includeCpu) { $system = Query Win32_PerfFormattedData_PerfOS_System }
    $gpuProcesses = @{}; $gpuTotals = @{}
    foreach ($engine in $engines) {
        if ($engine.Name -match '^pid_(\d+)_' -and $null -ne $engine.UtilizationPercentage) {
            $key = $Matches[1]; $engineKey = $engine.Name -replace '^pid_\d+_', ''
            $gpuTotals[$engineKey] += [double]$engine.UtilizationPercentage
            if (-not $gpuProcesses.ContainsKey($key) -or $engine.UtilizationPercentage -gt $gpuProcesses[$key].UtilizationPercentage) { $gpuProcesses[$key] = $engine }
        }
    }
    $totalMemory = $(if ($null -ne $os.TotalVisibleMemorySize -and $os.TotalVisibleMemorySize -gt 0) { [double]$os.TotalVisibleMemorySize * 1KB } else { $null })
    $freeMemory = $(if ($null -ne $os.FreePhysicalMemory) { [double]$os.FreePhysicalMemory * 1KB } else { $null })
    $cpuRows = @(foreach ($counter in $lastCpu) {
        $value = Rate $firstCpu[[string]$counter.Name] $counter PercentProcessorTime -Cpu -Inverse
        [pscustomobject]@{name = $counter.Name; percent = $(if ($null -ne $value) { Percent $value 100 } else { $null })}
    })
    $diskRows = @(foreach ($disk in $lastDisk) {
        if ($disk.Name -eq '_Total') { continue }
        $old = $firstDisk[[string]$disk.Name]
        [pscustomobject]@{name = $disk.Name; read_ms = Latency $old $disk AvgDisksecPerRead; write_ms = Latency $old $disk AvgDisksecPerWrite; queue = Number $disk.CurrentDiskQueueLength; read_bytes_sec = Rate $old $disk DiskReadBytesPersec; write_bytes_sec = Rate $old $disk DiskWriteBytesPersec}
    })
    $volumeRecords = @()
    if ($Kind -eq 'overview') { $volumeRecords = @(Query Win32_LogicalDisk 'DriveType=3') }
    $volumes = @(foreach ($volume in $volumeRecords) {
        [pscustomobject]@{name = $volume.DeviceID; total_bytes = Number $volume.Size; free_bytes = Number $volume.FreeSpace; free_percent = Percent (Number $volume.FreeSpace) (Number $volume.Size)}
    })
    $rows = @(foreach ($record in $processes) {
        if ($record.ProcessId -eq 0) { continue }
        $key = [string]$record.ProcessId; $metric = $last[$key]; $old = $first[$key]
        $stableIdentity = $record.CreationDate -and $identities.ContainsKey($key) -and $record.CreationDate -ceq $identities[$key].CreationDate
        if (-not $stableIdentity -or $null -eq $old.ElapsedTime -or $old.ElapsedTime -ne $metric.ElapsedTime) { $old = $null; $metric = $null }
        $row = [ordered]@{
            PID = [long]$record.ProcessId; Process = [string]$record.Name; CreatedAt = [string]$record.CreationDate
            SessionId = Number $record.SessionId; CommandLine = [string]$record.CommandLine
        }
        if ($includeCpu) {
            $cpu = Rate $old $metric PercentProcessorTime -Cpu
            $row.CPU = $(if ($null -ne $cpu -and $cores -gt 0) { Percent $cpu ($cores * 100) } else { $null })
            $row.Threads = Number $record.ThreadCount
        }
        if ($includeGpu) {
            $gpu = $(if ($stableIdentity) { $gpuProcesses[$key] } else { $null })
            $row.GPU = $(if ($gpu) { Percent (Number $gpu.UtilizationPercentage) 100 } else { $null })
            $row.Engine = $(if ($gpu) { ($gpu.Name -split '_engtype_', 2)[-1] } else { $null })
        }
        if ($includeMemory) {
            $workingSet = Number $record.WorkingSetSize
            $row.MemoryBytes = $workingSet
            $row.MemoryPercent = Percent $workingSet $totalMemory
            $row.MemoryMB = $(if ($null -ne $workingSet) { [math]::Round($workingSet / 1MB, 1) } else { $null })
            $row.PrivateBytes = Number $metric.PrivateBytes
            $row.Handles = Number $record.HandleCount
            $row.PageFaultsPerSec = Rate $old $metric PageFaultsPersec
        }
        if ($includeDisk) { $row.IOBytesPerSec = Rate $old $metric IODataBytesPersec }
        [pscustomobject]$row
    })
    $uptime = $null
    try { if ($os.LastBootUpTime -and $os.LocalDateTime) { $uptime = ($os.ConvertToDateTime($os.LocalDateTime) - $os.ConvertToDateTime($os.LastBootUpTime)).TotalSeconds } } catch { $warnings.Add('Uptime unavailable') }
    $busiest = $gpuTotals.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 1
    $sort = switch ($Kind) { 'gpu' { 'GPU' }; 'memory' { 'MemoryBytes' }; default { 'CPU' } }
    $selected = @($rows | Sort-Object $sort -Descending | Select-Object -First 100)
    if ($Kind -eq 'gpu') {
        $selected = @($rows | Where-Object { $null -ne $_.GPU } | Sort-Object GPU -Descending | Select-Object -First 100)
    }
    if ($Kind -eq 'diagnose') {
        # Preserve memory/I/O consumers and WMI providers without deeper enumeration.
        $leaders = @{}
        foreach ($field in @('CPU', 'MemoryBytes', 'IOBytesPerSec')) {
            foreach ($row in @($rows | Sort-Object $field -Descending | Select-Object -First 20)) { $leaders[[string]$row.PID] = $row }
        }
        foreach ($row in @($rows | Where-Object Process -ieq 'EXCEL.EXE' | Sort-Object MemoryBytes -Descending | Select-Object -First 20)) { $leaders[[string]$row.PID] = $row }
        foreach ($row in @($rows | Where-Object Process -ieq 'WmiPrvSE.exe' | Sort-Object CPU -Descending | Select-Object -First 20)) { $leaders[[string]$row.PID] = $row }
        $selected = @($leaders.Values | Sort-Object CPU -Descending)
    }
    $summary = [ordered]@{process_count = $rows.Count}
    if ($includeCpu) {
        $summary.cpu_percent = ($cpuRows | Where-Object name -eq '_Total').percent
        $summary.logical_processors = $cores
        $summary.cores = @($cpuRows | Where-Object name -ne '_Total')
        $summary.processor_queue = Number $system.ProcessorQueueLength
        $summary.context_switches_sec = Number $system.ContextSwitchesPersec
        $summary.thread_count = Number $system.Threads
    }
    if ($includeMemory) {
        $summary.total_memory_bytes = $totalMemory
        $summary.available_memory_bytes = $freeMemory
        $summary.memory_percent = $(if ($null -ne $freeMemory -and $null -ne $totalMemory) { Percent ($totalMemory - $freeMemory) $totalMemory } else { $null })
        $summary.committed_bytes = Number $memory.CommittedBytes
        $summary.commit_limit_bytes = Number $memory.CommitLimit
        $summary.commit_percent = Percent $summary.committed_bytes $summary.commit_limit_bytes
        $summary.page_reads_sec = Number $memory.PageReadsPersec
    }
    if ($includeGpu -or $Kind -eq 'diagnose') {
        $summary.gpu_percent = $(if ($busiest) { Percent $busiest.Value 100 } else { $null })
        $summary.gpu_engine = $(if ($busiest) { $busiest.Name } else { $null })
    }
    if ($includeGpu) {
        $summary.gpu_engine_count = $(if ($gpuTotals.Count) { $gpuTotals.Count } else { $null })
        $summary.gpu_engines = @(foreach ($engine in @($gpuTotals.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 32)) {
            [pscustomobject]@{name = $engine.Name; adapter = ($engine.Name -split '_eng_', 2)[0]; engine = ($engine.Name -split '_engtype_', 2)[-1]; percent = Percent $engine.Value 100}
        })
        $summary.gpu_process_count = $(if ($gpuTotals.Count) { @($rows | Where-Object { $null -ne $_.GPU -and $_.GPU -gt 0 }).Count } else { $null })
    }
    if ($includeDisk) {
        $summary.uptime_seconds = $uptime
        $summary.os = [string]$os.Caption
        $summary.model = [string]$computerInfo.Model
        $summary.console_user = [string]$computerInfo.UserName
        $summary.disks = $diskRows
        $summary.volumes = $volumes
    }
    [pscustomobject]@{
        ok = $true; computer = $Computer; kind = $Kind; checked_at = [datetime]::UtcNow.ToString('o')
        collection = [pscustomobject]@{profile = $(if ($Kind -eq 'diagnose') { 'light' } else { $Kind }); query_count = $queryCount}
        total_processes = $rows.Count; limit = 100; items = $selected; warnings = @($warnings)
        summary = [pscustomobject]$summary
    } | ConvertTo-Json -Depth 7 -Compress
} catch {
    [pscustomobject]@{ok = $false; error = $_.Exception.Message} | ConvertTo-Json -Compress
}
