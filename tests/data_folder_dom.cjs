// Data folder card: settings, each export's state, a held users-and-devices snapshot; responses are simulated.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { fixture, root } = require('./ui_fixture.cjs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const posts = [];
  const report = { users: { before: 5000, after: 2, added: 0, removed: 4998, changed: 2, removed_examples: ['u9', 'u10'] },
    machines: { before: 6000, after: 3, added: 1, removed: 5998, changed: 2, removed_examples: [] },
    warnings: ['users: more than 10% of existing records disappear.', '1 device rows have no ci/name hostname; retained in the export archive.'], review: ['Users: 4,998 of 5,000 existing records disappear.'] };
  const held = {
    folder: 'C:\\AtlasXL', enabled: true, review_large: true, checked: '2026-10-27T09:01:00+00:00',
    status: { state: 'held', message: 'A users-and-devices snapshot is waiting for your review.' },
    kinds: [
      { kind: 'directory', label: 'Users & devices', result: 'held', message: 'Large change: waiting for your review below.', files: ['sys_user.csv', 'alm_asset.csv'], at: '2026-10-27T09:01:00+00:00' },
      { kind: 'vdi', label: 'Citrix VDI', result: 'applied', message: 'Updated: 12 added, 3 updated', files: ['SingleSessionMachines.csv'], at: '2026-10-27T09:01:00+00:00' },
      { kind: 'packages', label: 'Package data', result: 'error', message: 'u_cmdb_software_package.xlsx: save the package export as CSV.', files: ['u_cmdb_software_package.xlsx'] },
    ],
    ignored: ['notes.xlsx'],
    held: { id: 'review-1', kind: 'directory', files: ['sys_user.csv', 'alm_asset.csv'], reason: 'Users: 4,998 of 5,000 existing records disappear.', report },
    history: [{ at: '2026-10-27T09:01:00+00:00', kind: 'vdi', label: 'Citrix VDI', files: ['SingleSessionMachines.csv'], summary: '12 added, 3 updated' }],
  };
  const synced = { ...held, status: { state: 'synced', message: 'Users and devices updated after review.' }, held: null,
    kinds: [{ ...held.kinds[0], result: 'applied', message: 'Updated: users +0 added' }, held.kinds[1], held.kinds[2]],
    history: [{ at: '2026-10-27T09:03:00+00:00', kind: 'directory', label: 'Users & devices', files: ['sys_user.csv', 'alm_asset.csv'], summary: 'users +0 added, 4,998 removed' }, ...held.history] };
  let current = { folder: 'C:\\AtlasXL', enabled: false, status: { state: 'off', message: 'The data folder is off.' }, kinds: [], history: [] };
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const f = await fixture({ html: 'frontend/database.html', url: 'http://localhost/manage-database', fetch: async (url, options = {}) => {
    if (url === '/api/session') return response({ token: 't' });
    if (url === '/api/data-folder') return response(current);
    if (url.startsWith('/api/data-folder/')) {
      posts.push([url, JSON.parse(options.body || '{}')]);
      if (url.endsWith('/settings')) return response(current = held);
      if (url.endsWith('/apply')) return response(current = synced);
      return response(current);
    }
    if (url === '/api/seating-sync') return response({ status: { state: 'off' }, history: [] });
    return response({ counts: { users: 1, machines: 1, assignments: 1 }, history: [] });
  } });
  const { w, run } = f, get = (id) => w.document.getElementById(id);
  run(fs.readFileSync(path.join(root, 'frontend/assets/data-folder.js'), 'utf8'));
  await sleep(30);
  assert.equal(get('data-folder-state').textContent, 'Off');
  assert.equal(get('data-folder-path').value, 'C:\\AtlasXL', 'The suggested folder is filled in');
  assert.equal(get('data-folder-kinds').children.length, 0, 'Nothing is listed while the folder is off');
  assert(get('data-folder-held').hidden);

  get('data-folder-enabled').checked = true;
  get('data-folder-enabled').dispatchEvent(new w.Event('change'));
  get('data-folder-save').onclick(); await sleep(30);
  assert.deepEqual(posts[0], ['/api/data-folder/settings', { folder: 'C:\\AtlasXL', enabled: true, review_large: true }]);
  assert.equal(get('data-folder-state').textContent, 'Waiting for review');
  assert.equal(get('data-folder-state').className, 'status-warn');
  const rows = [...get('data-folder-kinds').children].map((li) => li.textContent);
  assert.match(rows[0], /^Users & devicesWaiting for review · sys_user\.csv \+ alm_asset\.csv · Large change: waiting for your review below\./);
  assert.match(rows[1], /^Citrix VDIImported · SingleSessionMachines\.csv · Updated: 12 added, 3 updated/);
  assert.match(rows[2], /^Package dataNot imported · u_cmdb_software_package\.xlsx · u_cmdb_software_package\.xlsx: save the package export as CSV\./);
  assert.equal(get('data-folder-kinds').children[2].querySelector('span span').className, 'status-bad');
  assert.match(get('data-folder-ignored').textContent, /left alone: notes\.xlsx/);
  assert(!get('data-folder-held').hidden);
  assert.match(get('data-folder-held-reason').textContent, /sys_user\.csv \+ alm_asset\.csv: Users: 4,998 of 5,000 existing records disappear\./);
  const changes = [...get('data-folder-changes').children].map((li) => li.textContent);
  assert.match(changes[0], /^Users: 5,000 → 2 \(0 added, 4,998 removed, 2 updated\)$/);
  assert.equal(get('data-folder-changes').children[0].className, 'status-bad');
  assert.match(changes[1], /Users removed, for example: u9, u10/);
  assert(!changes.some((text) => /more than 10% of existing records disappear/.test(text)), 'The heading already gives the review reasons');
  assert(changes.some((text) => /1 device rows have no ci\/name hostname/.test(text)), 'Other notes are listed');

  w.confirm = () => false; get('data-folder-apply').onclick(); await sleep(20);
  assert.equal(posts.length, 1, 'Cancelling the confirmation applies nothing');
  let asked = '';
  w.confirm = (text) => { asked = text; return true; };
  get('data-folder-apply').onclick(); await sleep(30);
  assert.match(asked, /Replace users and devices with sys_user\.csv \+ alm_asset\.csv\? Users: 4,998 of 5,000 existing records disappear\. Atlas backs up/);
  assert.deepEqual(posts[1], ['/api/data-folder/apply', { id: 'review-1' }], 'Approval sends the review that was displayed');
  assert.equal(get('data-folder-state').textContent, 'Up to date');
  assert(get('data-folder-held').hidden);
  assert(get('data-folder-apply').disabled, 'No review remains to apply');
  assert.match(get('data-folder-history').textContent, /Users & devices · sys_user\.csv \+ alm_asset\.csv · users \+0 added, 4,998 removed/);
  get('data-folder-check').onclick(); await sleep(20);
  assert.deepEqual(posts[2], ['/api/data-folder/check', {}]);
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Data folder card fills in C:\\AtlasXL, lists each export with its state and unrecognised files, and applies only the held snapshot it displayed after confirmation');
  process.exit(0);
})().catch((error) => { console.error(error); process.exit(1); });
