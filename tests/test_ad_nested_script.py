import json, subprocess, unittest, shutil, os
from pathlib import Path

class DirectoryScriptTests(unittest.TestCase):
 def run_fixture(self, kind='user', broken=False, expiry='134050464000000000', shell='pwsh'):
  if not shutil.which(shell):self.skipTest(shell+' is not installed')
  source=Path('scripts/active_directory.ps1').read_text(encoding='utf8')
  if os.name!='nt':
   # AD providers below are fictional. Linux also needs a fictional report operator;
   # WindowsIdentity is Windows-only, and this replacement never reaches production.
   operator='[System.Security.Principal.WindowsIdentity]::GetCurrent().Name'
   self.assertEqual(source.count(operator),1,'Operator reporting boundary changed; review the fixture')
   source=source.replace(operator,"'FIXTURE\\Operator'",1)
  mock=r'''
$kind='KIND';$identity='fixture';$server='dc.test';$broken=BROKEN
function Get-Module { 'fixture' }
function Import-Module {}
function Get-ADUser {
 [pscustomobject]@{Name='Fixture';SamAccountName='fixture';DistinguishedName='CN=Fixture,OU=Test,DC=test';Enabled=$true;LockedOut=$false;PasswordExpired=$false;MemberOf=@('CN=A,DC=test');PrimaryGroupID=513;SID=[pscustomobject]@{AccountDomainSid=[pscustomobject]@{Value='S-1-5-21-1'}};'msDS-UserPasswordExpiryTimeComputed'=134050464000000000}
}
function Get-ADComputer { Get-ADUser }
function Get-ADGroup {
 param($Identity,$Properties,$Server)
 switch($Identity){
 'CN=A,DC=test' { [pscustomobject]@{Name='A';Description='Trading application access';DistinguishedName=$Identity;GroupScope='Global';GroupCategory='Security';MemberOf=@('CN=B,DC=test')} }
 'CN=B,DC=test' { if($broken){throw 'fixture failure'};[pscustomobject]@{Name='B';DistinguishedName=$Identity;GroupScope='Global';GroupCategory='Security';MemberOf=@('CN=A,DC=test')} }
 'S-1-5-21-1-513' { [pscustomobject]@{Name='Primary';DistinguishedName='CN=Primary,DC=test';GroupScope='Global';GroupCategory='Security';MemberOf=@('CN=C,DC=test')} }
 'CN=C,DC=test' { [pscustomobject]@{Name='C';DistinguishedName=$Identity;GroupScope='Global';GroupCategory='Security';MemberOf=@()} }
 default {throw 'Unexpected fixture group'}
 }
}
'''.replace('KIND',kind).replace('BROKEN','$true' if broken else '$false').replace('134050464000000000',expiry)
  r=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',mock+'\n'+source],capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stderr)
  data=json.loads(r.stdout)
  self.assertNotIn('error',data,'Mocked directory script failed: '+str(data.get('error','')))
  if os.name!='nt':self.assertEqual(data['operator'],r'FIXTURE\Operator')
  return data
 def test_nested_cycle_and_primary_parent(self):
  data=self.run_fixture();groups={g['name']:g['membership'] for g in data['groups']}
  self.assertEqual(groups,{'A':'Direct','B':'Nested','C':'Nested','Primary':'Primary'})
  self.assertEqual(next(g for g in data['groups'] if g['name']=='A')['description'],'Trading application access')
  self.assertTrue(data['nested_complete']);self.assertEqual(data['details']['Password expiry status'],'Computed')
 def test_windows_powershell_preserves_all_groups(self):
  for kind in ('user','computer'):
   data=self.run_fixture(kind=kind,shell='powershell.exe')
   self.assertEqual(len(data['groups']),4)
 def test_password_expiry_sentinels(self):
  self.assertEqual(self.run_fixture(expiry='9223372036854775807')['details']['Password expiry status'],'No expiry computed')
  self.assertEqual(self.run_fixture(expiry='0')['details']['Password expiry status'],'Must change / not set')
 def test_partial_and_machine(self):
  data=self.run_fixture('computer',True)
  self.assertFalse(data['nested_complete']);self.assertTrue(data['warnings']);self.assertNotIn('Password expires',data['details'])
  self.assertIn('C',[g['name'] for g in data['groups']])

if __name__=='__main__':unittest.main()
