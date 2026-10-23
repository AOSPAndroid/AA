const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {fixture}=require('./ui_fixture.cjs');
(async()=>{
 const requests=[];const f=await fixture();const {w}=f;
 w.AtlasClient.request=(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}));
 const m=new vm.SourceTextModule(fs.readFileSync('atlas/service-actions.js','utf8'),{context:f.context});await m.link(()=>{});await m.evaluate();
 m.namespace.openRemoteRegistry('pc1');assert.equal(requests.length,0,'opening the action does not enable a service');
 const body=w.document.querySelector('.atlas-dialog-body');const button=body.querySelector('button');assert(body.textContent.includes('PC1'));
 button.click();button.click();assert.equal(requests.length,1);assert.deepEqual(JSON.parse(requests[0].options.body),{computer:'PC1'});assert.equal(requests[0].options.method,'POST');
 requests[0].resolve({state:'Running',start_mode:'Manual'});await new Promise(r=>setImmediate(r));assert(body.textContent.includes('Running'));assert(button.disabled);
 w.AtlasReadOnly={reason:'Viewer'};m.namespace.openRemoteRegistry('pc2');const bodies=w.document.querySelectorAll('.atlas-dialog-body');assert(bodies[1].querySelector('button').disabled);assert.equal(requests.length,1);
 assert.equal(f.errors.length,0);w.close();console.log('PASS: target-specific explicit service action, duplicate prevention, result and viewer restriction');
})().catch(e=>{console.error(e);process.exitCode=1});
