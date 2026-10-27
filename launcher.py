"""Start the local administrator and a separate LAN read-only viewer."""
import argparse,json,os,socket,subprocess,sys,time,urllib.request,uuid,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def servers():
    admin=int(os.environ.get('ATLAS_ADMIN_PORT','8770'))
    viewer=int(os.environ.get('ATLAS_VIEWER_PORT','8771'))
    if admin==viewer or not all(1024<=p<=65535 for p in (admin,viewer)):
        raise ValueError('Choose two different ports between 1024 and 65535.')
    return [dict(mode='admin',module='backend.main:app',host='127.0.0.1',port=admin),
            dict(mode='viewer',module='backend.viewer:app',host='0.0.0.0',port=viewer)]

def record_path(mode):return ROOT/'data'/('server.json' if mode=='admin' else 'viewer-server.json')
def read_record(mode):
    path=record_path(mode)
    return json.loads(path.read_text()) if path.is_file() else None

def running(spec,record):
    if not record or record.get('port')!=spec['port'] or record.get('root')!=str(ROOT):return False
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{spec['port']}/api/health",timeout=2) as response:result=json.load(response)
        return result.get('application')=='Office Atlas' and result.get('mode')==spec['mode'] and result.get('instance_id')==record['instance_id']
    except Exception:return False

def stop_record(mode,record):
    pid=int(record['pid']);module='backend.viewer:app' if mode=='viewer' else 'backend.main:app'
    literal=lambda s:"'"+s.replace("'","''")+"'"
    script=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';if(-not $p){{exit 0}};if($p.CommandLine.Contains({literal(str(ROOT))}) -and $p.CommandLine.Contains({literal(module)}) -and $p.CommandLine.Contains('uvicorn')){{Stop-Process -Id {pid} -ErrorAction Stop}}else{{throw 'PID no longer belongs to this application; not stopped'}}"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:return result.returncode
    record_path(mode).unlink(missing_ok=True);return 0

def stop():
    from inbox_control import launcher_action
    collectors_stopped=launcher_action('stop')
    failed=0 if collectors_stopped is not False else 1
    for mode in ('viewer','admin'):
        record=read_record(mode)
        if record:failed |= stop_record(mode,record)
    print('Atlas servers stopped.' if not failed else 'Atlas shutdown needs attention. Any unresponsive server record was retained; check collector status before updating.')
    return failed

def start_server(spec):
    previous=read_record(spec['mode'])
    if running(spec,previous):return None
    if previous:raise RuntimeError(f"An unresponsive {spec['mode']} server record exists. Run Stop-All-Atlas.bat before restarting.")
    with socket.socket() as probe:
        if os.name=='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        probe.bind((spec['host'],spec['port']))
    instance=uuid.uuid4().hex;log_path=ROOT/'logs'/(spec['mode']+'-startup.log')
    environment=dict(os.environ,ATLAS_INSTANCE_ID=instance)
    with log_path.open('a',encoding='utf-8') as log:
        child=subprocess.Popen([sys.executable,'-m','uvicorn',spec['module'],'--app-dir',str(ROOT),'--host',spec['host'],'--port',str(spec['port']),'--no-proxy-headers'],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    record=dict(spec,pid=child.pid,root=str(ROOT),instance_id=instance)
    record_path(spec['mode']).write_text(json.dumps(record),encoding='utf-8')
    try:
        for _ in range(60):
            if child.poll() is not None:raise RuntimeError(f"{spec['mode']} startup failed. See {log_path}")
            if running(spec,record):return child
            time.sleep(1)
        raise RuntimeError(f"{spec['mode']} startup timed out. See {log_path}")
    except BaseException:
        if child.poll() is None:child.terminate()
        child.wait(timeout=10);record_path(spec['mode']).unlink(missing_ok=True);raise

def share_urls(port):
    try:addresses=sorted({r[4][0] for r in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not r[4][0].startswith(('127.','169.254.'))})
    except OSError:addresses=[]
    return [f'http://{ip}:{port}' for ip in addresses]

def run(open_browser=True):
    specs=servers()
    try:import fastapi,uvicorn  # noqa: F401 -- verify dependencies can actually import
    except ImportError:
        print('Dependencies missing. Run windows\\Install_Dependencies.bat using this same Python.');return 1
    for directory in ('logs','data'):(ROOT/directory).mkdir(exist_ok=True)
    # Existing servers keep their database until explicitly stopped.
    if not any(running(spec,read_record(spec['mode'])) for spec in specs):
        from runtime_paths import prepare_runtime_database
        prepare_runtime_database()
    started=[]
    try:
        # Complete admin schema initialization before the viewer opens the database.
        for spec in specs:
            child=start_server(spec)
            if child:started.append((spec,child))
    except Exception as error:
        for spec,child in reversed(started):
            child.terminate();child.wait(timeout=10);record_path(spec['mode']).unlink(missing_ok=True)
        print(str(error));return 1
    admin_url=f"http://127.0.0.1:{specs[0]['port']}";viewer_url=f"http://127.0.0.1:{specs[1]['port']}"
    urls=share_urls(specs[1]['port'])
    message=f'Admin: {admin_url}\nViewer preview: {viewer_url}\nShare on your network:\n'+'\n'.join(urls or [f"http://YOUR-IP:{specs[1]['port']}"])
    (ROOT/'data'/'share-addresses.txt').write_text(message+'\n',encoding='utf-8');print(message)
    from inbox_control import launcher_action
    launcher_action('start')
    if open_browser:webbrowser.open(admin_url);webbrowser.open(viewer_url)
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','stop']);p.add_argument('--no-browser',action='store_true');a=p.parse_args()
    if os.name!='nt':raise SystemExit('Use this launcher on Windows.')
    raise SystemExit(run(not a.no_browser) if a.action=='run' else stop())
