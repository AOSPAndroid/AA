<#
.SYNOPSIS
Prepare a private local queue for Outlook and Atlas running as different users.
.EXAMPLE
$bridge = .\Configure-Outlook-Bridge.ps1 -MailUser 'DOMAIN\x01426046' -AtlasUser 'DOMAIN\x01426046_dsk'
$env:ATLAS_MAIL_DIR = $bridge.Directory

Run in the elevated Atlas account on the Outlook PC. No credentials are saved.
Use -WhatIf to resolve identities and display the plan without changing anything.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$MailUser,
    [Parameter(Mandatory = $true)][string]$AtlasUser
)
$ErrorActionPreference = 'Stop'

function New-MailBridgeAcl {
    param(
        [System.Security.Principal.SecurityIdentifier]$MailSid,
        [System.Security.Principal.SecurityIdentifier]$AtlasSid
    )
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($AtlasSid)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    foreach ($entry in @(
        @($MailSid, [System.Security.AccessControl.FileSystemRights]::Modify),
        @($AtlasSid, [System.Security.AccessControl.FileSystemRights]::ReadAndExecute),
        @([System.Security.Principal.SecurityIdentifier]'S-1-5-18', [System.Security.AccessControl.FileSystemRights]::FullControl)
    )) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($entry[0], $entry[1], $inheritance, $propagation, $allow)
        $acl.AddAccessRule($rule)
    }
    return $acl
}

function Assert-NoReparseAncestor {
    param([string]$Path)
    $probe = [System.IO.DirectoryInfo]::new($Path)
    while ($null -ne $probe) {
        if ($probe.Exists -and ($probe.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "The bridge path contains a link or junction: $($probe.FullName). No permissions were changed."
        }
        $probe = $probe.Parent
    }
}

function Test-MailBridgeAcl {
    param($Actual, $Expected)
    $sidType = [System.Security.Principal.SecurityIdentifier]
    if (-not $Actual.AreAccessRulesProtected -or $Actual.GetOwner($sidType).Value -ne $Expected.GetOwner($sidType).Value) { return $false }
    $keys = @()
    foreach ($acl in @($Actual, $Expected)) {
        $rules = @($acl.GetAccessRules($true, $true, $sidType) | ForEach-Object {
            '{0}|{1}|{2}|{3}|{4}|{5}' -f $_.IdentityReference.Value, [int]$_.FileSystemRights, $_.AccessControlType, $_.InheritanceFlags, $_.PropagationFlags, $_.IsInherited
        } | Sort-Object)
        $keys += ($rules -join ';')
    }
    return $keys[0] -eq $keys[1]
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from the elevated PowerShell used for Atlas.'
}
try {
    $mailSid = ([System.Security.Principal.NTAccount]$MailUser).Translate([System.Security.Principal.SecurityIdentifier])
    $atlasSid = ([System.Security.Principal.NTAccount]$AtlasUser).Translate([System.Security.Principal.SecurityIdentifier])
} catch {
    throw 'An account could not be resolved. Use DOMAIN\username from whoami on the work PC, and check domain connectivity.'
}
if ($mailSid.Value -eq $atlasSid.Value) { throw 'Choose two different Windows accounts for this bridge.' }
if ($mailSid.Value -notlike 'S-1-5-21-*' -or $atlasSid.Value -notlike 'S-1-5-21-*') {
    throw 'Use the two named Windows user accounts, not a built-in group or service identity.'
}
if ($identity.User.Value -ne $atlasSid.Value) {
    throw "Run this script as $AtlasUser, the account that runs Atlas."
}
$mailAccount = $mailSid.Translate([System.Security.Principal.NTAccount]).Value
$atlasAccount = $atlasSid.Translate([System.Security.Principal.NTAccount]).Value
$directory = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) ('Atlas\OutlookBridge\' + $mailSid.Value)
Assert-NoReparseAncestor $directory
$expected = New-MailBridgeAcl $mailSid $atlasSid
$applied = $false
if (Test-Path -LiteralPath $directory) {
    # Re-running only accepts the exact existing protection. Never recursively
    # rewrite permissions on an existing queue, or repoint it to another reader.
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw 'The bridge path is not a directory.' }
    $actual = Get-Acl -LiteralPath $directory
    if (-not (Test-MailBridgeAcl $actual $expected)) {
        throw 'The bridge folder already exists with different permissions. No files or permissions were changed.'
    }
    Write-Host 'Existing bridge permissions verified.'
    $applied = $true
} elseif ($PSCmdlet.ShouldProcess($directory, "Create local mail queue: $mailAccount Modify; $atlasAccount Read; SYSTEM FullControl")) {
    $parent = Split-Path -Parent $directory
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    Assert-NoReparseAncestor $directory
    # Create the queue directory with its restricted ACL from the first instant.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [System.IO.FileSystemAclExtensions]::Create([System.IO.DirectoryInfo]::new($directory), $expected)
    } else {
        [System.IO.Directory]::CreateDirectory($directory, $expected) | Out-Null
    }
    Write-Host 'Private mail bridge created. Existing mailbox history was not moved.'
    $applied = $true
}
Write-Host ''
Write-Host 'In BOTH PowerShell windows, before launching the relevant process:'
Write-Host ("`$env:ATLAS_MAIL_DIR = '" + $directory.Replace("'", "''") + "'")
Write-Host "Normal window ($mailAccount): run windows\Install-Inbox-Collectors.bat once, then start collectors from Atlas Live Inbox."
Write-Host "Elevated window ($atlasAccount): restart Atlas using its usual launcher."
Write-Host 'Keep the watcher at the same elevation level as Outlook. Stop/status commands belong in the normal window.'
[pscustomobject]@{ Directory = $directory; MailAccount = $mailAccount; AtlasAccount = $atlasAccount; Applied = $applied }
