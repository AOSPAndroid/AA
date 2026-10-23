// Who has what: one person against several colleagues, coloured cells, filters and copy of missing groups.
const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
 const w=new JSDOM(fs.readFileSync('frontend/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/installer'}).window;
 let copied;Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
 w.S={target:'PC01'};w.page=()=>{};
 const g=(name,membership='Direct')=>({name,dn:'CN='+name+',OU=Groups,DC=corp,DC=test',description:name+' access',scope:'Global',category:'Security',membership});
 const people={
  newjoiner:[g('APP_Paris'),g('Domain Users','Primary'),g('NJ_Only'),g('Teams_Pilot')],
  bob:[g('APP_Paris'),g('Domain Users','Primary'),g('VPN_Paris'),g('Bloomberg','Nested')],
  carol:[g('APP_Paris'),g('Domain Users','Primary'),g('VPN_Paris'),g('Teams_Pilot','Nested')],
 };
 const asked=[];
 w.AtlasClient={request:async(url,options)=>{const body=JSON.parse(options.body);asked.push(body.identity);
  if(body.identity==='ghost')throw Error('No user matched');
  return {details:{Account:body.identity},groups:people[body.identity],warnings:[],membership_note:'Direct and primary'};}};
 w.eval(fs.readFileSync('frontend/assets/active-directory.js','utf8'));
 w.document.querySelector('#adKind').value='user';w.document.querySelector('#adIdentity').value='newjoiner';
 await w.document.querySelector('#adForm').onsubmit({preventDefault(){}});
 const root=w.document.querySelector('#adResults'),chips=()=>[...root.querySelectorAll('.ad-compare-summary .ad-chip')].map(c=>c.textContent);
 assert.deepEqual(chips(),['3direct','1primary'],'One object: coloured membership counts');
 assert(root.querySelector('.ad-cell-primary'));
 root.querySelector('[aria-label="Compare AD object"]').value='bob, carol ghost';
 await root.querySelector('.ad-group-compare').onsubmit({preventDefault(){}});
 assert.deepEqual(asked,['newjoiner','bob','carol','ghost']);
 assert.match(root.querySelector('.ad-group-compare + p').textContent,/ghost: No user matched/,'A failed lookup is reported; the others still compare');
 assert.deepEqual(chips(),['4differences','2missing from newjoiner','1only newjoiner','1partly shared','2everyone has','6all groups']);
 assert.equal(root.querySelector('[aria-label="Membership comparison"]').value,'diff','A comparison opens on the differences');
 assert.equal(root.querySelectorAll('.ad-groups tbody tr').length,4);
 assert.match(root.querySelector('.ad-hidden-note').textContent,/2 groups everyone has are hidden/);
 root.querySelector('.ad-hidden-note button').click();
 assert.equal(root.querySelector('[aria-label="Membership comparison"]').value,'all');
 assert.deepEqual([...root.querySelectorAll('.ad-groups thead th')].map(th=>th.textContent),['Name','newjoiner','bob','carol','Comparison','Description','Actions']);
 const rows=()=>[...root.querySelectorAll('.ad-groups tbody tr')];
 const line=r=>[r.querySelector('.ad-object-link').textContent,...[...r.querySelectorAll('.ad-cell')].map(c=>c.className.replace('ad-cell ad-cell-','')),r.querySelector('.ad-verdict').textContent];
 assert.deepEqual(rows().map(line),[
  ['VPN_Paris','missing ad-cell-target','has','has','Missing from newjoiner · 2 of 2 have it'],
  ['Bloomberg','missing ad-cell-target','nested','missing','Missing from newjoiner · 1 of 2 have it'],
  ['Teams_Pilot','has','missing','nested','newjoiner + 1 of 2'],
  ['NJ_Only','has','missing','missing','Only newjoiner'],
  ['APP_Paris','has','has','has','Everyone has it'],
  ['Domain Users','primary','primary','primary','Everyone has it'],
 ],'Missing groups come first');
 assert(rows()[0].classList.contains('ad-row-all-others'),'Missing where everyone else has it stands out');
 assert.equal(rows().length,6);
 root.querySelector('.ad-chip-missing').click();
 assert.deepEqual(rows().map(r=>r.querySelector('.ad-object-link').textContent),['VPN_Paris','Bloomberg'],'A chip filters the list');
 assert.equal(root.querySelector('.ad-chip-missing').getAttribute('aria-pressed'),'true');
 root.querySelector('.ad-chip-missing').click();assert.equal(rows().length,6,'Clicking again shows everything');
 const copy=root.querySelector('.ad-copy-missing');assert.equal(copy.textContent,'Copy 2 missing groups');
 await copy.onclick();assert.equal(copied,'VPN_Paris\nBloomberg');
 const view=root.querySelector('[aria-label="Membership comparison"]');view.value='partial';view.onchange();
 assert.deepEqual(rows().map(r=>r.querySelector('.ad-object-link').textContent),['Teams_Pilot']);
 assert.equal(w.document.querySelectorAll('.ad-health-card').length,3,'Health cards for everyone compared');
 root.querySelector('[aria-label="Compare AD object"]').value='a b c d e f';
 await root.querySelector('.ad-group-compare').onsubmit({preventDefault(){}});
 assert.match(root.querySelector('.ad-group-compare + p').textContent,/up to 5/);
 assert.equal(asked.length,4,'Too many names: nothing is queried');
 w.close();console.log('PASS: multi-person group comparison, coloured matrix cells, missing-first order, chip filters, copy missing groups, partial failures and limit');
})().catch(e=>{console.error(e);process.exit(1)});
