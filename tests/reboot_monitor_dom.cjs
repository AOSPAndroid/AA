const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync('frontend/assets/reboot-monitor.js', 'utf8');
const flush = () => new Promise(r => setImmediate(r));
async function fixture(readonly=false) {
  const dom = new JSDOM(`<head>${readonly ? '<meta name="atlas-mode" content="viewer">' : ''}</head><body><button id="queueToggle"><span id="queueCount" data-deployments="2">2</span></button><aside id="queueDrawer"><p id="rebootMonitorStatus"></p><div id="rebootMonitors"></div></aside></body>`, {runScripts:'outside-only'});
  const calls = [];
  let rows = [];
  dom.window.AtlasClient = {request: async(url,options={}) => {
    calls.push({url,options});
    if(url === '/api/reboot') {
      const target=JSON.parse(options.body).computer;
      rows=[{id:'123',target,state:'waiting_offline',message:'Waiting',events:[{time:'10:00:00',message:'Reply TTL=128'}]}];
      return {job:'123',target};
    }
    if(url.endsWith('/stop')) rows=[];
    return {reboots:rows};
  }};
  dom.window.eval(source);
  await flush();
  return {dom,w:dom.window,calls,setRows:v=>rows=v};
}
(async()=>{
  const f=await fixture();
  await f.w.AtlasReboots.start('PC-A');
  assert(f.w.document.querySelector('#queueDrawer').classList.contains('open'));
  assert.equal(f.w.document.querySelector('#queueCount').textContent,'3');
  assert.match(f.w.document.querySelector('pre').textContent,/TTL=128/);
  f.setRows([{id:'123',target:'PC-A',state:'complete',message:'Complete',events:[]}]);
  await f.w.AtlasReboots.refresh();
  assert.match(f.w.document.querySelector('#rebootMonitors').textContent,/Reboot complete/);
  assert.equal(f.w.document.querySelector('#queueCount').textContent,'2');
  f.setRows([]); await f.w.AtlasReboots.refresh();
  assert.equal(f.w.document.querySelector('#rebootMonitors').children.length,0);
  await f.w.AtlasReboots.start('PC-B');
  f.w.document.querySelector('[data-stop-reboot]').click();await flush();
  assert(f.calls.some(c=>c.url==='/api/reboots/123/stop'));
  f.w.dispatchEvent(new f.w.Event('pagehide'));f.dom.window.close();
  const viewer=await fixture(true);
  await assert.rejects(viewer.w.AtlasReboots.start('PC-A'),/Atlas Admin/);
  await viewer.w.AtlasReboots.refresh();
  assert.equal(viewer.calls.length,0);
  viewer.dom.window.close();
  console.log('PASS: reboot queue opens, combined counts, terminal, completion removal, stop and read-only guards');
})().catch(error=>{console.error(error);process.exit(1)});
