const {JSDOM}=require('jsdom'),fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 for(const readonly of [false,true]){
  const dom=new JSDOM(fs.readFileSync('frontend/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/installer'}),w=dom.window,calls=[];
  w.AtlasReadOnly=readonly;w.AtlasClient={sessionToken:async()=> 'test',request:async(url,options)=>{calls.push([url,options]);if(url.endsWith('/run'))return {};return {state:'complete',target:'TEST',account:'TEST',output:'done',exit_code:0};}};
  w.eval(fs.readFileSync('frontend/assets/local-terminal.js','utf8'));
  const get=id=>w.document.getElementById('term'+id);
  assert(get('Mode').closest('.term-configuration'));
  assert.equal(get('Import').closest('[role="group"]').getAttribute('aria-label'),'Script files');
  assert.equal(get('Run').closest('[role="group"]').getAttribute('aria-label'),'Execution');
  assert.equal(get('Copy').closest('[role="group"]').getAttribute('aria-label'),'Output');
  assert(w.document.querySelector('#terminal h2'));
  assert.equal(get('Run').disabled,readonly);
  get('Mode').value='script';get('Mode').onchange();get('Code').value='Get-Date\nGet-Location';get('Code').setSelectionRange(0,8);
  await get('Selection').onclick();await new Promise(r=>setTimeout(r,20));
  if(readonly)assert.equal(calls.length,0);else {assert.equal(JSON.parse(calls[0][1].body).code,'Get-Date');assert.equal(JSON.parse(calls[0][1].body).shell,'powershell');assert.equal(get('Output').textContent,'done');assert.equal(get('Run').disabled,false);}
  w.close();
 }
 console.log('PASS: selected-script execution, streamed result and read-only controls');
})().catch(e=>{console.error(e);process.exit(1)});
