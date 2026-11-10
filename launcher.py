"""Start the local administrator and a separate LAN read-only viewer."""
import argparse,json,os,socket,subprocess,sys,time,urllib.request,uuid,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
from runtime_paths import paths, configuration
from windows_process import WindowsProcess

def servers():
    admin=int(os.environ.get('ATLAS_ADMIN_PORT','8770'))
    viewer=int(os.environ.get('ATLAS_VIEWER_PORT','8771'))
    if admin==viewer or not all(1024<=p<=65535 for p in (admin,viewer)):
        raise ValueError('Choose two different ports between 1024 and 65535.')
    sharing=configuration(ROOT).get('share_viewer') is True
    if 'AA_SHARE_VIEWER' in os.environ:sharing=os.environ['AA_SHARE_VIEWER'].lower() in ('1','true','yes')
    return [dict(mode='admin',module='backend.factory:create_app',host='127.0.0.1',port=admin),
            dict(mode='viewer',module='backend.viewer:app',host='0.0.0.0' if sharing else '127.0.0.1',port=viewer)]

def record_path(mode):return paths(ROOT).root/('server.json' if mode=='admin' else 'viewer-server.json')
def read_record(mode):
    path=record_path(mode)
    if not path.is_file():return None
    try:record=json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:raise ValueError(f'Invalid {mode} server JSON. Record retained: {path}') from error
    if not isinstance(record,dict):raise ValueError(f'Invalid {mode} server record: {path}')
    return record

def same_root(record):
    root=record.get('root')
    return isinstance(root,str) and bool(root.strip()) and os.path.normcase(os.path.realpath(root))==os.path.normcase(os.path.realpath(ROOT))

def running(spec,record):
    if not record or record.get('port')!=spec['port'] or not same_root(record):return False
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{spec['port']}/api/health",timeout=2) as response:result=json.load(response)
        return result.get('application')=='Office Atlas' and result.get('mode')==spec['mode'] and result.get('instance_id')==record['instance_id']
    except Exception:return False

def discard_stale_record(mode,record):
    """Forget an exited/replaced process; never terminate it to recover a marker."""
    path=record_path(mode)
    pid=record.get('pid')
    if type(pid) is not int or not 0<pid<=0xffffffff:
        raise RuntimeError(f'Invalid PID in {mode} server record: {path}')
    try:
        with WindowsProcess(pid) as process:
            actual=process.metadata()
    except ProcessLookupError:
        reason='the recorded process has exited'
    except OSError as error:
        raise RuntimeError(f'Cannot inspect {mode} PID {pid}: {error}. Record retained: {path}') from error
    else:
        created=record.get('created')
        if not isinstance(created,str) or not created.isdigit() or created==actual['created']:
            return False
        reason='its PID now belongs to a different process'
    path.unlink(missing_ok=True)
    print(f'Cleared stale {mode} server record: {reason}.')
    return True

def stop_record(mode,record):
    if discard_stale_record(mode,record):return 0
    if not same_root(record) or not record.get('created') or not record.get('executable'):
        print(f'Cannot verify this live server (PID {record["pid"]}). Stop it with its original launcher. Record retained: {record_path(mode)}')
        return 1
    try:
        with WindowsProcess(int(record['pid']),terminate=True) as process:
            actual=process.metadata()
            if actual['created']!=record['created'] or os.path.normcase(actual['executable'])!=os.path.normcase(record['executable']):
                print('Server PID belongs to a different process; it was not stopped.')
                return 1
            process.stop()
    except ProcessLookupError:
        pass
    record_path(mode).unlink(missing_ok=True)
    return 0

def stop():
    from inbox_control import launcher_action
    collectors_stopped=launcher_action('stop')
    failed=0
    for mode in ('viewer','admin'):
        try:
            record=read_record(mode)
            if record:failed |= stop_record(mode,record)
        except (OSError,ValueError,RuntimeError) as error:
            failed=1
            print(f'Cannot stop {mode}: {error}')
    print('AA servers stopped.' if not failed else 'AA server shutdown needs attention; see the record/PID details above.')
    if collectors_stopped is False:print('Configured inbox collectors did not stop. Check collector status before updating.')
    return int(bool(failed or collectors_stopped is False))

def start_server(spec):
    previous=read_record(spec['mode'])
    if running(spec,previous):return None
    if previous and not discard_stale_record(spec['mode'],previous):
        raise RuntimeError(f"The recorded {spec['mode']} process (PID {previous['pid']}) still exists but is not responding. Run Stop AA.bat. Record: {record_path(spec['mode'])}")
    with socket.socket() as probe:
        if os.name=='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        probe.bind((spec['host'],spec['port']))
    instance=uuid.uuid4().hex;log_path=paths(ROOT).logs/(spec['mode']+'-startup.log')
    environment=dict(os.environ,ATLAS_INSTANCE_ID=instance)
    with log_path.open('a',encoding='utf-8') as log:
        child=subprocess.Popen([sys.executable,'-m','uvicorn',spec['module'],*(['--factory'] if spec['mode']=='admin' else []),'--app-dir',str(ROOT),'--host',spec['host'],'--port',str(spec['port']),'--no-proxy-headers'],cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    record=dict(spec,pid=child.pid,root=str(ROOT),instance_id=instance)
    if os.name=='nt':
        try:
            with WindowsProcess(child.pid) as process:record.update(process.metadata())
        except BaseException:
            child.terminate();child.wait(timeout=10);raise
    temporary=record_path(spec['mode']).with_suffix('.tmp')
    temporary.write_text(json.dumps(record),encoding='utf-8');temporary.replace(record_path(spec['mode']))
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
    for directory in (paths(ROOT).logs,paths(ROOT).root):directory.mkdir(parents=True,exist_ok=True)
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
    urls=share_urls(specs[1]['port']) if specs[1]['host']=='0.0.0.0' else []
    message=f'Admin: {admin_url}\nViewer preview: {viewer_url}\nShare on your network:\n'+'\n'.join(urls or ['Off. Set share_viewer in config.json or AA_SHARE_VIEWER=1 to share.'])
    (paths(ROOT).root/'share-addresses.txt').write_text(message+'\n',encoding='utf-8');print(message)
    from inbox_control import launcher_action
    launcher_action('start')
    if open_browser:webbrowser.open(admin_url);webbrowser.open(viewer_url)
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','stop']);p.add_argument('--no-browser',action='store_true');a=p.parse_args()
    if os.name!='nt':raise SystemExit('Use this launcher on Windows.')
    raise SystemExit(run(not a.no_browser) if a.action=='run' else stop())
