// Simulated responses only: no shares, machines or remote jobs are contacted.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check) {
  for (let i = 0; i < 100; i++) {if (check()) return; await sleep(10)}
  throw Error('Fixture did not settle');
}
(async () => {
  const calls = []; let catalogues = 0, rejectBulk;
  const f = await fixture({fetch: async (url, options = {}) => {
    calls.push({url: String(url), method: options.method || 'GET'});
    const reply = data => ({ok: true, status: 200, headers: {get: () => null}, json: async () => data});
    if (url === '/api/health') return reply({identity: 'FIXTURE', users: 0, machines: 0});
    if (url.startsWith('/api/catalog?')) {
      if (++catalogues === 2) return new Promise((resolve, reject) => {rejectBulk = reject});
      const folder = url.includes('Filtered') ? 'B' : 'A';
      return reply({available: true, items: [{folder, display_name: folder}], total: 1});
    }
    if (url.startsWith('/api/scripts?')) return reply({scripts: ['setup_i.ps1']});
    if (url.startsWith('/api/master/status')) return reply({});
    if (url.includes('/palette/desks')) return reply({records: []});
    if (url.startsWith('/api/deployments/recent')) return reply({deployments: []});
    return reply({available: false, items: [], deployments: []});
  }});
  await f.console();
  const {w, run} = f, get = id => w.document.getElementById(id);
  if (!get('deploymentPanel').dataset.installed) w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  await until(() => get('script').value && !run('packageBusy'));
  assert.equal(catalogues, 1, 'Workspace startup loads a single catalogue');
  assert.equal(calls.filter(c => c.url.startsWith('/api/scripts?')).length, 1);
  assert.equal(get('bulkPkg').options.length, 0, 'Hidden rollout controls do not enumerate the share');
  run('page("bulk")'); await until(() => rejectBulk);
  assert(get('bulkStart').disabled, 'Rollout cannot start while loading');
  run('page("workspace"); page("bulk")'); assert.equal(catalogues, 2, 'Reopening a pending lookup cannot duplicate it');
  rejectBulk(Error('Simulated repository failure'));
  await until(() => !run('bulkBusy'));
  assert.equal(run('bulkCatalogueLoaded'), false, 'A failed lookup remains retryable');
  run('page("workspace"); page("bulk")');
  await until(() => get('bulkScript').value && !run('bulkBusy'));
  assert.equal(catalogues, 3); assert.equal(get('bulkPkg').value, 'A');
  run('page("workspace"); page("bulk")'); assert.equal(catalogues, 3, 'Returning to Rollouts reuses its loaded selection');
  get('bulkSearch').value = 'Filtered'; await run('bulkPackages()');
  assert.equal(get('bulkPkg').value, 'A', 'Filtering retains the selected package');
  assert.equal(get('bulkPkg').options[0].value, 'B');
  assert.equal(get('pkg').value, 'A', 'Workspace and rollout package state remain independent');
  run('page("workspace"); page("bulk")'); assert.equal(catalogues, 4);
  run('refreshConsoleSummary()'); await sleep(30);
  const mutations = [], observer = new w.MutationObserver(records => mutations.push(...records));
  observer.observe(get('deploymentPanel'), {subtree: true, childList: true, attributes: true});
  for (let i = 0; i < 20; i++) run('refreshConsoleSummary()');
  await sleep(30); assert.equal(mutations.length, 0, 'Unchanged summary refreshes do not rewrite the DOM');
  run('S.target="TESTPC"; refreshConsoleSummary()'); await sleep(30);
  assert(mutations.length > 0); assert.equal(get('deploy').textContent, 'Install on TESTPC');
  assert(!get('deploy').disabled, 'Changed state still updates the controls');
  observer.disconnect();
  assert(calls.every(c => c.method === 'GET')); assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: no startup rollout scans, loading/duplicate guards, failure retry, retained independent filters and no repeated summary DOM writes');
})().catch(e => {console.error(e); process.exitCode = 1});
