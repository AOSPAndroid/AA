[CmdletBinding()]
param([string]$PackagePath)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ([Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run normally as the Teams/Outlook account (x01426046), not from elevated Atlas.'
}
if ($PackagePath) {
    Add-AppxPackage -Path (Resolve-Path -LiteralPath $PackagePath).Path
} else {
    $root = Split-Path -Parent $PSScriptRoot
    $manifest = Join-Path $root 'notification-listener\package\AppxManifest.xml'
    if (-not (Test-Path -LiteralPath $manifest)) { $manifest = Join-Path $root 'output\Atlas-Notification-Listener\AppxManifest.xml' }
    if (-not (Test-Path -LiteralPath $manifest)) { throw 'Run notification-listener\Build-Notification-Listener.ps1 first, or use -PackagePath with the signed MSIX package.' }
    $development = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -ErrorAction SilentlyContinue
    if (-not $development -or $development.AllowDevelopmentWithoutDevLicense -ne 1) {
        throw 'This folder is a development build. Developer Mode is not enabled. Install an organization-signed MSIX with -PackagePath; this script does not change Windows policy or certificate trust.'
    }
    Add-AppxPackage -Register $manifest
}
Write-Host 'Atlas Notification Listener registered for the current account. Run Start-Notification-Listener.ps1, then allow notification access in its window.'
