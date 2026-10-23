// User details must be useful without selecting a machine or running health checks.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const calls=[];
  const user={id:1,canonical_key:'uid:alice',name:'Alice Example',full_name:'Alice Example',user_name:'alice',employee_number:'alice',email:'alice@example.test',department:'Support',business_unit:'Technology',organisational_unit:'Operations',manager:'Morgan Example',location:'Paris',job_type:'Permanent',start_date:'2022-07-11 00:00:00',last_login:'2026-08-31 00:00:00',last_login_time:'46265.39671296296'};
  const f=await fixture({fetch:async url=>{
    url=String(url);calls.push(url);
    let data={users:[],machines:[],available:false};
    if(url.includes('/api/user/id%3A1') || url.includes('/api/user/uid%3Aalice'))data={user,machines:[{name:'PC-A'},{name:'PC-B'}]};
    else if(url.includes('/api/user/id%3A2'))data={user:{id:2,name:'Minimal Person',user_name:'minimal'},machines:[]};
    else if(url==='/api/health')data={identity:'FIXTURE',users:0,machines:0};
    else if(url==='/api/history')data=[];
    else if(url.includes('/catalog'))data={items:[]};
    else if(url.includes('/session'))data={token:'test'};
    else if(url.includes('/palette/desks'))data={records:[{id:'DESK-A',name:user.name,floor:4,team:'Support'}]};
    else if(url.includes('/palette/person/'))data={desks:[{id:'DESK-A',floor:4,match:'confirmed account link'}]};
    else if(url.includes('/api/search?')&&['Alice','user:Alice'].includes(new URL(url,'http://localhost').searchParams.get('term')))data={users:[{...user,palette_desks:[{id:'DESK-A',floor:4,match:'confirmed account link'}]}],machines:[]};
    else if(url.includes('/deployments/'))data={deployments:[]};
    return {ok:true,status:200,headers:{get:()=>null},json:async()=>data};
  }});
  await f.console();await f.run('sharedPaletteReady');await sleep(30);
  await f.run("loadUser('id:1')");
  const {w}=f, doc=w.document, panel=doc.querySelector('#kyc details');
  const before=calls.length;panel.querySelector('summary').click();
  assert.equal(panel.querySelector('summary').textContent,'User details');
  assert.equal(panel.querySelectorAll('.atlas-person-detail-sections > section').length,3);
  assert.equal(doc.querySelectorAll('#kyc details').length,1);
  for(const text of ['DaaS','BA2','Corporate grade','Persona','Out of office'])assert(!panel.textContent.includes(text),text);
  assert(!panel.querySelector('.daas-device-list'));assert(!panel.textContent.includes('Employee ID'));
  assert(panel.textContent.includes('Technology'));assert(panel.textContent.includes('2026-08-31 09:31:16'));
  assert(!panel.textContent.includes('2026-08-31 00:00:00'));
  assert(doc.querySelector('.domain-account-fact').textContent.includes('INTRANET\\alice'));
  assert.equal(calls.length,before);assert.equal(f.run('S.target'),'');
  const palette=doc.querySelector('.atlas-palette-mount').shadowRoot;
  for(const [label,query] of [['Find manager','user:Morgan Example'],['Same department','department:Support'],['Same office','location:Paris']]){
    const button=[...panel.querySelectorAll('[data-person-search]')].find(b=>b.textContent===label);
    button.focus();button.click();await sleep(220);
    assert(palette.querySelector('dialog').open);assert.equal(palette.querySelector('input').value,query);
    assert(calls.some(url=>url.includes('/api/search?')&&new URL(url,'http://localhost').searchParams.get('term')===query));
    assert.equal(f.run('S.user.id'),1);assert.equal(f.run('S.target'),'');
    palette.querySelector('.palette-close').click();assert.equal(doc.activeElement,button);
  }
  assert(!calls.some(url=>/preflight|overview|open-tool|api\/deploy\b/.test(url)));
  // G export IDs and corrected Windows logins stay distinct in display and copy.
  const domainUser={...user,user_name:'G00123456',login_id:'x00123456'};
  f.run('S.user='+JSON.stringify(domainUser)+';renderKyc()');
  assert.equal(doc.querySelectorAll('#kyc .domain-account-fact').length,1);
  assert.equal(doc.querySelector('#kyc .domain-account-fact b').textContent,'INTRANET\\x00123456');
  const copied=[];Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)},configurable:true});
  const copyButton=label=>doc.querySelector('#kyc [aria-label="'+label+'"]');
  assert(!doc.querySelector('#kyc .atlas-person-details').open);
  for(const label of ['Copy email','Copy account','Copy domain account','Copy name','Copy summary'])
    assert(!copyButton(label).closest('details'),'Quick copying is available before expanding details');
  copyButton('Copy domain account').click();await sleep(0);assert.equal(copied.at(-1),'INTRANET\\x00123456');
  copyButton('Copy account').click();await sleep(0);assert.equal(copied.at(-1),'G00123456');
  copyButton('Copy email').click();await sleep(0);assert.equal(copied.at(-1),user.email);
  assert.equal(copyButton('Copy email').dataset.copyState,'copied');
  assert.equal(doc.querySelector('#kyc [role="status"]').textContent,'Email copied');
  f.run('S.target="PC-NEW"');
  copyButton('Copy summary').click();await sleep(0);
  // The timestamp line can tick over a second between the copy and this comparison.
  const untimed=text=>text.replace(/^Timestamp: .*\n/m,'');
  assert.equal(untimed(copied.at(-1)),untimed(f.run('supportSummary()')),'Summary resolves the current machine at copy time');
  f.run('S.target=""');
  assert(f.run('supportSummary()').includes('Domain account: INTRANET\\x00123456'));
  assert(f.run('completeMachineReport()').includes('Domain account: INTRANET\\x00123456'));
  const shared=w.document.createElement('div');shared.innerHTML=w.AtlasUI.person(domainUser);
  assert.equal(shared.querySelector('.domain-account-fact b').textContent,'INTRANET\\x00123456');
  assert.equal(w.AtlasUI.domainAccount({login_id:'OTHER\\someone'}),'OTHER\\someone');
  assert.equal(w.AtlasUI.domainAccount({login_id:'someone@realm.example'}),'someone@realm.example');
  assert.equal(w.AtlasUI.domainAccount({user_name:'someone@realm.example'}),'someone@realm.example');
  assert.equal(w.AtlasUI.domainAccount({}),'');
  // Read-only lookup may host the palette; an edit dialog must still block it.
  const readOnly=w.AtlasUI.dialog('User & machine lookup');readOnly.element.classList.add('viewer-lookup-dialog');readOnly.body.innerHTML=w.AtlasUI.person(user);
  const manager=readOnly.body.querySelector('[data-person-search]');manager.click();await sleep(0);
  assert(palette.querySelector('dialog').open);assert(readOnly.element.open);palette.querySelector('.palette-close').click();
  const officeCopy=readOnly.body.querySelector('[aria-label="Copy office"]');
  officeCopy.click();await sleep(0);assert.equal(copied.at(-1),'Paris','Shared read-only cards support field copying');
  assert(readOnly.element.open);
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async()=>{throw Error('Denied')}},configurable:true});
  officeCopy.focus();officeCopy.click();await sleep(0);
  const fallback=[...doc.querySelectorAll('dialog[open]')].at(-1),field=fallback.querySelector('textarea');
  assert(field.readOnly);assert.equal(field.value,'Paris');
  assert.equal(field.selectionStart,0);assert.equal(field.selectionEnd,5);
  assert(fallback.textContent.includes('Ctrl+C'));fallback.close();
  assert.equal(doc.activeElement,officeCopy,'Manual copy restores focus to the initiating button');
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)},configurable:true});
  const editor=w.AtlasUI.dialog('Edit record');manager.click();await sleep(0);assert(!palette.querySelector('dialog').open);editor.element.close();readOnly.element.close();
  await f.run("loadUser('id:2')");
  assert.equal(doc.querySelectorAll('#kyc [data-person-search]').length,0);assert(!doc.querySelector('#kyc').textContent.includes('Technology'));
  assert(doc.querySelector('#kyc').textContent.includes('Last recorded loginNot supplied'));
  assert(!copyButton('Copy email'),'Missing fields do not create empty copy controls');
  const literal='A "Quoted" <script>alert(1)</script> & Co';
  readOnly.body.innerHTML=w.AtlasUI.person({name:literal,email:literal});
  doc.body.append(readOnly.element);
  assert(!readOnly.body.querySelector('script'));
  readOnly.body.querySelector('[aria-label="Copy email"]').click();await sleep(0);
  assert.equal(copied.at(-1),literal,'Copy preserves literal export values without executing markup');
  readOnly.element.remove();
  // The real console wiring must keep mapped people in the Workspace, for both
  // prefixed and ordinary name searches, with mouse and keyboard selection.
  const consoleUrl=w.location.href;
  for(const query of ['person:Alice','Alice']){
    await f.run("loadUser('id:2')");
    f.run(query.startsWith('person:')?"page('history')":"page('workspace')");
    const start=calls.length;
    await f.run('sharedPalette.open('+JSON.stringify(query)+')');await sleep(220);
    const result=palette.querySelector('[role=option]');
    assert.equal(palette.querySelectorAll('[role=option]').length,1,'confirmed person and desk appear once in the real Console');
    assert.equal(result.querySelector('.palette-kind').textContent,'Person');
    assert(result.textContent.includes('Open person details'));assert(result.textContent.includes('DESK-A'));assert(result.textContent.includes('Floor 4'));
    if(query.startsWith('person:'))result.click();
    else palette.querySelector('input').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,composed:true}));
    await sleep(30);
    assert(!palette.querySelector('dialog').open);
    assert(doc.querySelector('#workspace').classList.contains('active'));
    assert.equal(f.run('S.user.id'),1);assert.equal(f.run('S.target'),'');
    assert.equal(f.run('S.machines.map(m=>m.name).join(",")'),'PC-A,PC-B');
    assert.equal(w.location.href,consoleUrl);
    assert(!calls.slice(start).some(url=>url.includes('/palette/person/')));
    assert(calls.slice(start).some(url=>url.includes('/api/user/uid%3Aalice')),'palette follows the stable canonical account key');
    assert(!calls.slice(start).some(url=>url.includes('/api/user/id%3A1')),'palette never rebuilds an ID that a directory refresh could reuse');
    assert(!calls.slice(start).some(url=>/\/api\/(assistant|machine-health|performance)\//.test(url)));
  }
  // Filters are local and preserve target identity, row indices and assignment order.
  const machines = [
    {name:'GBRPWMF123', assigned_relationship:1}, {name:'PARPWMK123', assigned_relationship:1},
    {name:'NYKPWMK234'}, {name:'SGPPWMVDI345'}, {name:'NYKPLM456'}, {name:'ODD-PC'}
  ];
  f.run('S.machines='+JSON.stringify(machines)+';S.target="GBRPWMF123";renderMachines()');
  const filterHost=doc.querySelector('#machines'), networkBefore=calls.length;
  const visible=()=>[...filterHost.querySelectorAll('[data-machine]:not([hidden])')].map(row=>Number(row.dataset.machine));
  const press=kind=>filterHost.querySelector('[data-kind="'+kind+'"]').click();
  assert.deepEqual(visible(),[0,1,2,3,4,5]);
  press('kiosk');assert.deepEqual(visible(),[1,2]);
  press('vdi');assert.deepEqual(visible(),[1,2,3]);
  assert.equal(f.run('S.target'),'GBRPWMF123');
  press('all');assert.deepEqual(visible(),[0,1,2,3,4,5]);
  assert(filterHost.querySelector('[data-machine="0"]').classList.contains('selected'));
  press('other');assert.deepEqual(visible(),[4,5]);
  assert.equal(calls.length,networkBefore,'Filtering performs no fetch or remote scan');
  const filters=()=>[...filterHost.querySelectorAll('.atlas-machine-filters [data-kind]')];
  const countFor=kind=>filterHost.querySelector('[data-kind="'+kind+'"] .atlas-filter-count').textContent;
  const summary=()=>filterHost.querySelector('.atlas-machine-filter-heading small').textContent;
  assert.equal(filterHost.querySelector('.atlas-machine-filter-heading strong').textContent,'Linked devices');
  assert.equal(summary(),'2 of 6 shown');
  for(const kind of ['all','desktop','laptop','mobile'])assert(filterHost.querySelector('[data-kind="'+kind+'"]'));
  const zeroMobile=filterHost.querySelector('[data-kind="mobile"]');
  assert(zeroMobile.disabled,'Mobile stays visible, clearly unavailable for a PC-only result');
  assert.equal(zeroMobile.querySelector('.atlas-filter-label').textContent,'Mobile');
  assert.equal(countFor('mobile'),'0');assert.equal(zeroMobile.getAttribute('aria-label'),'Mobile, 0 devices');
  zeroMobile.click();assert.deepEqual(visible(),[4,5]);
  assert(filterHost.querySelector('[data-kind="laptop"]').disabled);
  assert(!filterHost.querySelector('[data-kind="mac"]'),'Absent optional kinds do not add zero-count filters');
  for(const kind of ['iphone','phone','tablet'])assert(!filterHost.querySelector('[data-kind="'+kind+'"]'));
  // Mobile aggregates real inventory kinds and inferred iPhone/Android/tablet
  // records without changing identities, order or the existing Windows target.
  const mixed=[
    {name:'GBRPWMF123',device_kind:'desktop',model_category:'Computer',model_id:'Dell Precision 3660'},
    {name:'LAPTOP-A',model_category:'Laptop',model_id:'Dell Latitude 7450'},
    {name:'LAPTOP-B',device_kind:'laptop',model_id:'Lenovo ThinkPad'},
    {name:'IPHONE-SERIAL-EXAMPLE123',device_kind:'iphone',model_category:'Mobile Device - Handheld',model_id:'APPLE iPhone 13'},
    {name:'CORP-ANDROID',model_category:'Mobile Device - Handheld',model_id:'Samsung Android phone'},
    {name:'CORP-TABLET',model_category:'Mobile Device - Handheld',model_id:'Samsung Android tablet'},
  ];
  f.run('S.machines='+JSON.stringify(mixed)+';renderMachines()');
  const mixedCalls=calls.length, originalRows=[...filterHost.querySelectorAll('[data-machine]')];
  assert.deepEqual(filters().map(button=>button.dataset.kind),['all','desktop','laptop','mobile']);
  assert.deepEqual(filters().map(button=>button.querySelector('.atlas-filter-count').textContent),['6','1','2','3']);
  assert.equal(filterHost.querySelector('[data-kind="mobile"]').getAttribute('aria-label'),'Mobile, 3 devices');
  assert.equal(summary(),'6 linked devices');
  assert.deepEqual(originalRows.map(row=>row.dataset.machineKind),['desktop','laptop','laptop','iphone','phone','tablet']);
  assert(originalRows[0].classList.contains('selected'));
  press('mobile');assert.deepEqual(visible(),[3,4,5]);assert.equal(summary(),'3 of 6 shown');
  assert.equal(filterHost.querySelector('[data-kind="all"]').getAttribute('aria-pressed'),'false');
  assert.equal(filterHost.querySelector('[data-kind="mobile"]').getAttribute('aria-pressed'),'true');
  press('desktop');assert.deepEqual(visible(),[0,3,4,5]);assert.equal(summary(),'4 of 6 shown');
  press('mobile');assert.deepEqual(visible(),[0]);
  press('desktop');assert.deepEqual(visible(),[0,1,2,3,4,5]);assert.equal(summary(),'6 linked devices');
  assert.equal(filterHost.querySelector('[data-kind="all"]').getAttribute('aria-pressed'),'true','Deselecting the final type resets All');
  press('laptop');press('mobile');assert.deepEqual(visible(),[1,2,3,4,5]);
  press('all');assert.deepEqual(visible(),[0,1,2,3,4,5]);
  assert.equal(filterHost.querySelector('[data-kind="mobile"]').getAttribute('aria-pressed'),'false');
  for(const [index,row] of [...filterHost.querySelectorAll('[data-machine]')].entries())assert.equal(row,originalRows[index]);
  assert.equal(f.run('S.machines.map(m=>m.name).join(",")'),mixed.map(machine=>machine.name).join(','));
  assert.equal(f.run('S.target'),'GBRPWMF123');
  assert.equal(calls.length,mixedCalls,'Mixed device filtering remains local');
  for(const machine of mixed.slice(3))assert(!w.AtlasUI.supportsWindows(machine));
  assert.equal(w.AtlasUI.machineKind({name:'UNRECOGNIZABLE',device_kind:'tablet'}),'tablet','Backend device-kind flags are authoritative');
  // Inline metadata groups retain badges, escaped export values and provenance.
  const metadata=doc.createElement('div'),assignee='A "Quoted" <script>alert(1)</script> & Co';
  metadata.innerHTML=w.AtlasUI.machineBadges({...mixed[3],assigned_to:assignee,assigned_at:'46296',install_status:'In Use <test>',last_used:'46297.5',last_logon_user:'alice',logon_relationship:1});
  assert.equal(metadata.querySelector('.atlas-device-status .kind').textContent,'iPhone');
  assert.equal(metadata.querySelector('.atlas-device-status .assigned').textContent,'Assigned');
  assert(metadata.querySelector('.assigned').title.includes(assignee));
  assert.equal(metadata.querySelector('.atlas-device-status .asset-state').textContent,'In Use <test>');
  assert.equal(metadata.querySelector('.atlas-device-status').querySelectorAll('.atlas-device-badge').length,3);
  assert.equal(metadata.querySelector('.atlas-device-history').querySelectorAll('.atlas-device-badge').length,2);
  assert.equal(metadata.querySelector('.atlas-device-history .last-used').textContent,'Last used: 2026-10-02');
  assert(metadata.querySelector('.last-used').title.includes('2026-10-02 12:00:00'));
  assert(metadata.querySelector('.atlas-device-history .logon').title.includes('not a live sign-in check'));
  assert(!metadata.querySelector('script,test'));
  for(const name of ['GBRPWMK1','PARPWMK2','NYKPWMK3','SGPPWMK4','nykpwmk5.example.test'])
    assert.equal(w.AtlasUI.machineKind({name}),'kiosk');
  assert.equal(w.AtlasUI.machineKind({name:'NYKPLM1'}),'other','K in country code is not a kiosk');
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
  console.log('PASS: grouped user details, domain copy, manager/team/office search, modal protection, mapped-person palette lookup, aggregate Mobile filters with unchanged target/order and no remote calls, zero-count primary filters and escaped device metadata');
})().catch(error=>{console.error(error);process.exit(1);});
