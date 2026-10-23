// All transport and deployment responses are simulated; no host is contacted.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const calls = [], writes = []; let staleResolve;
  const f = await fixture({fetch: async (url, options = {}) => {
    calls.push(String(url));
    const reply = data => ({ok: true, status: 200, headers: {get: () => null}, json: async () => data});
    if (url === '/api/session') return reply({token: 'test'});
    if (url === '/api/health') return reply({identity: 'FIXTURE', users: 0, machines: 0});
    if (url.includes('/palette/desks')) return reply({records: []});
    if (url.startsWith('/api/master/resolve/')) return reply({matched: false});
    if (url.startsWith('/api/search?')) {
      const term = new URL(url, 'http://localhost').searchParams.get('term');
      if (term === 'STALEPC') return new Promise(resolve => {staleResolve = () => resolve(reply({users: [], machines: []}));});
      return reply({users: [], machines: term === 'KNOWNPC' ? [{name: 'KNOWNPC', operational_status: 'Operational'}] : []});
    }
    if (url.startsWith('/api/catalog?')) return reply({available: true, items: [{folder: 'Example App', display_name: 'Example App'}]});
    if (url.startsWith('/api/scripts?')) return reply({scripts: ['setup_i.ps1']});
    if (url === '/api/deploy') {writes.push(JSON.parse(options.body)); return reply({job: 'simulated-job'});}
    if (url === '/api/job/simulated-job') return reply({state: 'complete', events: []});
    return reply({available: false, deployments: [], items: []});
  }});
  await f.console();
  const {w, run} = f, get = id => w.document.getElementById(id);
  if (!get('deploymentPanel').dataset.installed) w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  await sleep(80);
  const query = async term => {get('search').value = term; await run('search()');};
  const target = () => run('S.target');
  const remoteReads = () => calls.filter(url => /^\/api\/(ping|access|disk|overview|preflight|performance|software-tools)/.test(url));
  await query(' missing-pc.example ');
  assert.equal(target(), ''); assert(!get('useHostname').hidden);
  assert(get('unlistedTargetStatus').textContent.includes('MISSING-PC.EXAMPLE'));
  assert.equal(remoteReads().length, 0, 'Offering a hostname does not query it');
  get('useHostname').click(); await sleep(30);
  assert.equal(target(), 'MISSING-PC.EXAMPLE'); assert.equal(get('adminPc').value, target());
  assert.equal(get('deployTarget').textContent, target()); assert(!get('deploymentPanel').hidden);
  assert(get('barState').textContent.includes('not in directory'));
  assert.equal(run('S.machines.length'), 0, 'Direct selection does not create an inventory record');
  assert.equal(writes.length, 0, 'Selecting a target cannot start a deployment');
  assert(!get('deploy').disabled, JSON.stringify({pkg:get('pkg').value,script:get('script').value,disabled:get('script').disabled,text:get('deploy').textContent})); await run('deploy()');
  assert.equal(writes.length, 1); assert.equal(writes[0].computer, 'MISSING-PC.EXAMPLE');
  assert.equal(writes[0].folder, 'Example App'); assert.equal(writes[0].script, 'setup_i.ps1');
  await query('machine: other_pc'); get('useHostname').click(); assert.equal(target(), 'OTHER_PC');
  await query('CANDIDATE'); const oldClick = get('useHostname').onclick;
  get('search').value = 'DIFFERENT'; get('search').dispatchEvent(new w.Event('input', {bubbles: true}));
  assert(get('useHostname').hidden); oldClick(); assert.equal(target(), '');
  const stale = query('STALEPC'); await sleep(5); await query('LATESTPC');
  staleResolve(); await stale; oldClick(); assert.equal(target(), '');
  assert(get('unlistedTargetStatus').textContent.includes('LATESTPC'));
  get('useHostname').click(); assert.equal(target(), 'LATESTPC');
  const edited = query('STALEPC'); await sleep(5);
  get('search').value = 'UNSUBMITTED'; get('search').dispatchEvent(new w.Event('input', {bubbles: true}));
  staleResolve(); await edited; assert(get('useHostname').hidden, 'Editing during lookup cannot reveal an old offer');
  for (const term of ['user:alice', 'person:alice', 'a@example.test', 'first last', '*.example', '-bad', '.bad', 'bad..host', 'x'.repeat(65), "pc';bad"]){
    await query(term); assert.equal(target(), ''); assert(get('useHostname').hidden, term);
  }
  await query('KNOWNPC'); assert.equal(target(), 'KNOWNPC'); assert(get('useHostname').hidden);
  assert(get('unlistedTargetStatus').hidden, 'Inventory matches keep the existing selection path');
  const meta = w.document.createElement('meta'); meta.name = 'atlas-mode'; meta.content = 'viewer'; w.document.head.append(meta);
  run(fs.readFileSync(path.join(root, 'frontend/assets/readonly-console.js'), 'utf8'));
  await sleep(20);
  await query('VIEWER-PC'); get('useHostname').click(); await sleep(30);
  assert.equal(target(), 'VIEWER-PC'); w.AtlasReadOnly.enforce(); assert(get('deploy').disabled);
  const count = writes.length; await run('deploy()'); assert.equal(writes.length, count, 'Read-only transport blocks direct deployment too');
  await sleep(100); assert.equal(f.errors.length, 0, f.errors.join('\n')); w.close();
  console.log('PASS: unlisted hostname selection, real deployment payload, no automatic deployment/scan, prefixes/FQDN, invalid input, stale offers/responses, inventory selection and read-only guards');
})().catch(error => {console.error(error); process.exitCode = 1});
