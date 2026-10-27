// Shared map cards for mixed assets. All responses are fictional; no remote operations.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture,root}=require('./ui_fixture.cjs');
(async()=>{
const source=JSON.parse(fs.readFileSync(root+'/atlas/official-data.json','utf8'));
const desk={...source.records[0],kind:'desk',name:'Example Person',occupancy:'assigned'};
const user={id:1,name:'Example Person',user_name:'example'};
const machines=[
 {name:'TESTPC',model_id:'Dell Latitude 7450',model_category:'Laptop',assigned_to:'example',assigned_relationship:1,relationship_group:'Assigned to user'},
 {name:'IPHONE-EXAMPLE',model_id:'APPLE iPhone 13',model_category:'Mobile Device - Handheld',assigned_to:'example',last_used:'2026-10-02 12:00:00',install_status:'In Use',assigned_relationship:1,relationship_group:'Assigned to user'}
];
for(const readonly of [false,true]){
 const requests=[];
 const f=await fixture({html:'atlas/official-index.html',url:'http://127.0.0.1:8892/',fetch:async(url,options={})=>{
  url=String(url);requests.push([url,options.method||'GET']);let data;
  if(url.includes('official-data.json'))data={...source,records:[desk]};
  else if(url==='/api/official/state')data={records:[desk],legacy:[],mappings:{},read_only:readonly};
  else if(url.endsWith('/context'))data={desk,user,candidates:[user],machines,match_method:'confirmed',deployments:[]};
  else if(url.startsWith('/api/catalog')&&!readonly)data={items:[]};
  else if(url==='/api/session')data={token:'fixture'};
  else throw Error('Unexpected request: '+url);
  return{ok:true,json:async()=>data};
 }});
 const {w}=f;
 if(readonly){const meta=w.document.createElement('meta');meta.name='atlas-mode';meta.content='viewer';w.document.head.append(meta);
  f.run(fs.readFileSync(root+'/frontend/assets/readonly-console.js','utf8'));if(!w.document.body.classList.contains('atlas-readonly-console'))w.document.dispatchEvent(new w.Event('DOMContentLoaded'));}
 w.HTMLCanvasElement.prototype.getContext=()=>null;w.requestAnimationFrame=()=>1;w.cancelAnimationFrame=()=>{};
 const api=await f.map('\nexport {operations};');
 const host=w.document.createElement('div');host.id='ops-panel';w.document.querySelector('#detail').replaceChildren(host);
 await api.operations.select(desk);
 const phone=w.document.querySelector('[data-machine-kind=iphone]');
 assert(phone);assert(phone.textContent.includes('iPhone'));assert(phone.textContent.includes('Last used: 2026-10-02'));assert(phone.textContent.includes('In Use'));
 assert.equal(phone.querySelector('.ops-machine').hasAttribute('data-ad-identity'),false,'A phone does not offer computer groups');
 {
  assert(phone.querySelector('input').disabled,'A phone is not a deployment target');
  phone.querySelector('.ops-machine').dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
  const menu=w.document.querySelector('.atlas-ad-context');assert(menu);for(const cmd of ['ad-groups','ad-compare','specs','remote-registry','admin','deploy'])assert(menu.querySelector(`[data-cmd=${cmd}]`).disabled,cmd);assert(!menu.querySelector('[data-cmd=inventory]').disabled);assert(!menu.querySelector('[data-cmd=copy]').disabled);w.AtlasContext.close();
 }
 assert(requests.every(([url])=>!/machine-health|active-directory|remote-registry|deploy/.test(url)));
 assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
}
console.log('PASS: Admin and Demo map cards show mixed asset badges and prevent phone deployment, specifications and computer groups.');
})().catch(e=>{console.error(e);process.exit(1)});
