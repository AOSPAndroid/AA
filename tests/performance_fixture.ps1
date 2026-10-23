# Every provider and the sampling delay is simulated; no machine is queried.
$ErrorActionPreference = 'Stop'
$global:AtlasMode = 'normal'
$global:AtlasCalls = @{}
function Start-Sleep { param($Milliseconds) }
function Get-WmiObject {
    param($ComputerName, $Class, $Filter, $ErrorAction, $Property)
    if ($ComputerName -ne 'TESTPC') { throw 'Unexpected target' }
    if (-not $Property -or $Property -contains '*') { throw 'Every scan must project its fields' }
    $global:AtlasProperties[$Class] = @($Property)
    if ($global:AtlasMode -like 'excel*' -and (-not $Property -or $Property -contains '*' -or $Property -contains 'CommandLine')) { throw 'Light capture must request selected properties without command lines' }
    $global:AtlasCalls[$Class]++
    $sample = $global:AtlasCalls[$Class]
    if ($global:AtlasMode -eq 'partial' -and $Class -in @('Win32_PerfRawData_PerfOS_Processor', 'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine', 'Win32_PerfFormattedData_PerfOS_Memory')) { throw 'Provider unavailable' }
    switch ($Class) {
        'Win32_ComputerSystem' { return [pscustomobject]@{NumberOfLogicalProcessors = 4} }
        'Win32_Process' {
            return [pscustomobject]@{ProcessId = 42; Name = $(if ($global:AtlasMode -like 'excel*') { 'EXCEL.EXE' } elseif ($global:AtlasMode -eq 'identity' -and $sample -gt 1) { 'replacement.exe' } else { 'sample.exe' }); CreationDate = $(if ($global:AtlasMode -in @('excel_identity', 'gpu_identity') -and $sample -gt 1) { '20260910110000.000000+000' } else { '20260910100000.000000+000' }); WorkingSetSize = 4GB; ThreadCount = 650; HandleCount = 321; SessionId = 2; CommandLine = 'sample.exe -test'}
        }
        'Win32_OperatingSystem' { return [pscustomobject]@{TotalVisibleMemorySize = 16777216; FreePhysicalMemory = 2097152; Caption = 'Test Windows'} }
        'Win32_PerfRawData_PerfProc_Process' {
            return [pscustomobject]@{IDProcess = 42; ElapsedTime = 123; Timestamp_Sys100NS = (100000000 + $sample * 10000000); Timestamp_PerfTime = (100000000 + $sample * 10000000); Frequency_PerfTime = 10000000; PercentProcessorTime = ($sample * 10000000); IODataBytesPersec = ($sample * 1MB); PageFaultsPersec = ($sample * 7); PrivateBytes = 5GB}
        }
        'Win32_PerfRawData_PerfOS_Processor' {
            foreach ($name in @('_Total', '0', '1', '2', '3')) {
                [pscustomobject]@{Name = $name; Timestamp_Sys100NS = (100000000 + $sample * 10000000); PercentProcessorTime = ($sample * 1000000)}
            }
            return
        }
        'Win32_PerfRawData_PerfDisk_PhysicalDisk' { return [pscustomobject]@{Name = '0 C:'; Timestamp_PerfTime = (100000000 + $sample * 10000000); Frequency_PerfTime = 10000000; AvgDisksecPerRead = ($sample * 3000000); AvgDisksecPerRead_Base = ($sample * 10); AvgDisksecPerWrite = ($sample * 2000000); AvgDisksecPerWrite_Base = ($sample * 10); CurrentDiskQueueLength = 2; DiskReadBytesPersec = ($sample * 2MB); DiskWriteBytesPersec = ($sample * 1MB)} }
        'Win32_LogicalDisk' { return [pscustomobject]@{DeviceID = 'C:'; Size = 100GB; FreeSpace = 5GB} }
        'Win32_PerfFormattedData_PerfOS_Memory' { return [pscustomobject]@{CommittedBytes = 18GB; CommitLimit = 20GB; PageReadsPersec = 50} }
        'Win32_PerfFormattedData_PerfOS_System' { return [pscustomobject]@{ProcessorQueueLength = 8; ContextSwitchesPersec = 1234; Threads = 800} }
        'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine' {
            return @(
                [pscustomobject]@{Name = 'pid_42_luid_a_phys_0_eng_0_engtype_3D'; UtilizationPercentage = 45}
                [pscustomobject]@{Name = 'pid_99_luid_a_phys_0_eng_0_engtype_3D'; UtilizationPercentage = 35}
                [pscustomobject]@{Name = 'pid_42_luid_a_phys_0_eng_1_engtype_Copy'; UtilizationPercentage = 25}
            )
        }
        'Win32_PerfRawData_PerfProc_Thread' {
            if ($Filter -ne 'IDProcess=42') { throw 'Thread query not scoped to process' }
            if ($global:AtlasMode -eq 'excel_missing') { throw 'Thread provider unavailable' }
            return @(
                [pscustomobject]@{IDProcess = 42; IDThread = 100; ElapsedTime = 123; Timestamp_Sys100NS = (100000000 + $sample * 10000000); Timestamp_PerfTime = (100000000 + $sample * 10000000); Frequency_PerfTime = 10000000; PercentProcessorTime = ($sample * 8000000); ContextSwitchesPersec = ($sample * 120); ThreadState = 2; ThreadWaitReason = 6; PriorityCurrent = 8}
                [pscustomobject]@{IDProcess = 42; IDThread = 101; ElapsedTime = $(if ($global:AtlasMode -eq 'reuse') { $sample } else { 125 }); Timestamp_Sys100NS = (100000000 + $sample * 10000000); Timestamp_PerfTime = (100000000 + $sample * 10000000); Frequency_PerfTime = 10000000; PercentProcessorTime = 1000000; ContextSwitchesPersec = 5; ThreadState = 5; ThreadWaitReason = 6; PriorityCurrent = 8}
            )
        }
        default { throw "Unexpected class $Class" }
    }
}
function Sample($Kind = 'cpu') {
    $global:AtlasCalls = @{}
    $global:AtlasProperties = @{}
    (& (Join-Path $PSScriptRoot '../scripts/performance.ps1') -Computer TESTPC -Kind $Kind -ProcessId 42 -ExpectedCreated '20260910100000.000000+000' -ExpectedName 'sample.exe') | ConvertFrom-Json
}
$data = Sample overview
if (-not $data.ok) { throw $data.error }
if ($data.items[0].CPU -ne 25 -or $data.summary.cpu_percent -ne 90) { throw 'CPU normalization or inverse counter wrong' }
if ($data.items[0].MemoryPercent -ne 25 -or $data.summary.memory_percent -ne 87.5 -or $data.summary.total_memory_bytes -ne 16GB) { throw "RAM denominator wrong: $($data | ConvertTo-Json -Depth 6 -Compress)" }
if ($data.items[0].GPU -ne 45 -or $data.summary.gpu_percent -ne 80) { throw 'GPU engine aggregation wrong' }
if ($data.items[0].IOBytesPerSec -ne 1MB -or $data.items[0].PageFaultsPerSec -ne 7) { throw 'Process rates wrong' }
if ($data.summary.disks[0].read_ms -ne 30 -or $data.summary.disks[0].write_ms -ne 20) { throw 'Disk latency must use sample and base differences' }
if ($data.summary.volumes[0].free_percent -ne 5 -or $data.summary.commit_percent -ne 90) { throw 'Pressure totals wrong' }
$threads = Sample threads
if (-not $threads.ok) { throw $threads.error }
if ($threads.items[0].CoreCPU -ne 80 -or $threads.items[0].CPU -ne 20 -or $threads.items[0].ContextSwitches -ne 120) { throw 'Thread rates wrong' }
if ($null -ne $threads.items[0].WaitReason -or $threads.items[1].WaitReason -ne 'User request') { throw 'Wait reason displayed for non-waiting thread' }
$global:AtlasMode = 'reuse'; $reused = Sample threads
if ($null -ne ($reused.items | Where-Object TID -eq 101).CoreCPU) { throw 'Reused thread ID has a fabricated CPU rate' }
$global:AtlasMode = 'identity'; $changed = Sample threads
if ($changed.ok -or $changed.error -notmatch 'changed') { throw 'Changed process identity was accepted' }
$global:AtlasMode = 'partial'; $partial = Sample overview
if (-not $partial.ok -or $null -ne $partial.summary.cpu_percent -or $null -ne $partial.summary.gpu_percent -or $null -ne $partial.summary.commit_percent -or $partial.summary.memory_percent -ne 87.5 -or -not $partial.warnings.Count) { throw 'Partial counters must not become zero or hide working metrics' }
$global:AtlasMode = 'excel'; $diagnose = Sample diagnose
if (-not $diagnose.ok -or $diagnose.collection.profile -ne 'light' -or $diagnose.collection.query_count -ne 12 -or $diagnose.items[0].CPU -ne 25) { throw "Light capture failed: $($diagnose | ConvertTo-Json -Depth 6 -Compress)" }
foreach ($class in @('Win32_PerfRawData_PerfProc_Thread', 'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine', 'Win32_LogicalDisk')) {
    if ($global:AtlasCalls[$class]) { throw "Light capture unexpectedly queried $class" }
}
if ($null -ne $diagnose.summary.gpu_percent -or $diagnose.summary.volumes.Count -ne 0) { throw 'Deferred counters must not be fabricated' }
$global:AtlasMode = 'excel_identity'; $diagnose = Sample diagnose
if (-not $diagnose.ok -or $null -ne $diagnose.items[0].CPU) { throw 'Reused Excel PID was attributed to old process samples' }
$global:AtlasMode = 'normal'
foreach ($kind in @('overview', 'cpu', 'gpu', 'memory')) {
    $data = Sample $kind
    $expected = @{overview = 14; cpu = 8; gpu = 3; memory = 6}[$kind]
    if (-not $data.ok -or $data.collection.query_count -ne $expected -or $data.collection.profile -ne $kind) { throw "Unexpected $kind scan: $($data | ConvertTo-Json -Depth 7 -Compress)" }
    if ($kind -ne 'overview') {
        if ($global:AtlasCalls.Win32_PerfRawData_PerfDisk_PhysicalDisk -or $global:AtlasCalls.Win32_LogicalDisk) { throw "$kind queried disks" }
        if ($data.summary.PSObject.Properties.Name -contains 'disks' -or $data.items[0].PSObject.Properties.Name -contains 'IOBytesPerSec') { throw "$kind included unrelated disk fields" }
    }
    if ($kind -in @('cpu', 'memory')) {
        if ($global:AtlasCalls.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -or $data.items[0].PSObject.Properties.Name -contains 'GPU') { throw "$kind included GPU" }
    }
    if ($kind -in @('cpu', 'gpu')) {
        if ($global:AtlasCalls.Win32_OperatingSystem -or $global:AtlasCalls.Win32_PerfFormattedData_PerfOS_Memory -or $data.summary.PSObject.Properties.Name -contains 'memory_percent' -or $data.items[0].PSObject.Properties.Name -contains 'MemoryBytes') { throw "$kind included RAM" }
        if ($global:AtlasProperties.Win32_Process -contains 'WorkingSetSize' -or $global:AtlasProperties.Win32_PerfRawData_PerfProc_Process -contains 'PrivateBytes') { throw "$kind requested memory fields" }
    }
    if ($kind -in @('gpu', 'memory')) {
        if ($global:AtlasCalls.Win32_ComputerSystem -or $global:AtlasCalls.Win32_PerfRawData_PerfOS_Processor -or $global:AtlasCalls.Win32_PerfFormattedData_PerfOS_System -or $data.items[0].PSObject.Properties.Name -contains 'CPU') { throw "$kind included CPU" }
        if ($global:AtlasProperties.Win32_Process -contains 'ThreadCount' -or $global:AtlasProperties.Win32_PerfRawData_PerfProc_Process -contains 'PercentProcessorTime') { throw "$kind requested CPU fields" }
    }
    if ($kind -eq 'gpu') {
        if ($global:AtlasCalls.Win32_PerfRawData_PerfProc_Process) { throw 'GPU queried process CPU/memory counters' }
        if ($data.summary.gpu_engines.Count -ne 2 -or $data.summary.gpu_engines[0].percent -ne 80 -or $data.summary.gpu_process_count -ne 1) { throw 'GPU engines and active-process count wrong' }
    }
}
$global:AtlasMode = 'partial'; $data = Sample gpu
if (-not $data.ok -or $data.items.Count -ne 0 -or $null -ne $data.summary.gpu_percent -or $null -ne $data.summary.gpu_process_count -or -not $data.warnings.Count) { throw 'Missing GPU counters must remain unknown' }
# Use changed creation timestamps between identity snapshots for GPU attribution too.
$global:AtlasMode = 'gpu_identity'
$data = Sample gpu
if (-not $data.ok -or $data.items.Count -ne 0) { throw 'Reused PID received GPU attribution' }
Write-Output 'PASS: scoped Overview/CPU/GPU/Memory providers and properties, sampled rates, identity guards and partial counters'
