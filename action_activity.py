"""Read-only activity feed combining existing workers and in-flight requests."""
import copy
import re
import threading
import time
import uuid
from fastapi import HTTPException

ACTIVE = {'queued', 'running', 'paused', 'monitoring', 'starting', 'stopping'}
FAILURE = {'failed', 'unknown', 'interrupted', 'timed_out'}


def register(app, backend):
    pending, dismissed = {}, {}
    guard = threading.RLock()
    names = {'ping':'Ping', 'access':'Administrative access', 'disk':'Disk space',
             'overview':'System overview', 'processes':'Process scan', 'performance':'Performance scan',
             'preflight':'Deployment preflight', 'machine-health':'Health check',
             'cleanup-packages':'Package cleanup', 'open-tool':'Open remote tool',
             'package-folder':'Locate package folder'}
    writes = {'/api/kill':'Terminate process', '/api/remote-registry/enable':'Enable Remote Registry',
              '/api/software-tools/inventory':'Software inventory'}

    @app.middleware('http')
    async def capture(request, call_next):
        parts = request.url.path.strip('/').split('/')
        title = writes.get(request.url.path) if request.method == 'POST' else None
        target = ''
        if len(parts) >= 3 and parts[0] == 'api' and parts[1] in names:
            title = names[parts[1]]
            target = parts[3] if parts[1] == 'open-tool' and len(parts)>3 else parts[2]
            if parts[1] == 'machine-health' and len(parts)>3: title += ' · ' + parts[3]
            if parts[1] in ('performance','processes'):
                title += ' · ' + request.query_params.get('kind','cpu')
        if request.url.path.startswith('/api/database/') and request.method=='POST':
            title='Database · '+parts[2];target='Directory database'
        if request.url.path=='/api/atlas/import-db':title='Import database';target='Atlas database'
        if not title: return await call_next(request)
        if not target:
            try: target = str((await request.json()).get('computer',''))
            except Exception: pass
        key = 'request-' + uuid.uuid4().hex
        now = time.time()
        with guard:
            pending[key] = dict(id=key, title=title, target=target, state='running', started=now,
                                updated=now, message='In progress', log='', controls=[], view='admin')
        try:
            response = await call_next(request)
            with guard:
                pending[key].update(state='complete' if response.status_code<400 else 'failed',
                                    message='Finished' if response.status_code<400 else 'Request failed — see the action result',updated=time.time())
            return response
        except BaseException:
            with guard: pending[key].update(state='unknown', message='Request interrupted; remote outcome not confirmed',updated=time.time())
            raise

    def visible(row, now):
        if row['state'] in ACTIVE: return True
        return now-row.get('updated',0) < (60 if row['state'] in FAILURE else 10)

    def events_text(events):
        return '\n'.join('['+str(e.get('time',''))+'] '+str(e.get('message','')) +
                         ('\n'+'\n'.join(e['log']) if isinstance(e.get('log'),list) else '')
                         for e in events[-30:])[-6000:]

    @app.get('/api/actions')
    def activity():
        now = time.time()
        with guard:
            for key,row in list(pending.items()):
                if not visible(row,now): del pending[key]
            for key,expiry in list(dismissed.items()):
                if now>expiry: del dismissed[key]
            rows = copy.deepcopy(list(pending.values()))
        with backend.lock:
            jobs = copy.deepcopy(backend.jobs)
            queues = copy.deepcopy(backend.queue_jobs)
        children = {r.get('job') for j in list(jobs.values())+list(queues.values()) for r in j.get('items',j.get('results',[]))}
        for key,job in jobs.items():
            if key in children: continue
            events = job.get('events',[])
            results = job.get('results',[])
            bulk = 'results' in job
            message = events[-1].get('message','') if events else job.get('phase','In progress')
            if bulk:
                done = sum(r.get('completion') in ('Complete','Launched','Failed') for r in results)
                message = f'{done} of {len(results)} machines finished'
            row = dict(id='job-'+key,title=job.get('action_title') or ('Bulk deployment' if bulk else 'Deployment'),
                       target=job.get('target') or ('Multiple machines' if bulk else ''),state=job.get('state','unknown'),
                       updated=job.get('updated',0),started=job.get('started_at'),message=message,
                       log=events_text(events) if not bulk else '\n'.join(f"{r.get('machine','')}: {r.get('completion','Waiting')} {r.get('details','')}" for r in results)[-6000:],
                       controls=[],view='bulk' if bulk else 'workspace')
            if visible(row,now): rows.append(row)
        for key,queue in queues.items():
            items=queue.get('items',[])
            done=sum(r.get('state') not in ACTIVE and r.get('state')!='waiting' for r in items)
            controls=[]
            if queue.get('state')=='paused': controls.append(dict(label='Resume',url=f'/api/queue/{key}/resume'))
            elif queue.get('state') in ('queued','running'): controls.append(dict(label='Pause after current',url=f'/api/queue/{key}/pause'))
            if queue.get('state') in ACTIVE: controls.append(dict(label='Cancel waiting',url=f'/api/queue/{key}/cancel'))
            row=dict(id='queue-'+key,title='Deployment queue',target=', '.join(dict.fromkeys(r.get('target','') for r in items)),
                     state=queue.get('state','unknown'),updated=queue.get('updated',0),message=f'{done} of {len(items)} finished',
                     log='\n'.join(f"{r.get('target','')}: {r.get('state','waiting')}\n{events_text(r.get('events',[]))}" for r in items)[-6000:],controls=controls,view='workspace')
            if visible(row,now): rows.append(row)
        from psexec_runner import runner
        with runner.lock:
            for key,job in runner.jobs.items():
                row=dict(id='psexec-'+key,title='PsExec · '+job['title'],target=job['target'],state=job['state'],
                         updated=job.get('finished') or now,started=job.get('started'),message=job['state'],
                         log=job.get('output','')[-6000:],view='psexec',controls=[])
                if row['state'] in ACTIVE: row['controls']=[dict(label='Stop local session',url=f'/api/psexec/runs/{key}/stop')]
                if visible(row,now): rows.append(row)
        from local_terminal import runner as terminal_runner
        with terminal_runner.lock:
            for key,job in terminal_runner.jobs.items():
                row=dict(id='terminal-'+key,title=job['title'],target=job['target'],state=job['state'],
                         updated=job.get('finished') or now,started=job.get('started'),message=job['state'],
                         log=job.get('output','')[-6000:],view='terminal',controls=[])
                if row['state'] in ACTIVE: row['controls']=[dict(label='Stop local command',url=f'/api/terminal/runs/{key}/stop')]
                if visible(row,now): rows.append(row)
        from shared_operations import axis_activity
        rows.extend(row for row in axis_activity() if visible(row,now))
        with guard: rows=[r for r in rows if r['id'] not in dismissed]
        rows.sort(key=lambda r:(r['state'] not in ACTIVE,-r.get('updated',0)))
        return {'actions':rows,'count':sum(r['state'] in ACTIVE for r in rows)}

    @app.post('/api/actions/{key}/dismiss')
    def dismiss(key:str):
        if not re.fullmatch(r'[\w-]{1,100}',key): raise HTTPException(400,'Invalid action ID')
        row=next((r for r in activity()['actions'] if r['id']==key),None)
        if row and row['state'] in ACTIVE: raise HTTPException(409,'An ongoing action cannot be dismissed')
        with guard: dismissed[key]=time.time()+120
        return {'ok':True}
