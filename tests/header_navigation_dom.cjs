const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
for(const file of ['frontend/index.html','atlas/official-index.html']){
 const w=new JSDOM(fs.readFileSync(file,'utf8'),{url:'http://localhost/',runScripts:'outside-only'}).window;
 w.matchMedia=()=>({matches:false,addEventListener(){}});
 w.eval(fs.readFileSync('frontend/assets/shared-ui.js','utf8'));
 await new Promise(r=>w.document.addEventListener('DOMContentLoaded',r));
 await new Promise(r=>setTimeout(r,0));
 const h=w.document.querySelector('header');
 assert(h.classList.contains('atlas-unified-header'));
 assert.deepEqual([...h.querySelectorAll('.atlas-primary-nav a')].map(a=>a.textContent),['Map','Workspace','Knowledge Base']);
 assert(h.querySelector('.atlas-header-menu .atlas-display-mode'));
 const b=w.document.createElement('button');b.textContent='Late action';h.querySelector('.atlas-header-actions').append(b);
 await new Promise(r=>setTimeout(r,0));assert(b.closest('.atlas-header-menu'));
 w.close();
}
console.log('PASS: identical app navigation, shared More menu, display preference and late actions');
})().catch(e=>{console.error(e);process.exit(1)});

