"""Isolated seating UI fixture. No WMI workers or remote operations."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.staticfiles import StaticFiles
from types import SimpleNamespace
from backend import database_manager as dm
from sqlite_fixture import connect
from backend.runtime_paths import database_path
from fastapi.testclient import TestClient
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
 db=Path(td)/'office_atlas.db'
 with connect(database_path()) as a,connect(db) as b:a.backup(b)
 app=FastAPI();w=SimpleNamespace(MASTER_DB=db,jobs={},queue_jobs={})
 def token(r):
  if r.headers.get('x-atlas-token')!='test':raise HTTPException(403,'token')
 @app.get('/api/session')
 @app.get('/api/state')
 def state():return {'token':'test'}
 app.mount('/assets',StaticFiles(directory=ROOT/'frontend/assets'))
 dm.register_database_manager(app,w,token)
 client=TestClient(app)
 class Handler(BaseHTTPRequestHandler):
  def handle_request(self):
   body=self.rfile.read(int(self.headers.get('Content-Length','0')))
   r=client.request(self.command,self.path,content=body,headers=dict(self.headers))
   self.send_response(r.status_code)
   for k,v in r.headers.items():
    if k.lower() not in ('transfer-encoding','content-encoding','content-length'):self.send_header(k,v)
   self.send_header('Content-Length',str(len(r.content)));self.end_headers();self.wfile.write(r.content)
  do_GET=do_POST=handle_request
  def log_message(self,*args):pass
 ThreadingHTTPServer(('127.0.0.1',8893),Handler).serve_forever()
