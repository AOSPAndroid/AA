// The production Packages island against fictional metadata; no SharePoint access.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture}=require('./ui_fixture.cjs');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const response=data=>({ok:true,status:200,json:async()=>data});
// Wait for the island to render instead of trusting a fixed delay on a busy machine.
const until=async(check,ms=5000)=>{for(const end=Date.now()+ms;Date.now()<end;await sleep(20))if(check())return;throw Error('Packages view did not render in time')};
const first={id:'repo:ixExample',folder:'ixExample',short_name:'ixExample',display_name:'Example Browser',state:'Live',packager:'Operator',requester:'Requester',package_id:'EPP123',domain:'Client, Intranet',build:'Windows 11',created:'03/10/2026 09:32',source:'package.csv',imported_at:'2026-10-03T09:32:00Z',coverage:'matched',source_present:true,metadata_present:true};
const pending={...first,id:'data:ixPending',folder:'',short_name:'ixPending',display_name:'Pending Package',state:'Work in Progress',coverage:'metadata-only',source_present:false};
const unnamed={...pending,id:'data:/atlas-raw/example',short_name:'',display_name:'EPP-RAW-123',package_id:'EPP-RAW-123',metadata_note:'Short name not supplied; original record preserved.'};
const unusual={...pending,id:'data:/atlas-raw/path',short_name:'../ixExample',display_name:'<img src=x onerror="window.rawExecuted=true">',metadata_note:'Original short name preserved; no source folder match.'};
(async()=>{
 let requests=[],mode='all',inspect;
 const f=await fixture({fetch:async url=>{
   assert(url.startsWith('/api/package-data?'),'Package browsing makes read requests only');
   const params=new URL(url,'http://localhost').searchParams;requests.push(params);
   const items=params.get('term')==='missing'?[]:params.get('term')==='raw'?[unnamed,unusual]:params.get('state')==='Work in Progress'?[pending]:[first,pending];
   return response({items,total:items.length ? 205 : 0,offset:Number(params.get('offset')),limit:100,states:['Live','Work in Progress'],stats:{source_packages:8000,metadata_packages:2000,matched:1500,source_only:6500,metadata_only:500,ambiguous:0},note:''});
 }});
 const {w,run}=f,d=w.document;w.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};
 const copied=[];w.navigator.clipboard={writeText:async value=>{copied.push(value)}};
 w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden], .page:not(.active)')?[]:[{}]};
 w.AtlasUI.motion.isReduced=()=>true;
 const click=node=>{assert(node);node.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));};
 const choose=async (node,value)=>{Object.getOwnPropertyDescriptor(w[node.tagName==='SELECT'?'HTMLSelectElement':'HTMLInputElement'].prototype,'value').set.call(node,value);node.dispatchEvent(new w.Event(node.tagName==='SELECT'?'change':'input',{bubbles:true}));await sleep(240);};
 run(fs.readFileSync('frontend/assets/atlas-interactions.js','utf8'));await sleep(240);assert.equal(requests.length,0,'A hidden Packages tab does not scan its source');
 d.getElementById('workspace').classList.remove('active');d.getElementById('packages').classList.add('active');await sleep(260);assert.equal(requests.length,1);
 assert(d.querySelector('.package-counts').textContent.includes(w.Number(8000).toLocaleString()+' source packages'));assert.equal(d.querySelectorAll('.package-row-select').length,2);
 click(d.querySelector('.package-row-select'));await sleep(40);assert.match(d.querySelector('.package-detail').textContent,/EPP123/);
 assert(d.querySelector('.package-detail button').getAttribute('aria-label')==='Close package details');
 const beforeCopy=requests.length;
 click(d.querySelector('[data-package-copy="short_name"]'));await sleep(40);assert.equal(copied.at(-1),'ixExample');assert.match(d.querySelector('.package-copy-status').textContent,/Short name copied/);
 click(d.querySelector('[data-package-copy="package_id"]'));await sleep(40);assert.equal(copied.at(-1),'EPP123');assert.equal(requests.length,beforeCopy,'Copying stored identifiers makes no API request');
 w.navigator.clipboard.writeText=async()=>{throw Error('Clipboard denied')};click(d.querySelector('[data-package-copy="short_name"]'));await sleep(40);
 const manual=d.querySelector('dialog.atlas-dialog[open] textarea[readonly]');assert.equal(manual.value,'ixExample');assert.equal(manual.selectionEnd,manual.value.length);manual.closest('dialog').close();
 w.addEventListener('atlas:package-inspect',event=>inspect=event.detail.folder);
 click([...d.querySelectorAll('.package-detail button')].find(node=>node.textContent==='Inspect source scripts'));assert.equal(inspect,'ixExample');
 click([...d.querySelectorAll('button')].find(node=>node.textContent==='Next'));await sleep(240);assert.equal(requests.at(-1).get('offset'),'100');
 await choose(d.querySelector('.package-toolbar select'),'Work in Progress');assert.equal(requests.at(-1).get('offset'),'0');assert.equal(d.querySelectorAll('.package-row-select').length,1);
 click(d.querySelector('.package-row-select'));await sleep(40);assert.match(d.querySelector('.package-detail').textContent,/Metadata only/);assert(![...d.querySelectorAll('.package-detail button')].some(node=>node.textContent==='Inspect source scripts'));
 let copiedLater;w.navigator.clipboard.writeText=()=>new Promise(resolve=>copiedLater=resolve);click(d.querySelector('[data-package-copy="short_name"]'));await sleep(20);
 await choose(d.querySelector('[aria-label="Search package data"]'),'raw');assert.equal(d.querySelectorAll('.package-row-select').length,2);copiedLater();await sleep(40);assert(!d.querySelector('.package-copy-status'),'A late copy cannot report success on a changed selection');
 click(d.querySelector('.package-row-select'));await sleep(40);assert.match(d.querySelector('.package-detail h3').textContent,/EPP-RAW-123/);assert.match(d.querySelector('.package-detail').textContent,/Short name not supplied; original record preserved/);assert(![...d.querySelectorAll('.package-detail button')].some(node=>node.textContent==='Inspect source scripts'));
 click(d.querySelectorAll('.package-row-select')[1]);await sleep(40);assert.match(d.querySelector('.package-detail').textContent,/\.\.\/ixExample/);assert.equal(d.querySelector('.package-detail h3').textContent,unusual.display_name);assert(!d.querySelector('.package-detail img'));assert(!w.rawExecuted);assert(![...d.querySelectorAll('.package-detail button')].some(node=>node.textContent==='Inspect source scripts'));
 await choose(d.querySelector('[aria-label="Search package data"]'),'missing');assert.match(d.querySelector('.package-table-scroll').textContent,/No packages match/);
 const before=requests.length;d.getElementById('packages').classList.remove('active');await sleep(240);assert.equal(requests.length,before,'Leaving Packages aborts further loads');
 assert.deepEqual(f.errors,[]);w.dispatchEvent(new w.Event('pagehide'));w.close();
 // Demo renders stored metadata with the same toolbar and no source inspection.
 let demoItems=[unnamed];const demo=await fixture({fetch:async()=>response({items:demoItems,total:demoItems.length,limit:100,states:['Work in Progress'],stats:{source_packages:0,metadata_packages:demoItems.length,matched:0,source_only:0,metadata_only:demoItems.length,ambiguous:0},note:'Package source available in Admin'})});
 const dw=demo.w,dd=dw.document;dw.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};dw.AtlasReadOnly={reason:'Readonly',read:()=>null};dw.AtlasUI.motion.isReduced=()=>true;
 dd.getElementById('workspace').classList.remove('active');const Observer=dw.MutationObserver;let lateOpened=false;dw.MutationObserver=class extends Observer{observe(target,options){if(target.id==='packages'&&!lateOpened){lateOpened=true;target.classList.add('active');}super.observe(target,options)}};demo.run(fs.readFileSync('frontend/assets/atlas-interactions.js','utf8'));await sleep(260);await until(()=>dd.querySelector('.package-row-select'));
 assert.equal(dd.querySelector('.package-toolbar a').textContent,'Upload package data','Demo keeps the upload link; readonly-console.js greys it out');dd.querySelector('.package-row-select').click();await sleep(40);assert(![...dd.querySelectorAll('.package-detail button')].some(node=>node.textContent==='Inspect source scripts'));
 assert.match(dd.querySelector('.package-detail h3').textContent,/EPP-RAW-123/);assert.match(dd.querySelector('.package-detail').textContent,/Short name not supplied/);
 assert(dd.querySelector('[data-package-copy="short_name"]').disabled);assert(!dd.querySelector('[data-package-copy="package_id"]').disabled,'Read-only stored package IDs remain copyable');
 demoItems=[];[...dd.querySelectorAll('.package-toolbar button')].find(node=>node.textContent==='Refresh').click();await sleep(260);assert.match(dd.querySelector('.package-table-scroll').textContent,/Atlas Admin operator/);assert(!dd.querySelector('.package-table-scroll').textContent.includes('Upload the ServiceNow CSV'));
 assert.deepEqual(demo.errors,[]);dw.dispatchEvent(new dw.Event('pagehide'));dw.close();
 console.log('PASS: production Packages React view loads on demand, filters, paginates, shows metadata/source boundaries, inspects exact folders, and respects Demo');
})().catch(error=>{console.error(error);process.exitCode=1});
