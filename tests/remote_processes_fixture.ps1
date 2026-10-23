# Every WMI call and Terminate method is replaced with an in-memory fixture.
$ErrorActionPreference = 'Stop'
$global:AtlasTestMode = 'cpu'
$global:AtlasTestTerminateCalls = 0
$global:AtlasTestReturnCode = 0
$global:AtlasTestName = 'sample.exe'
$global:AtlasTestCreated = '20260910100000.000000+000'
$global:AtlasTestMissing = $false
function Get-WmiObject {
    param($ComputerName, $Class, $Filter, $ErrorAction)
    if ($ComputerName -ne 'TESTPC') { throw 'Unexpected target' }
    switch ($Class) {
        'Win32_Process' {
            if ($global:AtlasTestMissing) { return }
            $record = [pscustomobject]@{
                ProcessId = 42; Name = $global:AtlasTestName; CreationDate = $global:AtlasTestCreated
                WorkingSetSize = 104857600; SessionId = 2; CommandLine = 'sample.exe -test'
            }
            $record | Add-Member ScriptMethod Terminate {
                param($Reason)
                $global:AtlasTestTerminateCalls++
                return [pscustomobject]@{ ReturnValue = $global:AtlasTestReturnCode }
            }
            return $record
        }
        'Win32_ComputerSystem' { return [pscustomobject]@{ NumberOfLogicalProcessors = 4 } }
        'Win32_PerfFormattedData_PerfProc_Process' { return [pscustomobject]@{ IDProcess = 42; PercentProcessorTime = 200 } }
        'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine' {
            if ($global:AtlasTestMode -eq 'gpu-error') { throw 'Invalid class' }
            if ($global:AtlasTestMode -eq 'gpu-empty') { return }
            return @(
                [pscustomobject]@{ Name = 'pid_42_luid_0x0_phys_0_eng_0_engtype_3D'; UtilizationPercentage = 45 }
                [pscustomobject]@{ Name = 'pid_42_luid_0x0_phys_0_eng_1_engtype_Copy'; UtilizationPercentage = 25 }
            )
        }
        default { throw "Unexpected WMI class: $Class" }
    }
}
$scriptPath = Join-Path $PSScriptRoot '../scripts/remote_processes.ps1'
function Run-Case($Action = 'list', $Kind = 'cpu', $Created = '', $Name = '') {
    (& $scriptPath -Computer TESTPC -Action $Action -Kind $Kind -Value 42 -ExpectedCreated $Created -ExpectedName $Name) | ConvertFrom-Json
}
$cpu = Run-Case
if (-not $cpu.ok -or $cpu.items.Count -ne 1 -or $cpu.items[0].CPU -ne 50 -or $cpu.items[0].MemoryMB -ne 100 -or -not $cpu.items[0].CanTerminate) { throw "CPU snapshot failed: $($cpu | ConvertTo-Json -Depth 5)" }
$gpu = Run-Case -Kind gpu
if ($gpu.items.Count -ne 1 -or $gpu.items[0].GPU -ne 45 -or $gpu.items[0].Engine -ne '3D') { throw 'GPU must use busiest engine, not sum' }
foreach ($mode in @('gpu-error', 'gpu-empty')) {
    $global:AtlasTestMode = $mode
    $result = Run-Case -Kind gpu
    if ($result.ok -or -not $result.error) { throw 'GPU unavailability was hidden' }
}
$memory = Run-Case -Kind memory
if (-not $memory.ok -or $memory.items[0].MemoryMB -ne 100) { throw 'Memory must remain available' }
$changed = Run-Case -Action kill -Created '20260910090000.000000+000' -Name sample.exe
if ($changed.results[0].state -ne 'changed' -or $global:AtlasTestTerminateCalls) { throw 'Reused PID was terminated' }
$changedName = Run-Case -Action kill -Created $global:AtlasTestCreated -Name other.exe
if ($changedName.results[0].state -ne 'changed' -or $global:AtlasTestTerminateCalls) { throw 'Changed executable was terminated' }
$global:AtlasTestName = 'csrss.exe'
$blocked = Run-Case -Action kill
if ($blocked.results[0].state -ne 'blocked' -or $global:AtlasTestTerminateCalls) { throw 'Core Windows process was terminated' }
$global:AtlasTestName = 'sample.exe'
foreach ($code in @(2, 3, 8, 9, 21)) {
    $global:AtlasTestReturnCode = $code
    $denied = Run-Case -Action kill -Created $global:AtlasTestCreated -Name $global:AtlasTestName
    if ($denied.count -ne 0 -or $denied.failed -ne 1) { throw "Failure code $code was counted as success" }
}
$global:AtlasTestReturnCode = 0
$success = Run-Case -Action kill -Created $global:AtlasTestCreated -Name $global:AtlasTestName
if ($success.count -ne 1 -or $success.failed -ne 0) { throw 'Successful result missing' }
$global:AtlasTestMissing = $true
$gone = Run-Case -Action kill
if ($gone.count -ne 0 -or $gone.results.Count -ne 0) { throw 'Missing process reported as terminated' }
$empty = Run-Case -Kind memory
if ($empty.items.Count -ne 0) { throw 'Empty process list failed' }
Write-Output 'PASS: simulated WMI snapshots, GPU counters, process identity, protected processes and Windows return codes'
