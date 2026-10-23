const fs=require('fs'),assert=require('assert'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('frontend/index.html','utf8'),code=fs.readFileSync('frontend/assets/active-directory.js','utf8');
(async()=>{
 const d=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost/installer'}),w=d.window;let requests=[];
 w.S={target:'PC01'};w.AtlasClient={request:async(url,options)=>{requests.push(JSON.parse(options.body));return {queried_at:'now',server:'dc',operator:'operator',details:{Enabled:false,Name:'<img src=x>'},groups:[{name:'Test Group',membership:'Primary',category:'Security',scope:'Global',dn:'CN=Test'}],membership_note:'Direct and primary',warnings:[]};}};
 w.eval(code);w.AtlasAD.open();assert.equal(requests.length,0);
 w.document.getElementById('adSelected').click();assert.equal(requests.length,0);assert.equal(w.document.getElementById('adIdentity').value,'PC01');
 await w.document.getElementById('adForm').onsubmit({preventDefault(){}});assert.equal(requests.length,1);assert.equal(requests[0].kind,'computer');
 const result=w.document.getElementById('adResults');assert(result.textContent.includes('false'));assert(result.textContent.includes('Test Group'));assert.equal(result.querySelectorAll('img').length,0);
 const search=result.querySelector('[aria-label="Filter AD groups"]');search.value='missing';search.oninput();assert(result.textContent.includes('No matching groups'));
 w.AtlasReadOnly={};w.AtlasAD.open();assert(w.document.getElementById('adLookup').disabled);await w.document.getElementById('adForm').onsubmit({preventDefault(){}});assert.equal(requests.length,1);w.close();console.log('PASS: manual AD lookup, selected target, literal display, group filter and read-only blocking');
})().catch(e=>{console.error(e);process.exit(1)});
