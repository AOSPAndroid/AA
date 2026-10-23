import json,unittest
from fastapi import HTTPException
from service_actions import enable_remote_registry
class Transport:
 def __init__(self):self.calls=[];self.result={'computer':'PC1','service':'RemoteRegistry','state':'Running','start_mode':'Manual','previous_state':'Stopped','previous_start_mode':'Disabled'}
 def validate_pc(self,pc):
  if not pc.replace('-','').isalnum():raise ValueError('Invalid hostname')
  return pc.upper()
 def quote(self,value):return "'"+value+"'"
 def ps(self,script,timeout):self.calls.append((script,timeout));return json.dumps(self.result)
class Tests(unittest.TestCase):
 def test_fixed_service_and_bounded_transport(self):
  t=Transport();r=enable_remote_registry(t,'pc1');self.assertEqual(r['state'],'Running');script,timeout=t.calls[0]
  self.assertIn("Name='RemoteRegistry'",script);self.assertIn("ChangeStartMode('Manual')",script);self.assertNotIn('Automatic',script);self.assertEqual(timeout,30)
 def test_rejects_invalid_target_before_remote_call(self):
  t=Transport()
  with self.assertRaises(ValueError):enable_remote_registry(t,"PC';bad")
  self.assertEqual(t.calls,[])
 def test_rejects_failed_or_wrong_target_results(self):
  for field,value in [('state','Stopped'),('computer','OTHER'),('service','OtherService')]:
   t=Transport();t.result[field]=value
   with self.assertRaises(HTTPException):enable_remote_registry(t,'PC1')
if __name__=='__main__':unittest.main()
