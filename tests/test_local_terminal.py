import base64
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import local_terminal as terminal
from atlas_api import TOKEN


class TerminalTests(unittest.TestCase):
    def test_script_preserves_unicode_and_no_policy_bypass(self):
        command = terminal.Command(id=uuid4(), code="Write-Output 'été';\nGet-Date")
        args = terminal.prepare(command)[2]
        self.assertEqual(base64.b64decode(args[-1]).decode('utf-16le'), command.code)
        self.assertNotIn('-ExecutionPolicy', args)
        self.assertIn('-NonInteractive', args)

    def test_auth_elevation_streaming_and_idempotency(self):
        calls = []
        def launch(args, **kwargs):
            calls.append(args)
            return subprocess.Popen([sys.executable, '-u', '-c', "print('TERMINAL FIXTURE')"], **kwargs)
        runner = terminal.LocalRunner(popen=launch, preflight=lambda p:dict(exists=True,elevated=True,account='TEST'))
        self.addCleanup(runner.close)
        app = FastAPI(); terminal.register(app)
        with patch.object(terminal, 'runner', runner), TestClient(app) as client:
            payload = dict(id=str(uuid4()), code='Get-Date')
            headers = {'X-Atlas-Token':TOKEN}
            self.assertEqual(client.post('/api/terminal/run',json=payload).status_code,403)
            self.assertEqual(client.get('/api/terminal/runs').status_code,403)
            self.assertEqual(client.post('/api/terminal/run',json=payload,headers=headers).status_code,200)
            for _ in range(100):
                result=client.get('/api/terminal/runs/'+payload['id'],headers=headers).json()
                if result['state']=='complete':break
                time.sleep(.02)
            self.assertIn('TERMINAL FIXTURE',result['output'])
            self.assertEqual(result['exit_code'],0)
            client.post('/api/terminal/run',json=payload,headers=headers)
            self.assertEqual(len(calls),1)
            self.assertEqual(len(client.get('/api/terminal/runs',headers=headers).json()),1)
        denied=terminal.LocalRunner(preflight=lambda p:dict(exists=True,elevated=False))
        with self.assertRaises(HTTPException):denied.start(terminal.Command(id=uuid4(),code='Get-Date'))


if __name__=='__main__':unittest.main()
