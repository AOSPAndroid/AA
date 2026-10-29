[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Configuration)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
if ($config.version -ne 1) { throw 'Unsupported inbox configuration.' }
# This wrapper is launched by the limited interactive task, never elevated.
# Python finds Atlas's modules in the AA folder, one up from windows\.
$env:PYTHONPATH = Split-Path -Parent $PSScriptRoot
& $config.python -m backend.inbox.inbox_agent --configuration $Configuration
exit $LASTEXITCODE
