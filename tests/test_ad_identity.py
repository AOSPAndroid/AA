import json, subprocess, unittest, shutil
from pathlib import Path
class IdentityTests(unittest.TestCase):
 def resolve(self, scenario, identity='G01234'):
  if not shutil.which('pwsh'):self.skipTest('PowerShell Core is not installed')
  source=Path('scripts/active_directory.ps1').read_text(encoding='utf8')
  source=source[:source.index('function DateText')]
  mock=r'''
# Load serialization before the module mocks; avoid scanning unrelated runner modules.
$PSModuleAutoLoadingPreference='None'
Microsoft.PowerShell.Core\Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Utility" -ErrorAction Stop
$kind='user';$server='dc.test';$identity='IDENTITY';$scenario='SCENARIO'
function Get-Module { 'fixture' }
function Import-Module {}
function Get-ADUser {
 [CmdletBinding()]param($Identity,$Filter,$ResultSetSize,$Properties,$Server)
 if($Server -ne 'dc.test'){throw 'Server lost'}
 if($Identity){
  if($scenario -eq 'direct'){return [pscustomobject]@{SamAccountName='direct'}}
  if($scenario -eq 'denied'){throw 'Access denied'}
  $e=[System.Management.Automation.ErrorRecord]::new([Exception]::new('Not found'),'ADIdentityNotFoundException',[System.Management.Automation.ErrorCategory]::ObjectNotFound,$Identity)
  $PSCmdlet.ThrowTerminatingError($e)
 }
 if($ResultSetSize -ne 2 -or $Filter -notmatch 'employeeID -eq' -or $Filter -notmatch 'mail -eq'){throw 'Invalid bounded exact query'}
 if($scenario -eq 'none'){return}
 [pscustomobject]@{SamAccountName='resolved'}
 if($scenario -eq 'ambiguous'){[pscustomobject]@{SamAccountName='other'}}
}
'''.replace('IDENTITY',identity).replace('SCENARIO',scenario)
  # Includes cold PowerShell startup on hosted runners; all AD calls stay mocked.
  r=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',mock+'\n'+source+'\n$o | ConvertTo-Json -Compress'],capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stderr)
  return json.loads(r.stdout)
 def test_exact_and_fallback(self):
  self.assertEqual(self.resolve('direct')['SamAccountName'],'direct')
  self.assertEqual(self.resolve('fallback')['SamAccountName'],'resolved')
  self.assertEqual(self.resolve('fallback','user@example.test')['SamAccountName'],'resolved')
 def test_no_ambiguous_or_denied_selection(self):
  self.assertIn('No user matched',self.resolve('none')['error'])
  self.assertIn('More than one',self.resolve('ambiguous')['error'])
  self.assertIn('Access denied',self.resolve('denied')['error'])
if __name__=='__main__':unittest.main()
