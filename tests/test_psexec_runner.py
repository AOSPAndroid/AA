"""Real pipes with harmless local Python fixtures; never invoke PsExec."""
import base64
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import psexec_runner as px


def payload(**kw):
    return px.RunRequest(**dict(dict(id=uuid4(), template='identity', target='TESTPC', path=r'C:\Data\PsExec.exe'), **kw))


class PsExecTests(unittest.TestCase):
    def runner(self, script, **kw):
        calls = []
        def start(args, **options):
            calls.append(args)
            return subprocess.Popen([sys.executable, '-u', '-c', script], **options)
        runner = px.Runner(popen=start, preflight=lambda p:dict(exists=True,eula_accepted=False,account='TEST\\Operator',elevated=True), **kw)
        self.addCleanup(runner.close)
        return runner, calls

    def wait(self, runner, key, predicate=lambda j:j['state'] in px.TERMINAL):
        for _ in range(200):
            j = runner.snapshot(key)
            if predicate(j): return j
            time.sleep(.02)
        self.fail('Session did not reach expected state')

    def test_server_validation_and_shared_catalogue(self):
        self.assertEqual(len(px.CATALOGUE),72)
        js=(px.ROOT/'frontend/assets/psexec-catalogue.js').read_text()
        self.assertEqual(json.loads(js.split(' = ',1)[1].removesuffix(';\n')),list(px.CATALOGUE.values()))
        for target in ['*','HOST1,HOST2','@file','-s','HOST&calc','HOST\nCMD']:
            with self.assertRaises(HTTPException):px.prepare(payload(target=target))
        for values in [{'service':"x'; calc; #"},{'service':'Spooler','other':'x'}]:
            with self.assertRaises(HTTPException):px.prepare(payload(template='service',values=values))
        with self.assertRaises(HTTPException):px.prepare(payload(template='restart-service',values={'service':'Spooler'}))
        with self.assertRaises(HTTPException):px.prepare(payload(template='tcp',values={'destination':'SERVER01','port':'65536'}))
        item, target, args, text=px.prepare(payload(template='service',values={'service':'MSSQL$INSTANCE'}))
        self.assertIn("'Name=''MSSQL$INSTANCE'''",text)
        self.assertEqual(base64.b64decode(args[-1]).decode('utf-16le'),text)
        self.assertNotIn('-s',args);self.assertEqual(args.count('-accepteula'),1)

    def test_direct_tools_are_allowlisted_and_do_not_use_psexec_flags(self):
        for item in px.CATALOGUE.values():
            if not item.get('direct'):continue
            defaults={'pid':'1234','fileid':'123','service':'Spooler','port':'443','account':r'DOMAIN\user'}
            values={f['key']:defaults[f['key']] for f in item['fields']}
            _,_,args,_=px.prepare(payload(template=item['id'],values=values,confirmation='TESTPC',elevated=True))
            self.assertEqual(args[0], 'C:\\Data\\'+item['tool']+'.exe')
            self.assertNotIn('-nobanner',args)
            self.assertEqual(args.count('-accepteula'),1)
            if item.get('change'):
                with self.assertRaises(HTTPException):px.prepare(payload(template=item['id'],values=values))
        _,_,args,_=px.prepare(payload(template='pst-tcp',values={'port':'443'}))
        self.assertEqual(args[1:],['-accepteula','-n','10','TESTPC:443'])
        _,_,args,_=px.prepare(payload(template='pst-password-help'))
        self.assertEqual(args[1:],['-accepteula','-?'])
        for bad in ['1','4','123 & calc']:
            with self.assertRaises(HTTPException):px.prepare(payload(template='pst-kill',values={'pid':bad},confirmation='TESTPC'))
        with self.assertRaises(HTTPException):px.prepare(payload(template='pst-tcp',values={'port':'65536'}))

    def test_dism_system_context_and_restart_policy(self):
        for key in ('netfx3-enable','print-pdf-enable','dism-restorehealth'):
            with self.assertRaises(HTTPException):px.prepare(payload(template=key))
            item,target,args,text=px.prepare(payload(template=key,confirmation='TESTPC',elevated=True))
            self.assertIn('-s',args);self.assertNotIn('-h',args)
            self.assertIn('/NoRestart',args);self.assertIn(3010,item['success_exit_codes'])
            self.assertEqual(item['timeout_seconds'],3600)
        _,_,args,_=px.prepare(payload(template='netfx3-enable',confirmation='TESTPC'))
        self.assertEqual(args[-6:],['dism.exe','/Online','/Enable-Feature','/FeatureName:NetFx3','/All','/NoRestart'])

    def test_output_is_live_and_duplicate_start_is_idempotent(self):
        r,calls=self.runner("import time; print('FIRST',flush=True); time.sleep(.5); print('LAST',flush=True)")
        p=payload();j=r.start(p);key=j['id']
        self.wait(r,key,lambda j:'FIRST' in j['output'])
        self.assertNotIn('LAST',r.snapshot(key)['output'])
        r.start(p);self.assertEqual(len(calls),1)
        with self.assertRaises(HTTPException):r.start(payload())
        with self.assertRaises(HTTPException):r.start(payload(id=p.id,target='OTHERPC'))
        j=self.wait(r,key);self.assertEqual(j['state'],'complete');self.assertEqual(j['exit_code'],0)
        self.assertIn('LAST',j['output']);self.assertEqual(j['target'],'TESTPC')
        self.assertNotIn('_process',j)

    def test_interactive_input_and_normal_exit(self):
        r,_=self.runner("import sys\nprint('READY',flush=True)\nfor line in sys.stdin:\n print('ECHO:'+line.strip(),flush=True)\n if line.strip()=='exit':break")
        key=r.start(payload(template='shell',values={'session':'1'}))['id'];self.wait(r,key,lambda j:'READY' in j['output'])
        with self.assertRaises(HTTPException):r.send(key,'one\ntwo')
        r.send(key,'hostname');self.wait(r,key,lambda j:'ECHO:hostname' in j['output'])
        r.send(key,'exit');self.assertEqual(self.wait(r,key)['state'],'complete')
        with self.assertRaises(HTTPException):r.send(key,'later')

    def test_stop_timeout_and_bounded_transcript(self):
        r,_=self.runner("import time; print('x'*4000,flush=True); time.sleep(30)",limit=1024)
        key=r.start(payload())['id'];self.wait(r,key,lambda j:j['truncated']);r.stop(key)
        j=self.wait(r,key);self.assertEqual(j['state'],'stopped');self.assertLessEqual(len(j['output']),1024)
        self.assertIn('may still be running',j['output'])
        r,_=self.runner('import time; time.sleep(30)',timeout=.15)
        key=r.start(payload())['id'];self.assertEqual(self.wait(r,key)['state'],'timed_out')

    def test_nonzero_exit_and_no_input_for_templates(self):
        r,_=self.runner("import sys,time;print('failure');time.sleep(.3);sys.exit(7)")
        key=r.start(payload())['id']
        with self.assertRaises(HTTPException):r.send(key,'hostname')
        j=self.wait(r,key);self.assertEqual(j['state'],'failed');self.assertEqual(j['exit_code'],7)

    def test_preflight_requires_executable_and_elevation(self):
        for exists,elevated in [(False,True),(True,False)]:
            r,calls=self.runner('print(1)');r.preflight=lambda p:dict(exists=exists,elevated=elevated)
            with self.assertRaises(HTTPException):r.start(payload())
            self.assertFalse(calls)

    def test_first_use_acceptance_runs_selected_tool_once(self):
        for template,values in [('identity',{}),('pst-tcp',{'port':'443'})]:
            r,calls=self.runner('print("SIMULATED FIRST RUN")')
            # No acceptance registry record is required; the actual executable
            # handles the flag. The test launches only a harmless Python pipe.
            r.preflight=lambda p:dict(exists=True,elevated=True,account='TEST\\Operator')
            p=payload(template=template,values=values,path=r'C:\Data\PsExec64.exe')
            job=r.start(p);result=self.wait(r,job['id']);r.start(p)
            self.assertEqual(result['state'],'complete')
            self.assertIn('SIMULATED FIRST RUN',result['output'])
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0].count('-accepteula'),1)
            self.assertEqual(calls[0][0],r'C:\Data\PsExec64.exe' if template=='identity' else r'C:\Data\PsPing64.exe')

    def test_routes_require_token_and_reject_client_scripts(self):
        from atlas_api import TOKEN
        r,calls=self.runner('print("TEST")')
        app=FastAPI();px.register(app)
        with patch.object(px,'runner',r), TestClient(app) as client:
            p=payload().model_dump(mode='json')
            self.assertEqual(client.post('/api/psexec/run',json=p).status_code,403)
            bad=dict(p,script='calc.exe')
            self.assertEqual(client.post('/api/psexec/run',json=bad,headers={'X-Atlas-Token':TOKEN}).status_code,422)
            self.assertFalse(calls)
            response=client.post('/api/psexec/run',json=p,headers={'X-Atlas-Token':TOKEN})
            self.assertEqual(response.status_code,200)
            self.wait(r,p['id'])
            self.assertEqual(client.post(f"/api/psexec/runs/{p['id']}/stop",json={}).status_code,403)


if __name__=='__main__':unittest.main()
