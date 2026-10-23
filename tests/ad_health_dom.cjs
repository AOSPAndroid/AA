const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
 const w=new JSDOM(fs.readFileSync('frontend/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/installer'}).window;
 w.S={target:'PC01'};w.page=()=>{};let copied,calls=0;
 Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async s=>copied=s}});
 const a={kind:'user',queried_at:'2026-10-01T09:00:00Z',server:'dc.test',details:{Account:'alice',Enabled:true,'Locked out':true,'Password expired':true,'Account expiration':'2026-09-01T00:00:00Z','OU / parent container':'OU=Paris,DC=test'},groups:[{name:'NestedApp',dn:'CN=NestedApp',membership:'Nested'}],warnings:[],nested_complete:true};
 const b={...a,details:{Account:'bob',Enabled:false,'Locked out':false,'Password expired':false,'OU / parent container':'OU=London,DC=test'},groups:[],nested_complete:false,warnings:['Nested lookup partial']};
 w.AtlasClient={request:async()=>++calls===1?a:b};w.document.querySelector('#adKind').value='user';
 w.eval(fs.readFileSync('frontend/assets/active-directory.js','utf8'));
 await w.document.querySelector('#adForm').onsubmit({preventDefault(){}});
 assert(w.document.querySelector('.ad-health-strip').textContent.includes('Locked'));assert(w.document.querySelector('.ad-health-strip').textContent.includes('Expired'));
 w.document.querySelector('[aria-label="Compare AD object"]').value='bob';await w.document.querySelector('#adResults form').onsubmit({preventDefault(){}});
 assert.equal(w.document.querySelectorAll('.ad-health-card').length,2);assert(w.document.querySelector('.ad-property-different'));assert(w.document.querySelector('#adOverview').textContent.includes('Partial'));
 await w.document.querySelector('#adCopySummary').onclick();assert(copied.includes('alice')&&copied.includes('bob'));assert(copied.includes('[Nested] NestedApp'));assert(copied.includes('Only alice (not bob): NestedApp'));assert(copied.includes('dc.test'));
 w.document.querySelector('[aria-label="Compare AD object"]').oninput();assert.equal(w.document.querySelectorAll('.ad-health-card').length,1);
 await w.document.querySelector('#adCopySummary').onclick();assert(!copied.includes('bob'));
 w.document.querySelector('#adKind').value='computer';await w.document.querySelector('#adForm').onsubmit({preventDefault(){}});assert(w.document.querySelector('.ad-health-strip').textContent.includes('Machine password changed'));assert(!w.document.querySelector('.ad-health-strip').textContent.includes('Lockout'));
 w.close();console.log('PASS: health flags, property differences, nested evidence, full support copy and stale comparison clearing');
})().catch(e=>{console.error(e);process.exit(1)});
