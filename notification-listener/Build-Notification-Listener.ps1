[CmdletBinding()]
param([string]$ContractsDirectory, [string]$MakeAppxPath, [string]$Publisher = 'CN=Atlas Local', [switch]$IncludeTests)
$ErrorActionPreference = 'Stop'
# Kept in notification-listener\; paths below are from AA's folder, one up.
$root = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $root 'output\Atlas-Notification-Listener'
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
if (-not (Test-Path -LiteralPath (Join-Path $framework 'csc.exe'))) { throw 'Build requires 64-bit Windows and .NET Framework 4.8.' }
if (-not $ContractsDirectory) {
    $cache = Join-Path $root 'output\notification-build-cache'
    $ContractsDirectory = Join-Path $cache 'contracts\ref\netstandard2.0'
    if (-not (Test-Path -LiteralPath $ContractsDirectory)) {
        New-Item -ItemType Directory -Force -Path $cache | Out-Null
        $archive = Join-Path $cache 'contracts.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.contracts/10.0.19041.2/microsoft.windows.sdk.contracts.10.0.19041.2.nupkg' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $cache 'contracts') -Force
    }
}
$references = @('System.Runtime','System.Runtime.WindowsRuntime','System.Runtime.InteropServices.WindowsRuntime','System.Collections','System.Threading.Tasks','System.Drawing','System.Windows.Forms','System.Web.Extensions') | ForEach-Object { '/r:' + (Join-Path $framework ($_ + '.dll')) }
$references += @('Windows.Foundation.FoundationContract','Windows.Foundation.UniversalApiContract') | ForEach-Object { '/r:' + (Join-Path $ContractsDirectory ($_ + '.winmd')) }
New-Item -ItemType Directory -Force -Path (Join-Path $destination 'Assets') | Out-Null
$common = @('/nologo','/optimize+','/platform:x64',('/resource:' + (Join-Path $root 'backend\inbox\inbox_schema.sql') + ',inbox_schema.sql'))
& (Join-Path $framework 'csc.exe') @common @references /target:winexe ('/win32manifest:' + (Join-Path $root 'notification-listener\app.manifest')) ('/out:' + (Join-Path $destination 'Atlas.NotificationListener.exe')) (Join-Path $root 'notification-listener\Store.cs') (Join-Path $root 'notification-listener\Program.cs')
if ($LASTEXITCODE) { throw 'Notification listener compilation failed.' }
'<?xml version="1.0"?><configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8" /></startup></configuration>' | Set-Content -LiteralPath (Join-Path $destination 'Atlas.NotificationListener.exe.config') -Encoding UTF8
$manifest = [xml](Get-Content -LiteralPath (Join-Path $root 'notification-listener\AppxManifest.xml') -Raw)
$manifest.Package.Identity.SetAttribute('Publisher', $Publisher)
$manifest.Save((Join-Path $destination 'AppxManifest.xml'))
# Simple package assets generated locally; no external icons or personal data.
Add-Type -AssemblyName System.Drawing
foreach ($asset in @(@('Square150x150Logo.png',150), @('Square44x44Logo.png',44), @('StoreLogo.png',50))) {
    $size = [int]$asset[1]
    $bitmap = [Drawing.Bitmap]::new($size,$size)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $font = [Drawing.Font]::new('Segoe UI', [single]($size * 0.55), [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
    try {
        $graphics.Clear([Drawing.Color]::FromArgb(30,64,100))
        $graphics.DrawString('A',$font,[Drawing.Brushes]::White,[single]($size * 0.22),[single]($size * 0.13))
        $bitmap.Save((Join-Path $destination ('Assets\' + $asset[0])),[Drawing.Imaging.ImageFormat]::Png)
    } finally { $font.Dispose(); $graphics.Dispose(); $bitmap.Dispose() }
}
if ($IncludeTests) {
    & (Join-Path $framework 'csc.exe') @common @references /target:exe ('/out:' + (Join-Path $root 'output\NotificationWriter.Tests.exe')) (Join-Path $root 'notification-listener\Store.cs') (Join-Path $root 'tests\notification_writer.cs')
    if ($LASTEXITCODE) { throw 'Notification writer tests failed to compile.' }
}
if ($MakeAppxPath) {
    $msix = Join-Path $root 'output\Atlas-Notification-Listener-unsigned.msix'
    & $MakeAppxPath pack /o /d $destination /p $msix
    if ($LASTEXITCODE) { throw 'MSIX validation/packaging failed.' }
    Write-Host "Unsigned package built: $msix. Sign with a certificate trusted by the target PC before installation."
}
Write-Host "Built listener: $destination"
Write-Host 'No package was installed, no permissions were granted, and no notifications were read.'
