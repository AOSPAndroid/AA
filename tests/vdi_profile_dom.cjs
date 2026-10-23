// Fictional Citrix/user records and intercepted reads only; no Windows or AD access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {fixture, root} = require('./ui_fixture.cjs');
const settle = () => new Promise(resolve => setTimeout(resolve, 20));
const reply = data => ({ok: true, status: 200, json: async () => data});
const vdi = {
  id: 'vdi:fictional-record', name: 'GBRGLOIVB-FICT001.citrix.example.test',
  model_category: 'VDI', device_kind: 'vdi', windows_remote_supported: true,
  match_type: 'Citrix assigned', assigned_relationship: 1, source: 'Citrix',
  vdi_key: 'fictional-record', vdi_short_name: 'GBRGLOIVB-FICT001',
  vdi_catalog: 'Fictional shared catalog <script>literal</script>',
  vdi_delivery_group: 'Fictional shared delivery group',
  vdi_registration_state: 'Unregistered', vdi_power_state: 'On',
  vdi_maintenance_mode: 'Off', vdi_maintenance_enabled: false,
  vdi_user_change_persistence: 'Discard',
  vdi_user_display_names: 'Fictional One; Fictional Two',
  vdi_assigned_users: ['EXAMPLE\\fict.one', 'EXAMPLE\\<img src=x onerror=bad()>'],
  vdi_assignment_count: 2, vdi_imported_at: '2026-10-07T09:00:00Z',
};
const laptop = {name: 'FICT-LAPTOP', model_category: 'Laptop', assigned_to: 'fict.one'};
const users = {
  'id:1': {id: 1, name: 'Fictional One', user_name: 'fict.one', canonical_key: 'uid:fict.one'},
  'id:2': {id: 2, name: 'Fictional Two', user_name: 'fict.two', canonical_key: 'uid:fict.two'},
};

(async () => {
  const requests = [], ad = [];
  let manualHealth = false, copied = '';
  const f = await fixture({fetch: async (url, options = {}) => {
    url = String(url);requests.push(url);
    if (url === '/api/active-directory/lookup') {
      const payload = JSON.parse(options.body);ad.push(payload);
      return reply({kind: 'computer', details: {Account: payload.identity, Enabled: true}, groups: [], warnings: [], membership_note: 'Fictional groups'});
    }
    assert.equal(options.method || 'GET', 'GET', 'Fixture forbids writes');
    if (url.startsWith('/api/machine-health/')) {
      assert(manualHealth, 'Only an explicit manual check may read VDI health');
      const [computer, metric] = url.split('/').slice(-2);
      assert.equal(decodeURIComponent(computer), vdi.name.toUpperCase());
      return reply({computer: vdi.name.toUpperCase(), metric, state: 'ready', checked_at: '2026-10-07T10:15:00Z', data: {available: true}});
    }
    if (url === '/api/vdi-data/record/fictional-record') return reply({
      name: vdi.name, source: 'fictional-citrix.csv', sheet: 'Citrix', row: 2,
      source_rows: 1, original_cells: true, fields: [
        {header: 'MachineName', label: 'Machine name', value: vdi.name},
        {header: '<img src=x onerror=bad()>', label: 'Unknown source field', value: '<script>literal source cell</script>'},
        {header: 'AssignedUsers', label: 'Assigned accounts', value: vdi.vdi_assigned_users.join(';')},
      ],
    });
    if (url.startsWith('/api/directory/record')) throw Error('VDI must not use the ServiceNow directory archive');
    if (url.startsWith('/api/user/')) {
      const id = decodeURIComponent(url.split('/').at(-1));
      const user = users[id] || Object.values(users).find(item => item.canonical_key === id);
      assert(user);return reply({user, machines: user.id === 1 ? [laptop, vdi] : [vdi]});
    }
    if (url.startsWith('/api/master/resolve/')) return reply({matched: false});
    if (url.startsWith('/api/search?')) {
      const term = new URL(url, 'http://fictional.test').searchParams.get('term');
      return reply(term === 'user:one' ? {users: [users['id:1']], machines: []}
        : term === 'user:fictional' ? {users: Object.values(users), machines: []} : {users: [], machines: [vdi]});
    }
    if (url === '/api/session') return reply({token: 'fictional'});
    if (url === '/api/health') return reply({identity: 'FIXTURE', users: 2, machines: 2});
    if (url === '/api/history' || url === '/api/psexec/runs') return reply([]);
    return reply({available: false, records: [], users: [], machines: [], items: [], scripts: [], deployments: []});
  }});
  const {w, run} = f, d = w.document;
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async value => {copied = value;}}});
  await f.console();run(fs.readFileSync(root + '/frontend/assets/active-directory.js', 'utf8'));
  run('installSelectionSidebar()');await settle();
  const healthReads = () => requests.filter(url => url.startsWith('/api/machine-health/'));
  const card = () => d.querySelector('#machines [data-machine-kind="vdi"]');
  assert.equal(w.AtlasUI.machineKind({name: vdi.name, model_category: 'VDI'}), 'vdi', 'Category identifies VDI without a VDI hostname');
  assert.equal(w.AtlasUI.machineKind({name: vdi.name, device_kind: 'VDI'}), 'vdi');
  assert.equal(w.AtlasUI.supportsWindows({...vdi, windows_remote_supported: false}), false, 'An unsafe inventory identity cannot become a remote target');
  assert.equal(w.AtlasUI.machineKind(laptop), 'laptop');
  await run("loadUser('id:1')");await settle();
  assert.equal(healthReads().length, 0, 'Rendering an imported profile does not probe devices');
  assert.equal(d.querySelector('#machines [data-kind="vdi"] .atlas-filter-count').textContent, '1');
  assert(card().textContent.includes('Shared (2)'));
  assert.equal(card().querySelector('.vdi-state').textContent, 'Citrix: Unregistered');
  assert.equal(card().querySelector('.vdi-power').textContent, 'Power: On');
  assert(card().querySelector('.vdi-snapshot').title.includes(vdi.vdi_imported_at));
  assert(!card().querySelector('.vdi-state.good, .vdi-power.good'), 'Imported Citrix state does not claim current health');
  const details = card().querySelector('.atlas-machine-details');
  assert.equal(details.querySelector('summary').textContent, 'Citrix details');
  assert(!details.open);
  for (const value of [vdi.name, vdi.vdi_catalog, vdi.vdi_delivery_group, 'Off', 'Discard', vdi.vdi_imported_at, vdi.vdi_user_display_names])
    assert(details.textContent.includes(value), 'Citrix details retain ' + value);
  assert.deepEqual([...details.querySelectorAll('.atlas-vdi-assigned-accounts li')].map(node => node.textContent), vdi.vdi_assigned_users);
  assert(!details.querySelector('script, img'), 'Source and account strings remain literal text');
  assert.equal(details.querySelector('[data-export-kind]').dataset.exportKind, 'vdi');
  card().querySelector('.workspace-machine-select').click();await settle();
  assert.equal(run('S.target'), vdi.name.toUpperCase());
  assert.equal(d.querySelector('#adminPc').value, vdi.name.toUpperCase());
  assert(card().classList.contains('selected'), 'Original mixed-case FQDN retains selected styling');
  assert.equal(d.querySelector('#barState').textContent, 'Citrix snapshot · Unregistered · On');
  assert(d.querySelector('#healthLine p').textContent.includes('manual health check'));
  assert(d.querySelector('#healthLine').textContent.includes('Not scanned'));
  const selected = run('S.target'), ordered = [...d.querySelectorAll('#machines [data-machine]')].map(node => node.dataset.machine);
  d.querySelector('#machines [data-kind="vdi"]').click();
  assert.equal(card().hidden, false);assert(d.querySelector('#machines [data-machine-kind="laptop"]').hidden);
  assert.equal(run('S.target'), selected, 'Type filtering never retargets the deployment');
  assert.deepEqual([...d.querySelectorAll('#machines [data-machine]')].map(node => node.dataset.machine), ordered, 'Type filtering preserves row identities and order');
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(healthReads().length, 0, 'VDI selection never schedules a delayed quick scan');
  assert(run('completeMachineReport()').includes(vdi.vdi_catalog));
  assert(run('completeMachineReport()').includes(vdi.vdi_assigned_users[1]));
  details.querySelector('[data-export-kind="vdi"]').click();await settle();
  const exportDialog = d.querySelector('.atlas-export-dialog');assert(exportDialog.open);
  assert.equal(requests.filter(url => url.startsWith('/api/vdi-data/record/')).length, 1);
  assert(exportDialog.textContent.includes('Imported Citrix snapshot'));
  assert(!exportDialog.querySelector('script, img'));
  exportDialog.querySelector('.atlas-export-copy').click();await settle();
  assert(copied.includes('fictional-citrix.csv'));assert(copied.includes('<script>literal source cell</script>'));
  exportDialog.close();
  await run("loadUser('id:2')");await settle();
  assert.equal(run('S.target'), selected, 'A shared VDI has the same qualified target on both profiles');
  assert.equal(healthReads().length, 0, 'One-device automatic selection still does not scan imported VDI');
  card().dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  d.querySelector('#machineMenu [data-cmd="ad-groups"]').click();await settle();
  assert.equal(ad.length, 1);assert.equal(ad[0].kind, 'computer');assert.equal(ad[0].identity, vdi.name);
  assert.equal(run('S.target'), selected, 'Group lookup keeps the exact existing target');
  run('page("workspace")');
  manualHealth = true;d.querySelector('#healthLine [data-health-refresh]').click();await settle();manualHealth = false;
  assert.equal(healthReads().length, 8, 'Explicit health scans retain all eight Windows readings');
  assert.equal(w.AtlasHealth.snapshot(d.querySelector('#healthLine'), selected).metrics[0].checkedAt, '2026-10-07T10:15:00Z', 'Health time comes from the check, not the import');
  d.querySelector('#search').value = 'machine:' + vdi.name;await run('search()');await settle();
  assert.equal(run('S.target'), selected, 'Qualified machine search selects the same VDI');
  assert.equal(healthReads().length, 8, 'Machine search performs no automatic Citrix check');
  assert.equal(w.AtlasUI.personKey({id: 1}), 'id:1', 'Legacy numeric profiles remain supported');
  assert.equal(w.AtlasUI.personKey({id: 1, canonical_key: 'uid:fict.one'}), 'uid:fict.one');
  assert(w.AtlasContext.attributes('user', users['id:1']).includes('data-context-person="uid:fict.one"'));
  d.querySelector('#search').value = 'user:one';await run('search()');await settle();
  assert(requests.includes('/api/user/uid%3Afict.one'), 'Single-result lookup follows the stable canonical account');
  d.querySelector('#search').value = 'user:fictional';await run('search()');await settle();
  d.querySelector('#users [data-user="1"]').click();await settle();
  assert(requests.includes('/api/user/uid%3Afict.two'), 'Clicking a search result never rebuilds a potentially reused numeric ID');
  // Demo/Preview may inspect all stored data while live checks remain unavailable.
  w.AtlasReadOnly = {reason: 'Read-only fixture', read: () => null};w.AtlasAD.clear();
  await run("loadUser('id:2')");await settle();
  assert(card().textContent.includes('Shared (2)'));assert(card().querySelector('.atlas-vdi-assigned-accounts'));
  assert(d.querySelector('.selection-scan').disabled);d.querySelector('.selection-scan').click();
  card().dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  d.querySelector('#machineMenu [data-cmd="ad-groups"]').click();await settle();
  assert.equal(ad.length, 1, 'Readonly group navigation never performs a live lookup');
  assert.equal(healthReads().length, 8, 'Readonly VDI inspection performs no scans');
  const invalid = {...vdi, name: 'INVALID INVENTORY NAME', windows_remote_supported: false};
  run('clearLookup()');w.vdiInvalid = invalid;run('S.machines=[vdiInvalid];renderMachines()');await settle();
  assert.equal(run('S.target'), '');assert.equal(d.querySelector('#adminPc').value, '');
  assert(card().querySelector('.atlas-vdi-details'), 'Invalid remote identity retains its stored Citrix details');
  assert(card().textContent.includes('No safe Windows target supplied'));
  assert(!w.AtlasUI.machineSnapshotNote(invalid).includes('run a manual health check'));
  assert(w.AtlasUI.machineSnapshotNote(invalid).includes('unavailable'));
  const detached = d.createElement('div');
  detached.innerHTML = w.AtlasUI.machineBadges({...vdi, vdi_assignment_count: 0, assigned_relationship: 0, vdi_assigned_users: [], vdi_imported_at: null}) + w.AtlasUI.machineDetails({...vdi, vdi_assignment_count: 0, vdi_assigned_users: [], vdi_imported_at: null});
  assert(!detached.querySelector('.shared'));assert(detached.textContent.includes('Unassigned'));
  assert(detached.textContent.includes('Import time unavailable'));assert(detached.textContent.includes('No assigned accounts supplied'));
  assert(w.AtlasUI.machineBadges({...vdi, vdi_assignment_count: undefined}).includes('Shared (2)'), 'Count falls back to supplied raw account refs');
  detached.innerHTML = w.AtlasUI.machineDetails({...vdi, name: 'FICT-PC', vdi_original_name: 'EXAMPLE\\FICT-PC', vdi_domain: 'EXAMPLE', vdi_source: 'fictional-citrix.csv'});
  assert(detached.textContent.includes('Citrix machine nameEXAMPLE\\FICT-PC'));
  assert(detached.textContent.includes('Remote targetFICT-PC'));
  assert(detached.textContent.includes('DomainEXAMPLE'));assert(detached.textContent.includes('fictional-citrix.csv'));
  assert.equal(f.errors.length, 0, f.errors.join('\n'));
  w.dispatchEvent(new w.Event('pagehide'));w.close();
  console.log('PASS: shared Citrix profile/filter/details/source export, exact FQDN targeting and AD navigation, truthful snapshot timestamps, manual-only health, readonly and invalid-target guards');
})().catch(error => {console.error(error);process.exitCode = 1});
