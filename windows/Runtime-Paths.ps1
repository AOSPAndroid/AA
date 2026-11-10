# Resolve the same workspace precedence as runtime_paths.py for native launch/setup helpers.
function Get-AARuntimeFolder([string]$InstallRoot) {
    $configPath = Join-Path $InstallRoot 'config.json'
    $config = $null
    if (Test-Path -LiteralPath $configPath) {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    }
    $folder = $env:AA_DATA_HOME
    if (-not $folder -and $config) { $folder = $config.runtime_folder }
    if (-not $folder -and $config) { $folder = $config.database_folder }
    if (-not $folder -and $env:ATLAS_DB_PATH) {
        $folder = Split-Path -Parent ([IO.Path]::GetFullPath($env:ATLAS_DB_PATH))
    }
    if (-not $folder) { $folder = Join-Path $InstallRoot 'data' }
    if ($folder -eq '~') { $folder = [Environment]::GetFolderPath('UserProfile') }
    elseif ($folder.StartsWith('~\') -or $folder.StartsWith('~/')) {
        $folder = Join-Path ([Environment]::GetFolderPath('UserProfile')) $folder.Substring(2)
    }
    return [IO.Path]::GetFullPath($folder)
}
