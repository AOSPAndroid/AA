"""An extracted release boots with fictional data and simulated, unexecuted runtimes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from tools.build_aa_bundle import build


class ReleaseBundle(unittest.TestCase):
    def test_extracted_application_starts_and_excludes_retired_or_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtimes=root/'runtimes'
            for kind in ('cpu','vulkan'):
                folder=runtimes/('llama-'+kind);folder.mkdir(parents=True)
                (folder/'llama-server.exe').write_bytes(b'UNEXECUTED TEST FIXTURE')
            archive=root/'aa-windows.zip';build(runtimes,archive)
            with zipfile.ZipFile(archive) as z:
                names=z.namelist()
                self.assertFalse(any('/drawio/' in n or '/tests/' in n or n.endswith(('config.json','.gguf','database040926.xlsx')) for n in names))
                metadata=json.loads(z.read('AA/BUNDLE-MANIFEST.json'))
                import hashlib
                for name,digest in metadata['files'].items():self.assertEqual(hashlib.sha256(z.read('AA/'+name)).hexdigest(),digest,name)
                z.extractall(root/'unpacked')
            install=root/'unpacked/AA'
            env=dict(os.environ,AA_DATA_HOME=str(root/'runtime'),ATLAS_IMPORT_FOLDER=str(root/'empty-imports'),
                     AA_AXIS_STATE=str(root/'runtime/axis/state'),AA_AXIS_TERMINAL_STATE=str(root/'legacy-state'))
            env.pop('ATLAS_DB_PATH',None)
            code='''from backend.factory import create_app
from fastapi.testclient import TestClient
app=create_app()
from backend import main
main.identity=lambda:'FICTIONAL TEST OPERATOR'
with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
 assert client.get('/').status_code==200
 assert client.get('/api/health').json()['users']==128
 assert client.get('/drawio/index.html').status_code==404
 assert client.get('/action-capabilities.js').status_code==200
 assert client.get('/api/knowledge/articles').json()['articles']==[]
'''
            result=subprocess.run([sys.executable,'-c',code],cwd=install,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
