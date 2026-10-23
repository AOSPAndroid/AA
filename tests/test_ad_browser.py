import json,subprocess,unittest,shutil
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import active_directory as ad
class BrowserTests(unittest.TestCase):
 def test_transport_validation_and_token(self):
  from atlas_api import TOKEN
  app=FastAPI();ps=Mock(return_value='{"items":[]}');ad.register(app,ps)
  with TestClient(app) as c:
   self.assertEqual(c.post('/api/active-directory/browse',json={}).status_code,403);ps.assert_not_called()
   headers={'x-atlas-token':TOKEN}
   self.assertEqual(c.post('/api/active-directory/browse',headers=headers,json={'server':'dc;bad'}).status_code,400)
   self.assertEqual(c.post('/api/active-directory/browse',headers=headers,json={'limit':5001}).status_code,422)
   self.assertEqual(c.post('/api/active-directory/browse',headers=headers,json={}).status_code,200)
 def test_ps51_browse_and_literal_filter(self):
  if not shutil.which('powershell.exe'):self.skipTest('Windows PowerShell is not installed')
  ps=Mock(return_value='{"items":[]}')
  ad.browse(ad.Browse(operation='search',query="x*)(name=*)'",server='dc.test'),ps)
  script=ps.call_args.args[0]
  mock=r'''
function Import-Module {}
function Get-ADRootDSE { [pscustomobject]@{defaultNamingContext='DC=test'} }
function Get-ADObject {
 param($LDAPFilter,$SearchBase,$SearchScope,$ResultSetSize,$ResultPageSize,$Properties,$Server)
 if($SearchScope -ne 'Subtree' -or $SearchBase -ne 'DC=test' -or $Server -ne 'dc.test'){throw 'Wrong query scope'}
 if(!$LDAPFilter.Contains('\2a\29\28name=\2a\29')){throw 'LDAP escaping missing'}
 [pscustomobject]@{Name='PC01';ObjectClass='computer';DistinguishedName='CN=PC01,DC=test';ObjectGUID='12345678-1234-1234-1234-123456789012';sAMAccountName='PC01$'}
}
'''
  r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',mock+script],capture_output=True,text=True,timeout=10)
  result=json.loads(r.stdout);self.assertEqual(result['items'][0]['account'],'PC01$');self.assertFalse(result['more'])
if __name__=='__main__':unittest.main()
