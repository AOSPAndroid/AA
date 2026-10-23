const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync('frontend/assets/action-widgets.js','utf8');
const flush=()=>new Promise(r=>setImmediate(r));
async function fixture(viewer=false){
 const dom=new JSDOM(`<head>${viewer?'<meta name="atlas-mode" content="viewer">':''}</head><body><button id="queueToggle"><span id="queueCount" data-deployments="2" data-reboots="1"></span></button><aside id="queueDrawer"><p id="actionWidgetsStatus"></p><div id="actionWidgets"></div></aside></body>`,{runScripts:'outside-only'});
 const calls=[];let rows=[{id:'psexec-1',title:'PsExec',target:'PC-A',state:'running',message:'Running',log:'<script>bad()</script>',controls:[{label:'Stop local session',url:'/api/psexec/runs/1/stop'}]}];
 dom.window.AtlasClient={request:async(url,options={})=>{calls.push({url,options});return {actions:rows}}};
 dom.window.eval(source);await flush();
 return {dom,w:dom.window,calls,setRows:value=>rows=value};
}
(async()=>{
 const f=await fixture();await f.w.AtlasActions.refresh();
 assert.equal(f.w.document.querySelector('#queueCount').textContent,'4');
 assert.equal(f.w.document.querySelectorAll('#actionWidgets script').length,0);
 assert.match(f.w.document.querySelector('pre').textContent,/<script>/);
 f.w.document.querySelector('[data-action-control]').click();await flush();
 assert(f.calls.some(c=>c.url==='/api/psexec/runs/1/stop'&&c.options.method==='POST'));
 f.setRows([]);await f.w.AtlasActions.refresh();
 assert.equal(f.w.document.querySelector('#queueCount').textContent,'3');
 assert.match(f.w.document.querySelector('#actionWidgets').textContent,/No ongoing/);
 let stopped=false;
 f.w.AtlasActions.put({id:'diagnostics',title:'Capture',state:'running',controls:[{label:'Stop',run:()=>stopped=true}]});
 f.w.document.querySelector('[data-action-control]').click();await flush();assert(stopped);
 f.w.dispatchEvent(new f.w.Event('pagehide'));f.dom.window.close();
 const viewer=await fixture(true);await viewer.w.AtlasActions.refresh();assert.equal(viewer.calls.length,0);viewer.dom.window.close();
 console.log('PASS: activity widgets, combined count, safe output, supported controls, cleanup and read-only guard');
})().catch(error=>{console.error(error);process.exit(1)});
