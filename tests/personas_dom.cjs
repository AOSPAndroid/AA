// Simulated responses only: personas are saved in a fake Atlas and installing records the request.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, what = 'Fixture did not settle') {
  for (let i = 0; i < 150; i++) {if (check()) return; await sleep(10)}
  throw Error(what);
}
function server() {
  const state = {personas: [], next: 1, calls: [], problem: null};
  const reply = (data, status = 200) => ({ok: status < 400, status, headers: {get: () => null}, json: async () => data});
  async function fetch(url, options = {}) {
    url = String(url);
    const method = options.method || 'GET', body = options.body ? JSON.parse(options.body) : null;
    state.calls.push({url, method, body});
    const pathname = new URL(url, 'http://127.0.0.1:8892').pathname, query = new URL(url, 'http://127.0.0.1:8892').searchParams;
    if (pathname === '/api/session') return reply({token: 'fixture'});
    if (pathname === '/api/health') return reply({identity: 'FIXTURE', users: 0, machines: 0});
    if (pathname === '/api/catalog') return reply({available: true, total: 2, items: [
      {folder: 'Office', display_name: 'Microsoft Office', version: '16'}, {folder: 'Teams', display_name: 'Teams'}]
      .filter(item => !query.get('term') || item.folder.toLowerCase().includes(query.get('term').toLowerCase()))});
    if (pathname === '/api/scripts') return reply({scripts: query.get('package') !== 'Teams' ? ['setup_i.ps1']
      : state.problem ? ['teams_i.ps1'] : ['teams_i.ps1', 'teams_machine_i.ps1']});
    if (pathname === '/api/personas' && method === 'GET')
      return reply({repository: true, max_items: 40, personas: state.personas.map(p => ({...p, items: p.items.map(i => ({...i, problem: state.problem && i.folder === state.problem.folder ? state.problem.text : null}))}))});
    if (pathname === '/api/personas' && method === 'POST') {
      if (state.personas.some(p => p.name.toLowerCase() === body.name.toLowerCase())) return reply({detail: `A persona named ${body.name} already exists.`}, 409);
      const saved = {...body, name: body.name.trim().replace(/\s+/g, ' '), id: 'a'.repeat(11) + (state.next++), revision: 1};
      state.personas.push(saved);
      return reply(saved);
    }
    const one = pathname.match(/^\/api\/personas\/([a-f0-9]+)(\/install)?$/), persona = one && state.personas.find(p => p.id === one[1]);
    if (one && one[2]) return reply({queue: 'q'.repeat(32), persona: persona.name, computer: body.computer, count: persona.items.length, items: []});
    if (one && method === 'PUT') {
      Object.assign(persona, body, {revision: persona.revision + 1});
      return reply(persona);
    }
    if (pathname.startsWith('/api/deployments/')) return reply({deployments: []});
    if (pathname === '/api/actions') return reply({actions: []});
    return reply({available: false, items: [], deployments: []});
  }
  return {state, fetch};
}
async function open({viewer = false, kits} = {}) {
  const fake = server(), f = await fixture({fetch: fake.fetch});
  if (kits) f.w.localStorage.setItem('atlasDeploymentKits', JSON.stringify(kits));
  if (viewer) {
    const meta = f.w.document.createElement('meta'); meta.name = 'atlas-mode'; meta.content = 'viewer'; f.w.document.head.append(meta);
    f.run(fs.readFileSync(path.join(root, 'frontend/assets/readonly-console.js'), 'utf8'));
  }
  await f.console();
  const get = id => f.w.document.getElementById(id);
  if (!get('deploymentPanel').dataset.installed) f.w.document.dispatchEvent(new f.w.Event('DOMContentLoaded'));
  return {...f, ...fake, get};
}
const posts = state => state.calls.filter(c => c.method !== 'GET' && c.url !== '/api/session');
function select(w, el, value) {
  el.value = value;
  el.dispatchEvent(new w.Event('change', {bubbles: true}));
}
function type(w, el, value) {
  el.value = value;
  el.dispatchEvent(new w.Event('input', {bubbles: true}));
}
function choose(f, target) {
  f.run(`S.target = ${JSON.stringify(target)}`);
  f.get('deployTarget').textContent = target || 'Select a machine';
}

(async () => {
  const f = await open(), {w, run, get, state} = f, d = w.document;
  run('page("personas")');
  assert(get('personas').classList.contains('active'));
  assert.equal(d.querySelector('[data-page="personas"]').getAttribute('aria-current'), 'page');
  await until(() => /No personas yet/.test(get('personaList').textContent), 'Empty list');
  assert(get('personaSave').disabled, 'Nothing to save yet');
  assert(get('personaInstall').disabled);
  assert.match(get('personaInstall').title, /Save the persona first/);

  // Build a persona: two packages from the catalogue, each with the script for its action.
  type(w, get('personaName'), '  New   starter ');
  type(w, get('personaPackageSearch'), 'off');
  await until(() => get('personaResults').querySelector('button'), 'Catalogue results');
  assert.match(get('personaResults').textContent, /Microsoft Office · 16/);
  get('personaResults').querySelector('button').click();
  await until(() => d.querySelector('#personaItems [aria-label="Script for Microsoft Office · 16"]')?.value === 'setup_i.ps1', 'Office script');
  type(w, get('personaPackageSearch'), 'teams');
  await until(() => /Teams/.test(get('personaResults').textContent));
  get('personaResults').querySelector('button').click();
  await until(() => get('personaItems').querySelectorAll('.personas-row').length === 2 && !get('personaSave').disabled, 'Teams added');
  const teamsScript = d.querySelector('[aria-label="Script for Teams"]');
  assert.deepEqual([...teamsScript.options].map(o => o.value), ['teams_i.ps1', 'teams_machine_i.ps1']);
  select(w, teamsScript, 'teams_machine_i.ps1');
  // Moving and removing keep the order the queue will run in.
  d.querySelector('[aria-label="Move up: Teams"]').click();
  assert.deepEqual([...get('personaItems').querySelectorAll('.personas-row b')].map(b => b.textContent), ['Teams', 'Microsoft Office · 16']);
  get('personaFresh').click();
  get('personaSave').click();
  await until(() => state.personas.length === 1 && /Saved New starter/.test(get('personaMessage').textContent), 'Saved');
  assert.deepEqual(posts(state)[0].body, {name: 'New starter', description: '', fresh: true, threads: 8, revision: 0,
    items: [{folder: 'Teams', script: 'teams_machine_i.ps1', action: 'Install'}, {folder: 'Office', script: 'setup_i.ps1', action: 'Install'}]});
  assert.match(get('personaList').textContent, /New starter/);
  assert(get('personaSave').disabled, 'Saved state is clean');

  // One click installs it on the selected machine; the machine field follows Workspace.
  assert.match(get('personaInstall').title, /Enter or select the machine/);
  choose(f, 'PC-ONE');
  await until(() => get('personaMachine').value === 'PC-ONE' && !get('personaInstall').disabled, 'Machine follows selection');
  assert.equal(get('personaInstall').textContent, 'Install on PC-ONE');
  get('personaInstall').click();
  await until(() => posts(state).length === 2, 'Install requested');
  const id = state.personas[0].id;
  assert.deepEqual(posts(state)[1], {url: `/api/personas/${id}/install`, method: 'POST', body: {computer: 'PC-ONE', revision: 1}});
  await until(() => /Started New starter on PC-ONE/.test(get('personaMessage').textContent));
  assert(get('queueDrawer').classList.contains('open'), 'The queue opens to show the run under Ongoing actions');
  assert(!state.calls.some(c => c.url === '/api/queue'), 'The server builds the queue; the browser does not');

  // A typed machine stays until "Use selected"; unsaved edits must be saved before installing.
  type(w, get('personaMachine'), 'PC-TWO');
  choose(f, 'PC-THREE');
  await sleep(20);
  assert.equal(get('personaMachine').value, 'PC-TWO');
  get('personaUseSelected').click();
  assert.equal(get('personaMachine').value, 'PC-THREE');
  type(w, get('personaDescription'), 'First day kit');
  assert(get('personaInstall').disabled);
  assert.match(get('personaInstall').title, /Save your changes before installing/);
  assert(!get('personaSave').disabled);
  w.confirm = () => false;
  get('personaNew').click();
  assert.equal(get('personaDescription').value, 'First day kit', 'Declining keeps the unsaved edits');
  get('personaSave').click();
  await until(() => state.personas[0].revision === 2 && get('personaSave').disabled, 'Updated');
  assert.equal(posts(state).at(-1).method, 'PUT');
  assert.equal(posts(state).at(-1).body.revision, 1);

  // Workspace: pick a persona and install every package on the selected machine.
  await until(() => [...get('personaPick').options].some(o => o.value === id));
  assert.match(get('personaPickInstall').title, /Choose a persona/);
  select(w, get('personaPick'), id);
  assert.equal(get('personaPickInstall').textContent, 'Install 2 packages');
  assert.match(get('personaPickNote').textContent, /Teams · Microsoft Office/);
  assert.equal(w.localStorage.getItem('atlasPersonaPick'), id, 'The last persona is remembered for the next machine');
  get('personaPickInstall').click();
  await until(() => posts(state).at(-1).url.endsWith('/install') && posts(state).at(-1).body.computer === 'PC-THREE', 'Workspace install');
  choose(f, '');
  await sleep(20);
  assert(get('personaPickInstall').disabled);
  assert.match(get('personaPickInstall').title, /Select a machine first/);

  // A package removed from the repository blocks installing until the persona is fixed.
  state.problem = {folder: 'Teams', text: 'No install script named teams_machine_i.ps1'};
  choose(f, 'PC-ONE');
  await run('AtlasPersonas.load()');
  assert.match(get('personaList').textContent, /1 to fix/);
  assert.match(d.querySelector('.personas-row.has-problem').textContent, /No install script named teams_machine_i.ps1/);
  assert(get('personaInstall').disabled);
  assert.match(get('personaInstall').title, /Fix 1 package first: Teams/);
  assert(get('personaPickInstall').disabled);
  // Opening the script list again picks the package's current script; Save clears the problem.
  d.querySelector('[aria-label="Script for Teams"]').dispatchEvent(new w.Event('focus'));
  await until(() => !d.querySelector('.personas-row.has-problem') && !get('personaSave').disabled, 'Script reloaded');
  assert.equal(d.querySelector('[aria-label="Script for Teams"]').value, 'teams_i.ps1');
  state.problem = null;

  // Queue drawer: save the queue as a persona, and queue a persona without starting it.
  get('personaSave').click();
  await until(() => get('personaSave').disabled);
  run(`deploymentQueue = [{computer: "PC-ONE", folder: "C:\\\\Repo\\\\Office", script: "setup_i.ps1", action: "Repair", fresh: false, threads: 12, state: "waiting"}]`);
  get('personaQueueName').value = 'Office repair';
  get('personaSaveQueue').click();
  await until(() => state.personas.length === 2, 'Saved from queue');
  assert.deepEqual(posts(state).at(-1).body.items, [{folder: 'Office', script: 'setup_i.ps1', action: 'Repair'}]);
  assert.equal(posts(state).at(-1).body.threads, 12);
  run('deploymentQueue = []; renderQueue()');
  await until(() => d.querySelectorAll('[data-persona-queue]').length === 2);
  const queueButton = d.querySelector(`[data-persona-queue="${id}"]`);
  assert.equal(queueButton.textContent, 'Add for PC-ONE');
  const before = posts(state).length;
  queueButton.click();
  assert.deepEqual(JSON.parse(run('JSON.stringify(deploymentQueue.map(x => [x.computer, x.folder, x.script, x.action, x.state]))')),
    [['PC-ONE', 'Teams', 'teams_i.ps1', 'Install', 'waiting'], ['PC-ONE', 'Office', 'setup_i.ps1', 'Install', 'waiting']]);
  assert.equal(posts(state).length, before, 'Adding to the queue starts nothing');

  // Names are escaped wherever they are shown.
  state.personas.push({id: 'b'.repeat(12), name: '<img src=x onerror=alert(1)>', description: '', revision: 1, fresh: false, threads: 8, items: [{folder: 'Office', script: 'setup_i.ps1', action: 'Install'}]});
  await run('AtlasPersonas.load()');
  for (const host of ['personaList', 'personaPick', 'personaQueueList']) assert.equal(get(host).querySelector('img'), null, host);
  assert.deepEqual(f.errors, []);
  w.close();

  // Kits from an earlier version's browser storage are imported once, by package name.
  const old = await open({kits: [{name: 'Starter', items: [{folder: 'C:\\Repo\\Office', script: 'setup_i.ps1', action: 'Install', threads: 4}]}]});
  old.run('page("personas")');
  await until(() => !old.get('personaImportKits').hidden, 'Import offered');
  assert.equal(old.get('personaImportKits').textContent, 'Import 1 browser kit');
  old.get('personaImportKits').click();
  await until(() => old.state.personas.length === 1 && old.get('personaImportKits').hidden, 'Imported');
  assert.deepEqual(old.state.personas[0].items, [{folder: 'Office', script: 'setup_i.ps1', action: 'Install'}]);
  assert.equal(old.w.localStorage.getItem('atlasDeploymentKits'), null);
  old.w.close();

  // Demo shows the same page with every change and install greyed out, and asks the network for nothing.
  const demo = await open({viewer: true});
  demo.run('page("personas")');
  await sleep(50);
  if (!demo.w.document.body.classList.contains('atlas-readonly-console')) demo.w.document.dispatchEvent(new demo.w.Event('DOMContentLoaded'));
  await sleep(50);
  choose(demo, 'PC-ONE');
  await sleep(20);
  for (const id of ['personaNew', 'personaSave', 'personaInstall', 'personaPickInstall', 'personaSaveQueue', 'personaFromQueue', 'personaUseSelected', 'personaName'])
    assert(demo.get(id).disabled, id);
  assert.equal(demo.get('personaInstall').getAttribute('aria-disabled'), 'true');
  assert.match(demo.get('personaList').textContent, /saved and installed in Atlas Admin/);
  assert(!demo.state.calls.some(c => c.url.startsWith('/api/personas')), 'Demo never asks for saved personas');
  await sleep(300); // let deferred console startup finish before closing the window
  demo.w.close();
  console.log('PASS: personas are built from the catalogue, saved, installed on the selected or typed machine in one click, blocked when unsaved or broken, queued without starting, imported from old kits, escaped and greyed out in Demo');
})().catch(e => {console.error(e); process.exit(1)});
