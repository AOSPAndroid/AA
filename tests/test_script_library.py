import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import script_library
from script_library import BUILTIN, build, parse_targets, register

TOKEN = {'X-Atlas-Token': 'test-token'}


class ScriptLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'scripts.json'
        self.token = patch('atlas_api.TOKEN', 'test-token')
        self.token.start()
        self.started = []
        self.start = patch.object(script_library.runner, 'start', side_effect=lambda job: self.started.append(job) or {'id': str(job.id), 'state': 'starting'})
        self.start.start()
        app = FastAPI()
        register(app, self.path)
        self.client = TestClient(app)

    def tearDown(self):
        self.start.stop()
        self.token.stop()
        self.tmp.cleanup()

    def run_script(self, **body):
        return self.client.post('/api/script-library/run', json={'id': str(uuid4()), **body}, headers=TOKEN)

    def test_targets_are_names_only(self):
        self.assertEqual(parse_targets('GBRPWMF20847950, gbrpwmf20847950;PC-2\n\tpc3.corp.example'), ['GBRPWMF20847950', 'PC-2', 'pc3.corp.example'])
        for bad in ('PC1;Remove-Item C:\\', "PC1'; calc", 'PC1$(calc)', '', ' , '):
            with self.assertRaises(HTTPException, msg=bad):
                parse_targets(bad)
        with self.assertRaises(HTTPException):
            parse_targets(' '.join(f'PC{i}' for i in range(501)))

    def test_values_are_quoted_before_the_script(self):
        code = build('Write-Host $Services', ['PC1', 'PC2'], BUILTIN[0]['params'], {'Services': "Example Service\nO'Brien svc, PrintService"})
        self.assertTrue(code.startswith('$ErrorActionPreference = "Continue"\n$Computers = @(\'PC1\', \'PC2\')\n'))
        self.assertIn("$Services = @('Example Service', 'O''Brien svc', 'PrintService')", code)
        self.assertLess(code.index('$Services'), code.index('function Write-Ok'))
        self.assertTrue(code.rstrip().endswith('Write-Host $Services'))
        with self.assertRaises(HTTPException):
            build('x', ['PC1'], BUILTIN[1]['params'], {'Services': 'Example Service', 'StartMode': 'Disabled'})

    def test_service_names_must_be_supplied_before_any_job_starts(self):
        for script in ('services-disable', 'services-enable', 'services-status'):
            item = script_library.BUILTIN_BY_ID[script]
            self.assertEqual(item['params'][0]['default'], '')
            for values in ({}, {'Services': ''}, {'Services': ' \n , ; '}):
                with self.subTest(script=script, values=values):
                    response = self.run_script(script=script, targets='PC1', confirmed=True, values=values)
                    self.assertEqual(response.status_code, 422)
                    self.assertIn('enter at least one value', response.json()['detail'])
        self.assertEqual(self.started, [])
        self.assertEqual(script_library.BUILTIN_BY_ID['software-find']['params'][0]['default'], '')

    def test_download_helpers_are_complete_without_replacing_native_prompts(self):
        library = self.client.get('/api/script-library').json()
        for name in ('Write-Ok', 'Write-Fail', 'Write-Warn', 'Write-Info', 'Get-Wmi', 'Get-WqlText'):
            self.assertIn(f'function {name}', library['export_helpers'])
        self.assertNotIn('function Read-Host', library['export_helpers'])
        self.assertIn('function Read-Host', library['helpers'], 'Atlas keeps its existing input adapter')

    def test_builtin_runs_need_confirmation_when_they_change_machines(self):
        library = self.client.get('/api/script-library').json()
        ids = [item['id'] for item in library['builtin']]
        self.assertIn('services-disable', ids)
        disable = next(item for item in library['builtin'] if item['id'] == 'services-disable')
        self.assertEqual(disable['params'][0]['default'], '')
        self.assertEqual(self.run_script(script='services-disable', targets='PC1').status_code, 428)
        self.assertEqual(self.run_script(script='services-disable', targets='PC1', confirmed=True,
                                         values={'Services': 'Example Service'}, code='Remove-Item C:\\').status_code, 200)
        job = self.started[-1]
        self.assertEqual((job.title, job.targets), ('Stop and disable services', ['PC1']))
        self.assertNotIn('Remove-Item', job.code, 'Built-in code cannot be replaced from the browser')
        self.assertIn('ChangeStartMode(\'Disabled\')', job.code)
        self.assertEqual(self.run_script(script='disk-space', targets='PC1').status_code, 200, 'Read-only scripts run without confirmation')
        self.assertEqual(self.run_script(script='online', targets='bad name!').status_code, 422)
        self.assertEqual(self.client.post('/api/script-library/run', json={'id': str(uuid4()), 'script': 'online', 'targets': 'PC1'}).status_code, 403)

    def test_saved_scripts_with_revisions(self):
        body = {'name': 'Example task', 'description': 'Mine', 'changes': True, 'code': 'foreach ($c in $Computers) { Write-Ok $c }'}
        put = lambda script_id, data: self.client.put(f'/api/script-library/saved/{script_id}', json=data, headers=TOKEN)
        self.assertEqual(put('example-task', body).json()['revision'], 1)
        self.assertEqual(put('example-task', body).status_code, 409, 'A stale window cannot overwrite')
        self.assertEqual(put('example-task', {**body, 'name': 'Example task v2', 'revision': 1}).json()['revision'], 2)
        self.assertEqual(put('services-disable', body).status_code, 400, 'Built-in IDs are reserved')
        self.assertEqual(put('Bad ID', body).status_code, 400)
        self.assertEqual(self.client.put('/api/script-library/saved/x', json=body).status_code, 403)
        saved = self.client.get('/api/script-library').json()['saved']
        self.assertEqual([(item['id'], item['name']) for item in saved], [('example-task', 'Example task v2')])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['version'], 1)
        self.assertEqual(self.run_script(script='example-task', targets='PC1').status_code, 428)
        self.assertEqual(self.run_script(script='example-task', targets='PC1', confirmed=True).status_code, 200)
        self.assertTrue(self.started[-1].code.rstrip().endswith(body['code']))
        self.assertEqual(self.run_script(script='example-task', targets='PC1', confirmed=True, code='Write-Host draft').status_code, 200)
        self.assertTrue(self.started[-1].code.rstrip().endswith('Write-Host draft'), 'An open draft runs what is in the editor')
        self.assertEqual(self.run_script(script='missing', targets='PC1', confirmed=True).status_code, 404)
        self.assertEqual(self.client.delete('/api/script-library/saved/example-task?revision=1', headers=TOKEN).status_code, 409)
        self.assertEqual(self.client.delete('/api/script-library/saved/example-task?revision=2', headers=TOKEN).status_code, 200)
        self.assertEqual(self.client.get('/api/script-library').json()['saved'], [])


@unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'), 'PowerShell is not installed')
class BuiltinSyntax(unittest.TestCase):
    def test_every_builtin_parses(self):
        shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        for script in BUILTIN:
            values = {param['name']: 'Example Service' for param in script['params']
                      if param['kind'] == 'list' and not param.get('default')}
            code = build(script['code'], ['PC1'], script['params'], values)
            check = ('$errors = $null; [void][System.Management.Automation.Language.Parser]::ParseInput([Console]::In.ReadToEnd(), [ref]$null, [ref]$errors); '
                     '$errors | ForEach-Object { $_.Message }')
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', check], input=code, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.stdout.strip(), '', script['id'])


if __name__ == '__main__':
    unittest.main()
