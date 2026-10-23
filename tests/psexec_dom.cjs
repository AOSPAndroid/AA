// No PsExec executable or remote machine is used by these tests.
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const {fixture,root}=require('./ui_fixture.cjs');
(async()=>{
  let requests=0; const copied=[];
  const f=await fixture({fetch:async()=>{requests++;throw Error('PsExec must make no requests')}});
  const {w,run}=f, get=id=>w.document.getElementById('px'+id);
  run(fs.readFileSync(path.join(root,'frontend/assets/app.js'),'utf8'));
  run('function toast(){}');
  run(fs.readFileSync(path.join(root,'frontend/assets/psexec-catalogue.js'),'utf8'));
  run(fs.readFileSync(path.join(root,'frontend/assets/psexec-commands.js'),'utf8'));
  run(fs.readFileSync(path.join(root,'frontend/assets/console-psexec.js'),'utf8'));
  const {build,commands}=w.AtlasPsExecCommands;
  const options={target:'TESTPC',path:'C:\\Data\\PsExec.exe',shell:'powershell'};
  assert.equal(commands.length,72);
  const netfx=build('netfx3-enable',options).command;
  assert(netfx.includes("'-s'"));assert(netfx.includes("'/FeatureName:NetFx3'"));assert(netfx.includes("'/NoRestart'"));
  assert.equal(get('Path').value,options.path);
  assert(get('Copy').disabled);
  assert(w.document.querySelector('[data-page="psexec"]'));
  run("S.target='TESTPC'; AtlasPsExec.open()");
  assert.equal(get('Target').value,'TESTPC');assert(!get('Copy').disabled);
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)}});
  await get('Copy').onclick();assert.equal(copied[0],build('identity',options).command);
  assert(copied[0].startsWith("& 'C:\\Data\\PsExec.exe' '\\\\TESTPC'"));
  assert.equal(copied[0].split('-accepteula').length-1,1);assert(!copied[0].includes("'-s'"));assert(!copied[0].includes("'-h'"));
  assert(get('EulaNote').textContent.includes('executing a copied command'));
  assert.equal(get('EulaNote').querySelector('a').href,'https://learn.microsoft.com/en-us/sysinternals/license-terms');
  const input=(id,value)=>{get(id).value=value;get(id).dispatchEvent(new w.Event('input'))};
  input('Target','MANUALPC');run("S.target='NEXTPC'; AtlasPsExec.syncTarget(S.target)");
  assert.equal(get('Target').value,'MANUALPC');assert.equal(run('S.target'),'NEXTPC');
  get('Follow').click();assert.equal(get('Target').value,'NEXTPC');
  run("S.target=''; AtlasPsExec.syncTarget('')");assert(get('Copy').disabled);assert(!get('Command').textContent.includes('NEXTPC'));
  input('Target','TESTPC & whoami');assert(get('Copy').disabled);
  input('Target','TESTPC');input('Path','C:\\Data With Spaces\\PsExec64.exe');
  assert(!get('Copy').disabled);get('Shell').value='cmd';get('Shell').dispatchEvent(new w.Event('change'));
  assert(get('Command').textContent.startsWith('"C:\\Data With Spaces\\PsExec64.exe" "\\\\TESTPC"'));
  get('Favourite').click();
  [...get('Categories').children].find(b=>b.textContent==='Favourites').click();
  assert.equal(get('Cards').children.length,1);
  [...get('Categories').children].find(b=>b.textContent==='All').click();
  input('Search','Excel');assert([...get('Cards').querySelectorAll('strong')].some(n=>n.textContent.includes('Excel')));
  input('Search','does-not-exist');assert(get('Cards').textContent.includes('No matches'));
  input('Search','');
  w.document.querySelector('[data-template="restart-service"]').click();assert(get('Copy').disabled);
  get('Elevated').checked=true;get('Elevated').dispatchEvent(new w.Event('change'));
  const service=w.document.getElementById('pxArg-service');service.value='MSSQL$INSTANCE';service.dispatchEvent(new w.Event('input'));
  assert(!get('Copy').disabled);
  assert(get('Command').textContent.includes('"-h"'));
  const payload=get('Command').textContent.match(/"([A-Za-z0-9+/=]+)"$/)[1];
  assert(Buffer.from(payload,'base64').toString('utf16le').includes("'MSSQL$INSTANCE'"));
  service.value="x';Stop-Process -Id 1;#";service.dispatchEvent(new w.Event('input'));assert(get('Copy').disabled);
  w.document.querySelector('[data-template="identity"]').click();assert(!get('Elevated').checked);
  for(const target of ['*','HOST1,HOST2','@targets.txt','-s','HOST\nwhoami','HOST&calc','HOST%PATH%','HOST"','..bad']) assert.throws(()=>build('identity',{...options,target}));
  for(const executable of ['psexec.exe','\\\\server\\share\\PsExec.exe','C:\\%PATH%\\PsExec.exe','C:\\Data\\other.exe','C:\\Data!x\\PsExec.exe']) assert.throws(()=>build('identity',{...options,path:executable}));
  for(const port of ['0','65536','1;2']) assert.throws(()=>build('tcp',{...options,values:{destination:'SERVER01',port}}));
  get('Tool').value='PsInfo';get('Tool').dispatchEvent(new w.Event('change'));
  assert.equal(get('Cards').querySelectorAll('button').length,4);
  get('Cards').querySelector('button').click();assert(get('Elevated').disabled);
  assert(get('Command').textContent.includes('PsInfo64.exe'));
  assert(!get('Command').textContent.includes('-nobanner'));
  assert.equal(get('Command').textContent.split('-accepteula').length-1,1);
  assert(build('pst-tcp',{...options,values:{port:'443'}}).command.includes('TESTPC:443'));
  assert.throws(()=>build('pst-kill',{...options,values:{pid:'4'}}));
  // Parse every generated remote PowerShell script without executing it.
  const scripts=commands.map(c=>{
    const result=build(c.id,{...options,values:{service:'MSSQL$INSTANCE',destination:'SERVER01',port:'445',pid:'1234',session:'1',fileid:'123',account:'DOMAIN\\user'}});
    assert.equal(result.command.split('-accepteula').length-1,1,c.id);
    return result;
  }).filter(c=>c.encoded).map(c=>c.readable);
  const os=require('node:os'), cp=require('node:child_process'), dir=fs.mkdtempSync(path.join(os.tmpdir(),'atlas-psexec-'));
  try {
    const source=path.join(dir,'scripts.json');fs.writeFileSync(source,JSON.stringify(scripts));
    const ps="$ErrorActionPreference='Stop'; $scripts=Get-Content -Raw -LiteralPath '"+source.replace(/'/g,"''")+"' | ConvertFrom-Json; foreach($s in $scripts){$tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($s,[ref]$tokens,[ref]$errors);if($errors.Count){throw ($errors | Out-String)}}";
    if(process.platform==='win32') {const r=cp.spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',ps],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);}
  } finally {
    const resolved=fs.realpathSync(dir), temp=fs.realpathSync(os.tmpdir());
    assert.equal(path.dirname(resolved),temp);assert(path.basename(resolved).startsWith('atlas-psexec-'));
    fs.rmSync(resolved,{recursive:true,force:true});
  }
  assert.equal(requests,0);assert.equal(f.errors.length,0,f.errors.join('\n'));
  w.close();console.log('PASS: PsExec templates, quoting, validation, target isolation, filters, favourites, clipboard and no remote requests.');
})().catch(e=>{console.error(e);process.exit(1)});
