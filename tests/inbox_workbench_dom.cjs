// Live Inbox request tools: health, performance, AD groups and deployment run beside the message
// without switching to Workspace; the deployment panel moves in and back; "Back to Live Inbox"
// after a Live Inbox button opens another page; Workspace is still used outside Live Inbox.
const assert = require('node:assert/strict');
const { fixture } = require('./ui_fixture.cjs');
const { profileSnapshot } = require('./performance_sample.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 4000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(15)) if (check()) return;
  throw Error('Timed out: ' + label);
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
const person = { id: 7, full_name: 'Alex Morgan', user_name: 'INBOX0', email: 'alex@example.test' };
const laptop = { name: 'LAPTOP-01', device_kind: 'laptop', windows_remote_supported: 1 };
const sample = { ...profileSnapshot('overview'), computer: 'LAPTOP-01' };
const marie = { id: 9, full_name: 'Marie Dupont', user_name: 'X09', email: 'marie@example.test', written: 'DUPONT Marie', machines: [{ name: 'LAPTOP-09', windows_remote_supported: 1 }] };
const group = (name, membership = 'Direct') => ({ name, membership, category: 'Security', scope: 'Global', dn: 'CN=' + name });
const ad = (kind, identity) => ({ kind, queried_at: '2026-10-21T09:00:00Z', server: 'dc.example.test', operator: 'EXAMPLE\\operator', warnings: [], nested_complete: true,
  details: kind === 'user' ? { Account: identity, Name: identity === 'X09' ? 'Marie Dupont' : 'Alex Morgan', Enabled: true, 'Locked out': identity === 'INBOX0', 'Password expired': false } : { Name: identity, Enabled: true },
  groups: identity === 'X09' ? [{ ...group('App-Outlook'), description: 'Outlook users' }, group('APP-Visio'), group('VPN-Users', 'Nested'), group('Domain Users', 'Primary')]
    : [group('Paris-Printers', 'Nested'), { ...group('App-Outlook'), description: 'Outlook users' }, group('Domain Users', 'Primary')] });
const people = { 7: { user: { ...person, department: 'Client Services', location: 'Paris', manager: 'Jo Lead' }, machines: [laptop, { name: 'PHONE-01', device_kind: 'phone', windows_remote_supported: 0 }], desks: [{ id: '04R019086', floor: 4, match: 'confirmed account link' }] },
  9: { user: marie, machines: marie.machines, desks: [] }, 8: { user: { id: 8, full_name: 'Sam Lee', user_name: 'INBOX1' }, machines: [], desks: [] } };

(async () => {
  const calls = [], pendingLookups = new Map();
  const f = await fixture({ fetch: async (url, options = {}) => {
    url = String(url); const method = options.method || 'GET', body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url, method, body });
    if (url === '/api/session') return response({ token: 'fixture' });
    if (url === '/api/health') return response({ identity: 'EXAMPLE\\operator', ok: true });
    if (url.startsWith('/api/user/')) return response({ user: person, machines: [laptop] });
    if (url.startsWith('/api/catalog')) return response({ available: true, items: [{ folder: 'Example App', display_name: 'Example App' }], total: 1 });
    if (url.startsWith('/api/scripts?')) return response({ scripts: url.includes('Repair') ? ['setup_r.ps1'] : ['setup_i.ps1'] });
    if (url.startsWith('/api/machine-health/')) { const [, , , pc, metric] = url.split('/'); return response({ computer: pc, metric, state: 'ready', data: { free_bytes: 50 * 1024 ** 3, total_bytes: 256 * 1024 ** 3, uptime_seconds: 3600 }, checked_at: '2026-10-21T09:00:00Z' }); }
    if (url.startsWith('/api/performance/LAPTOP-01?kind=overview')) return response(sample);
    if (url === '/api/active-directory/lookup') return response(ad(body.kind, body.identity));
    if (url.startsWith('/api/inbox/person/')) return response(people[url.split('/').at(-1)]);
    if (url.startsWith('/api/search?term=') && pendingLookups.has(decodeURIComponent(url.split('term=')[1]))) return pendingLookups.get(decodeURIComponent(url.split('term=')[1]));
    if (url.startsWith('/api/search?term=')) return response(url.endsWith('=sam') ? { users: [{ id: 8, full_name: 'Sam Lee', user_name: 'INBOX1' }, { id: 12, full_name: 'Sam Green', user_name: 'X12' }], machines: [] }
      : url.endsWith('=laptop-09') ? { users: [], machines: [{ name: 'LAPTOP-09', windows_remote_supported: 1 }] } : { users: [], machines: [] });
    if (url === '/api/knowledge/articles/visio') return response({ id: 'visio', title: 'Visio requests', tags: ['software'], markdown: '## Steps\n1. Check the licence group.' });
    if (url === '/api/kill') return response({ count: 1, results: [{ Process: 'Renderer.exe', PID: 42, state: 'terminated' }] });
    return response({ deployments: [], items: [] });
  } });
  const { w, run } = f, d = w.document, $ = id => d.getElementById(id);
  w.matchMedia = () => ({ matches: false, addEventListener() {} }); // A desktop-width window.
  let clipboard = '';
  Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: async text => { clipboard = text; } }, configurable: true });
  await f.console();
  d.dispatchEvent(new w.Event('DOMContentLoaded'));
  await sleep(60);
  const actions = w.AtlasInboxActions;

  // Outside Live Inbox (or before it has rendered) the Workspace tools are used as before.
  await actions.run({ action: 'health', user: person, machine: 'LAPTOP-01' });
  assert($('workspace').classList.contains('active'), 'Without Live Inbox on screen, Health opens Workspace');

  // Live Inbox as React renders it: the list and the message details in .inbox-grid.
  $('liveInbox').innerHTML = '<div class="live-inbox"><div class="inbox-grid"><div class="inbox-mail-list"></div><div class="inbox-context"><button id="openPerson">Open in Workspace</button></div></div></div>';
  $('openPerson').onclick = () => w.dispatchEvent(new w.CustomEvent('atlas:inbox-person', { detail: { id: 7 } }));
  run("page('inbox')");
  const grid = d.querySelector('.inbox-grid'), work = () => $('inboxWork'), pane = tab => d.querySelector(`[data-work-pane="${tab}"]`);
  const fetched = prefix => calls.filter(c => c.url.startsWith(prefix));
  calls.length = 0;

  // Health: a full scan beside the message; the page does not change.
  await actions.run({ action: 'health', user: person, machine: 'LAPTOP-01' });
  assert($('inbox').classList.contains('active') && !$('workspace').classList.contains('active'), 'Health stays in Live Inbox');
  assert.equal(work().parentNode, grid, 'The tools are the third column of the inbox grid');
  assert(!work().hidden);
  assert.match(d.querySelector('[data-work-title]').textContent, /LAPTOP-01 · Alex Morgan/);
  assert.equal(d.querySelector('[data-work-tab="health"]').getAttribute('aria-selected'), 'true');
  assert.equal(run('S.target'), 'LAPTOP-01', 'Atlas target follows the request');
  await until(() => fetched('/api/machine-health/LAPTOP-01/').length === 8, 'all health checks');
  await until(() => pane('health').querySelector('[data-metric="storage"]')?.textContent.includes('50.0 GiB free'), 'storage reading');

  // Performance: tiles, findings and the busiest processes; End… asks first.
  d.querySelector('[data-work-tab="performance"]').click();
  await until(() => pane('performance').querySelector('.inbox-work-tiles'), 'performance tiles');
  assert.equal(fetched('/api/performance/LAPTOP-01?kind=overview').length, 1);
  const tiles = [...pane('performance').querySelectorAll('.inbox-work-tile')].map(t => [t.querySelector('small').textContent, t.querySelector('b').textContent, t.dataset.tone]);
  assert.deepEqual(tiles.slice(0, 3), [['CPU', '82%', 'warn'], ['Memory', '91%', 'bad'], ['C: free', '5%', 'bad']]);
  assert.match(pane('performance').querySelector('.inbox-work-notes').textContent, /RAM pressure/);
  const first = () => pane('performance').querySelector('tbody tr td').textContent;
  assert.equal(first(), 'Renderer.exe');
  pane('performance').querySelector('[data-work-sort="Memory"]').click();
  assert.equal(first(), 'Renderer.exe');
  assert.equal(pane('performance').querySelector('[data-work-sort="Memory"]').getAttribute('aria-pressed'), 'true');
  const end = () => pane('performance').querySelector('[data-work-end="42"]');
  w.confirm = () => false; end().click(); await sleep(30);
  assert.equal(fetched('/api/kill').length, 0, 'Cancelled End sends nothing');
  w.confirm = () => true; end().click();
  await until(() => fetched('/api/kill').length === 1 && fetched('/api/performance/').length === 2, 'process ended and rescanned');
  assert.deepEqual(fetched('/api/kill')[0].body, { computer: 'LAPTOP-01', value: '42', created: '20260910100000.000000+000', name: 'Renderer.exe' });

  // User groups: account problems first, Direct before Primary before Nested, filter and copy.
  await actions.run({ action: 'user-groups', user: person, machine: 'LAPTOP-01' });
  await until(() => pane('user-groups').querySelector('.inbox-work-groups'), 'user groups');
  assert.deepEqual(fetched('/api/active-directory/lookup').at(-1).body, { kind: 'user', identity: 'INBOX0', server: '' });
  assert.equal(pane('user-groups').querySelector('.inbox-work-chips').textContent, 'Locked out');
  assert.deepEqual([...pane('user-groups').querySelectorAll('[data-group] > span')].map(n => n.textContent), ['App-Outlook', 'Domain Users', 'Paris-Printers']);
  const filter = pane('user-groups').querySelector('[data-work-filter]');
  filter.value = 'paris'; filter.dispatchEvent(new w.Event('input', { bubbles: true }));
  assert.match(pane('user-groups').querySelector('[data-work-hidden]').textContent, /2 groups hidden/);
  pane('user-groups').querySelector('[data-work-copy]').click();
  await until(() => clipboard === 'Paris-Printers', 'copied visible group names');
  assert($('inbox').classList.contains('active'));

  // Machine groups: the computer account; computers report only the checks AD returns.
  await actions.run({ action: 'machine-groups', user: person, machine: 'LAPTOP-01' });
  await until(() => pane('machine-groups').querySelector('.inbox-work-groups'), 'machine groups');
  assert.deepEqual(fetched('/api/active-directory/lookup').at(-1).body, { kind: 'computer', identity: 'LAPTOP-01', server: '' });
  assert.equal(pane('machine-groups').querySelector('.inbox-work-chips').textContent, 'enabled');

  // Deploy: the Workspace deployment panel moves beside the message with the package and script chosen.
  await actions.run({ action: 'deploy', user: person, machine: 'LAPTOP-01', pkg: { folder: 'Example App', display_name: 'Example App' }, deployAction: 'Repair' });
  assert($('inbox').classList.contains('active'), 'Deploy stays in Live Inbox');
  assert.equal($('deploymentPanel').closest('[data-work-pane]'), pane('deploy'));
  assert(!$('deploymentPanel').hidden, 'The deployment panel is usable beside the message');
  assert.deepEqual([$('pkg').value, $('action').value, $('script').value], ['Example App', 'Repair', 'setup_r.ps1']);
  // Switching tools keeps the half-prepared deployment.
  d.querySelector('[data-work-tab="health"]').click();
  assert.equal($('deploymentPanel').closest('[data-work-pane]'), pane('deploy'));
  d.querySelector('[data-work-tab="deploy"]').click();
  assert.equal($('script').value, 'setup_r.ps1');

  // Leaving from the sidebar: the panel returns to Workspace, no "Back" button.
  run("page('workspace')");
  assert.equal($('deploymentPanel').parentNode, $('workspace'));
  assert(!$('deploymentPanel').hidden, 'Workspace shows its deployment panel again');
  assert.equal($('script').value, 'setup_r.ps1', 'The prepared deployment survives the move');
  assert(!$('inboxReturn') || $('inboxReturn').hidden, 'The sidebar does not offer Back to Live Inbox');
  run("page('inbox')");
  assert.equal($('deploymentPanel').closest('[data-work-pane]'), pane('deploy'), 'Coming back re-opens the deployment beside the message');

  // A Live Inbox button that opens another page offers the way back.
  $('openPerson').click();
  assert($('workspace').classList.contains('active'));
  await until(() => $('inboxReturn') && !$('inboxReturn').hidden, 'Back to Live Inbox');
  $('inboxReturn').click();
  assert($('inbox').classList.contains('active'));
  assert($('inboxReturn').hidden);

  // Reboot from the panel keeps its confirmation.
  const reboots = []; w.AtlasReboots.start = async pc => reboots.push(pc);
  w.confirm = () => false; d.querySelector('[data-work-reboot]').click(); await sleep(30);
  assert.deepEqual(reboots, []);
  w.confirm = () => true; d.querySelector('[data-work-reboot]').click();
  await until(() => reboots.length === 1, 'reboot');
  assert.deepEqual(reboots, ['LAPTOP-01']);

  // Person: record, desk and devices; their PC tools in one click.
  await actions.run({ action: 'person', user: person });
  await until(() => pane('person').querySelector('.inbox-work-record'), 'person record');
  const record = Object.fromEntries([...pane('person').querySelectorAll('.inbox-work-record dt')].map(dt => [dt.textContent, dt.nextElementSibling.textContent]));
  assert.deepEqual([record.Department, record.Location, record.Desk, record.Manager], ['Client Services', 'Paris', '04R019086 (floor 4)', 'Jo Lead']);
  assert.match(pane('person').querySelector('[data-work-device="PHONE-01"]').textContent, /Inventory only/);
  pane('person').querySelector('[data-work-use="LAPTOP-01"][data-then="performance"]').click();
  assert.equal(d.querySelector('[data-work-tab="performance"]').getAttribute('aria-selected'), 'true');

  // The message's people and PCs, one click each; a person without a PC given gets their own.
  w.dispatchEvent(new w.CustomEvent('atlas:inbox-detail', { detail: { match: { user: person }, machines: [laptop], analysis: { machines: [], people: [marie, { ambiguous: true, written: 'Lee Wong', candidates: [] }] } } }));
  const chips = () => [...d.querySelectorAll('[data-work-request] button')].map(b => [b.textContent, b.getAttribute('aria-pressed')]);
  assert.deepEqual(chips(), [['Alex Morgan · sender', 'true'], ['Marie Dupont', 'false'], ['LAPTOP-01', 'true'], ['LAPTOP-09', 'false']]);
  d.querySelector('[data-work-person="1"]').click();
  await until(() => w.AtlasInboxWork.state().machine === 'LAPTOP-09', "Marie's PC picked");
  assert.match(d.querySelector('[data-work-title]').textContent, /LAPTOP-09 · Marie Dupont/);
  d.querySelector('[data-work-machine="0"]').click();
  assert.deepEqual([w.AtlasInboxWork.state().machine, w.AtlasInboxWork.state().user], ['LAPTOP-01', 7], 'A PC chip brings its owner');

  // Same access as a colleague: groups Marie has that Alex lacks.
  d.querySelector('[data-work-tab="user-groups"]').click();
  await until(() => pane('user-groups').querySelector('[data-work-compare-with]'), 'compare offer');
  pane('user-groups').querySelector('[data-work-compare-with="X09"]').click();
  await until(() => pane('user-groups').querySelector('[data-compare="missing"]'), 'comparison');
  assert.deepEqual([...pane('user-groups').querySelectorAll('[data-compare="missing"] [data-group] > span')].map(n => n.textContent), ['APP-Visio', 'VPN-Users']);
  assert.match(pane('user-groups').querySelector('[data-work-compare-result]').textContent, /Marie Dupont has, Alex Morgan lacks \(2\)[\s\S]*Only Alex Morgan has \(1\)[\s\S]*2 groups in common/);
  pane('user-groups').querySelector('[data-work-copy-missing]').click();
  await until(() => clipboard === 'APP-Visio\nVPN-Users', 'copied missing groups');

  // Anyone else: several matches are listed, one opens directly.
  const find = term => { const form = d.querySelector('[data-work-lookup]'); form.elements.term.value = term; form.dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true })); };
  find('sam');
  await until(() => d.querySelectorAll('[data-work-pick-user]').length === 2, 'lookup results');
  d.querySelector('[data-work-pick-user="0"]').click();
  await until(() => /Sam Lee/.test(d.querySelector('[data-work-title]').textContent), 'picked person');
  find('laptop-09');
  await until(() => w.AtlasInboxWork.state().machine === 'LAPTOP-09' && w.AtlasInboxWork.state().tab === 'health', 'single PC opens');

  // Late lookup responses cannot replace a newer result or an explicit context change.
  const deferredLookup = term => {
    let finish;
    pendingLookups.set(term, new Promise(resolve => { finish = (data, status = 200) => resolve(response(data, status)); }));
    find(term);
    return finish;
  };
  const obsoletePc = { users: [], machines: [{ name: 'OBSOLETE-PC', windows_remote_supported: 1 }] };
  const results = d.querySelector('[data-work-results]');
  const oldSuccess = deferredLookup('old-success');
  const oldFailure = deferredLookup('old-failure');
  const latest = deferredLookup('latest');
  oldSuccess(obsoletePc); oldFailure({ detail: 'OBSOLETE LOOKUP FAILURE' }, 503);
  await sleep(30);
  assert.equal(results.getAttribute('aria-busy'), 'true', 'Obsolete completions cannot finish the latest loading state');
  assert(!results.textContent.includes('OBSOLETE'));
  latest({ users: [], machines: [{ name: 'LAPTOP-09', windows_remote_supported: 1 }] });
  await until(() => results.hidden, 'latest lookup opens its PC');
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09');

  const afterLatest = deferredLookup('after-latest');
  find('laptop-09');
  await until(() => results.hidden, 'newer PC result selected');
  afterLatest(obsoletePc); await sleep(30);
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09', 'An older response completing after the latest result cannot replace its PC');

  const beforeManualChoice = deferredLookup('before-manual-choice');
  d.querySelector('[data-work-person="1"]').click();
  await until(() => w.AtlasInboxWork.state().user === 9, 'manual request person');
  beforeManualChoice(obsoletePc); await sleep(30);
  assert.deepEqual([w.AtlasInboxWork.state().user, w.AtlasInboxWork.state().machine], [9, 'LAPTOP-09'], 'An earlier search cannot replace a manually chosen person and their PC');

  for (const selector of ['[data-work-person="1"]', '[data-work-machine="1"]']) {
    const beforeSameChoice = deferredLookup('before-same-' + selector);
    d.querySelector(selector).click();
    beforeSameChoice(obsoletePc); await sleep(30);
    assert.deepEqual([w.AtlasInboxWork.state().user, w.AtlasInboxWork.state().machine], [9, 'LAPTOP-09'], 'Explicitly choosing the current person or PC also cancels pending lookup');
  }

  const beforeClear = deferredLookup('before-clear');
  find(''); beforeClear(obsoletePc); await sleep(30);
  assert(results.hidden && !results.hasAttribute('aria-busy'), 'Clearing lookup invalidates pending results');
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09');

  const beforeMessage = deferredLookup('before-message');
  w.dispatchEvent(new w.CustomEvent('atlas:inbox-detail', { detail: { message: { id: 200 }, match: { user: marie }, analysis: {} } }));
  beforeMessage(obsoletePc); await sleep(30);
  assert(results.hidden);
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09', 'An earlier message lookup cannot replace the current selection');

  const beforeClose = deferredLookup('before-close');
  d.querySelector('[data-work-close]').click();
  beforeClose(obsoletePc); await sleep(30);
  assert(work().hidden, 'An obsolete lookup cannot reopen closed tools');
  w.AtlasInboxWork.open({ user: marie, machine: 'LAPTOP-09' }, 'person');
  const beforeLeaving = deferredLookup('before-leaving');
  run("page('workspace');page('inbox')");
  beforeLeaving(obsoletePc); await sleep(30);
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09', 'Leaving and returning cannot revive an obsolete lookup');

  // PC tools that open over Live Inbox.
  const opened = []; w.AtlasSoftware.load = pc => opened.push(['software', pc]); w.AtlasServices = { load: () => opened.push(['services', run('S.target')]) }; w.AtlasHealth.specs = pc => opened.push(['specs', pc]);
  for (const key of ['software', 'services', 'specs']) d.querySelector(`[data-work-${key}]`).click();
  assert.deepEqual(opened, [['software', 'LAPTOP-09'], ['services', 'LAPTOP-09'], ['specs', 'LAPTOP-09']]);
  assert($('inbox').classList.contains('active'));

  // Knowledge Base articles open beside the message; diagrams still need the viewer.
  w.AtlasKnowledgeArticles = { render: async (markdown, target) => { target.textContent = 'rendered: ' + markdown; } };
  await actions.run({ action: 'knowledge', document: 'article:visio' });
  await until(() => /rendered: ## Steps/.test(pane('knowledge').textContent), 'article');
  assert.match(pane('knowledge').textContent, /Visio requests/);
  assert.equal(w.AtlasInboxWork.state().machine, 'LAPTOP-09', 'An article keeps the PC on screen');
  const diagrams = []; w.AtlasKnowledge.show = id => diagrams.push(id);
  await actions.run({ action: 'knowledge', document: 'kb-network' });
  assert.deepEqual(diagrams, ['kb-network']);

  // A sender without a Windows PC: Person and User groups only.
  await actions.run({ action: 'user-groups', user: { ...person, id: 8, user_name: 'INBOX1', full_name: 'Sam Lee' }, machine: '' });
  assert.deepEqual([...d.querySelectorAll('[data-work-tab]')].filter(b => !b.disabled).map(b => b.dataset.workTab), ['person', 'user-groups', 'knowledge']);
  assert(d.querySelector('[data-work-tool="msra"]').disabled);
  assert.match(d.querySelector('[data-work-title]').textContent, /No Windows PC · Sam Lee/);

  // Close: the tools hide and the deployment panel goes home.
  d.querySelector('[data-work-close]').click();
  assert(work().hidden);
  assert.equal($('deploymentPanel').parentNode, $('workspace'));
  assert(calls.every(c => c.method === 'GET' || ['/api/active-directory/lookup', '/api/kill'].includes(c.url)), 'Nothing deploys or reboots by itself');
  await sleep(100);
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Live Inbox request tools run person (record, desk, devices), health, performance (End… confirmed), user and PC AD groups (filter, copy, compare with a colleague), deployment, software/services/specs and articles beside the message; request people and PCs one click each; lookup of anyone; the deployment panel moves in and back intact; Back to Live Inbox after a Live Inbox button; reboot confirmed; Workspace fallback outside Live Inbox');
  process.exit(0);
})().catch(error => { console.error(error); process.exit(1); });
