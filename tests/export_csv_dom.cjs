// Actual local export handlers only: no server or remote operations.
const assert = require('node:assert/strict'), fs = require('node:fs');
const {fixture, root} = require('./ui_fixture.cjs');
(async () => {
  const f = await fixture({fetch:async () => { throw Error('CSV export must stay local'); }});
  const {w, run} = f, downloads = [], urls = [], revoked = [];
  // Node Blob exposes text(); URL and click record the generated download.
  w.Blob = Blob;
  w.URL.createObjectURL = blob => { const url='blob:fixture-'+urls.length; urls.push({url,blob}); return url; };
  w.URL.revokeObjectURL = url => revoked.push(url);
  w.HTMLAnchorElement.prototype.click = function () { downloads.push({href:this.href,name:this.download}); };
  for (const file of ['app.js','console-deployment.js']) run(fs.readFileSync(root+'/frontend/assets/'+file,'utf8'));
  run(`S.rows=[{machine:'PC-A',copy:'Complete',launch:'Launched',pid:0,completion:'Unknown',exit_code:-1,details:'  =1+1'}]; exportCsv();`);
  let csv=await urls[0].blob.text();
  assert.equal(downloads[0].name,'bulk.csv');
  assert(csv.includes('"0"'),'numeric zero must survive export');
  assert(csv.endsWith('"\'  =1+1"'),'formula prefixes remain literal after leading spaces');
  assert(csv.includes('"\'-1"'),'signed spreadsheet values cannot become formulas');
  run(`softwareState.softwareTarget='PC-A'; softwareState.currentSoftware=[
    {Name:'=1+1',Version:'+2+2',Publisher:'@example'},
    {Name:'\tformula',Version:'',Publisher:'Line, "quoted"'},
    {Name:'Plain application',Version:0,Publisher:null}
  ]; exportSoftwareCsv();`);
  csv=await urls[1].blob.text();
  assert.equal(downloads[1].name,'PC-A_installed_software_core.csv');
  assert(csv.includes('"\'=1+1","\'+2+2","\'@example"'));
  assert(csv.includes('"\'\tformula","","Line, ""quoted"""'));
  assert(csv.includes('"Plain application","0",""'));
  assert.deepEqual(revoked,urls.map(entry=>entry.url),'every local export releases its Blob URL');
  assert.equal(w.AtlasUI.csvCell('\r\nline'), '"\'\r\nline"');
  assert.equal(w.AtlasUI.csvCell(' "ordinary"'), '" ""ordinary"""');
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
  console.log('PASS: actual bulk/software CSV exports keep formulas literal, preserve zeros/quotes/blanks and revoke Blob URLs without network');
})().catch(error=>{console.error(error);process.exitCode=1});
