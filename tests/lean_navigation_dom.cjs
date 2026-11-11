// Simulated local data only; opening navigation never executes a remote action.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const reply = data => ({ok:true,status:200,headers:{get:()=>null},json:async()=>data});
(async () => {
  const calls=[];
  const f=await fixture({fetch:async (url, options={}) => {
    calls.push({url:String(url),method:options.method||'GET'});
    if(url==='/api/health')return reply({identity:'FIXTURE',users:0,machines:0});
    if(url.startsWith('/api/catalog'))return reply({available:false,items:[],total:0});
    if(url.startsWith('/api/scripts'))return reply({scripts:[]});
    if(url.includes('/palette/desks'))return reply({records:[]});
    if(url.startsWith('/api/history'))return reply([]);
    return reply({items:[],deployments:[],available:false});
  }});
  await f.console();await sleep(40);
  const {w,run}=f,d=w.document,tools=d.getElementById('console-tools');
  for(const name of ['AtlasTerminal','AtlasScripts','AtlasPsExec'])w[name]={open(){}};
  w.AtlasClipboard={shown(){}};
  assert(!tools.open,'Specialist tools start folded away');
  assert.equal(d.querySelectorAll('.console-sidebar nav > button').length,6);
  assert.equal(d.querySelector('.workspace-launchers'),null,'Workspace shows search/activity instead of a second navigation catalogue');
  for(const id of ['terminal','scripts','clipboard','bulk','psexec']) {
    tools.open=false;run(`page(${JSON.stringify(id)})`);
    assert(tools.open,`${id} opens its navigation group`);
    assert(d.getElementById(id).classList.contains('active'));
    assert.equal(d.querySelector('.console-sidebar [aria-current="page"]').dataset.page,id==='psexec'?'scripts':id);
  }
  for(let i=0;i<50 && run('bulkBusy');i++)await sleep(10);
  assert(!run('bulkBusy'),'Navigation lookup has settled before the fixture closes');
  assert(calls.every(call=>call.method==='GET'),'Navigation must not dispatch operations');
  assert.deepEqual(f.errors,[]);w.dispatchEvent(new w.Event('pagehide'));w.close();
  for(const id of ['directory-import','package-data-import','vdi-data-import','desk-moves-panel']) {
    const data=await fixture({html:'frontend/database.html',url:`http://localhost/manage-database#${id}`,fetch:async()=>reply({counts:{users:0,machines:0,assignments:0},history:[]})});
    const manual=data.w.document.getElementById('manual-imports');
    assert(!manual.open);
    data.run(fs.readFileSync('frontend/assets/database.js','utf8'));await sleep(10);
    assert(manual.open,`${id} reveals manual imports`);
    assert.equal(data.w.document.activeElement.id,id);
    if(id==='desk-moves-panel')assert(data.w.document.getElementById(id).open);
    assert.deepEqual(data.errors,[]);data.w.close();
  }
  console.log('PASS: compact navigation, direct specialist routes, no dispatched operations, and keyboard-focused manual import deep links');
})().catch(error=>{console.error(error);process.exitCode=1});
