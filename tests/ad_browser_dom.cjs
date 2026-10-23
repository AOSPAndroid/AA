const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
 const w=new JSDOM(fs.readFileSync('frontend/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/installer'}).window;
 w.S={};w.page=()=>{};w.HTMLElement.prototype.scrollIntoView=function(){};let requests=[];
 w.AtlasClient={request:async(url,opts)=>{const p=JSON.parse(opts.body);requests.push(p);return {base:p.base||'DC=test',parent:p.base?'DC=test':'',items:[{name:'Paris',kind:'organizationalUnit',dn:'OU=Paris,DC=test'},{name:'PC01',kind:'computer',account:'PC01$',dn:'CN=PC01,DC=test',guid:'12345678-1234-1234-1234-123456789012'},{name:'App',kind:'group',dn:'CN=App,DC=test'}],more:true}}};
 w.eval(fs.readFileSync('frontend/assets/active-directory.js','utf8'));
 const d=w.document,host=d.querySelector('#adBrowser');w.AtlasAD.command('ad-browser');assert(host.open);
 const style=d.createElement('style');style.textContent=fs.readFileSync('frontend/assets/design-system.css','utf8');d.head.append(style);
 for(const field of host.querySelectorAll('.ad-browser-tools input,.ad-browser-tools select')){
  assert.equal(parseFloat(w.getComputedStyle(field.closest('label')).minWidth),0,'wrapping browser labels can shrink below intrinsic input width');
  assert.equal(parseFloat(w.getComputedStyle(field).minWidth),0,'AD browser fields can shrink to their label');
  assert.equal(w.getComputedStyle(field).width,'100%');
  assert.equal(w.getComputedStyle(field).boxSizing,'border-box');
 }
 await host.querySelector('[data-root]').onclick();assert.equal(requests[0].operation,'children');assert.equal(host.querySelectorAll('tbody tr').length,3);
 const button=text=>[...host.querySelectorAll('button')].find(b=>b.textContent===text);
 await button('Open').onclick();assert.equal(requests.at(-1).base,'OU=Paris,DC=test');
 await host.querySelector('[data-more]').onclick();assert.equal(requests.at(-1).limit,400);
 await button('See members').onclick();assert.equal(requests.at(-1).operation,'members');
 let selected;w.AtlasAD.show=(...args)=>selected=args;button('See groups').onclick();assert.equal(selected[0],'computer');assert.equal(selected[1],'12345678-1234-1234-1234-123456789012');
 w.AtlasReadOnly=true;const n=requests.length;await host.querySelector('[data-root]').onclick();assert.equal(requests.length,n);
 w.close();console.log('PASS: directory navigation, members, incremental results, exact-object group lookup and read-only guard');
})().catch(e=>{console.error(e);process.exit(1)});
