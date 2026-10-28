const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const settle = () => new Promise(r => setTimeout(r, 40));
(async () => {
  const requests = [], copied = [];
  const f = await fixture({url:'http://127.0.0.1:8771/installer', fetch:async (url, options={}) => {
    requests.push([String(url), options.method || 'GET']);
    const p = new URL(url, 'http://127.0.0.1:8771').pathname;
    let data;
    if (p === '/api/health') data = {identity:'Demo',version:'7.0.0',users:1,machines:1,database:true};
    else if (p === '/api/master/status') data = {available:true,users:1,machines:1,assignments:1};
    else if (p === '/api/palette/desks') data = {records:[]};
    else throw Error('Unexpected network request: '+url);
    return {ok:true,json:async()=>data,headers:new Headers()};
  }});
  const {w,run}=f, d=w.document;
  const meta=d.createElement('meta'); meta.name='atlas-mode'; meta.content='viewer'; d.head.append(meta);
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)}});
  run(fs.readFileSync(path.join(root,'frontend/assets/readonly-console.js'),'utf8'));
  await f.console(); await settle();
  if (!d.body.classList.contains('atlas-readonly-console')) { d.dispatchEvent(new w.Event('DOMContentLoaded')); await settle(); }
  for(const page of ['workspace','admin','bulk','personas','history','psexec']) {
    d.querySelector(`[data-page="${page}"]`).click(); await settle();
    assert(d.getElementById(page).classList.contains('active'),page);
  }
  run('S.machines=[{name:"TESTPC",operational_status:"Operational"}];setTarget("TESTPC","Operational");page("workspace")');
  await settle();
  assert(d.querySelector('#healthLine').textContent.includes('elevated'));
  run('page("admin")');
  for(const view of ['overview','cpu','gpu','memory']) {
    d.querySelector(`[data-performance="${view}"]`).click(); await settle();
    assert(d.querySelector('#refreshProcesses').disabled);
    assert(d.querySelector('#processStatus').textContent.includes('elevated'));
  }
  run('page("psexec")'); await settle();
  assert.equal(d.querySelectorAll('[data-template]').length,72);
  d.querySelector('[data-template="shell"]').click();
  const session=d.querySelector('#pxArg-session');session.value='1';session.dispatchEvent(new w.Event('input'));
  await settle(); assert(!d.querySelector('#pxCopy').disabled);
  d.querySelector('#pxCopy').click();await settle();assert(copied[0].includes('TESTPC'));
  assert.equal(copied[0].split('-accepteula').length-1,1);
  for(const id of ['pxRun','bulkStart','diagnoseSlowness','refreshProcesses','deploy','killBtn']) {
    const b=d.getElementById(id);assert(b.disabled,id);b.click();
    b.disabled=false;await settle();assert(b.disabled,'Must remain disabled: '+id);
  }
  for(const [url,options] of [['/api/performance/TESTPC',{}],['/api/deploy',{method:'POST'}],['/api/psexec/run',{method:'POST'}],['https://other.test/api/health',{}]])
    await assert.rejects(w.AtlasClient.request(url,options),/elevated/);
  await run('runSharedCommand("deploy")');
  for (const id of ['update-users', 'update-devices', 'update-packages', 'update-floorplans']) {
    await run('runSharedCommand("' + id + '")');
    assert.equal(w.location.pathname, '/installer', 'Read-only update commands cannot navigate to Admin');
  }
  await run('runSharedCommand("catalogue")');await settle();assert(d.querySelector('.atlas-catalogue'));
  assert(d.querySelector('#catalog-status').textContent.includes('Windows Admin'));
  assert(requests.every(([url,method])=>method==='GET' && /^\/api\/(health|master\/status|palette\/desks)$/.test(url)),JSON.stringify(requests));
  assert.equal(f.errors.length,0,f.errors.join('\n'));
  w.close();console.log('PASS: full read-only console navigation, metrics views, PsExec preparation/copy, disabled actions and zero remote probes.');
})().catch(e=>{console.error(e);process.exit(1)});
