// Run with node --experimental-vm-modules. Actual DOM and event handlers; local fixture only, no live administration.
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),vm=require('node:vm');
const {JSDOM,VirtualConsole}=require(process.env.JSDOM_MODULE||'jsdom');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:8892';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await sleep(30)}throw Error('Condition timed out')}
(async()=>{
 const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'frontend/index.html'),'utf8'),{url:base+'/installer',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc}),w=dom.window;
 w.fetch=(url,o)=>fetch(new URL(url,base),o);w.confirm=()=>false;w.matchMedia=()=>({matches:false,addEventListener(){}});
 w.HTMLElement.prototype.scrollIntoView=function(){};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 w.AtlasHealth={cancel(){},badges(){return ''},mount(){return Promise.resolve()},quick(){return Promise.resolve()},report(){return []}};
 const context=dom.getInternalVMContext(),modules=new Map();
 async function moduleFor(spec){
  const file=path.join(root,'atlas',path.basename(spec.split(/[?#]/,1)[0]));
  if(modules.has(file))return modules.get(file);
  const promise=(async()=>{const mod=new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});await mod.link(moduleFor);await mod.evaluate();return mod})();modules.set(file,promise);return promise;
 }
 w.Headers=Headers;w.AbortController=AbortController;
 for(const file of ['client.js','shared-ui.js'])vm.runInContext(fs.readFileSync(path.join(root,'frontend/assets',file),'utf8'),context);
 vm.runInContext(require('./ui_fixture.cjs').consoleSource(),context,{importModuleDynamically:moduleFor});
 vm.runInContext(fs.readFileSync(path.join(root,'frontend/assets/remote-software.js'),'utf8'),context);
 await until(()=>w.document.querySelector('#identity').textContent==='LOCAL UI TEST');
 await until(()=>w.document.querySelector('#pkg').value==='Example App');
 assert.equal(w.document.querySelector('.header-actions .atlas-motion-toggle'),null);
 await vm.runInContext("runSharedCommand('animations')",context);assert(w.AtlasUI.motion.isReduced());assert.equal(w.localStorage.getItem('atlas-motion'),'reduce');
 await vm.runInContext("runSharedCommand('animations')",context);assert(!w.AtlasUI.motion.isReduced());assert.equal(w.localStorage.getItem('atlas-motion'),'full');
 await vm.runInContext("runSharedCommand('contacts')",context);
 assert(w.document.querySelector('.atlas-site-info'));
 assert.equal(w.document.querySelectorAll('.site-contact').length,4);
 assert.equal(w.location.pathname,'/installer');
 w.document.querySelector('.atlas-site-info').close();
 for(const page of ['admin','bulk','personas','history','terminal','psexec','workspace']){w.document.querySelector(`[data-page="${page}"]`).click();assert(w.document.querySelector('#'+page).classList.contains('active'));assert(w.document.querySelector('#pageTitle').textContent.trim().length>0)}
 assert.equal(w.document.querySelectorAll('nav .nav-label').length,11); // includes Live Inbox, Clipboard and Personas
 assert(!w.document.querySelector('[data-page="knowledge"]'));assert(w.document.querySelector('[data-section="knowledge"]'));
 w.document.querySelector('[data-section="knowledge"]').click();assert(w.document.querySelector('#knowledge.active'));assert.equal(w.document.querySelector('#pageTitle').textContent,'Knowledge Base');vm.runInContext('page("workspace")',context);
 assert(w.document.querySelector('main > #active-directory.page'));
 await vm.runInContext("runSharedCommand('packages')",context);assert(w.document.querySelector('#packages.active'));w.document.querySelector('#openCatalogue').click();assert(w.document.querySelector('#packages.active'));
 vm.runInContext('page("active-directory")',context);assert(w.document.querySelector('#active-directory.active'));vm.runInContext('page("workspace")',context);
 for(const [toggle,drawer,close] of [['queueToggle','queueDrawer','closeQueue'],['deploymentsToggle','deploymentsDrawer','closeDeployments']]){w.document.querySelector('#'+toggle).click();assert(w.document.querySelector('#'+drawer).classList.contains('open'));w.document.querySelector('#'+close).click();assert(!w.document.querySelector('#'+drawer).classList.contains('open'))}
 // Disclosure clicks, panel exclusivity, Escape, and focus restoration.
 const q=w.document.querySelector('#queueToggle'),live=w.document.querySelector('#deploymentsToggle');
 q.focus();q.click();await sleep(20);assert.equal(q.getAttribute('aria-expanded'),'true');
 live.click();await sleep(20);assert(!w.document.querySelector('#queueDrawer').classList.contains('open'));assert.equal(live.getAttribute('aria-expanded'),'true');
 live.click();await sleep(20);assert.equal(live.getAttribute('aria-expanded'),'false');assert.equal(w.document.activeElement,q);
 q.click();await sleep(20);w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await sleep(20);assert.equal(q.getAttribute('aria-expanded'),'false');
 const trigger=w.document.querySelector('#targetActions .toolmenu-btn');trigger.click();assert.equal(trigger.getAttribute('aria-expanded'),'true');trigger.click();assert.equal(trigger.getAttribute('aria-expanded'),'false');trigger.click();w.document.body.click();assert.equal(trigger.getAttribute('aria-expanded'),'false');
 assert.equal(w.document.querySelector('nav [aria-current="page"]').dataset.page,'workspace');
 assert.equal(w.document.querySelector('#pageTitle').textContent,'Workspace');
 await until(()=>w.document.querySelector('.atlas-palette-mount')?.shadowRoot);
 const palette=w.document.querySelector('.atlas-palette-mount').shadowRoot,commandButton=palette.querySelector('#atlas-commands'),commandSearch=palette.querySelector('input');
 commandButton.focus();commandButton.click();await until(()=>palette.querySelector('dialog').open);
 await sleep(100);commandSearch.value='> history';commandSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(palette.querySelectorAll('[role=option]').length,1);commandSearch.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await sleep(30);assert(w.document.querySelector('#history').classList.contains('active'));assert.equal(palette.activeElement,commandButton);
 w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true}));await until(()=>palette.querySelector('dialog').open);await sleep(100);commandSearch.value='> zzzznonexistent';commandSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(palette.querySelectorAll('[role=option]').length,0);palette.querySelector('.palette-close').click();
 w.document.querySelector('#openShortcuts').click();assert(!w.document.querySelector('#shortcutHelp').classList.contains('hidden'));w.document.querySelector('#closeShortcutHelp').click();
 w.document.querySelector('[data-page="workspace"]').click();
 const users=await(await fetch(base+'/api/search?term='+encodeURIComponent(process.env.ATLAS_TEST_USER||'smith'))).json();assert(users.users.length);
 const search=w.document.querySelector('#search');search.value=users.users[0].user_name;search.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
 await until(()=>w.document.querySelector('#kyc .usercard'));assert(w.document.querySelector('.lookup-column #kyc .usercard'));
 assert(w.document.querySelector('.deployment-panel #deploy'));
 const ids=[...w.document.querySelectorAll('[id]')].map(e=>e.id);assert.equal(ids.length,new Set(ids).size,'unique control IDs');
 await sleep(200);assert.equal(errors.length,0,errors.join('\n'));console.log('PASS: console initialization, labelled navigation, eight sidebar pages and section navigation, queue/live drawers, real directory lookup, new layout anchors, unique IDs');w.close();
})().catch(e=>{console.error(e);process.exit(1)});
