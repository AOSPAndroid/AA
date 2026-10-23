// On-demand source fields in the shared renderer; no remote administration.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
(async () => {
  let calls = 0, signal, pending, copied;
  const f = await fixture({fetch: async (url, options) => {
    assert(String(url).startsWith('/api/directory/record?'));
    calls++; signal = options.signal;
    if (pending) await pending;
    return {ok:true,json:async()=>({name:'Example Person',source:'example.xlsx',sheet:'Users',row:2,original_cells:true,fields:[
      {label:'Business unit',header:'u_business_unit',field:'business_unit',value:'Technology',stored_value:'Technology'},
      {label:'Last login time',header:'last_login_time',field:'last_login_time',value:'46265.39671296296',stored_value:'46265.39671296296'},
      {label:'Future field',header:'<img src=x onerror=bad()>',value:'0'},
      {label:'Blank',header:'blank',value:''},
    ]})};
  }});
  const w=f.w, doc=w.document;
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
  doc.querySelector('#kyc').innerHTML = w.AtlasUI.person({canonical_key:'uid:u1',name:'Example Person',department:'Support',business_unit:'Technology',last_login_time:'46265.39671296296'});
  assert(doc.querySelector('#kyc').textContent.includes('Technology'));
  assert(doc.querySelector('#kyc').textContent.includes('2026-08-31 09:31:16'));
  assert.equal(calls,0);
  const button=doc.querySelector('[data-export-kind]');
  // Machine cards deliberately stop bubbling. The inspector must still open.
  button.parentElement.onclick = event => event.stopPropagation();
  button.focus();button.click();await tick();
  let dialog=doc.querySelector('.atlas-export-dialog');
  assert.equal(calls,1);assert.equal(dialog.querySelectorAll('article').length,4);
  assert.equal(dialog.querySelector('img'),null);
  assert(dialog.textContent.includes('Export value: 46265.39671296296'));
  assert(dialog.textContent.includes('Not supplied'));
  const input=dialog.querySelector('input');input.value='future';input.dispatchEvent(new w.Event('input'));
  assert.equal(dialog.querySelectorAll('article').length,1);assert(dialog.querySelector('article').textContent.endsWith('0'));
  dialog.querySelector('.atlas-export-copy').click();await tick();
  assert(copied.includes('Technology'));assert(copied.includes('2026-08-31 09:31:16'));
  dialog.querySelector('header button').click();assert(signal.aborted);assert.equal(doc.activeElement,button);
  let resolve;pending = new Promise(r=>{resolve=r;});button.click();
  dialog=doc.querySelector('.atlas-export-dialog');dialog.close();resolve();await tick();
  assert.equal(doc.querySelector('.atlas-export-dialog'),null);assert.equal(f.errors.length,0);
  w.close();console.log('PASS: full export fields, date conversion, separate business unit, zero/blanks, escaped headers, filtering, copying, deferred requests and cancellation');
})().catch(error=>{console.error(error);process.exit(1);});
