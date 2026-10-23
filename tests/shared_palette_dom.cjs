// Real shared component in a browser-like DOM; all requests/actions are fixtures.
const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function loadModule(file,context,cache=new Map()){
 if(cache.has(file))return cache.get(file);
 const mod=new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});cache.set(file,mod);
 await mod.link(spec=>loadModule(path.resolve(path.dirname(file),spec),context,cache));await mod.evaluate();return mod;
}
(async()=>{
 const results=[],styles=[];
 for(const mode of ['map','console']){
  const dom=new JSDOM('<header><button id="old">Commands</button></header>',{url:'http://127.0.0.1:8770/',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
  w.HTMLElement.prototype.scrollIntoView=function(){};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
  const calls=[],allRequests=[];let requests=[];
  const desk={id:'04R024065',floor:4,match:'confirmed account link'},secondDesk={...desk,id:'04R024066'};
  let personDesks=[desk];
  w.fetch=async(url)=>{
   requests.push(url);
   allRequests.push(url);
   if(url.includes('/api/palette/person/'))return {ok:true,json:async()=>({desks:personDesks})};
   const term=new URL(url,w.location.href).searchParams.get('term');
   // Deliberately return an obsolete query last, even if its signal was aborted.
   if(term==='slow')await sleep(350);
   return {ok:true,json:async()=>({users:term==='Alice'||term?.startsWith('user:')?[{id:7,full_name:'Alice Example',user_name:'alice',email:'alice@example.test'}]:[],machines:term==='slow'?[{name:'OBSOLETE'}]:term?.startsWith('machine:')?[{name:'PC-1',model_id:'Fixture'}]:[]})};
  };
  const {namespace}=await loadModule(path.join(root,'atlas/command-palette.js'),dom.getInternalVMContext());
  const registry=await loadModule(path.join(root,'atlas/command-registry.js'),dom.getInternalVMContext());
  const records=[desk,secondDesk].map(d=>({...d,name:'Alice Example',team:'Fixture'}));
  const palette=namespace.installCommandPalette({getRecords:()=>records,onSelect:id=>calls.push(['desk',id]),toast:s=>calls.push(['toast',s]),runCommand:id=>calls.push(['command',id]),openPerson:id=>calls.push(['person',id]),openMachine:id=>calls.push(['machine',id]),...(mode==='map'?{triggerParent:w.document.querySelector('header')}:{replaceTrigger:w.document.querySelector('#old'),preferPersonDetails:true,prepare:async()=>{}})});
  const input=palette.root.querySelector('input'),options=()=>[...palette.root.querySelectorAll('[role=option]')],type=s=>{input.value=s;input.dispatchEvent(new w.Event('input',{bubbles:true,composed:true}))},key=k=>input.dispatchEvent(new w.KeyboardEvent('keydown',{key:k,bubbles:true,composed:true}));
  const trigger=palette.root.querySelector('button');trigger.focus();await palette.open();
  results.push(options().map(o=>o.textContent));assert.equal(options().length,registry.namespace.COMMANDS.length);styles.push(palette.root.querySelector('link').getAttribute('href'));assert.match(styles.at(-1),/^\/command-palette\.css\?v=\d+$/);
  type('> history');assert.equal(options().length,1);key('Enter');await sleep(0);assert.deepEqual(calls.pop(),['command','history']);assert(!palette.dialog.open);assert.equal(palette.root.activeElement,trigger);
  await palette.open();type('desk:04R024065');key('Enter');await sleep(0);assert.deepEqual(calls.pop(),['desk','04R024065']);
  for(const desks of [[desk],[desk,secondDesk],[]]){
   personDesks=desks;requests=[];
   await palette.open();type('person:Alice');await sleep(220);key('Enter');await sleep(10);
   if(mode==='console'){
    assert.deepEqual(calls.pop(),['person','id:7']);assert(!palette.dialog.open);
    assert(!requests.some(url=>url.includes('/api/palette/person/')),'console person selection must not resolve map destinations');
   }else if(desks.length===2){
    assert(palette.dialog.open);assert.equal(options().length,3);
    key('ArrowDown');key('Enter');await sleep(0);assert.deepEqual(calls.pop(),['desk',secondDesk.id]);
   }else assert.deepEqual(calls.pop(),desks.length?['desk',desk.id]:['person','id:7']);
  }
  personDesks=[desk];requests=[];
  await palette.open();type('Alice');
  if(mode==='console'){
   assert.equal(options().length,0,'wait for directory people before offering named desk hits');
   key('Enter');await sleep(0);assert.equal(calls.length,0);assert(palette.dialog.open);
  }
  await sleep(220);
  assert.equal(options()[0].querySelector('.palette-kind').textContent,mode==='console'?'Person':'Desk');
  key('Enter');await sleep(10);assert.deepEqual(calls.pop(),mode==='console'?['person','id:7']:['desk',desk.id]);
  if(mode==='console')assert(!requests.some(url=>url.includes('/api/palette/person/')));
  await palette.open();type('slow');await sleep(210);type('machine:PC');await sleep(550);assert.equal(options().length,1);assert(options()[0].textContent.includes('PC-1'));assert(!options()[0].textContent.includes('OBSOLETE'));key('Enter');await sleep(0);assert.deepEqual(calls.pop(),['machine','PC-1']);
  await palette.open();key('ArrowDown');assert.equal(input.getAttribute('aria-activedescendant'),'atlas-command-1');
  let leaked=0;w.document.addEventListener('keydown',()=>leaked++);key('d');assert.equal(leaked,0,'palette typing must not reach console shortcuts');
  type('<script>');await sleep(220);assert.equal(options().length,0);assert(!palette.root.querySelector('script'));palette.close();
  assert.equal(palette.root.querySelector('#atlas-ask, .palette-assistant'),null,'both hosts expose search only');
  assert(!registry.namespace.COMMANDS.some(command=>command.id==='assistant'||/Ask Atlas/i.test(command.title)));
  assert(!/Ask Atlas|offline assistant/i.test(palette.root.textContent),'no AI hints or hidden transcript remain');
  const callsBefore=calls.length;
  for(const query of ['Ask > Explain DNS','ask: Explain DNS','Why is Excel slow?','> assistant']){
   trigger.focus();await palette.open();type(query);await sleep(220);
   assert.equal(input.value,query,'former AI prefixes remain ordinary search text');
   assert.equal(input.getAttribute('role'),'combobox');
   assert.equal(input.placeholder,'Search people, machines, desks or actions…');
   assert.equal(options().length,0,'questions do not create an AI result');
   key('Enter');await sleep(0);assert.equal(calls.length,callsBefore,'unmatched questions perform no action');
   assert(palette.dialog.open);palette.close();assert.equal(palette.root.activeElement,trigger);
  }
  assert(allRequests.every(url=>/^\/api\/(search\?|palette\/person\/)/.test(url)),'search only requests directory data; no AI or machine scans');
  for(const [id, update] of Object.entries(registry.namespace.DATABASE_UPDATES)){
   assert.equal(registry.namespace.commandUrl(id),'/manage-database#'+update.section);
   const command=registry.namespace.COMMANDS.find(c=>c.id===id);assert(command && !command.viewer && !command.requiresTarget);
   await palette.open();type('> '+command.title);assert.equal(options()[0].querySelector('.palette-kind').textContent,'Action');key('Enter');await sleep(0);assert.deepEqual(calls.pop(),['command',id]);
  }
  assert.throws(()=>registry.namespace.commandUrl('assistant'));
  assert.throws(()=>registry.namespace.commandUrl('reboot-now'));
  for(const command of registry.namespace.COMMANDS){const url=registry.namespace.commandUrl(command.id,'PC & 1');assert.equal(new URL(url,w.location.href).searchParams.get('machine'),command.id==='knowledge'||command.id.startsWith('kb-')||Object.hasOwn(registry.namespace.DATABASE_UPDATES,command.id)?null:'PC & 1');}
  w.close();
 }
 assert.deepEqual(results[0],results[1]);assert.equal(styles[0],styles[1]);await checkCombinedResults();console.log('PASS: identical search-only commands/styles, no AI UI or requests, keyboard selection, focus, identity-safe merged people/desks, fresh map resolution, console person routing, ambiguous/unlinked fallback, explicit desk navigation, stale response protection, shortcut isolation and URL allowlist.');
})().catch(error=>{console.error(error);process.exitCode=1});

async function checkCombinedResults() {
 for (const mode of ['map', 'console', 'viewer']) {
  const dom = new JSDOM('<header></header>', {url:'http://127.0.0.1:8770/', runScripts:'outside-only', pretendToBeVisual:true}), w = dom.window;
  w.HTMLElement.prototype.scrollIntoView = function() {};
  w.HTMLDialogElement.prototype.showModal = function() {this.open = true};
  w.HTMLDialogElement.prototype.close = function() {this.open = false; this.dispatchEvent(new w.Event('close'))};
  const first = {id:'DESK-A',floor:4,match:'confirmed account link'}, second = {id:'DESK-B',floor:4,match:'confirmed account link'};
  const person = {id:7,full_name:'Alice Example',user_name:'alice',email:'alice@example.test',palette_desks:[first]};
  const record = desk => ({...desk,name:'Alice Example',team:'Fixture'});
  const state = {records:[record(first)],users:[person],desks:{7:[first]},fail:false};
  const calls = [], requests = [], allRequests = [];
  w.fetch = async url => {
   requests.push(url);
   allRequests.push(url);
   const parsed = new URL(url,w.location.href);
   if (parsed.pathname === '/api/search') {
    assert.equal(parsed.searchParams.get('palette'),'true','palette asks for identity-aware desk enrichment');
    return {ok:!state.fail,json:async()=>({users:state.users,machines:[]})};
   }
   if (parsed.pathname.startsWith('/api/palette/person/'))
    return {ok:true,json:async()=>({desks:state.desks[decodeURIComponent(parsed.pathname.split('/').pop()).slice(3)] || []})};
   throw Error('Unexpected request: '+url);
  };
  const {namespace} = await loadModule(path.join(root,'atlas/command-palette.js'),dom.getInternalVMContext());
  const palette = namespace.installCommandPalette({
   getRecords:()=>state.records,onSelect:id=>calls.push(['desk',id]),toast:text=>calls.push(['toast',text]),
   runCommand:id=>calls.push(['command',id]),openPerson:id=>calls.push(['person',id]),openMachine:name=>calls.push(['machine',name]),
   triggerParent:w.document.querySelector('header'),preferPersonDetails:mode==='console',readOnly:mode==='viewer',
  });
  const input=palette.root.querySelector('input'),options=()=>[...palette.root.querySelectorAll('[role=option]')];
  const key=value=>input.dispatchEvent(new w.KeyboardEvent('keydown',{key:value,bubbles:true,composed:true}));
  const outcomes=()=>calls.filter(call=>call[0]!=='toast');
  const search=async query=>{calls.length=0;requests.length=0;await palette.open(query);await sleep(220);return options()};
  // A confirmed identity produces one result, whether activated by key or pointer.
  for (const activation of ['key','click']) {
   const rows=await search('Alice');
   assert.equal(rows.length,1,mode+' combines the person and confirmed local desk');
   assert.equal(rows[0].querySelector('.palette-kind').textContent,'Person');
   for(const text of ['alice@example.test','DESK-A','Floor 4','confirmed account link',mode==='console'?'Open person details':'Locate on map'])
    assert(rows[0].textContent.includes(text),text);
   if(activation==='key')key('Enter');else rows[0].click();
   await sleep(10);
   assert.deepEqual(outcomes(),[mode==='console'?['person','id:7']:['desk','DESK-A']]);
   assert(!palette.dialog.open);
   assert.equal(requests.filter(url=>url.includes('/api/palette/person/')).length,mode==='console'?0:1,'map pointer and keyboard choices resolve the current identity afresh');
  }
  // Search metadata is only a preview; a removed map assignment cannot be used.
  let rows=await search('Alice');state.desks[7]=[];rows[0].click();await sleep(10);
  assert.deepEqual(outcomes(),[['person','id:7']]);
  // Several mapped desks are still one person result with bounded location text.
  const desks=[first,second,{id:'DESK-C',floor:5,match:first.match},{id:'DESK-D',floor:6,match:first.match},{id:'DESK-E',floor:7,match:first.match}];
  state.records=desks.map(record);state.users=[{...person,palette_desks:desks}];state.desks[7]=desks;
  rows=await search('Alice');assert.equal(rows.length,1);assert(rows[0].textContent.includes('+2 more mapped desks'));assert(!rows[0].textContent.includes('DESK-D'));assert(!rows[0].textContent.includes('DESK-E'));
  rows[0].click();await sleep(10);
  if(mode==='console')assert.deepEqual(outcomes(),[['person','id:7']]);
  else{assert(palette.dialog.open);assert.equal(options().length,6);options()[1].click();await sleep(0);assert.deepEqual(outcomes(),[['desk','DESK-B']])}
  // Globally unique full-name matches remain visibly unconfirmed account links.
  state.records=[record(first)];state.users=[{...person,palette_desks:[{...first,match:'matching name; account not confirmed'}]}];
  rows=await search('Alice');assert.equal(rows.length,1);assert(rows[0].textContent.includes('matching name; account not confirmed'));
  // Equal names alone neither merge accounts nor remove ambiguous local desks.
  state.records=[record(first),record(second)].map(row=>({...row,name:'Sam Example'}));
  state.users=[{...person,id:7,full_name:'Sam Example',user_name:'sam.a',palette_desks:[]},{...person,id:8,full_name:'Sam Example',user_name:'sam.b',palette_desks:[]}];state.desks[7]=[];state.desks[8]=[];
  rows=await search('Sam');assert.equal(rows.length,4);const people=rows.filter(row=>row.querySelector('.palette-kind').textContent==='Person');assert.equal(people.length,2);assert(people[0].textContent.includes('sam.a'));assert(people[1].textContent.includes('sam.b'));people[1].click();await sleep(10);assert.deepEqual(outcomes(),[['person','id:8']]);
  // Confirmed links can place same-named accounts independently, using IDs only.
  state.users=[{...state.users[1],palette_desks:[second]},{...state.users[0],palette_desks:[first]}];state.desks[7]=[first];state.desks[8]=[second];
  rows=await search('Sam');assert.equal(rows.length,2);assert(rows[0].textContent.includes(mode==='console'?'sam.b':'sam.a'));assert(rows[1].textContent.includes(mode==='console'?'sam.a':'sam.b'));
  // A backend without enrichment preserves its separate local fallback.
  state.records=[state.records[0]];state.users=[{id:7,full_name:'Sam Example',user_name:'sam.a'}];
  rows=await search('Sam');assert.equal(rows.length,2);assert(rows.some(row=>row.querySelector('.palette-kind').textContent==='Desk'));
  // Numeric database IDs can change on refresh; a returned canonical key identifies
  // the selected account for both full profiles and a fresh map resolution.
  state.records=[];state.users=[{...person,id:7,canonical_key:'uid:fict-stable',palette_desks:[]}];
  rows=await search('Alice');assert.equal(rows.length,1);rows[0].click();await sleep(10);
  assert.deepEqual(outcomes(),[['person','uid:fict-stable']],mode+' retains the returned canonical user key');
  assert.equal(requests.some(url=>url.endsWith('/uid%3Afict-stable')),mode!=='console','map resolution uses the canonical account, console opens it directly');
  state.records=[{...record(first),name:'Sam Example'}];
  state.fail=true;rows=await search('Sam');assert.equal(rows.length,1);assert.equal(rows[0].querySelector('.palette-kind').textContent,'Desk');assert(palette.root.querySelector('#atlas-command-status').textContent.includes('Directory unavailable'));rows[0].click();await sleep(0);assert.deepEqual(outcomes(),[['desk','DESK-A']]);
  rows=await search('desk:DESK-A');assert.equal(rows.length,1);assert.equal(requests.length,0,'explicit desk lookup never contacts directory or assistant');key('Enter');await sleep(0);assert.deepEqual(outcomes(),[['desk','DESK-A']]);
  assert(!allRequests.some(url=>/\/api\/(assistant|machine-health|performance)\//.test(url)),'person/desk lookup never runs AI or WMI');
  assert.equal(palette.root.querySelector('#atlas-ask, .palette-assistant'),null,mode+' has no AI controls');
  w.close();
 }
}
