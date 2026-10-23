"""Independent, bounded read-only health checks; no remote process creation."""
import json,threading,time
from datetime import datetime,timezone
from fastapi import HTTPException
from reboot_monitor import has_echo_reply

# Fixed PowerShell queries. Host names are validated and quoted by the existing transport.
QUERIES={
'wmi':"$x=Get-WmiObject -ComputerName $pc Win32_OperatingSystem -ErrorAction Stop; if(!$x){throw 'No WMI result'}; @{available=$true}",
'cshare':"$x=Get-Item -LiteralPath ('\\\\'+$pc+'\\C$') -ErrorAction Stop; @{available=[bool]$x.PSIsContainer}",
'cpu':"$x=@(Get-WmiObject -ComputerName $pc Win32_Processor -ErrorAction Stop); if(!$x.Count){throw 'No processor data'}; @{processors=@($x | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage)}",
'ram':"$o=Get-WmiObject -ComputerName $pc Win32_OperatingSystem -ErrorAction Stop; $c=Get-WmiObject -ComputerName $pc Win32_ComputerSystem -ErrorAction Stop; if(!$o -or $null -eq $o.TotalVisibleMemorySize -or $null -eq $o.FreePhysicalMemory){throw 'Memory data unavailable'}; @{installed_bytes=$c.TotalPhysicalMemory;usable_kib=$o.TotalVisibleMemorySize;free_kib=$o.FreePhysicalMemory}",
'gpu':"$x=@(Get-WmiObject -ComputerName $pc Win32_VideoController -ErrorAction Stop); if(!$x.Count){throw 'No display adapter data'}; @{adapters=@($x | Select-Object Name,DriverVersion)}",
'storage':"$x=Get-WmiObject -ComputerName $pc Win32_LogicalDisk -Filter 'DeviceID=\"C:\"' -ErrorAction Stop; if(!$x -or $null -eq $x.Size -or $null -eq $x.FreeSpace){throw 'C drive data unavailable'}; @{drive='C:';total_bytes=$x.Size;free_bytes=$x.FreeSpace}",
'system':"$o=Get-WmiObject -ComputerName $pc Win32_OperatingSystem -ErrorAction Stop; if(!$o.LastBootUpTime -or !$o.LocalDateTime){throw 'Boot time unavailable'}; $b=$o.ConvertToDateTime($o.LastBootUpTime); $now=$o.ConvertToDateTime($o.LocalDateTime); @{windows=$o.Caption;version=$o.Version;last_boot=$b.ToString('yyyy-MM-dd HH:mm:ss');uptime_seconds=[math]::Max(0,($now-$b).TotalSeconds)}"
}

class HealthChecks:
    def __init__(self,wmi):
        self.wmi=wmi;self.slots=threading.BoundedSemaphore(12);self.lock=threading.Lock();self.cache={};self.active={}
    def check(self,pc,metric):
        pc=self.wmi.validate_pc(pc)
        if metric not in QUERIES and metric!='ping':raise HTTPException(404,'Unknown health check')
        key=(pc,metric)
        with self.lock:
            old=self.cache.get(key)
            if old and time.monotonic()-old[0]<5:return old[1]
            event=self.active.get(key);owner=event is None
            if owner:event=self.active[key]=threading.Event()
        if not owner:
            if event.wait(22):
                with self.lock:
                    old=self.cache.get(key)
                    if old:return old[1]
            return self.result(pc,metric,'unavailable',None,'Check still running; refresh shortly')
        try:
            if not self.slots.acquire(timeout=.2):return self.result(pc,metric,'unavailable',None,'Health service busy; refresh shortly')
            try:
                if metric=='ping':data={'available':has_echo_reply(self.wmi.run(['ping.exe','-4','-n','1','-w','1200',pc],False,timeout=5))}
                else:
                    script="$ErrorActionPreference='Stop';$pc="+self.wmi.quote(pc)+"; & {"+QUERIES[metric]+"} | ConvertTo-Json -Depth 5 -Compress"
                    data=json.loads(self.wmi.ps(script,timeout=18))
                    if not isinstance(data,dict):raise ValueError('Invalid health response')
                result=self.result(pc,metric,'ready',data)
            except Exception as exc:
                result=self.result(pc,metric,'unavailable',None,str(exc)[:300] or 'Query failed')
            finally:self.slots.release()
            with self.lock:
                if len(self.cache)>=256:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=(time.monotonic(),result)
            return result
        finally:
            with self.lock:self.active.pop(key,None);event.set()
    @staticmethod
    def result(pc,metric,state,data,error=None):
        return {'computer':pc,'metric':metric,'state':state,'data':data,'error':error,'checked_at':datetime.now(timezone.utc).isoformat()}

def register_machine_health(app,wmi):
    checks=HealthChecks(wmi)
    @app.get('/api/machine-health/{pc}/{metric}')
    def health(pc:str,metric:str):return checks.check(pc,metric)
    return checks
