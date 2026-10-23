const assert = require('node:assert/strict');
const { fixture } = require('./ui_fixture.cjs');
const settle = async () => { await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); };
(async () => {
  const calls = [], writes = [];
  let resolveA;
  const row = folder => ({folder, display_name: 'Application ' + folder, version:'1', revision:7,
    scripts:{Install:[folder + '_i.ps1'],Uninstall:[],Repair:[]}, complete:true, files_checked:1,
    availability:'No recall flags detected', checked_at:'2026-09-09T12:00:00Z'});
  const f = await fixture({fetch:async (url, options={}) => {
    calls.push(String(url));const reply = data => ({ok:true,status:200,json:async()=>data});
    if(url.includes('/palette/desks'))return {...reply({records:[]}),headers:{get:()=>null}};
    if(url==='/api/session')return reply({token:'fixture'});
    if(url==='/api/catalog/metadata'){writes.push(JSON.parse(options.body));assert.equal(options.headers.get('X-Atlas-Token'),'fixture');return reply({saved:true,revision:8});}
    if(url.includes('/api/catalog/details?folder=A'))return new Promise(resolve=>{resolveA=()=>resolve(reply(row('A')))});
    if(url.includes('/api/catalog/details?folder=B'))return reply(row('B'));
    if(url.startsWith('/api/catalog?'))return reply({items:[row('A'),row('B')],total:2});
    return reply({items:[],deployments:[]});
  }});
  await f.console();await settle();const {w,run}=f;
  const pkg=w.document.querySelector('#pkg'),script=w.document.querySelector('#script');
  pkg.innerHTML='<option value="A">Application A</option><option value="B">Application B</option>';pkg.value='B';
  script.innerHTML='<option>B_i.ps1</option>';run("S.target='PC-A';syncDeploymentPanel()");
  const originalURL=w.location.href;
  await run("runSharedCommand('catalogue')");await settle();
  const dialog=w.document.querySelector('.atlas-catalogue');assert(dialog.open);assert.equal(w.location.href,originalURL);
  assert.equal(w.document.querySelectorAll('.atlas-catalogue').length,1);await run('openConsoleCatalogue()');assert.equal(w.document.querySelectorAll('.atlas-catalogue').length,1);
  assert.equal(pkg.value,'B');assert.equal(script.value,'B_i.ps1');assert.equal(run('S.target'),'PC-A');
  dialog.querySelector('[data-catalog-folder="A"]').click();await settle();dialog.querySelector('[data-catalog-folder="B"]').click();await settle();resolveA();await settle();
  assert.equal(dialog.querySelector('#catalog-detail h3').textContent,'Application B');
  const form=dialog.querySelector('form');form.elements.display_name.value='Renamed B';form.elements.version.value='2';
  form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
  assert.deepEqual(writes,[{folder:'B',display_name:'Renamed B',version:'2',revision:7}]);assert.equal(pkg.value,'B');assert.equal(pkg.selectedOptions[0].textContent,'Renamed B · 2');assert.equal(script.value,'B_i.ps1');assert.equal(run('S.target'),'PC-A');
  const search=dialog.querySelector('#catalog-search');search.value='pending';search.dispatchEvent(new w.Event('input'));dialog.close();const count=calls.length;await new Promise(r=>setTimeout(r,240));assert.equal(calls.length,count);assert(!w.document.querySelector('.atlas-catalogue'));
  assert(!calls.some(url=>/\/api\/(deploy|machine-health|open-tool)/.test(url)));assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
  console.log('PASS: shared catalogue, console stays in place, stale inspection rejected, authenticated save, selection retained and close cancels debounce');
})().catch(error=>{console.error(error);process.exitCode=1});
