// Recorded operations and result rows only; all transport is intercepted.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const settle = () => new Promise(resolve => setTimeout(resolve, 15));
const reply = data => ({ok:true,status:200,json:async()=>data});
const deferred = () => {let resolve;const promise = new Promise(done=>{resolve=done});return {promise,resolve};};
(async () => {
  const requests = [], history = [];
  const f = await fixture({fetch:async (url, options={})=>{
    url=String(url);requests.push(url);assert.equal(options.method||'GET','GET','No deployment mutation is allowed');
    if(url==='/api/history') {const pending=deferred();history.push(pending);return pending.promise;}
    if(url==='/api/health')return reply({identity:'FIXTURE',users:0,machines:0});
    if(url==='/api/session')return reply({token:'test'});
    if(url==='/api/psexec/runs')return reply([]);
    return reply({items:[],records:[],scripts:[],deployments:[],available:false});
  }});
  await f.console();await settle();
  const {w,run}=f,d=w.document, body=d.querySelector('#historyBody'), status=d.querySelector('#historyStatus'), refresh=d.querySelector('#refreshHistory');
  assert(d.querySelector('#bulkBody .atlas-table-empty'));
  assert(d.querySelector('#copyFailed').disabled);assert(d.querySelector('#exportCsv').disabled);
  run("S.rows=[];renderBulk({state:'running'})");
  assert(d.querySelector('#bulkBody').textContent.includes('Waiting for device results'));
  run("renderBulk({state:'complete'})");
  assert(d.querySelector('#bulkBody').textContent.includes('No per-device results returned'));
  assert(d.querySelector('#bulkSummary').textContent.includes('complete'));
  run("S.rows=[{machine:'FICT-PC',copy:'Complete',launch:'Launched',pid:0,completion:'Launched',exit_code:0,details:'<script>literal</script>'}];renderBulk({phase:'Launching',state:'running'})");
  assert(!d.querySelector('#bulkBody .atlas-table-empty'));assert(!d.querySelector('#exportCsv').disabled);assert(d.querySelector('#copyFailed').disabled);
  assert(d.querySelector('#bulkSummary').textContent.includes('Launched / complete'));
  assert.equal(d.querySelector('#bulkBody script'),null);assert(d.querySelector('#bulkBody').textContent.includes('<script>literal</script>'));
  run("S.rows[0].completion='Failed';renderBulk({state:'failed'})");assert(!d.querySelector('#copyFailed').disabled);
  assert.equal(d.querySelector('#bulkBody tr[data-state=failed] .status-bad').textContent,'Failed','Failures are red');assert(d.querySelector('#bulkSummary .status-bad'),'The failed count is red');
  assert.deepEqual(['0','1603',''].map(c=>run(`exitTone(${JSON.stringify(c)})`)),['status-ok','status-bad','status-neutral']);
  run("S.rows=[];renderBulk({state:'complete'})");assert(d.querySelector('#copyFailed').disabled);assert(d.querySelector('#exportCsv').disabled);

  const first=run('loadDeploymentHistory()');await settle();
  assert(refresh.disabled);assert.equal(body.getAttribute('aria-busy'),'true');assert.equal(status.dataset.state,'loading');
  assert(body.textContent.includes('Loading history'));
  history.at(-1).resolve(reply([]));await first;
  assert(!refresh.disabled);assert.equal(body.getAttribute('aria-busy'),'false');assert(body.textContent.includes('No recent operations'));assert.equal(status.dataset.state,'ready');

  const failed=run('loadDeploymentHistory()');await settle();const callsBefore=requests.length;
  history.at(-1).resolve({ok:false,status:503,json:async()=>({detail:'<script>History offline</script>'})});await failed;
  assert.equal(status.dataset.state,'error');assert(status.textContent.includes('<script>History offline</script>'));assert.equal(status.querySelector('script'),null);assert(body.textContent.includes('Use Refresh to try again'));
  assert(!refresh.disabled);await settle();assert.equal(requests.length,callsBefore,'Errors never retry in the background');

  const old=run('loadDeploymentHistory()');await settle();const oldReply=history.at(-1);
  const current=run('loadDeploymentHistory()');await settle();const currentReply=history.at(-1);
  const row={started:'2026-10-07',target:'FICT-PC',package:'Literal <b>package</b>',action:'Install',mode:'Copy',state:'Launched',exit_code:0};
  currentReply.resolve(reply([row]));await current;
  assert.equal(status.textContent,'1 recorded operation');assert.equal(body.querySelectorAll('tr').length,1);assert.equal(body.querySelector('b'),null);assert(body.textContent.includes('Literal <b>package</b>'));assert(body.textContent.includes('0'));
  const accepted=body.innerHTML;oldReply.resolve({ok:false,status:500,json:async()=>({detail:'Stale error'})});await old;
  assert.equal(body.innerHTML,accepted);assert.equal(status.dataset.state,'ready');assert(!refresh.disabled);

  const preserve=run('loadDeploymentHistory()');await settle();assert.equal(body.innerHTML,accepted,'Refresh retains the previously accepted rows while loading');
  history.at(-1).resolve({ok:false,status:503,json:async()=>({detail:'Retry unavailable'})});await preserve;
  assert.equal(body.innerHTML,accepted);assert.equal(status.dataset.state,'error');

  const pair=run('loadDeploymentHistory()');await settle();
  history.at(-1).resolve(reply([row,{...row,target:'OTHER-PC',state:'failed',exit_code:1603}]));await pair;
  assert.equal(status.textContent,'2 recorded operations · 1 failed');
  assert.equal(body.querySelector('tr[data-state=failed] .history-state').textContent,'failed');
  const filter=d.querySelector('#historyFilter');filter.value='other failed';filter.dispatchEvent(new w.Event('input'));
  assert.deepEqual([...body.querySelectorAll('tr')].map(tr=>tr.hidden),[true,false],'Every filter word must match');
  filter.value='';filter.dispatchEvent(new w.Event('input'));assert(![...body.querySelectorAll('tr')].some(tr=>tr.hidden));
  const opened=[];run('window.__page=page;window.__setTarget=setTarget');w.page=name=>opened.push(name);w.setTarget=(name,source)=>opened.push(name,source);
  body.querySelector('[data-history-target="OTHER-PC"]').click();
  assert.deepEqual(opened,['workspace','OTHER-PC','Deployment history'],'A machine name opens it in Workspace');
  run('page=window.__page;setTarget=window.__setTarget');
  const late=run('loadDeploymentHistory()');await settle();const lateReply=history.at(-1);
  w.AtlasReadOnly={reason:'Read-only fixture'};const beforeReadonly=requests.length;await run('loadDeploymentHistory()');
  assert.equal(requests.length,beforeReadonly,'Read-only view does not request unavailable history');
  assert(body.textContent.includes('not included in this read-only view'));assert(status.textContent.includes('Atlas Admin'));assert(refresh.disabled);assert.equal(body.getAttribute('aria-busy'),'false');
  lateReply.resolve(reply([row]));await late;assert(body.textContent.includes('not included'));assert(refresh.disabled);
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.dispatchEvent(new w.Event('pagehide'));w.close();
  console.log('PASS: truthful empty/progress bulk rows and result actions, history loading/empty/error/retry, escaped recorded rows, state badges, green/red results and exit codes, failure count, filter and machine links, stale refresh isolation and no read-only history requests or background retries');
})().catch(error=>{console.error(error);process.exitCode=1});
