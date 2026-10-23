const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
const w=new JSDOM('<main><section><h2>CPU PC01</h2><button id="run">Scan CPU</button><button disabled>Reboot</button><label>PID<input id="pid"></label><label>Object type<select><option>Computer</option><option>User</option></select></label><div hidden><button>Hidden action</button></div></section></main>',{runScripts:'outside-only'}).window;
w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden]')?[]:[{}]};
w.HTMLElement.prototype.scrollIntoView=function(){};
let calls=0;w.document.querySelector('#run').onclick=()=>calls++;
w.eval(fs.readFileSync('frontend/assets/shared-ui.js','utf8').split('/* An on-demand index')[1].replace(/^.*?\*\//s,''));
await new Promise(r=>w.document.addEventListener('DOMContentLoaded',r));
const d=w.document,t=d.querySelector('.atlas-reachable-toggle'),p=d.querySelector('.atlas-reachable-panel'),s=p.querySelector('input');
t.click();assert.equal(p.hidden,false);assert(!p.textContent.includes('Hidden action'));assert(!p.textContent.includes('Object typeComputerUser'));assert([...p.querySelectorAll('.atlas-reachable-list button span')].some(n=>n.textContent==='Object type'));assert.equal(p.querySelectorAll('.atlas-action-group').length,1);assert(p.querySelector('button:disabled'));
s.value='scan';s.dispatchEvent(new w.Event('input'));p.querySelector('.atlas-reachable-list button').click();assert.equal(calls,1);assert(p.hidden);
t.click();s.value='pid';s.dispatchEvent(new w.Event('input'));p.querySelector('.atlas-reachable-list button').click();assert.equal(d.activeElement.id,'pid');assert.equal(calls,1);
t.click();s.value='scan';s.dispatchEvent(new w.Event('input'));d.querySelector('#run').disabled=true;p.querySelector('.atlas-reachable-list button').click();assert.equal(calls,1);
d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));assert(p.hidden);assert.equal(d.activeElement,t);
w.close();console.log('PASS: action search, field focus, original handler, hidden/disabled controls, activation recheck and Escape');
})().catch(e=>{console.error(e);process.exit(1)});
