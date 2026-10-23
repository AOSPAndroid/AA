# Simulated processes only. No Windows provider or real Terminate method is used.
$ErrorActionPreference = 'Stop'
$global:AtlasKillCalls = [System.Collections.Generic.List[long]]::new()
$global:AtlasReplacement = @{}
$global:AtlasGone = @(406)

function New-TestProcess($Id, $Name, $Created = '20260910100000.000000+000') {
    $record = [pscustomobject]@{ ProcessId = $Id; Name = $Name; CreationDate = $Created; CommandLine = 'a180 in arguments'; Code = 0 }
    $record | Add-Member ScriptMethod Terminate {
        param($Reason)
        $global:AtlasKillCalls.Add([long]$this.ProcessId)
        return [pscustomobject]@{ ReturnValue = $this.Code }
    }
    return $record
}
$global:AtlasProcesses = @(
    foreach ($id in 100..249) { New-TestProcess $id "unrelated-$id.exe" }
    New-TestProcess 401 'a180.exe'
    New-TestProcess 402 'A180Updater.exe'
    New-TestProcess 403 'tool-a180-worker.exe'
    New-TestProcess 404 'unrelated.exe'
    New-TestProcess 405 'a180-reused.exe'
    New-TestProcess 406 'a180-gone.exe'
    New-TestProcess 407 'csrss.exe'
    New-TestProcess 4 'a180-system.exe'
    New-TestProcess 499 'worker-A180.exe'
    New-TestProcess 501 'openfin.exe'
    New-TestProcess 502 'OpenFin.exe'
    New-TestProcess 503 'openfin-helper.exe'
)
$global:AtlasReplacement[405] = New-TestProcess 405 'a180-reused.exe' '20260910110000.000000+000'

function Get-WmiObject {
    param($ComputerName, $Class, $Filter, $ErrorAction)
    if ($ComputerName -ne 'TESTPC' -or $Class -ne 'Win32_Process') { throw 'Unexpected provider query' }
    if (-not $Filter) { return $global:AtlasProcesses }
    if ($Filter -match '^ProcessId=(\d+)$') {
        $id = [long]$Matches[1]
        if ($id -in $global:AtlasGone) { return }
        if ($global:AtlasReplacement.ContainsKey([int]$id)) { return $global:AtlasReplacement[[int]$id] }
        return @($global:AtlasProcesses | Where-Object ProcessId -eq $id)
    }
    if ($Filter -match "^Name='([^']+)'$") {
        $name = $Matches[1]
        return @($global:AtlasProcesses | Where-Object { $_.Name -ieq $name })
    }
    throw "Unexpected filter: $Filter"
}
$scriptPath = Join-Path $PSScriptRoot '../scripts/remote_processes.ps1'
$exact = (& $scriptPath -Computer TESTPC -Action kill -Value openfin.exe -Match exact) | ConvertFrom-Json
if (-not $exact.ok -or $exact.count -ne 2 -or $exact.failed -ne 0 -or ($global:AtlasKillCalls -join ',') -ne '501,502') {
    throw 'OpenFin must terminate every exact name, excluding openfin-helper.exe'
}
$global:AtlasKillCalls.Clear()
$contains = (& $scriptPath -Computer TESTPC -Action kill -Value a180 -Match contains) | ConvertFrom-Json
if (-not $contains.ok -or $contains.count -ne 4 -or $contains.results.Count -ne 7 -or ($global:AtlasKillCalls -join ',') -ne '401,402,403,499') {
    throw "Full-list literal case-insensitive matching failed: $($contains | ConvertTo-Json -Depth 5)"
}
if (($contains.results | Where-Object PID -eq 405).state -ne 'changed') { throw 'Reused PID was not skipped' }
if (($contains.results | Where-Object PID -eq 406).state -ne 'gone') { throw 'Disappeared process was not skipped' }
if (($contains.results | Where-Object PID -eq 4).state -ne 'blocked') { throw 'System PID was not protected' }
if ($contains.results.PID -contains 404) { throw 'Command-line arguments were matched instead of names' }

$global:AtlasKillCalls.Clear()
$wildcard = (& $scriptPath -Computer TESTPC -Action kill -Value '*' -Match contains) | ConvertFrom-Json
if ($wildcard.count -ne 0 -or $wildcard.results.Count -ne 0 -or $global:AtlasKillCalls.Count) { throw 'Wildcard was interpreted as a pattern' }
$global:AtlasProcesses = @($global:AtlasProcesses | Where-Object ProcessId -eq 407)
$blocked = (& $scriptPath -Computer TESTPC -Action kill -Value exe -Match contains) | ConvertFrom-Json
if ($blocked.count -ne 0 -or $blocked.results[0].state -ne 'blocked' -or $global:AtlasKillCalls.Count) { throw 'Core Windows executable was not protected' }

$denied = New-TestProcess 701 'a180-denied.exe'; $denied.Code = 2
$global:AtlasProcesses = @(New-TestProcess 700 'a180-good.exe'; $denied)
$partial = (& $scriptPath -Computer TESTPC -Action kill -Value A180 -Match contains) | ConvertFrom-Json
if ($partial.count -ne 1 -or $partial.failed -ne 1 -or ($partial.results | Where-Object PID -eq 701).message -ne 'Access denied') { throw 'Partial failures were hidden' }
$global:AtlasKillCalls.Clear()
$empty = (& $scriptPath -Computer TESTPC -Action kill -Value absent -Match contains) | ConvertFrom-Json
if ($empty.count -ne 0 -or $empty.results.Count -ne 0 -or $global:AtlasKillCalls.Count) { throw 'No matches were reported as success' }
Write-Output 'PASS: exact OpenFin, full-list case-insensitive literal names, PID rechecks, protected/gone processes and partial results'
