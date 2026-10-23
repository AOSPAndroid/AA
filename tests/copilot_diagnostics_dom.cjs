// Manual handoff only. Every collected reading below comes from intercepted fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const source = name => fs.readFileSync(path.join(root, 'frontend/assets', name), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const requests = [], copied = [], toasts = [];
  let seedHealth = false;
  const f = await fixture({fetch: async url => {
    requests.push(url);
    assert(seedHealth && url.startsWith('/api/machine-health/TESTPC/'), 'unexpected network: ' + url);
    const metric = url.split('/').pop();
    return {ok:true, json:async () => ({computer:'TESTPC', metric,
      state:metric === 'gpu' ? 'unavailable' : 'ready',
      data:metric === 'cpu' ? {processors:[{Name:'Fixture CPU', LoadPercentage:0, NumberOfCores:4, NumberOfLogicalProcessors:8}]} : {available:true},
      ...(metric === 'cpu' ? {checked_at:'2026-10-01T09:14:00Z'} : {}),
      ...(metric === 'gpu' ? {error:'Access denied <script>window.bad=1</script>'} : {})})};
  }});
  const {w, run} = f, get = id => w.document.getElementById(id);
  const group = context => w.document.querySelector(`.copilot-tools[data-diagnostics-context="${context}"]`);
  const button = context => group(context).querySelector('[data-copy-diagnostics]');
  const status = context => group(context).querySelector('[data-diagnostics-status]').textContent;
  w.toastFixture = value => toasts.push(value);
  Object.defineProperty(w.navigator, 'clipboard', {value:{writeText:async text => copied.push(text)}, configurable:true});
  run(source('app.js'));
  run('function toast(value){window.toastFixture(value)}');
  run(source('console-processes.js'));
  run(source('slowdown-diagnostics.js'));
  run(source('copilot-diagnostics.js'));
  const A = w.AtlasCopilot;
  const links = [...w.document.querySelectorAll('[data-copilot-link]')].map(link => link.href);
  assert.equal(A.report(), '');
  assert.equal(await A.copy(), false);
  assert.equal(A.report('unknown'), '');
  assert(button('selection').disabled && button('admin').disabled);
  assert.equal(requests.length, 0);
  assert.equal(copied.length, 0);
  assert(links.every(link => link === 'https://m365.cloud.microsoft/chat/'));
  assert([...w.document.querySelectorAll('[data-open-copilot]')].every(control => control.tagName === 'BUTTON' && !control.disabled));
  assert([...w.document.querySelectorAll('[data-copilot-link], [data-reopen-copilot], [data-copilot-status]')].every(control => control.hidden));

  // Real pure readers: copied data retains actual check times, missing times and target scope.
  const host = get('healthLine');
  seedHealth = true;
  await w.AtlasHealth.scan(host, 'TESTPC');
  seedHealth = false;
  assert.equal(requests.length, 8);
  const items = Array.from({length:8}, (_, index) => ({Process:`cpu-${index}.exe`, PID:index+10, SessionId:1, CPU:index, Threads:index+1, MemoryBytes:987654321}));
  w.cpuFixture = {ok:true,computer:'TESTPC',kind:'cpu',checked_at:'2026-10-01T09:15:00Z',total_processes:80,
    summary:{cpu_percent:0,logical_processors:8,processor_queue:null,memory_percent:99,gpu_percent:98,context_switches_sec:0},
    items, warnings:['Partial counters <img src=x onerror=window.bad=2>']};
  w.gpuFixture = {ok:true,computer:'TESTPC',kind:'gpu',summary:{gpu_percent:0,gpu_engine_count:2},items:[{Process:'gpu-only.exe',PID:99,GPU:null,CPU:92}]};
  run("acceptPerformanceSnapshot('TESTPC','cpu',window.cpuFixture); acceptPerformanceSnapshot('TESTPC','gpu',window.gpuFixture)");
  assert.equal(w.AtlasPerformance.snapshot('TESTPC').views.find(view => view.kind === 'gpu').checkedAt, null);
  assert.equal(w.AtlasPerformance.snapshot('OTHERPC').views.length, 0);
  assert(w.AtlasHealth.snapshot(host, 'OTHERPC').metrics.every(metric => metric.state === 'not_scanned'));
  w.selectedUser = {full_name:'Alice <script>window.bad=3</script>',user_name:'ACCOUNT1',email:'alice@example.test',manager:'Fixture Manager'};
  w.inventory = [{name:'TESTPC',device_kind:'laptop',model_id:'Fixture model',asset_tag:'ASSET1',assigned_to:'Alice',last_used:'2026-09-30'},
    {name:'IPHONE-SERIAL',device_kind:'iphone',model_id:'Apple iPhone 13',assigned_to:'Alice',install_status:'In Use'},
    {name:'OTHERPC',device_kind:'desktop',model_id:'Other model'}];
  run("S.user=window.selectedUser; S.machines=window.inventory; S.selectedDevice='testpc'; S.target='OLDPC'");
  A.refresh();
  assert(!button('selection').disabled);
  let text = A.report();
  assert(text.includes('Device: TESTPC') && !text.includes('Device: OLDPC'));
  assert(text.includes('Fixture CPU') && text.includes('2026-10-01T09:14:00Z'));
  assert(text.includes('CPU: 0%') && text.includes('Processor queue: Not measured'));
  assert(text.includes('CPU · 2026-10-01T09:15:00Z') && text.includes('GPU · Check time not supplied'));
  assert(text.includes('Access denied <script>window.bad=1</script>'));
  assert(text.includes('Partial counters <img src=x onerror=window.bad=2>'));
  assert(text.includes('Top 5 of 8 returned processes by CPU (80 processes reported in total)'));
  const cpuSection = text.split('CPU · 2026-10-01T09:15:00Z')[1].split('GPU ·')[0];
  assert.equal((cpuSection.match(/cpu-\d\.exe/g) || []).length, 5);
  assert(cpuSection.includes('cpu-7.exe') && !cpuSection.includes('cpu-2.exe'));
  assert(!cpuSection.includes('RAM') && !cpuSection.includes('GPU'));
  assert(text.includes('GPU Not measured'), 'missing process GPU never becomes zero');
  assert.equal(items.map(item => item.Process).join(','), Array.from({length:8}, (_, index) => `cpu-${index}.exe`).join(','));
  assert(text.includes('Not captured for this target'));
  assert(text.includes('Connection path not reported') && !text.includes('This device is a thin client'));
  assert.equal(requests.length, 8, 'report and refresh never collect');

  // Refresh is state-only even with all snapshot readers present.
  const readers = {health:w.AtlasHealth.snapshot, performance:w.AtlasPerformance.snapshot, diagnostics:w.AtlasDiagnostics.snapshot};
  let reads = 0;
  w.AtlasHealth.snapshot = (...args) => { reads++; return readers.health(...args); };
  w.AtlasPerformance.snapshot = (...args) => { reads++; return readers.performance(...args); };
  w.AtlasDiagnostics.snapshot = (...args) => { reads++; return readers.diagnostics(...args); };
  A.refresh();
  assert.equal(reads, 0, 'selection refresh must not even read diagnostics');
  get('adminPc').value = ' otherpc ';
  get('adminPc').dispatchEvent(new w.Event('input'));
  text = A.report('admin');
  assert(text.includes('Device: OTHERPC') && text.includes('Other model'));
  assert(!text.includes('ACCOUNT1') && !text.includes('alice@example.test') && !text.includes('Fixture CPU') && !text.includes('cpu-7.exe'));
  assert(text.includes('Not scanned for this target'));
  get('adminPc').value = '';
  get('adminPc').dispatchEvent(new w.Event('input'));
  assert.equal(A.report('admin'), '', 'Admin does not fall back to directory selection');
  assert(button('admin').disabled);
  get('adminPc').value = 'testpc';
  get('adminPc').dispatchEvent(new w.Event('input'));
  assert(A.report('admin').includes('ACCOUNT1'), 'only matching Admin target shares selected user context');

  // Inventory-only mobiles never consult Windows readers, even if stale Windows data is present.
  run("S.selectedDevice='IPHONE-SERIAL'");
  reads = 0; A.refresh(); text = A.report();
  assert(text.includes('Apple iPhone 13') && text.includes('Inventory-only device') && text.includes('Assigned to: Alice'));
  assert(!text.includes('cpu-7.exe') && !text.includes('Existing performance snapshots'));
  assert.equal(reads, 0);
  run("S.selectedDevice=''; S.target=''");
  reads = 0; A.refresh(); text = A.report();
  assert(text.includes('No device selected; user context only') && text.includes('ACCOUNT1'));
  assert.equal(reads, 0);
  assert(!button('selection').disabled);
  run('S.user=null'); A.refresh();
  assert.equal(A.report(), '');
  button('selection').disabled = false;
  button('selection').click(); await settle();
  assert.equal(copied.length, 0, 'forced activation without a selection cannot copy');

  // Guard even a misbehaving snapshot provider. Source text remains literal; never execute it.
  run("S.user=window.selectedUser; S.selectedDevice='TESTPC'");
  w.AtlasHealth.snapshot = () => ({computer:'WRONG',state:'ready',metrics:[{key:'cpu',label:'CPU',state:'ready',text:'WRONG HEALTH SECRET'}]});
  w.AtlasPerformance.snapshot = () => ({computer:'TESTPC',state:'ready',views:[{computer:'WRONG',kind:'cpu',data:{items:[{Process:'WRONG PROCESS SECRET'}]}}, {computer:'TESTPC',kind:'gpu',data:{computer:'WRONG',items:[{Process:'WRONG DATA SECRET'}]}}]});
  w.AtlasDiagnostics.snapshot = () => ({computer:'WRONG',state:'complete',report:'WRONG SLOWNESS SECRET'});
  text = A.report(); assert(!text.includes('WRONG'));
  w.AtlasHealth.snapshot = () => { throw Error('Health reader denied'); };
  w.AtlasPerformance.snapshot = () => ({computer:'TESTPC',state:'failed',views:[{computer:'TESTPC',kind:'cpu',checkedAt:null,data:null,error:'Provider unavailable'}]});
  w.AtlasDiagnostics.snapshot = () => ({computer:'TESTPC',state:'stopped',sampleCount:1,startedAt:'2026-10-01T09:00:00Z',checkedAt:null,reason:'Stopped by operator',report:'Cause not established from available samples.'});
  text = A.report();
  assert(text.includes('Health reader denied') && text.includes('Not captured · Provider unavailable'));
  assert(text.includes('State: stopped · Samples: 1') && text.includes('Last sample: Check time not supplied'));
  assert(text.includes('Cause not established') && !text.includes('State: complete'));

  // Read-only supports manual copy/open; denied clipboard has a truthful textarea fallback.
  w.AtlasReadOnly = {reason:'Read-only preview'}; A.refresh();
  assert(!button('selection').disabled && !button('admin').disabled);
  assert(await A.copy());
  assert(copied.at(-1).includes('Read-only viewer') && copied.at(-1).includes('Alice <script>window.bad=3</script>'));
  assert(status('selection').includes('TESTPC · Diagnostics copied'));
  assert.equal(w.bad, undefined);
  assert.equal(w.document.querySelectorAll('img[src="x"]').length, 0);
  assert.deepEqual([...w.document.querySelectorAll('[data-copilot-link]')].map(link => link.href), links);
  const toastCount = toasts.length;
  w.navigator.clipboard.writeText = async () => { throw Error('Clipboard denied'); };
  assert.equal(await A.copy(), false);
  const field = w.document.querySelector('dialog.atlas-dialog[open] textarea[readonly]');
  assert(field && field.value.includes('Device: TESTPC'));
  assert.equal(w.document.activeElement, field);
  assert.equal(field.selectionStart, 0); assert.equal(field.selectionEnd, field.value.length);
  assert(status('selection').includes('TESTPC · Select the text to copy manually'));
  assert.equal(toasts.length, toastCount, 'manual fallback must not report clipboard success');
  field.closest('dialog').close();

  // Freeze the exact report before asynchronous clipboard work and never label a new target copied.
  let resolveCopy;
  w.navigator.clipboard.writeText = text => { copied.push(text); return new Promise(resolve => { resolveCopy = resolve; }); };
  const copying = A.copy();
  const frozen = copied.at(-1), count = copied.length;
  assert(button('selection').disabled);
  assert.equal(await A.copy(), false);
  assert.equal(copied.length, count, 'duplicate copy does not duplicate clipboard calls');
  run("S.selectedDevice='OTHERPC'; S.user=null"); A.refresh();
  resolveCopy(); assert(await copying);
  assert.equal(copied.at(-1), frozen);
  assert(frozen.includes('Device: TESTPC') && !frozen.includes('Device: OTHERPC'));
  assert(status('selection').startsWith('OTHERPC · Selected device'));
  assert(!status('selection').includes('copied'));
  assert(!button('selection').disabled);

  // A companion is an explicit top-level window, not a diagnostic transfer or iframe.
  const openCalls = [], navigations = [], popups = [];
  let allowPopup = false, launchReads = 0;
  w.AtlasHealth.snapshot = w.AtlasPerformance.snapshot = w.AtlasDiagnostics.snapshot = () => { launchReads++; throw Error('Launch must not read diagnostics'); };
  function popup() {
    const popupDocument = w.document.implementation.createHTMLDocument('Fixture companion');
    const create = popupDocument.createElement.bind(popupDocument);
    const child = {closed:false,opener:w,focusCount:0,documentReads:0,focus(){this.focusCount++;},close(){this.closed=true;}};
    Object.defineProperty(child, 'document', {get(){child.documentReads++; return popupDocument;}});
    popupDocument.createElement = tag => {
      const element = create(tag);
      if (tag === 'a') element.click = () => navigations.push({href:element.href,target:element.target,rel:element.rel,referrer:element.referrerPolicy,
        opener:child.opener, policy:popupDocument.querySelector('meta[name="referrer"]')?.content});
      return element;
    };
    popups.push(child); return child;
  }
  w.open = (...args) => { openCalls.push(args); return allowPopup ? popup() : null; };
  const launch = context => group(context).querySelector('[data-open-copilot]');
  const reopen = context => group(context).querySelector('[data-reopen-copilot]');
  const popupStatus = context => group(context).querySelector('[data-copilot-status]');
  const manualLink = context => group(context).querySelector('[data-copilot-link]');
  const diagnosticsStatus = status('selection'), beforeLaunchCopies = copied.length;
  launch('selection').click();
  assert.equal(openCalls.length, 1, 'blocked launch makes exactly one synchronous attempt');
  assert(popupStatus('selection').textContent.includes('browser blocked'));
  assert(!manualLink('selection').hidden && !manualLink('admin').hidden);
  assert(reopen('selection').hidden);
  assert.equal(status('selection'), diagnosticsStatus, 'Copilot status does not replace diagnostics status');
  assert.equal(w.location.pathname, '/installer', 'launch never navigates Atlas or silently falls back to a tab');
  Object.defineProperties(w.screen, {availWidth:{value:1920,configurable:true},availHeight:{value:1080,configurable:true},availLeft:{value:-1920,configurable:true},availTop:{value:20,configurable:true}});
  allowPopup = true;
  launch('admin').click();
  assert.equal(openCalls.length, 2);
  assert.equal(navigations.length, 1, 'successful popup has one explicit navigation');
  assert.deepEqual(navigations[0], {href:'https://m365.cloud.microsoft/chat/',target:'_self',rel:'noreferrer noopener',referrer:'no-referrer',opener:null,policy:'no-referrer'});
  assert.equal(openCalls[1][0], 'about:blank'); assert.equal(openCalls[1][1], '_blank');
  const geometry = Object.fromEntries(openCalls[1][2].split(',').slice(1).map(feature => feature.split('=').map((part,index) => index ? Number(part) : part)));
  assert(openCalls[1][2].startsWith('popup,') && !openCalls[1][2].includes('noopener'), 'blank-window result remains observable');
  assert(geometry.width > 0 && geometry.width <= 1920 && geometry.height > 0 && geometry.height <= 1080);
  assert(geometry.left >= -1920 && geometry.left + geometry.width <= 0);
  assert(geometry.top >= 20 && geometry.top + geometry.height <= 1100);
  assert(manualLink('selection').hidden && reopen('selection').hidden);
  assert(popupStatus('selection').textContent.includes('launch requested') && !popupStatus('selection').textContent.includes('ready'));
  launch('selection').click(); launch('admin').click();
  assert.equal(openCalls.length, 2, 'both controls share one observable companion');
  assert.equal(popups[0].focusCount, 2);
  assert.equal(popups[0].documentReads, 1, 'no destination inspection or polling after navigation');

  // COOP can report a severed proxy as closed while the actual window remains open.
  popups[0].closed = true;
  launch('selection').click(); launch('admin').click();
  assert.equal(openCalls.length, 2, 'closed or isolated proxy never causes an automatic second window');
  assert(popupStatus('selection').textContent.includes('closed or isolated'));
  assert(!reopen('selection').hidden && !reopen('admin').hidden && !manualLink('selection').hidden);
  Object.defineProperties(w.screen, {availWidth:{value:320,configurable:true},availHeight:{value:300,configurable:true},availLeft:{value:0,configurable:true},availTop:{value:0,configurable:true}});
  reopen('admin').click();
  assert.equal(openCalls.length, 3, 'reopening is a separate intentional action');
  assert.equal(navigations.length, 2);
  assert(openCalls[2][2].includes('width=320,height=300,left=0,top=0'), 'small available screens are clamped');
  assert(reopen('selection').hidden && manualLink('selection').hidden);
  assert.equal(await A.reopen(), true, 'a still-observable window is focused even through explicit reopen API');
  assert.equal(openCalls.length, 3);
  popups[1].closed = true;
  allowPopup = false;
  assert.equal(A.reopen(), false);
  assert.equal(openCalls.length, 4);
  assert(!reopen('admin').hidden && popupStatus('admin').textContent.includes('browser blocked'), 'blocked explicit reopening remains explicitly retryable');
  const unsafe = popup();
  Object.defineProperty(unsafe, 'opener', {get(){return w;},set(){}});
  w.open = () => unsafe;
  assert.equal(A.reopen(), false);
  assert(unsafe.closed, 'a window with an unprotected opener is closed before navigation');
  assert.equal(unsafe.documentReads, 0, 'opener protection is verified before preparing external navigation');
  assert.equal(navigations.length, 2);
  assert(popupStatus('admin').textContent.includes('could not be prepared'));
  assert.equal(launchReads, 0);
  assert.equal(copied.length, beforeLaunchCopies, 'opening Copilot never copies or transmits diagnostics');
  assert.deepEqual([...w.document.querySelectorAll('[data-copilot-link]')].map(link => link.href), links);
  assert([...w.document.querySelectorAll('[data-copilot-link]')].every(link => link.target === '_blank' && link.rel.includes('noopener') && link.rel.includes('noreferrer') && link.getAttribute('referrerpolicy') === 'no-referrer'));
  assert(!launch('selection').disabled && !launch('admin').disabled, 'read-only viewers can open the companion');
  assert.equal(requests.length, 8, 'the coordinator never starts diagnostics or sends evidence');
  assert.equal(f.errors.length, 0, f.errors.join('\n'));
  w.close();
  console.log('PASS: manual Copilot handoff, cached evidence and target guards, timestamps/missing readings, bounded processes, safe clipboard fallback, protected companion window, blocking/reuse/COOP/reopen, screen bounds and zero automatic data transfer');
})().catch(error => { console.error(error); process.exitCode = 1; });
