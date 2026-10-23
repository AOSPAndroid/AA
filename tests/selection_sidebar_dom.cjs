// Synthetic records and manually resolved health checks; no AD or Windows access.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const settle = () => new Promise(resolve => setTimeout(resolve, 25));
(async () => {
  const calls = [], pending = [];
  const reply = data => ({ok:true,status:200,json:async()=>data});
  const f = await fixture({fetch: async (url, options = {}) => {
    calls.push(url);
    if (url.startsWith('/api/machine-health/')) return new Promise(resolve => pending.push({url,signal:options.signal,resolve:data=>resolve(reply(data))}));
    if (url === '/api/health') return reply({identity:'FIXTURE',users:0,machines:0});
    if (url === '/api/history' || url === '/api/psexec/runs') return reply([]);
    if (url === '/api/session') return reply({token:'test'});
    return reply({available:false,users:[],machines:[],items:[],scripts:[],deployments:[]});
  }});
  const {w,run} = f, d = w.document;
  await f.console();run('installSelectionSidebar();renderNavigationIcons();AtlasUI.installIcons()');await settle();
  const side = d.querySelector('#selectionSummary'), host = d.querySelector('#healthLine');
  const iconMarkup = kind => {const node=d.createElement('span');node.innerHTML=w.AtlasUI.icon(kind);return node.innerHTML;};
  const count = () => calls.filter(url => url.startsWith('/api/machine-health/')).length;
  assert(!side.querySelector('.selection-empty').hidden);
  for (const selector of ['[data-page="packages"]', '.atlas-primary-nav a[href="/"]', '[data-section="workspace"]', '[data-section="knowledge"]', '#deploymentsToggle', '#queueToggle', '#deploymentToggle']) {
    assert.equal(d.querySelectorAll(selector+' .atlas-icon').length,1,selector);
    assert.equal(d.querySelector(selector+' svg').getAttribute('aria-hidden'),'true');
  }
  run(`S.user={name:'Alice <script>literal</script>',user_name:'alice',email:'alice@example.test',department:'Support',location:'Paris'};S.machines=[{name:'PC-A',model_id:'Dell Latitude',asset_tag:'BB01',assigned_to:'alice'},{name:'PC-B',model_id:'HP Desktop'},{name:'IPHONE-EXAMPLE',model_id:'Apple iPhone 15',model_category:'Mobile Device - Handheld'}];renderKyc();renderMachines();setTarget('PC-A','',false)`);
  await settle();assert.equal(count(),0);assert(!side.querySelector('script'));
  assert(side.textContent.includes('Alice <script>literal</script>'));assert(side.textContent.includes('Dell Latitude'));
  assert.equal(side.querySelector('.selection-device-icon').innerHTML,iconMarkup('laptop'));
  const initial = count();
  for (const page of ['admin','packages','active-directory','bulk','history','psexec','knowledge','workspace']) run(`page('${page}')`);
  await settle();assert.equal(count(),initial,'Changing pages does not repeat health checks');
  assert(!side.querySelector('.selection-user').hidden);assert(!side.querySelector('.selection-machine').hidden);
  assert.equal(run('S.target'),'PC-A','Page changes retain the target');
  assert(!w.AtlasReadOnly);assert(host.isConnected);
  const checking = w.AtlasHealth.scan(host,'PC-A',()=>run('S.target')==='PC-A',['ping','cshare','storage','system']);await settle();
  assert.equal(count(),4);assert(side.textContent.includes('Checking…'));assert(side.querySelector('.selection-scan').disabled);
  function answer(entry) {
    const [pc,key] = entry.url.split('/').slice(-2);
    entry.resolve({computer:pc,metric:key,state:'ready',checked_at:'2026-10-03T12:00:00Z',data:{available:true,free_bytes:80*1073741824,total_bytes:256*1073741824,uptime_seconds:90000,windows:'Windows 11',version:'24H2',processors:[{Name:'Intel <Example> CPU',LoadPercentage:12,NumberOfCores:8,NumberOfLogicalProcessors:16}],installed_bytes:16*1073741824,usable_kib:16*1048576,free_kib:8*1048576}});
  }
  pending.splice(0).forEach(answer);await checking;await settle();
  assert(side.textContent.includes('Available'));assert(side.textContent.includes('80.0 GiB free'));assert(side.textContent.includes('Last check'));
  assert(!side.textContent.includes('Intel'),'Quick checks do not invent hardware specifications');
  run("page('admin')");side.querySelector('.selection-scan').click();await settle();assert.equal(count(),12,'Manual scan from another page checks all eight readings once');
  pending.splice(0).forEach(answer);await settle();assert(side.textContent.includes('Intel <Example> CPU'));assert(side.textContent.includes('16.0 GiB'));assert(!side.querySelector('script'));
  assert(d.querySelector('#admin.active'),'Scanning does not change the page');
  assert.equal(d.querySelectorAll('#deploymentToggle .atlas-icon').length,1,'Changing selection keeps the deployment icon');
  // Identical updates do not replace focused buttons or re-render the records.
  let writes = 0;const observer = new w.MutationObserver(records=>writes+=records.length);observer.observe(side,{childList:true,subtree:true,characterData:true});
  side.querySelector('.selection-scan').focus();run('AtlasSelection.refresh();AtlasSelection.refresh()');await settle();assert.equal(writes,0);observer.disconnect();
  assert.equal(d.activeElement,side.querySelector('.selection-scan'));
  // A superseded scan cannot populate the new machine's card.
  const stale = w.AtlasHealth.scan(host,'PC-A',()=>run('S.target')==='PC-A',['ping','cshare','storage','system']);await settle();const old = pending.splice(0);
  run("setTarget('PC-B','',false)");old.forEach(answer);await stale;await settle();
  assert(side.textContent.includes('PC-B'));assert(!side.textContent.includes('Intel'));assert(side.querySelector('.selection-readings').textContent.includes('Not scanned'));
  const beforePhone = count();run("setTarget('IPHONE-EXAMPLE')");await settle();assert.equal(count(),beforePhone);
  assert.equal(run('S.target'),'');assert(side.querySelector('.selection-scan').hidden);assert(side.textContent.includes('Inventory device'));assert(!side.textContent.includes('80.0 GiB'));
  assert.equal(side.querySelector('.selection-device-icon').innerHTML,iconMarkup('phone'));
  run("S.machines.push({name:'TABLET-FICT',device_kind:'tablet'});setTarget('TABLET-FICT','',false)");
  assert.equal(side.querySelector('.selection-device-icon').innerHTML,iconMarkup('tablet'));
  assert.equal(d.querySelector('#adminPc').value,'');
  for (const id of ['refreshProcesses','diagnoseSlowness','adminServices','refreshServices'])
    assert(d.getElementById(id).disabled, id+' disables immediately for an inventory-only device');
  assert.equal(d.querySelector('#servicesTarget').textContent,'No target','target-change listeners observe the cleared Admin field');
  w.AtlasReadOnly = {reason:'Read-only fixture'};run("setTarget('PC-B')");await settle();const beforeReadOnly=count();
  assert(side.querySelector('.selection-scan').disabled);side.querySelector('.selection-scan').click();assert.equal(count(),beforeReadOnly);assert(side.textContent.includes('live health requires Admin'));
  run('clearLookup()');await settle();assert(!side.querySelector('.selection-empty').hidden);assert(side.querySelector('.selection-machine').hidden);assert(side.querySelector('.selection-user').hidden);
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.dispatchEvent(new w.Event('pagehide'));w.close();
  console.log('PASS: selection sidebar, page continuity, manual health/specs, no extra scans, stale isolation, literal records, stable buttons, icons, phones and read-only guards');
})().catch(error=>{console.error(error);process.exitCode=1});
