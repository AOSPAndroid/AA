const assert=require('node:assert/strict');
const {fixture}=require('./ui_fixture.cjs');
(async()=>{
 const requests=[],store=new Map();
 const f=await fixture({fetch:async(url,o={})=>{
  requests.push(url);let data={};
  if(url==='/api/session')data={token:'test'};
  else if(url==='/api/knowledge')data={documents:[]};
  else if(url.startsWith('/api/knowledge/')&&o.method==='PUT'){const d=JSON.parse(o.body);data={revision:d.revision+1,updated:new Date().toISOString()};store.set(url,d);}
  else if(url.includes('/catalog'))data={items:[]};else if(url.includes('/scripts'))data={scripts:[]};else if(url.includes('/deployments'))data={deployments:[]};
  return {ok:true,status:200,headers:{get:()=>null},json:async()=>data};
 }});
 await f.console();const {w}=f,A=w.AtlasKnowledge;await A.open();
 const frame=w.document.querySelector('#kbDrawio'),sent=[];
 const emit=(value,origin=w.location.origin,source=frame.contentWindow)=>w.dispatchEvent(new w.MessageEvent('message',{origin,source,data:JSON.stringify(value)}));
 frame.contentWindow.postMessage=(text,origin)=>{assert.equal(origin,w.location.origin);const m=JSON.parse(text);sent.push(m);if(m.action==='export')emit({event:'export',xml:A.getDocument().xml,message:m});};
 emit({event:'configure'},'https://evil.test');assert.equal(sent.length,0);
 emit({event:'configure'});assert.equal(sent.pop().action,'configure');
 emit({event:'init'});assert.equal(sent.pop().action,'load');emit({event:'load'});
 await A.command('kb-process');assert.equal(sent.pop().actionName,'atlasProcess');
 const graph=w.AtlasKnowledgeConverter.fromNotes('Check ping? -> [Yes] Check application\nCheck ping? -> [No] Check network');
 assert.equal(graph.nodes.length,3);assert.equal(graph.edges.length,2);
 const xml=w.AtlasKnowledgeConverter.toXml(graph);A.validateXML(xml);
 emit({event:'autosave',xml});await A.command('kb-save');assert.equal(store.size,1);assert.equal(A.getDocument().revision,1);
 assert.throws(()=>A.validateXML('<!DOCTYPE mxfile><mxfile/>'));assert.throws(()=>A.validateXML('<html/>'));
 assert.equal(typeof w.history.replaceState,'function');
 w.AtlasReadOnly={};w.URL.createObjectURL=()=> 'blob:test';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};
 const count=requests.length;await A.command('kb-save');assert.equal(requests.length,count);
 w.close();console.log('PASS: Draw.io handshake, origin checks, action bridge, XML persistence, revision, local notes conversion, preview no uploads');
})().catch(e=>{console.error(e);process.exitCode=1});
