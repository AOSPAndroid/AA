// Intercepted inventory/actions only; no Windows operations or server required.
const assert = require('node:assert/strict'), fs = require('node:fs');
const {fixture, root} = require('./ui_fixture.cjs');
const settle = async () => { for (let index=0; index<25; index++) await Promise.resolve(); };
(async () => {
  let result = 'unknown', jobReads = 0;
  const calls = [], timers = new Map(); let timerId = 0;
  const f = await fixture({fetch:async (url, options={}) => {
    calls.push([url, options.method || 'GET']);
    let data;
    if (url === '/api/session') data = {token:'fixture'};
    else if (url === '/api/software-tools/inventory') data = {scan:'scan1',computer:'PC-A',software:[{row:0,Name:'Fixture app',Version:'1',Kind:'MSI',Scope:'Machine',availability:'ready'}]};
    else if (url === '/api/software-tools/preview') data = {plan:'plan1',computer:'PC-A',name:'Fixture app',version:'1',scope:'Machine',action:'Uninstall',command:'inert fixture command'};
    else if (url === '/api/software-tools/uninstall') data = {job:'job1',computer:'PC-A'};
    else if (url === '/api/software-tools/jobs/job1') {
      jobReads++;
      if (result === 'error') throw Error('Fixture connection unavailable');
      data = {state:result,events:[{message:'Fixture observation only'}]};
    } else throw Error('Unexpected request '+url);
    return {ok:true,status:200,json:async()=>data};
  }});
  const {w, run} = f, get=id=>w.document.getElementById(id);
  w.setTimeout = (fn, delay) => { const id=++timerId; timers.set(id,{fn,delay}); return id; };
  w.clearTimeout = id => timers.delete(id);
  for (const file of ['app.js','console-deployment.js','remote-software.js']) run(fs.readFileSync(root+'/frontend/assets/'+file,'utf8'));
  run('function toast(){}');
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  async function start() {
    await w.AtlasSoftware.load('PC-A');
    get('softwareBody').querySelector('[data-software-action]').click();
    get('softwareUninstall').click(); await settle();
    get('softwareConfirm').value='PC-A'; get('softwareConfirm').dispatchEvent(new w.Event('input'));
    assert(!get('softwareExecute').disabled);
    get('softwareExecute').click(); await settle();
  }
  async function nextTimer() {
    const entry=[...timers.entries()].find(([,value])=>value.delay>=1500);
    assert(entry,'expected bounded job monitor timer'); timers.delete(entry[0]); entry[1].fn(); await settle();
  }
  await start();
  assert.equal(jobReads,1); assert(get('softwareActionLog').textContent.includes('State: unknown'));
  assert(!get('softwareUninstall').disabled && get('softwareExecute').disabled);
  assert.equal(timers.size,0,'unknown terminal outcomes stop all monitoring');
  assert.equal(run("softwareState.software.has('PC-A')"),false,'terminal outcomes invalidate old inventory');
  get('softwareActionDialog').close(); result='interrupted'; await start();
  assert.equal(jobReads,2); assert(get('softwareActionLog').textContent.includes('State: interrupted'));
  assert.equal(timers.size,0);
  get('softwareActionDialog').close(); result='error'; const before=jobReads; await start();
  for (let index=1; index<8; index++) await nextTimer();
  assert.equal(jobReads-before,8,'connection failures stop after eight attempts');
  assert.equal(timers.size,0);
  assert(get('softwareActionLog').textContent.includes('may still be running'));
  assert(get('softwareActionLog').textContent.includes('Monitoring stopped'));
  assert(!get('softwareUninstall').disabled && get('softwareExecute').disabled);
  get('softwareActionDialog').close(); result='running'; await start();
  const prior=jobReads; assert(timers.size);
  w.dispatchEvent(new w.Event('pagehide'));
  assert.equal(timers.size,0,'leaving Atlas stops its software job watcher');
  assert.equal(jobReads,prior);
  assert.equal(calls.filter(([url])=>url==='/api/software-tools/uninstall').length,4,'monitoring never retries an action');
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
  console.log('PASS: software monitoring settles unknown/interrupted, bounds failed reads, cancels on pagehide, invalidates inventory and never retries actions');
})().catch(error=>{console.error(error);process.exitCode=1});
