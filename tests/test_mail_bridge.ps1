# Validate the exact ACL builder without running workstation configuration.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'Configure-Outlook-Bridge.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$builder = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'New-MailBridgeAcl' }, $true)
$checker = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-MailBridgeAcl' }, $true)
$reader = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$writer = [System.Security.Principal.SecurityIdentifier]'S-1-5-21-100-200-300-9999'
$acl = $builder.Body.GetScriptBlock().Invoke($writer, $reader)[0]
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 3) { throw 'The queue must have three explicit, protected rules.' }
$readerRule = @($rules | Where-Object { $_.IdentityReference.Value -eq $reader.Value })[0]
if (($readerRule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Write) -ne 0) { throw 'The reader must not have write access.' }
if (($readerRule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -ne [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) { throw 'The reader needs read access.' }
$writerRule = @($rules | Where-Object { $_.IdentityReference.Value -eq $writer.Value })[0]
if (($writerRule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Modify) -ne [System.Security.AccessControl.FileSystemRights]::Modify) { throw 'The writer needs modify access.' }
if (@($rules | Where-Object { $_.IdentityReference.Value -in @('S-1-1-0','S-1-5-11','S-1-5-32-545','S-1-5-32-544') }).Count) { throw 'Unexpected broad group grant.' }

# Exercise the Windows reader against a real restricted folder and SQLite file.
# Only this newly created temporary directory has its ACL changed.
$testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('atlas-mail-reader-test-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($testDirectory) | Out-Null
$cleanupAcl = New-Object System.Security.AccessControl.DirectorySecurity
$cleanupAcl.SetAccessRuleProtection($true, $false)
$cleanupAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($reader, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
$previousDirectory = [Environment]::GetEnvironmentVariable('ATLAS_BRIDGE_TEST_DIR', 'Process')
$previousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $atomicDirectory = Join-Path $testDirectory 'atomic-create'
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [System.IO.FileSystemAclExtensions]::Create([System.IO.DirectoryInfo]::new($atomicDirectory), $acl)
    } else {
        [System.IO.Directory]::CreateDirectory($atomicDirectory, $acl) | Out-Null
    }
    $createdAcl = Get-Acl -LiteralPath $atomicDirectory
    if (-not $checker.Body.GetScriptBlock().Invoke($createdAcl, $acl)[0]) { throw 'An unchanged existing bridge must pass its permissions check.' }
    if ($checker.Body.GetScriptBlock().Invoke((Get-Acl -LiteralPath $testDirectory), $acl)[0]) { throw 'A folder with inherited broad permissions must be rejected.' }
    $env:ATLAS_BRIDGE_TEST_DIR = $testDirectory
    $env:PYTHONPATH = $root
    @'
import os
from pathlib import Path
from outlook_watcher import MailQueue, utcnow, write_json
base = Path(os.environ['ATLAS_BRIDGE_TEST_DIR'])
queue = MailQueue(base, utcnow())
queue.close()
(base / 'watcher.lock').write_bytes(b'0')
write_json(base / 'status.json', {'state': 'stopped'})
(base / 'notifications.lock').write_bytes(b'0')
write_json(base / 'notifications-status.json', {'state': 'watching', 'updated_at': utcnow().isoformat()})
'@ | py -3.12 -
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the isolated queue.' }
    Set-Acl -LiteralPath $testDirectory -AclObject $acl
    @'
import os
from pathlib import Path
from mail_inbox import queue_reader, watcher_status
from notification_inbox import notification_status
base = Path(os.environ['ATLAS_BRIDGE_TEST_DIR'])
with queue_reader(base) as queue:
    assert queue.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
assert watcher_status(base)['state'] == 'stopped'
assert notification_status(base)['state'] == 'stopped'
for name in ('watcher.lock', 'status.json', 'inbox.sqlite3', 'notifications.lock', 'notifications-status.json'):
    try:
        with (base / name).open('r+b'):
            raise AssertionError('Reader could open ' + name + ' for writing')
    except PermissionError:
        pass
print('PASS: Windows queue, status and lock reads succeed with read-only NTFS permissions; write opens fail.')
'@ | py -3.12 -
    if ($LASTEXITCODE -ne 0) { throw 'Read-only Windows bridge test failed.' }
} finally {
    # Restore DACL write access only; do not attempt to write audit rules/SACLs.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($testDirectory), $cleanupAcl)
        [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($atomicDirectory), $cleanupAcl)
    } else {
        ([System.IO.DirectoryInfo]::new($testDirectory)).SetAccessControl($cleanupAcl)
        ([System.IO.DirectoryInfo]::new($atomicDirectory)).SetAccessControl($cleanupAcl)
    }
    [Environment]::SetEnvironmentVariable('ATLAS_BRIDGE_TEST_DIR', $previousDirectory, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $previousPythonPath, 'Process')
    $resolvedTest = (Resolve-Path -LiteralPath $testDirectory).Path
    $allowedParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedTest.StartsWith($allowedParent, [System.StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolvedTest) -notlike 'atlas-mail-reader-test-*') { throw 'Refusing cleanup outside the isolated test directory.' }
    # Delete only known fixture files and the empty atomic-create directory.
    # Unexpected files stop cleanup rather than being removed recursively.
    $knownFiles = @('inbox.sqlite3','watcher.lock','status.json','notifications.lock','notifications-status.json')
    foreach ($entry in Get-ChildItem -LiteralPath $resolvedTest -Force) {
        if ($entry.Name -notin ($knownFiles + 'atomic-create')) { throw 'Unexpected file in test directory; leaving it intact.' }
    }
    foreach ($name in $knownFiles) {
        $file = Join-Path $resolvedTest $name
        if (Test-Path -LiteralPath $file -PathType Leaf) { Remove-Item -LiteralPath $file }
    }
    if (Test-Path -LiteralPath $atomicDirectory) { [System.IO.Directory]::Delete($atomicDirectory, $false) }
    [System.IO.Directory]::Delete($resolvedTest, $false)
}
Write-Host 'PASS: setup syntax and exact collector/reader/SYSTEM ACL boundaries.'
