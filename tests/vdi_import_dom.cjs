// Supplemental Citrix imports: all API results/files are fictional; no real upload runs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => {let resolve; const promise = new Promise(r => resolve = r); return {promise,resolve};};
const response = (data,status=200) => ({ok:status<400,status,json:async()=>data});
const source = fs.readFileSync('frontend/assets/vdi-data-import.js','utf8');
const report = {
 rows:5,unique:3,before:5,after:6,added:1,changed:2,removed:0,retained:3,
 duplicates:2,matched_users:3,unmatched_users:1,ambiguous_users:1,associations:5,
 invalid_machines:0,warnings:['Usernames are matched; display names are not assumed.'],
 columns:['Name','MachineCatalog','DeliveryGroup','User','SessionState','Extra'],
 unmatched_examples:[{account:'EXAMPLE\\unknown',machine_name:'EXAMPLE\\VDI-A',reason:'No exact username'}],
 ambiguous_examples:[{account:'EXAMPLE\\shared',machine_name:'EXAMPLE\\VDI-B',matches:['user:1','user:2']}],
 collision_examples:[{short_name:'VDI-A',machines:['EXAMPLE\\VDI-A','OTHER\\VDI-A']}],
 machine_examples:[{machine_name:'EXAMPLE\\VDI-A',catalog:'Trading pool',delivery_group:'Office',users:['EXAMPLE\\alice','EXAMPLE\\bob','<img src=x onerror=alert(1)>']},{machine_name:'EXAMPLE\\VDI-B',catalog:'Finance',delivery_group:'Shared',users:[]}],
 removed_examples:['EXAMPLE\\VDI-OLD'],
};
const preview = mode => ({id:'vdi-stage',source:'citrix.csv',full_snapshot:mode,expires_minutes:60,report:{...report,removed:mode?3:0,retained:mode?0:3,after:mode?3:6}});
(async()=>{
 const startup=deferred(),upload=deferred(),staleFailure=deferred();
 const requests=[];let previews=0,saves=0,statuses=0,sessions=0,cancels=0;
 const f=await fixture({html:'frontend/database.html',url:'http://localhost/manage-database#vdi-data-import',fetch:async(url,options={})=>{
  requests.push({url,options});
  assert(url==='/api/session'||url.startsWith('/api/vdi-data/import/'),'VDI uploads never request directory/package/remote operations');
  if(url==='/api/session'){sessions++;return response({token:'fictional-token'});}
  if(url==='/api/vdi-data/import/status'){if(++statuses===1)return startup.promise;return response({count:3,last_import:{source:'citrix.xlsx',at:'2026-10-07'}});}
  if(url.startsWith('/api/vdi-data/import/preview?')){
   previews++;assert.equal(options.method,'POST');assert.equal(options.headers.get('X-Atlas-Token'),'fictional-token');
   assert.equal(options.headers.get('Content-Type'),'application/octet-stream');
   assert.equal(options.headers.get('X-File-Name'),encodeURIComponent(options.body.name));
   if(previews===1)return upload.promise;
   if(previews===5)return staleFailure.promise;
   return response(preview(new URL(url,'http://localhost').searchParams.get('full_snapshot')==='true'));
  }
  if(url==='/api/vdi-data/import/apply/vdi-stage'){
   saves++;assert.equal(options.method,'POST');assert.equal(options.headers.get('Content-Type'),'application/json');
   assert.deepEqual(JSON.parse(options.body),{full_snapshot:true},'Save uses the immutable staged mode');
   return saves===1?response({detail:'VDI data changed. Validate again.'},409):response({count:3,backup:'vdi-only.json.gz'});
  }
  if(url==='/api/vdi-data/import/preview/vdi-stage'&&options.method==='DELETE'){cancels++;return response({ok:true});}
  throw Error('Unexpected request '+url);
 }});
 const {w,run}=f,d=w.document,get=id=>d.getElementById('vdi-data-'+id);
 const select=(name,size=100)=>{Object.defineProperty(get('file'),'files',{configurable:true,value:[{name,size}]});get('file').onchange();};
 assert.equal(new Set([...d.querySelectorAll('[id]')].map(n=>n.id)).size,d.querySelectorAll('[id]').length,'Upload IDs are unique');
 assert.equal(d.querySelectorAll('.atlas-upload-grid > section').length,4);
 assert.match(d.getElementById('vdi-data-import').textContent,/replaces its complete user\s+list/);
 assert(d.querySelector('script[src="/assets/vdi-data-import.js"]'));
 run(source);await sleep(20);
 assert(!get('full').checked&&!get('validate').disabled&&get('apply').disabled&&get('review').hidden);
 await get('validate').onclick();assert.match(get('message').textContent,/Choose a Citrix/);
 select('not-a-workbook.xls');await get('validate').onclick();
 select('too-large.xlsx',51*1024*1024);await get('validate').onclick();assert.match(get('message').textContent,/50 MB/);
 assert.equal(sessions+previews+saves,0,'Rejected files never start uploads or establish a session');
 select('Citrix EMEA.csv');const active=get('validate').onclick();await sleep(20);
 assert(get('file').disabled&&get('full').disabled&&get('validate').disabled&&!get('progress').hidden);
 assert.equal(get('controls').getAttribute('aria-busy'),'true');
 assert(!d.getElementById('validate').disabled&&!d.getElementById('package-data-validate').disabled,'Other upload sections stay independent');
 await get('validate').onclick();assert.equal(previews,1,'Busy state prevents duplicate raw uploads');
 get('full').checked=true;get('full').onchange();assert.match(get('mode').textContent,/omitted VDI machines will be removed/);
 upload.resolve(response(preview(false)));await active;
 assert(get('review').hidden&&get('apply').disabled,'Late preview for the old import mode cannot be saved');
 await get('validate').onclick();assert(!get('review').hidden&&!get('apply').disabled);
 assert.match(get('summary').textContent,/5 source rows.*3 removed.*0 existing VDI records retained/);
 assert.match(get('user-summary').textContent,/5 linked user associations.*3 matched.*1 unmatched.*1 ambiguous/);
 assert.match(get('user-examples').textContent,/EXAMPLE\\alice|EXAMPLE\\unknown/);
 assert.match(get('user-examples').textContent,/2 possible users/);
 assert.match(get('record-examples').textContent,/EXAMPLE\\VDI-A, OTHER\\VDI-A/);
 assert.match(get('columns').textContent,/SessionState, Extra/);
 assert.match(get('examples').textContent,/EXAMPLE\\alice, EXAMPLE\\bob/);
 assert.match(get('examples').textContent,/<img src=x onerror/);assert.equal(get('review').querySelectorAll('img,script').length,0,'Raw export text never becomes HTML');
 assert(!get('removals').hidden);assert.match(get('removed-examples').textContent,/VDI-OLD/);
 await get('apply').onclick();assert.match(get('message').textContent,/VDI data changed/);assert(!get('apply').disabled&&!get('review').hidden,'Rejected save remains reviewable');
 get('full').checked=false;get('full').onchange();assert(get('review').hidden&&get('apply').disabled,'Changing snapshot mode invalidates staged data');
 await get('validate').onclick();assert.match(get('summary').textContent,/0 removed.*3 existing VDI records retained/);assert(get('removals').hidden);
 await get('cancel').onclick();assert.equal(cancels,1);assert(get('review').hidden&&get('apply').disabled);
 select('Citrix EMEA.XLSX');get('full').checked=true;get('full').onchange();await get('validate').onclick();
 // A programmatically changed checkbox without its change event must not alter the staged request.
 get('full').checked=false;await get('apply').onclick();
 assert.equal(saves,2);assert.match(get('message').textContent,/VDI data saved: 3 machines.*vdi-only.json.gz/);
 assert.match(get('status').textContent,/3 VDI machines.*citrix.xlsx/);assert(get('review').hidden&&get('apply').disabled);
 startup.resolve(response({count:999,last_import:null}));await sleep(20);
 assert.match(get('status').textContent,/3 VDI machines/,'Slow startup status cannot overwrite status after saving');
 select('stale.csv');const failing=get('validate').onclick();await sleep(10);select('new.csv');
 staleFailure.resolve(response({detail:'Old source rejected'},400));await failing;
 assert.match(get('message').textContent,/new.csv selected/,'Late errors from an old file cannot overwrite new selection feedback');
 assert(get('review').hidden&&get('apply').disabled);
 const registry=new vm.SourceTextModule(fs.readFileSync('atlas/command-registry.js','utf8'),{context:f.context});await registry.link(()=>{});await registry.evaluate();
 const command=registry.namespace.COMMANDS.find(c=>c.id==='update-vdi');
 assert(command&&!command.viewer&&!command.requiresTarget);assert.equal(registry.namespace.commandUrl('update-vdi','FICT-PC'),'/manage-database#vdi-data-import');
 assert.deepEqual(f.errors,[]);w.close();
 for(const type of ['viewer','preview']){
  let calls=0;const ro=await fixture({html:'frontend/database.html',fetch:async()=>{calls++;throw Error('Read-only uploads must not request APIs');}});
  if(type==='viewer'){const meta=ro.w.document.createElement('meta');meta.name='atlas-mode';meta.content='viewer';ro.w.document.head.append(meta);}else ro.w.AtlasReadOnly={};
  ro.run(source);const control=id=>ro.w.document.getElementById('vdi-data-'+id);
  assert(control('file').disabled&&control('validate').disabled&&control('apply').disabled&&control('full').disabled);
  for(const id of ['validate','apply','cancel'])await control(id).onclick();
  assert.equal(calls,0);assert.match(control('message').textContent,/available in Admin/);assert.deepEqual(ro.errors,[]);ro.w.close();
 }
 console.log('PASS: independent Citrix CSV/XLSX workflow, merge/snapshot review, all user references, escaped original columns, busy/stale protection, save retry, cancellation, command route and read-only guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
