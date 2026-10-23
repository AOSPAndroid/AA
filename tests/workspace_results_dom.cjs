// Fictional directory data and intercepted requests only; no live machine actions.
const assert = require('node:assert/strict');
const {fixture} = require('./ui_fixture.cjs');
const settle = () => new Promise(resolve => setTimeout(resolve, 20));
const reply = data => ({ok: true, status: 200, json: async () => data});
const deferred = () => {let resolve;const promise = new Promise(done => {resolve = done});return {promise, resolve};};
(async () => {
  const calls = [], quick = [], copied = [], pending = new Map();
  const users = [
    {id: 1, canonical_key: 'uid:fict.one', name: 'Fictional Same Name', user_name: 'fict.one', email: 'one@example.test', location: 'Paris'},
    {id: 2, canonical_key: 'uid:fict.two', name: 'Fictional Same Name <script>literal</script>', user_name: 'fict.two', email: '', location: 'London'},
  ];
  const machines = [
    {name: 'FICT-ASSIGNED', model_category: 'Laptop', assigned_relationship: 1, logon_relationship: 0, match_type: 'Assigned'},
    {name: 'FICT-LAST-LOGON', model_category: 'Computer', assigned_relationship: 0, logon_relationship: 1, match_type: 'Last logged on (inventory)'},
    {name: 'FICT-BOTH', model_category: 'Computer', assigned_relationship: 1, logon_relationship: 1, match_type: 'Assigned + last logged on (inventory)'},
    {name: 'IPHONE-FICT', device_kind: 'iphone', model_category: 'Mobile Device', windows_remote_supported: false, assigned_relationship: 1},
  ];
  const shared = {name: 'GBRGLOIVB-FICT.example.test', device_kind: 'vdi', vdi_key: 'fict-vdi', assigned_relationship: 1, vdi_assignment_count: 2, vdi_assigned_users: ['EXAMPLE\\fict.one', 'EXAMPLE\\fict.two'], vdi_registration_state: 'Registered', vdi_power_state: 'On', vdi_imported_at: '2026-10-07T09:00:00Z'};
  const f = await fixture({fetch: async (url, options = {}) => {
    url = String(url);calls.push(url);assert.equal(options.method || 'GET', 'GET', 'Fixture forbids operations');
    if (pending.has(url)) return pending.get(url).promise;
    if (url.startsWith('/api/user/')) return reply({user: users[0], machines});
    if (url.startsWith('/api/master/resolve/')) {
      const term = decodeURIComponent(url.split('/').at(-1));
      if (term === 'SHARED') return reply({matched: false, machine: shared, users: users.map(user => ({...user, assigned_relationship: 1}))});
      if (term === 'AMBIGUOUS') return reply({matched: false, ambiguous: true, machine: null, machines: [shared, {...shared, name: 'GBRGLOIVB-FICT.other.example.test', vdi_key: 'other-vdi'}]});
      return reply({matched: false});
    }
    if (url.startsWith('/api/search?')) {
      const term = new URL(url, 'http://fixture.test').searchParams.get('term');
      if (term === 'user:capped') return reply({users:Array.from({length:100},(_,i)=>({...users[0],id:i+1,user_name:'fict.'+i,canonical_key:'uid:fict.'+i})),machines:[]});
      return reply(term === 'user:people' ? {users, machines: []} : {users: [], machines: []});
    }
    if (url === '/api/health') return reply({identity: 'FIXTURE', users: 2, machines: 4});
    if (url === '/api/history' || url === '/api/psexec/runs') return reply([]);
    return reply({available: false, items: [], scripts: [], users: [], machines: [], records: [], deployments: []});
  }});
  const {w, run} = f, d = w.document;
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async value => copied.push(value)}});
  // Observe the selection adapter without scheduling any Windows reads.
  w.AtlasHealth.quick = (host, pc, current) => {quick.push(pc);return w.AtlasHealth.mount(host, pc, current)};
  await f.console();await run('sharedPaletteReady');await settle();
  const status = d.querySelector('#lookupStatus'), empty = d.querySelector('.lookup-empty'), column = d.querySelector('.lookup-column');
  const search = term => {d.querySelector('#search').value = term;return run('search()')};
  assert(status.hidden);assert(!empty.hidden);
  await search('user:people');
  assert(!status.hidden);assert(status.textContent.includes('2 users'));
  assert(empty.hidden, 'Populated results cannot retain the idle invitation');
  const rows = [...d.querySelectorAll('.workspace-user-result')];assert.equal(rows.length, 2);
  assert.equal(d.querySelector('.workspace-result-heading small').textContent, '2 records');
  rows.forEach((row, index) => {
    assert.equal(row.querySelector('[data-user]').dataset.user, String(index));
    assert.equal(row.querySelector('[data-email]').dataset.email, String(index), 'Email action stays paired with the exact account');
  });
  assert.equal(rows[0].querySelector('[data-user]').type, 'button');
  assert(rows[1].querySelector('[data-email]').disabled);assert.equal(rows[1].querySelector('script'), null);
  const beforeCopy = calls.length;rows[0].querySelector('[data-email]').click();await settle();
  assert.equal(copied.at(-1), users[0].email);assert.equal(calls.length, beforeCopy);assert.equal(run('S.target'), '');assert.equal(run('S.user'), null);
  rows[0].querySelector('[data-user]').click();await settle();
  assert(calls.includes('/api/user/uid%3Afict.one'));assert(empty.hidden);
  assert.equal(status.textContent, 'User record · 4 linked devices');
  assert.equal(d.querySelector('.atlas-machine-filter-heading strong').textContent, 'Linked devices');
  const cards = [...d.querySelectorAll('#machines [data-machine]')], buttons = cards.map(card => card.querySelector('.workspace-machine-select'));
  assert.deepEqual(cards.map(card => card.querySelector('.workspace-device-relationship').textContent), ['Assigned to this user', 'Last logged on only · inventory', 'Assigned + last logged on · inventory', 'Assigned to this user']);
  assert(cards[1].querySelector('.workspace-device-relationship').title.includes('not confirm a current sign-in'));
  assert(buttons.every(button => button.getAttribute('aria-pressed') === 'false'));
  buttons[0].click();assert.equal(buttons[0].getAttribute('aria-pressed'), 'true');assert.equal(run('S.target'), 'FICT-ASSIGNED');
  const selected = run('S.target'), beforeControls = quick.length;
  cards[1].querySelector('.copyhost').click();cards[1].querySelector('details summary').click();
  assert.equal(run('S.target'), selected, 'Copy and disclosure controls never select their enclosing card');
  assert.equal(quick.length, beforeControls);
  buttons[3].click();assert.equal(run('S.target'), '');assert.equal(buttons[0].getAttribute('aria-pressed'), 'false');assert.equal(buttons[3].getAttribute('aria-pressed'), 'true');
  assert(empty.hidden, 'Inventory-only selection is populated state');
  const sharedStart = calls.length;await search('SHARED');
  assert.equal(calls.length, sharedStart + 1, 'Known machine context uses the resolve response directly');
  assert.equal(run('S.user'), null, 'A shared machine never invents a selected user');
  assert.equal(d.querySelectorAll('.workspace-user-result').length, 2);assert.equal(d.querySelector('.workspace-result-heading strong').textContent, 'Linked users');
  assert.equal(d.querySelector('.atlas-machine-filter-heading strong').textContent, 'Matching devices');
  assert.equal(d.querySelector('.atlas-machine-filter-heading small').textContent, '1 device');
  assert.equal(d.querySelector('.workspace-device-relationship').textContent, 'Citrix inventory · assignment snapshot');
  assert.equal(run('S.target'), shared.name.toUpperCase());assert.equal(quick.length, 1, 'Shared VDI selection adds no automatic probes');
  await search('AMBIGUOUS');assert.equal(run('S.target'), '');assert.equal(d.querySelectorAll('#machines [data-machine]').length, 2);
  assert(status.textContent.includes('choose the full device identity'));assert.equal(d.querySelectorAll('.workspace-user-result').length, 0);
  // Every pending response and error belongs to its exact search sequence.
  const oldUrl = '/api/search?term=user%3Aold', old = deferred();pending.set(oldUrl, old);
  const oldSearch = search('user:old');await settle();assert.equal(status.dataset.state, 'loading');assert.equal(column.getAttribute('aria-busy'), 'true');assert(empty.hidden);
  await search('user:people');const freshText = status.textContent;
  old.resolve({ok: false, status: 503, json: async () => ({detail: 'Old failed request'})});await oldSearch;
  assert.equal(status.textContent, freshText);assert.equal(status.dataset.state, 'ready');assert.equal(column.getAttribute('aria-busy'), 'false');
  const failUrl = '/api/search?term=user%3Afail', failed = deferred();pending.set(failUrl, failed);
  const failure = search('user:fail');failed.resolve({ok: false, status: 503, json: async () => ({detail: '<script>Literal unavailable</script>'})});await assert.rejects(failure);
  assert.equal(status.dataset.state, 'error');assert(status.textContent.includes('<script>Literal unavailable</script>'));assert(!status.querySelector('script'));assert(empty.hidden);assert.equal(column.getAttribute('aria-busy'), 'false');
  const clearUrl = '/api/search?term=user%3Acleared', clearing = deferred();pending.set(clearUrl, clearing);
  const clearingSearch = search('user:cleared');await settle();run('clearLookup()');
  clearing.resolve(reply({users, machines: []}));await clearingSearch;
  assert.equal(d.querySelectorAll('.workspace-user-result').length, 0, 'Clear cancels a pending lookup presentation');assert(status.hidden);assert(!empty.hidden);
  await search('nothing with spaces');assert.equal(empty.hidden, false);assert.equal(empty.querySelector('h3').textContent, 'No matching records');
  await search('FICT-UNLISTED');assert(!d.querySelector('#useHostname').hidden);assert(empty.hidden);
  d.querySelector('#useHostname').click();assert.equal(run('S.target'), 'FICT-UNLISTED');assert(status.textContent.includes('Hostname target'));assert(!d.querySelector('#deploymentPanel').hidden);
  assert(!calls.some(url => /machine-health|active-directory|performance/.test(url)), 'Presentation and copy introduce no remote reads');
  assert.equal(f.errors.length, 0, f.errors.join('\n'));
  await search('user:capped');assert(status.textContent.includes('100 users shown'));assert(status.textContent.includes('refine search'));assert(!status.textContent.includes('found'), 'Capped result counts must not claim a total match count');
  w.dispatchEvent(new w.Event('pagehide'));w.close();
  console.log('PASS: paired user results/copy, truthful relationship and count labels, accessible PC/mobile selection, no accidental controls or added scans, shared/ambiguous machine context, race-safe lookup statuses, clear/error/empty states and hostname deployment fallback');
})().catch(error => {console.error(error);process.exitCode = 1});
