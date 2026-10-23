// Simulated responses only: kits are saved in browser storage and never start a deployment.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  for (let i = 0; i < 100; i++) {if (check()) return; await sleep(10)}
  throw Error('Fixture did not settle');
}
async function open(viewer = false) {
  const calls = [];
  const f = await fixture({fetch: async (url, options = {}) => {
    calls.push({url: String(url), method: options.method || 'GET'});
    const reply = data => ({ok: true, status: 200, headers: {get: () => null}, json: async () => data});
    if (url === '/api/health') return reply({identity: 'FIXTURE', users: 0, machines: 0});
    if (url.startsWith('/api/catalog?')) return reply({available: true, items: [{folder: 'Office', display_name: 'Office'}, {folder: 'Teams', display_name: 'Teams'}], total: 2});
    if (url.startsWith('/api/scripts?')) return reply({scripts: ['setup_i.ps1']});
    if (url.startsWith('/api/deployments/recent')) return reply({deployments: []});
    return reply({available: false, items: [], deployments: []});
  }});
  if (viewer) f.w.AtlasReadOnly = true;
  await f.console();
  return {...f, calls, get: id => f.w.document.getElementById(id)};
}
(async () => {
  const {w, run, get, calls, errors} = await open();
  if (!get('deploymentPanel').dataset.installed) w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  await until(() => get('script').value && !run('packageBusy'));
  assert.match(get('kitList').textContent, /No kits yet/);

  // Build a two-package queue for one machine and save it as a kit.
  run('S.target = "PC-ONE"'); run('addQueue()');
  get('pkg').value = 'Teams'; get('action').value = 'Repair'; run('addQueue()');
  get('saveKit').click();
  assert.equal(JSON.parse(w.localStorage.getItem('atlasDeploymentKits') || '[]').length, 0, 'A kit needs a name');
  get('kitName').value = '  New   starter '; get('saveKit').click();
  const kits = JSON.parse(w.localStorage.getItem('atlasDeploymentKits'));
  assert.equal(kits.length, 1); assert.equal(kits[0].name, 'New starter');
  assert.deepEqual(kits[0].items.map(i => [i.folder, i.action]), [['Office', 'Install'], ['Teams', 'Repair']]);
  assert(!('computer' in kits[0].items[0]), 'Kits are machine-independent');

  // Adding the kit for another machine queues every package for that machine only.
  run('deploymentQueue = []; renderQueue()');
  run('S.target = "PC-TWO"'); run('AtlasKits.render()');
  assert.equal(w.document.querySelector('[data-kit-add]').textContent, 'Add for PC-TWO');
  w.document.querySelector('[data-kit-add]').click();
  assert.deepEqual(JSON.parse(run('JSON.stringify(deploymentQueue.map(x => [x.computer, x.folder, x.action, x.state]))')),
    [['PC-TWO', 'Office', 'Install', 'waiting'], ['PC-TWO', 'Teams', 'Repair', 'waiting']]);
  assert.equal(get('queueItems').querySelectorAll('.queue-row').length, 2);
  assert(calls.every(c => c.method === 'GET'), 'Adding a kit never starts deployment');

  // Saving under the same name replaces the kit; no target means the add button is disabled.
  get('kitName').value = 'new STARTER'; get('saveKit').click();
  assert.equal(JSON.parse(w.localStorage.getItem('atlasDeploymentKits')).length, 1);
  run('S.target = ""'); run('AtlasKits.render()');
  assert(w.document.querySelector('[data-kit-add]').disabled);
  w.confirm = () => true; w.document.querySelector('[data-kit-delete]').click();
  assert.equal(JSON.parse(w.localStorage.getItem('atlasDeploymentKits')).length, 0);

  // Names are escaped in the list.
  w.localStorage.setItem('atlasDeploymentKits', JSON.stringify([{name: '<img src=x onerror=alert(1)>', items: [{folder: 'A'}]}]));
  run('AtlasKits.render()');
  assert.equal(get('kitList').querySelector('img'), null);
  assert.deepEqual(errors, []);
  w.close();

  // Demo is read-only: kits cannot be saved or queued.
  const demo = await open(true);
  demo.w.localStorage.setItem('atlasDeploymentKits', JSON.stringify([{name: 'Starter', items: [{folder: 'A'}]}]));
  demo.run('S.target = "PC-ONE"'); demo.run('AtlasKits.render()');
  assert(demo.get('saveKit').disabled);
  assert(demo.w.document.querySelector('[data-kit-add]').disabled);
  await sleep(300); // let deferred console startup finish before closing the window
  demo.w.close();
  console.log('PASS: deployment kits save named machine-independent sets, queue them per target without deploying, replace by name, escape names and stay read-only in Demo');
})().catch(e => {console.error(e); process.exit(1)});
