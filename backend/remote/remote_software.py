"""Reviewed remote uninstall plans; execution stays on the selected Windows host."""
import copy,json,re,threading,time,uuid
from pathlib import Path
from fastapi import Request,HTTPException
GUID=re.compile(r'^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$')
ROOT=Path(__file__).resolve().parents[2]

class UnknownOutcome(RuntimeError):pass
class ReportedFailure(RuntimeError):pass

def split_executable(command):
    """Accept local .exe registrations, never evaluate them through cmd/PowerShell."""
    command=str(command or '').strip()
    if any(c in command for c in '\r\n\x00'):raise ValueError('Invalid registered command.')
    if command.startswith('"'):
        end=command.find('"',1)
        if end<0:raise ValueError('Malformed registered executable path.')
        exe=command[1:end];args=command[end+1:].strip()
    else:
        m=re.match(r'(.+?\.exe)(?:\s+(.*))?$',command,re.I)
        if not m:raise ValueError('No supported executable in the registered uninstall command.')
        exe=m[1];args=m[2] or ''
    if not re.match(r'^(?:[A-Za-z]:\\|%[A-Za-z0-9_]+%\\)',exe) or not exe.lower().endswith('.exe'):
        raise ValueError('Requires a registered local executable path. Use the package-script deployment workflow for other command types.')
    if '"' in exe or any(c in exe for c in '<>|?*'):raise ValueError('Invalid executable path.')
    return exe,args

def capability(item,operator_sid,action='Uninstall'):
    if action not in ('Uninstall','Repair'):return 'blocked','Choose Uninstall or Repair.'
    if (action=='Uninstall' and item.get('NoRemove')) or item.get('NonRemovable'):return 'blocked','The product registration marks this application as non-removable.'
    if item.get('Kind')=='MSIX/Appx':
        if action=='Repair':return 'blocked','No generic remote Appx repair is configured; reset is not the same as repair.'
        if not re.fullmatch(r'S-1-\d+(?:-\d+)+',item.get('UserSid','')):return 'blocked','No installed user registration was identified.'
        return 'ready','Removes this package for the displayed user SID only; provisioned packages are not removed.'
    if item.get('Scope')=='User' and item.get('UserSid')!=operator_sid:return 'blocked','Requires execution as the owning user. Use Remote Assistance or your managed deployment system.'
    if item.get('Kind')=='MSI':
        return ('ready','Silent MSI '+action.lower()+', no automatic restart.') if GUID.fullmatch(item.get('ProductCode','')) else ('blocked','Missing valid MSI ProductCode.')
    command=item.get('ModifyPath') if action=='Repair' else (item.get('QuietUninstallString') or item.get('UninstallString'))
    try:split_executable(command)
    except ValueError as e:return 'blocked',str(e)
    return ('ready','Uses the registered silent uninstall command. Restart behaviour is vendor-defined.') if action=='Uninstall' and item.get('QuietUninstallString') else ('configure','Enter vendor-documented silent arguments. Interactive uninstallers cannot be operated through WMI.')

def make_plan(item,operator_sid,arguments=None,action='Uninstall'):
    mode,reason=capability(item,operator_sid,action)
    if mode=='blocked':raise ValueError(reason)
    plan={'item':copy.deepcopy(item),'reason':reason,'action':action}
    if item['Kind']=='MSI':
        plan.update(command=f'msiexec.exe {"/fomus" if action=="Repair" else "/x"} {item["ProductCode"].upper()} /qn /norestart /L*v "<operation folder>\\installer.log"',executable='msiexec.exe',arguments='')
    elif item['Kind']=='MSIX/Appx':
        name=item.get('PackageFullName','');sid=item['UserSid']
        if not re.fullmatch(r'[A-Za-z0-9_.~\-]+',name):raise ValueError('Invalid Appx package name.')
        plan.update(command=f"Remove-AppxPackage -Package '{name}' -User '{sid}'",executable='',arguments='')
    else:
        exe,registered=split_executable(item.get('ModifyPath') if action=='Repair' else (item.get('QuietUninstallString') or item.get('UninstallString')))
        if mode=='configure':
            if not isinstance(arguments,str) or not arguments.strip():raise ValueError('Enter the complete vendor-documented silent argument string, preserving required original arguments.')
            args=arguments.strip()
        else:args=registered
        if len(args)>4000 or any(c in args for c in '\r\n\x00'):raise ValueError('Invalid uninstall arguments.')
        plan.update(executable=exe,arguments=args,command='"'+exe+'" '+args)
    return plan

def remote_call(wmi,pc,plan=None,include_cache=False,include_appx=False,timeout=240):
    windows=wmi.ps(f"(Get-WmiObject -ComputerName {wmi.quote(pc)} -Class Win32_OperatingSystem -ErrorAction Stop).WindowsDirectory",timeout=30).strip()
    if not re.fullmatch(r'[A-Za-z]:\\[^\r\n"<>|?*]+',windows):raise ValueError('Cannot resolve the target Windows directory.')
    folder=windows+'\\Temp\\AtlasSoftware_'+uuid.uuid4().hex
    share=Path(wmi.unc(pc,folder));share.mkdir(parents=True,exist_ok=False)
    script=folder+'\\remote_software.ps1';output=folder+'\\result.json'
    (share/'remote_software.ps1').write_bytes((ROOT/'scripts/remote_software.ps1').read_bytes())
    command='powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+script+'" -OutputPath "'+output+'"'
    if plan is not None:
        (share/'plan.json').write_text(json.dumps(plan),encoding='utf-8');command+=' -PlanPath "'+folder+'\\plan.json"'
    if include_cache:command+=' -IncludeCache'
    if include_appx:command+=' -IncludeAppx'
    pid=wmi.wmi_create(pc,command)
    try:
        deadline=time.monotonic()+timeout;result=share/'result.json'
        while time.monotonic()<deadline:
            if result.is_file():
                data=json.loads(result.read_text(encoding='utf-8-sig'))
                if not isinstance(data,dict) or type(data.get('ok')) is not bool:
                    raise ValueError('Invalid remote result record')
                if not data['ok']:raise ReportedFailure(data.get('error') or 'Remote operation failed.')
                if plan is not None and type(data.get('exit_code')) is not int:
                    raise ValueError('Remote mutation result lacks an integer exit code')
                data['operation_folder']=folder;data['pid']=pid
                return data
            running=wmi.wmi_running(pc,pid)
            if not running:
                # Final file may need a brief SMB visibility grace period.
                for _ in range(5):
                    if result.is_file():break
                    time.sleep(.2)
                if not result.is_file():raise UnknownOutcome(f'Remote process exited without a result. Check {folder}; do not assume success or retry automatically.')
            time.sleep(1)
        raise UnknownOutcome(f'Monitoring timed out. The remote process may still be running (PID {pid}). Check {folder} before further actions.')
    except (UnknownOutcome,ReportedFailure):raise
    except Exception as e:
        raise UnknownOutcome(f'Monitoring lost after starting PID {pid}: {e}. Inspect {folder} before retrying.') from e

def verdict(result,kind,action='Uninstall'):
    ec=str(result.get('exit_code','unknown'))
    if ec=='0' or (kind=='MSI' and ec in ('3010','1641')):
        note=action+' command reported success'
        if ec in ('3010','1641'):note+='; restart required or initiated'
        if not result.get('verification_complete'):note+='; inventory verification incomplete'
        elif action=='Repair':note+='; registration '+('remains present' if result.get('registration_remaining') else 'is missing—review the repair log')+'; application health not verified'
        elif result.get('registration_remaining'):note+='; registration is still present—review before retrying'
        else:note+='; selected registration is no longer present'
        return 'complete',note+' (exit '+ec+').'
    if kind=='MSI' and ec=='1605':return 'failed','Windows Installer reports this product is not installed in the execution context (1605).'
    if kind=='MSI' and ec=='1618':return 'failed','Another Windows Installer operation is in progress (1618).'
    return 'failed','Uninstaller returned '+ec+'. Inspect the operation log; vendor exit-code meanings can differ.'

def register_remote_software(app,wmi,check_token):
    scans={};plans={};mutex=threading.Lock()
    def prune():
        now=time.time()
        for pool in (scans,plans):
            for k,v in list(pool.items()):
                if now-v['at']>900:pool.pop(k,None)
    @app.post('/api/software-tools/inventory')
    def inventory(body:dict,request:Request):
        check_token(request);pc=wmi.validate_pc(body.get('computer',''))
        if not wmi.job_service.inventory.acquire(blocking=False):raise HTTPException(429,'Three inventory scans are active; try again shortly.')
        try:data=remote_call(wmi,pc,include_cache=body.get('cache') is True,include_appx=body.get('appx') is True)
        except Exception as e:raise HTTPException(502,str(e))
        finally:wmi.job_service.inventory.release()
        items=data.get('software') or []
        if isinstance(items,dict):items=[items]
        sid=data.get('operator_sid','');id=uuid.uuid4().hex
        with mutex:
            prune()
            # One current scan per target. Other target selections remain bound to their own scan.
            for k,v in list(scans.items()):
                if v['pc']==pc:scans.pop(k)
            if len(scans)>=20:scans.pop(next(iter(scans)))
            scans[id]={'at':time.time(),'pc':pc,'items':copy.deepcopy(items),'sid':sid}
        for i,item in enumerate(items):
            item['row']=i;item['availability'],item['reason']=capability(item,sid)
            item['repair_availability'],item['repair_reason']=capability(item,sid,'Repair')
        return {'scan':id,'computer':pc,'software':items,'cache':data.get('cache') or [],'warnings':data.get('warnings') or [],'collected_at':data.get('collected_at'),'operator_sid':sid}
    @app.post('/api/software-tools/preview')
    def preview(body:dict,request:Request):
        check_token(request)
        with mutex:
            prune();scan=copy.deepcopy(scans.get(body.get('scan')))
        if not scan:raise HTTPException(409,'Inventory expired. Scan again.')
        row=body.get('row')
        if type(row) is not int or not 0<=row<len(scan['items']):raise HTTPException(400,'Select an inventory row.')
        try:plan=make_plan(scan['items'][row],scan['sid'],body.get('arguments'),body.get('action','Uninstall'))
        except ValueError as e:raise HTTPException(400,str(e))
        id=uuid.uuid4().hex;plan.update(pc=scan['pc'],at=time.time(),scan=body['scan'])
        with mutex:
            if len(plans)>=100:plans.pop(next(iter(plans)))
            plans[id]=plan
        return {'plan':id,'computer':plan['pc'],'name':plan['item']['Name'],'version':plan['item'].get('Version',''),'scope':plan['item'].get('Scope',''),'sid':plan['item'].get('UserSid',''),'command':plan['command'],'reason':plan['reason'],'action':plan['action']}
    def worker(job,plan,guard):
        pc=plan['pc']
        try:
            wmi.emit(job,'Rechecking application registration on '+pc+' before '+plan['action'].lower()+'.','running')
            data=remote_call(wmi,pc,plan=plan,timeout=int(wmi.CONFIG.get('deployment_timeout_seconds',3600)))
            state,message=verdict(data,plan['item']['Kind'],plan['action'])
            details=message+'\nOperation folder: '+data['operation_folder']
            wmi.emit(job,details,state,exit_code=str(data.get('exit_code')),result=data)
            wmi.history_update(job,state=state,exit_code=str(data.get('exit_code')),finished=time.strftime('%Y-%m-%d %H:%M:%S'),details=details)
        except Exception as e:
            if isinstance(e,UnknownOutcome):
                wmi.job_service.unresolved.add(pc)
            state='unknown' if isinstance(e,UnknownOutcome) else 'failed'
            wmi.emit(job,str(e),state)
            wmi.history_update(job,state=state,finished=time.strftime('%Y-%m-%d %H:%M:%S'),details=str(e))
        finally:guard.release()
    @app.post('/api/software-tools/uninstall')
    def uninstall(body:dict,request:Request):
        check_token(request)
        with mutex:
            prune();plan=copy.deepcopy(plans.get(body.get('plan')))
            if not plan or plan['scan'] not in scans:raise HTTPException(409,'Preview is stale or inventory was refreshed. Preview again.')
            if body.get('confirmation')!=plan['pc']:raise HTTPException(400,'Type the exact target hostname to confirm this action.')
        wmi.job_service.target_ready(plan['pc'])
        guard=wmi.target_lock(plan['pc'])
        if not guard.acquire(blocking=False):raise HTTPException(409,'Another deployment or uninstall is active on this target.')
        job=uuid.uuid4().hex
        try:
            wmi.job_service.target_ready(plan['pc'])
            wmi.history_create(job,plan['pc'],plan['item']['Name'],plan['action'],plan['command'],'remote-uninstall')
            wmi.jobs[job]={'state':'queued','target':plan['pc'],'events':[]}
            with mutex:plans.pop(body['plan'],None)
            wmi.start_job(worker,job,plan,guard)
        except Exception:
            guard.release();raise
        return {'job':job,'computer':plan['pc']}
    @app.get('/api/software-tools/jobs/{job}')
    def job_status(job:str):
        data=wmi.jobs.get(job)
        if data is None:raise HTTPException(404,'Job unavailable. Consult deployment history.')
        with wmi.lock:return {'state':data['state'],'events':copy.deepcopy(data.get('events',[]))}
