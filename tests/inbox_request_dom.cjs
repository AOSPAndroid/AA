// Live Inbox request suggestions and their Workspace actions, against fictional data only.
// No mailbox, package share or remote machine is contacted.
const assert = require('node:assert/strict'), fs = require('node:fs');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 6000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(20)) if (check()) return;
  throw Error('Fixture did not settle');
}
const response = data => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => data });
const person = { id: 7, name: 'Alex Morgan', full_name: 'Alex Morgan', user_name: 'INBOX0', email: 'alex@example.test' };
const laptop = { name: 'LAPTOP-01', device_kind: 'laptop', windows_remote_supported: 1, model_id: 'Latitude', match_type: 'Assigned' };
const phone = { name: 'PHONE-01', device_kind: 'phone', windows_remote_supported: 0, match_type: 'Assigned' };
const message = { id: 1, sender_name: 'Alex Morgan', sender_address: 'alex@example.test', subject: 'Install request', received_at: '2026-10-15T09:00:00Z', match: { kind: 'email', basis: 'email', user: person, candidates: [person] } };
const analysis = {
  kind: 'software', action: 'Install', search: '',
  packages: [{ folder: 'Example App', display_name: 'Example App', score: 1 }, { folder: 'Odd', display_name: '<img src=x onerror="window.pkgExecuted=true">', score: 0.5 }],
  categories: [{ id: 'slow', label: 'Slow or freezing PC', matched: ['slow'], tools: ['performance', 'health', 'reboot'] }],
  tools: ['performance', 'health', 'reboot', 'user-groups'],
  machines: [{ name: 'NAMED-PC-02', device_kind: 'desktop', windows_remote_supported: 1, linked: false }],
  people: [{ id: 9, full_name: 'Marie Dupont', written: 'Marie Dupont', machines: [{ name: 'LAPTOP-09', device_kind: 'laptop', windows_remote_supported: 1 }, { name: 'LAPTOP-01', windows_remote_supported: 1 }] }],
  knowledge: [{ id: 'kb-slow', title: 'Slow PC runbook' }], warnings: ['Knowledge Base unavailable: test'],
};

(async () => {
  // Part 1: the compiled Live Inbox sends the right action, person, machine and package.
  let detail = { message: { ...message, body: 'Please install Example App. NAMED-PC-02 is slow.' }, match: message.match, machines: [laptop, phone], analysis };
  const f = await fixture({ fetch: async url => {
    const parsed = new URL(url, 'http://localhost');
    if (parsed.pathname === '/api/inbox/control') return response({ configured: true, state: 'running', desired: { running: true, outlook: true, notifications: false } });
    if (parsed.pathname === '/api/inbox/messages') return response({ items: [message], total: 1, newest_id: 1, next_after: 1, has_more: false, watcher: { running: true, state: 'watching' } });
    if (parsed.pathname === '/api/inbox/messages/1') return response(detail);
    return response({});
  } });
  const { w, run } = f, d = w.document, sent = [];
  w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  w.AtlasUI.motion.isReduced = () => true;
  w.addEventListener('atlas:inbox-action', event => sent.push(JSON.parse(JSON.stringify(event.detail))));
  run(fs.readFileSync('frontend/assets/atlas-interactions.js', 'utf8'));
  d.getElementById('workspace').classList.remove('active'); d.getElementById('inbox').classList.add('active');
  await until(() => d.querySelector('.inbox-request-card [data-package]'));
  const card = d.querySelector('.inbox-request-card');
  assert.match(card.querySelector('[data-request-kind]').textContent, /Software request · Install/);
  assert.match(card.textContent, /Slow or freezing PC/);
  assert.equal(card.querySelector('img'), null, 'Package names are escaped');
  const target = card.querySelector('select');
  assert.deepEqual([...target.options].map(o => o.value), ['NAMED-PC-02', 'LAPTOP-01', 'LAPTOP-09'], "Named machine first; inventory-only phone excluded; then PCs of people named, once each");
  assert.match(target.options[2].textContent, /LAPTOP-09 · Marie Dupont/);
  card.querySelector('[data-package="Example App"] button').click();
  assert.deepEqual(sent.at(-1), { action: 'deploy', machine: 'NAMED-PC-02', user: person, pkg: analysis.packages[0], deployAction: 'Install' });
  Object.getOwnPropertyDescriptor(w.HTMLSelectElement.prototype, 'value').set.call(target, 'LAPTOP-01');
  target.dispatchEvent(new w.Event('change', { bubbles: true }));
  await until(() => target.value === 'LAPTOP-01');
  [...card.querySelectorAll('[data-package="Example App"] button')].find(b => b.textContent === 'Add to queue').click();
  assert.equal(sent.at(-1).action, 'queue'); assert.equal(sent.at(-1).machine, 'LAPTOP-01');
  card.querySelector('[data-tool-suggestion="performance"]').click();
  assert.deepEqual([sent.at(-1).action, sent.at(-1).machine], ['performance', 'LAPTOP-01']);
  card.querySelector('[data-tool-suggestion="user-groups"]').click();
  assert.equal(sent.at(-1).user.user_name, 'INBOX0');
  [...card.querySelectorAll('button')].find(b => b.textContent === 'Slow PC runbook').click();
  assert.deepEqual(sent.at(-1), { action: 'knowledge', document: 'kb-slow' });
  assert.match(card.textContent, /Knowledge Base unavailable: test/);
  const named = d.querySelector('[data-mentioned-machine="NAMED-PC-02"]');
  assert.match(named.textContent, /Named in message/);
  [...named.querySelectorAll('button')].find(b => b.textContent === 'Reboot…').click();
  assert.deepEqual([sent.at(-1).action, sent.at(-1).machine], ['reboot', 'NAMED-PC-02']);
  assert.match(d.querySelector('.inbox-devices:not([aria-label]) li:last-child').textContent, /Inventory only/, 'Phones get no Windows actions');
  assert.equal(w.pkgExecuted, undefined);
  assert.deepEqual(f.errors, []);
  w.close();

  // Part 2: the console handler opens the normal tools and never deploys by itself.
  const calls = [];
  const g = await fixture({ fetch: async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || 'GET' });
    if (url.startsWith('/api/user/')) return response({ user: person, machines: [laptop] });
    if (url.startsWith('/api/catalog')) return response({ available: true, items: [{ folder: 'Other', display_name: 'Other' }], total: 1 });
    if (url.startsWith('/api/scripts?')) return response({ scripts: url.includes('Repair') ? ['setup_r.ps1'] : ['setup_i.ps1'] });
    return response({ deployments: [], items: [] });
  } });
  await g.console();
  const x = g.w, get = id => x.document.getElementById(id), actions = x.AtlasInboxActions;
  if (!get('deploymentPanel').dataset.installed) x.document.dispatchEvent(new x.Event('DOMContentLoaded'));
  await sleep(50);
  await actions.run({ action: 'deploy', user: person, machine: 'LAPTOP-01', pkg: { folder: 'Example App', display_name: 'Example App' }, deployAction: 'Repair' });
  assert.equal(g.run('S.target'), 'LAPTOP-01'); assert.equal(g.run('S.user.id'), 7);
  assert.deepEqual([get('pkg').value, get('action').value, get('script').value], ['Example App', 'Repair', 'setup_r.ps1']);
  assert(get('workspace').classList.contains('active'));
  await actions.run({ action: 'queue', user: person, machine: 'LAPTOP-01', pkg: { folder: 'Example App', display_name: 'Example App' }, deployAction: 'Install' });
  assert.deepEqual(JSON.parse(g.run('JSON.stringify(deploymentQueue.map(x => [x.computer, x.folder, x.action, x.script]))')), [['LAPTOP-01', 'Example App', 'Install', 'setup_i.ps1']]);
  assert(get('queueDrawer').classList.contains('open'));
  const reboots = []; x.AtlasReboots.start = async pc => reboots.push(pc);
  x.confirm = () => false; await actions.run({ action: 'reboot', user: person, machine: 'LAPTOP-01' });
  assert.deepEqual(reboots, [], 'Cancelled reboot does nothing');
  x.confirm = () => true; await actions.run({ action: 'reboot', user: person, machine: 'LAPTOP-01' });
  assert.deepEqual(reboots, ['LAPTOP-01']);
  const shown = []; x.AtlasAD = { show: (...args) => shown.push(args) };
  await actions.run({ action: 'user-groups', user: person });
  await actions.run({ action: 'machine-groups', user: person, machine: 'LAPTOP-01' });
  assert.deepEqual(shown, [['user', 'INBOX0'], ['computer', 'LAPTOP-01']]);
  g.run("S.machines.push({ name: 'PHONE-01', device_kind: 'phone', windows_remote_supported: 0 })");
  await assert.rejects(actions.run({ action: 'deploy', user: person, machine: 'PHONE-01', pkg: { folder: 'Example App' } }), /inventory only/);
  assert(calls.every(c => c.method === 'GET'), 'No deployment, queue or reboot request was sent by Atlas itself');
  x.AtlasReadOnly = { reason: 'Read only' };
  await assert.rejects(actions.run({ action: 'target', user: person, machine: 'LAPTOP-01' }), /Atlas Admin/);
  await sleep(300);
  x.close();
  console.log('PASS: Live Inbox request card sends person/machine/package actions, named machines first, escaping, inventory-only guard; handler selects package and script, queues without deploying, confirms reboots, opens AD groups and refuses in Demo');
})().catch(error => { console.error(error); process.exit(1); });
