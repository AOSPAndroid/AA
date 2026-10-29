[CmdletBinding()]
param([string]$DataDirectory = $env:ATLAS_MAIL_DIR, [switch]$AutoStart, [switch]$Background)
$ErrorActionPreference = 'Stop'
$savedConfig = Join-Path (Split-Path -Parent $PSScriptRoot) 'data\inbox-integration.json'
if (-not $PSBoundParameters.ContainsKey('DataDirectory') -and (Test-Path -LiteralPath $savedConfig)) {
    $DataDirectory = (Get-Content -LiteralPath $savedConfig -Raw | ConvertFrom-Json).directory
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ([Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run normally as the Teams/Outlook account (x01426046), not from elevated Atlas.'
}
$package = Get-AppxPackage -Name Atlas.NotificationListener | Select-Object -First 1
if (-not $package) { throw 'Install the Atlas Notification Listener package for this Windows account first. See docs/notification-listener.md.' }
if ([version]$package.Version -lt [version]'1.1.0.0') { throw 'Update the Atlas Notification Listener package to 1.1.0.0 or newer for integrated GUI controls.' }
$arguments = ''
if ($DataDirectory) {
    $directory = (Resolve-Path -LiteralPath $DataDirectory).Path
    if ($directory.Contains('"') -or $directory -eq [IO.Path]::GetPathRoot($directory)) { throw 'Choose a dedicated Atlas data folder.' }
    $arguments = '--data-dir "' + $directory.TrimEnd('\') + '"'
}
if ($AutoStart) { $arguments += ' --auto-start' }
if ($Background) { $arguments += ' --background' }
# Activate the installed app identity so Windows can attach its consent prompt.
# Arguments are passed to Windows activation, never through a command shell.
if (-not ('AtlasNotificationActivation' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAtlasApplicationActivationManager {
 [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string app, [MarshalAs(UnmanagedType.LPWStr)] string args, uint options, out uint pid);
 [PreserveSig] int ActivateForFile(IntPtr app, IntPtr items, IntPtr verb, out uint pid);
 [PreserveSig] int ActivateForProtocol(IntPtr app, IntPtr items, out uint pid);
}
public static class AtlasNotificationActivation {
 public static uint Open(string app, string args) {
  var manager = (IAtlasApplicationActivationManager)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")));
  try { uint pid; Marshal.ThrowExceptionForHR(manager.ActivateApplication(app,args,0,out pid)); return pid; }
  finally { Marshal.ReleaseComObject(manager); }
 }
}
'@
}
$processId = [AtlasNotificationActivation]::Open(($package.PackageFamilyName + '!Listener'), $arguments)
Write-Host "Atlas Notification Listener opened (PID $processId). First-time Windows consent is available in Listener settings from Atlas Live Inbox."
