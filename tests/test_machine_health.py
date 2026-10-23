import concurrent.futures,json,threading,unittest
from machine_health import HealthChecks,QUERIES
from fastapi import HTTPException
class Transport:
 def validate_pc(self,pc):
  if not pc.replace('-','').isalnum():raise ValueError('Invalid hostname')
  return pc.upper()
 def quote(self,s):return "'"+s+"'"
 def ps(self,script,timeout):return json.dumps({'available':True})
 def run(self,*a,**kw):return type('Result',(),{'returncode':0})()
class Tests(unittest.TestCase):
 def test_failed_is_not_zero(self):
  t=Transport();t.ps=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('timeout'))
  r=HealthChecks(t).check('PC1','ram');self.assertEqual(r['state'],'unavailable');self.assertIsNone(r['data']);self.assertIn('checked_at',r)
 def test_validates_before_query(self):
  h=HealthChecks(Transport())
  with self.assertRaises(ValueError):h.check("PC';evil",'cpu')
  with self.assertRaises(HTTPException):h.check('PC','execute')
 def test_metrics_independent_and_duplicate_shared(self):
  gate=threading.Event();started=threading.Event();calls=[];t=Transport()
  def ps(script,timeout):
   calls.append(script)
   if 'Win32_Processor' in script:started.set();gate.wait(3)
   return '{"available":true}'
  t.ps=ps;h=HealthChecks(t)
  with concurrent.futures.ThreadPoolExecutor(3) as pool:
   slow=pool.submit(h.check,'pc','cpu');self.assertTrue(started.wait(1));duplicate=pool.submit(h.check,'PC','cpu');fast=pool.submit(h.check,'PC','wmi')
   self.assertEqual(fast.result(1)['state'],'ready');self.assertFalse(slow.done());gate.set();self.assertEqual(slow.result(),duplicate.result())
  self.assertEqual(sum('Win32_Processor' in x for x in calls),1)
 def test_power_shell_queries_are_read_only(self):
  for script in QUERIES.values():
   self.assertNotIn('Win32_Product',script);self.assertNotIn('Invoke-',script);self.assertNotIn('Remove-',script)
if __name__=='__main__':unittest.main()
