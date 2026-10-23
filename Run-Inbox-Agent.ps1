[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Configuration)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
if ($config.version -ne 1) { throw 'Unsupported inbox configuration.' }
# This wrapper is launched by the limited interactive task, never elevated.
& $config.python (Join-Path $PSScriptRoot 'inbox_agent.py') --configuration $Configuration
exit $LASTEXITCODE
