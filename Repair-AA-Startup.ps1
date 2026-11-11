[CmdletBinding()]
param([string]$InstallRoot = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'launcher.py') -PathType Leaf)) {
    throw 'Copy this script into your AA folder, beside Start AA.bat, before running it.'
}

# Older AA builds always kept ownership records under data, even when their
# databases lived elsewhere. Check that location and the configured workspace.
$folders = @((Join-Path $InstallRoot 'data'))
$config = $null
$configPath = Join-Path $InstallRoot 'config.json'
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
}
$runtime = $env:AA_DATA_HOME
if (-not $runtime -and $config) { $runtime = $config.runtime_folder }
if (-not $runtime -and $config) { $runtime = $config.database_folder }
if (-not $runtime -and $env:ATLAS_DB_PATH) {
    $runtime = Split-Path -Parent ([IO.Path]::GetFullPath($env:ATLAS_DB_PATH))
}
if ($runtime) {
    if ($runtime -eq '~') { $runtime = [Environment]::GetFolderPath('UserProfile') }
    elseif ($runtime.StartsWith('~\') -or $runtime.StartsWith('~/')) {
        $runtime = Join-Path ([Environment]::GetFolderPath('UserProfile')) $runtime.Substring(2)
    }
    if (-not [IO.Path]::IsPathRooted($runtime)) { $runtime = Join-Path $InstallRoot $runtime }
    $folders += [IO.Path]::GetFullPath($runtime)
}

$retained = 0
$cleared = 0
foreach ($folder in ($folders | Select-Object -Unique)) {
    foreach ($name in @('server.json', 'viewer-server.json')) {
        $recordPath = Join-Path $folder $name
        if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { continue }
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $recordPid = 0L
        if (-not [long]::TryParse([string]$record.pid, [ref]$recordPid) -or
                $recordPid -le 0 -or $recordPid -gt [uint32]::MaxValue) {
            throw "Invalid PID. Record retained for inspection: $recordPath"
        }
        # A failed query must stop recovery, never masquerade as an absent PID.
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$recordPid" -ErrorAction Stop
        if ($null -ne $process) {
            Write-Host "PID $recordPid ($($process.Name)) still exists. Record retained: $recordPath"
            $retained++
            continue
        }
        $backup = $recordPath + '.stale-' + [guid]::NewGuid().ToString('N')
        Move-Item -LiteralPath $recordPath -Destination $backup -ErrorAction Stop
        Write-Host "Archived stale record for exited PID ${recordPid}: $backup"
        $cleared++
    }
}
if ($retained) {
    throw "$retained record(s) still refer to a running process. Use Stop AA.bat from its original installation. No processes were stopped by this repair."
}
Write-Host "Repair complete ($cleared stale records archived). Run Start AA.bat again."
