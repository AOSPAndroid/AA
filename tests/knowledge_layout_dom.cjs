// Real KB presentation with controlled geometry/editor replies; no live services.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture}=require('./ui_fixture.cjs');
const settle=()=>new Promise(resolve=>setTimeout(resolve,25));
(async()=>{
 for(const readonly of [false,true]){
  const calls=[],writes=[],observers=[];
  const f=await fixture({fetch:async(url,options={})=>{
   calls.push(url);if(options.method==='PUT'){writes.push(JSON.parse(options.body));return {ok:true,json:async()=>({revision:1,updated:'2026-10-07T12:00:00Z'})};}
   assert.equal(options.method||'GET','GET');return {ok:true,json:async()=>url==='/api/knowledge'?{documents:[{id:'FICT',title:'Fictional document',updated:'2026-10-07T12:00:00Z'}]}:{token:'fixture'}};
  }});
  const {w,run}=f,d=w.document,root=d.querySelector('#knowledge');
  const style=d.createElement('style');style.textContent=fs.readFileSync('frontend/assets/design-system.css','utf8');d.head.append(style);
  if(readonly)w.AtlasReadOnly={reason:'Read-only fixture'};
  root.classList.add('active');d.body.classList.add('knowledge-open');root.closest('main').style.paddingBottom='12px';
  let width=1154,height=768,top=91,scroll=0;
  Object.defineProperty(w,'innerHeight',{get:()=>height});Object.defineProperty(w,'scrollY',{get:()=>scroll});
  root.getClientRects=()=>root.classList.contains('active')?[{width}]:[];
  root.getBoundingClientRect=()=>({width,top:60,bottom:height,height:height-60});
  const original=w.HTMLElement.prototype.getBoundingClientRect;
  w.HTMLElement.prototype.getBoundingClientRect=function(){return this.matches('.kb-layout')?{width,top,bottom:height,height:height-top}:original.call(this)};
  w.ResizeObserver=class{constructor(callback){this.callback=callback;this.nodes=[];observers.push(this)}observe(node){this.nodes.push(node)}disconnect(){this.nodes=[]}};
  run(fs.readFileSync('frontend/assets/knowledge-converter.js','utf8'));run(fs.readFileSync('frontend/assets/knowledge-base.js','utf8'));
  const api=w.AtlasKnowledge;await api.open();await settle();
  const frame=d.getElementById('kbDrawio'),notes=d.getElementById('kbNotes'),docs=d.getElementById('kbLibraryDock'),dock=d.getElementById('kbNotesDock');
  const documentsButton=root.querySelector('[data-kb="toggle-documents"]'),notesButton=root.querySelector('[data-kb="toggle-notes"]'),focus=root.querySelector('[data-kb="focus"]');
  assert.equal(root.style.getPropertyValue('--kb-available-height'),'665px');assert.equal(root.dataset.kbNarrow,'false');
  assert(!docs.hidden);assert(dock.hidden);assert.equal(documentsButton.getAttribute('aria-expanded'),'true');assert.equal(notesButton.getAttribute('aria-expanded'),'false');
  assert.equal(root.querySelectorAll('.kb-heading').length,1);assert(root.querySelector('.kb-heading #kbTitle'));assert(root.querySelector('.kb-heading [data-kb="save"]'));assert.equal(root.querySelector('.kb-editor-bar'),null);
  assert.equal(root.querySelector('[data-kb="save"]').textContent,readonly?'Download':'Save');
  const emit=message=>w.dispatchEvent(new w.MessageEvent('message',{source:frame.contentWindow,origin:w.location.origin,data:JSON.stringify(message)}));
  const messages=[];let capture;
  frame.contentWindow.postMessage=text=>{const message=JSON.parse(text);messages.push(message);if(message.action==='export')capture=()=>emit({event:'export',xml:api.getDocument().xml,message});};
  emit({event:'load'});
  notes.value='Fictional draft notes';notes.dispatchEvent(new w.Event('input'));
  const draft=api.getDocument(),beforeCalls=calls.length;
  notesButton.click();await settle();assert(!dock.hidden);assert.equal(notesButton.getAttribute('aria-expanded'),'true');
  notes.focus();await api.command('kb-toggle-notes');assert(dock.hidden);assert.equal(d.activeElement,notesButton,'Collapsing a focused dock returns focus to its disclosure');
  await api.command('kb-notes');assert(!dock.hidden);assert.equal(d.activeElement,notes);
  await api.command('kb-focus');assert(docs.hidden&&dock.hidden);assert.equal(focus.getAttribute('aria-pressed'),'true');assert.equal(root.querySelector('.kb-focus-label').textContent,'Restore panels');
  assert.equal(d.activeElement,frame,'Focus editor puts keyboard focus into the preserved iframe');
  await api.command('kb-focus');assert(!docs.hidden&&!dock.hidden);assert.equal(focus.getAttribute('aria-pressed'),'false');
  await api.command('kb-focus');documentsButton.click();assert(!docs.hidden,'Opening a visually closed Documents dock exits focus and reveals it');assert(!root.classList.contains('kb-focused'));
  await api.command('kb-focus');notesButton.click();assert(!dock.hidden,'Opening a visually closed Notes dock exits focus and reveals it');
  const search=d.getElementById('kbSearch');search.focus();await api.command('kb-toggle-documents');assert(docs.hidden);assert.equal(d.activeElement,documentsButton);
  width=620;height=600;top=130;w.dispatchEvent(new w.Event('resize'));await settle();
  assert.equal(root.dataset.kbNarrow,'true');assert.equal(root.style.getPropertyValue('--kb-available-height'),'458px');
  assert.equal(w.getComputedStyle(docs).display,'block','Narrow document dock has one outer scrollport');
  assert.equal(w.getComputedStyle(d.getElementById('kbDocuments')).overflow,'visible','Document rows keep their natural browse height instead of flex-shrinking beneath dock controls');
  assert(!dock.hidden,'Resize retains explicit dock choices');
  // Normal document scroll never changes the sizing anchor or grows the editor.
  scroll=80;top=50;w.dispatchEvent(new w.Event('scroll'));observers.at(-1).callback([]);await settle();assert.equal(root.style.getPropertyValue('--kb-available-height'),'458px');
  height=500;w.dispatchEvent(new w.Event('atlas-display-change'));await settle();assert.equal(root.style.getPropertyValue('--kb-available-height'),'358px');
  root.classList.remove('active');height=700;w.dispatchEvent(new w.Event('resize'));await settle();assert.equal(root.style.getPropertyValue('--kb-available-height'),'358px');
  root.classList.add('active');await api.open();await settle();assert.equal(root.style.getPropertyValue('--kb-available-height'),'558px');
  assert.equal(d.getElementById('kbDrawio'),frame,'Docking/resizing/reopening preserves the editor session');assert.equal(d.getElementById('kbNotes'),notes);assert.equal(notes.value,draft.notes);assert.deepEqual(api.getDocument(),draft);
  assert.equal(messages.length,0,'Presentation changes do not send editor commands, fit, capture or reload');assert.equal(calls.length,beforeCalls,'Presentation changes do not issue API requests');assert.equal(writes.length,0);
  // A pending explicit capture survives a dock toggle and container resize.
  w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};
  const save=api.command('kb-save');await settle();assert(capture);await api.command('kb-toggle-documents');height=720;w.dispatchEvent(new w.Event('resize'));await settle();capture();await save;
  assert.equal(d.getElementById('kbDrawio'),frame);assert.equal(api.getDocument().notes,draft.notes);assert.equal(writes.length,readonly?0:1);
  w.dispatchEvent(new w.Event('pagehide'));assert(observers.every(observer=>observer.nodes.length===0));w.dispatchEvent(new w.Event('pageshow'));await settle();assert(observers.at(-1).nodes.includes(root));
  assert.deepEqual(f.errors,[]);w.close();
 }
 console.log('PASS: compact KB bar, measured PC/narrow/restore height, stable scroll sizing, accessible dock/focus controls, unchanged iframe/drafts/pending capture, cleanup/reopen and readonly local-only behavior');
})().catch(error=>{console.error(error);process.exitCode=1});
