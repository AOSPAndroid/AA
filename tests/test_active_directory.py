import json
import subprocess
import unittest
from unittest.mock import Mock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import active_directory as ad

class ADTests(unittest.TestCase):
 def test_literal_validation_and_domain(self):
  script=ad.script_for(ad.Lookup(kind='user',identity=r'DOMAIN\user'))
  self.assertIn("$identity='user';$server='DOMAIN'",script)
  for identity in ["x';whoami", '*', '@file', 'a,b', 'a b', 'user\nexit', '-admin']:
   with self.assertRaises(HTTPException):ad.script_for(ad.Lookup(kind='user',identity=identity))
  with self.assertRaises(HTTPException):ad.script_for(ad.Lookup(kind='computer',identity='PC',server='dc;exit'))
 def test_report_ids_map_to_x_user_accounts(self):
  for identity in ['G01426046','b01426046','x01426046',r'INTRANET\G01426046']:
   script=ad.script_for(ad.Lookup(kind='user',identity=identity))
   self.assertIn("$identity='X01426046'",script)
  self.assertIn("$identity='X00123@example.test'",ad.script_for(ad.Lookup(kind='user',identity='g00123@example.test')))
  for identity in ['bob','g123-admin','GBRPWMF20844775','12345']:
   self.assertIn("$identity='"+identity+"'",ad.script_for(ad.Lookup(kind='user',identity=identity)))
  self.assertIn("$identity='G01426046'",ad.script_for(ad.Lookup(kind='computer',identity='G01426046')))
 def test_result_and_errors(self):
  payload=ad.Lookup(kind='computer',identity='PC01')
  ps=Mock(return_value=json.dumps({'details':{'Enabled':False},'groups':[]}))
  self.assertFalse(ad.lookup(payload,ps)['details']['Enabled']);self.assertEqual(ps.call_args.kwargs['timeout'],35)
  for response in ['not json','[]','{"details": {}, "groups": null}']:
   with self.assertRaises(HTTPException):ad.lookup(payload,Mock(return_value=response))
  with self.assertRaises(HTTPException) as e:ad.lookup(payload,Mock(side_effect=subprocess.TimeoutExpired('powershell',35)))
  self.assertEqual(e.exception.status_code,504)
 def test_readable_errors(self):
  xml = '#< CLIXML\n<Objs xmlns="http://schemas.microsoft.com/powershell/2004/04"><S S="Error">Get-ADUser: Cannot find object._x000D__x000A_At line:14 char:1</S></Objs>'
  self.assertEqual(ad.readable_error(xml),'Get-ADUser: Cannot find object.')
  self.assertNotIn('Objs',ad.readable_error('# CLIXML <Objs broken'))
  with self.assertRaises(HTTPException) as e:
   ad.lookup(ad.Lookup(kind='user',identity='test'),Mock(return_value='{"error":"No user matched. Check server."}'))
  self.assertIn('No user matched', e.exception.detail)
 def test_token_before_any_query(self):
  from atlas_api import TOKEN
  app=FastAPI();ps=Mock(return_value='{"details": {}, "groups": []}');ad.register(app,ps)
  with TestClient(app) as client:
   body={'kind':'user','identity':'testuser'}
   self.assertEqual(client.post('/api/active-directory/lookup',json=body).status_code,403);ps.assert_not_called()
   self.assertEqual(client.post('/api/active-directory/lookup',json=body,headers={'x-atlas-token':TOKEN}).status_code,200)
   self.assertEqual(client.post('/api/active-directory/lookup',json={**body,'password':'secret'},headers={'x-atlas-token':TOKEN}).status_code,422)
if __name__=='__main__':unittest.main()
