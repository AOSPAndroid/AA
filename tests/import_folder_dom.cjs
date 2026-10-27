// Import folder card: the exports found, results, a held users & devices review; responses are simulated.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { fixture, root } = require('./ui_fixture.cjs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const posts = [];
  const counts = { before: 18739, after: 2, added: 2, removed: 18739, changed: 0 };
  const held = {
    folder: 'C:\\AtlasXL', enabled: true, review_large: true,
    status: { state: 'held', message: 'Users & devices: waiting for your review below.' },
    files: [
      { name: 'Notes.xlsx', kind: '', used: false, modified: '2026-10-27T09:00:00+00:00', size: 10 },
      { name: 'SingleSessionMachines (1).csv', kind: 'vdi', used: true, modified: '2026-10-27T09:00:00+00:00', size: 10 },
      { name: 'SingleSessionMachines.csv', kind: 'vdi', used: false, modified: '2026-10-20T09:00:00+00:00', size: 10 },
      { name: 'alm_asset.csv', kind: 'devices', used: true, modified: '2026-10-27T09:00:00+00:00', size: 10 },
      { name: 'sys_user.csv', kind: 'users', used: true, modified: '2026-10-27T09:00:00+00:00', size: 10 },
      { name: 'u_cmdb_software_package.csv', kind: 'packages', used: true, modified: '2026-10-27T09:00:00+00:00', size: 10 },
    ],
    groups: {
      directory: { result: 'held', message: 'This snapshot removes 18,739 of 18,739 users.' },
      vdi: { result: 'applied', message: '2 VDIs.' },
      packages: { result: 'error', message: 'CSV headers must be unique and non-empty.' },
    },
    held: { id: 'review-1', files: ['sys_user.csv', 'alm_asset.csv'], reason: 'This snapshot removes 18,739 of 18,739 users.',
      report: { users: counts, machines: { ...counts, before: 50, after: 49, removed: 1 }, missing_desk_accounts: [{ desk: '02R015079', account: 'uid:x' }], warnings: ['users: more than 10% of existing records disappear.'] } },
    history: [{ at: '2026-10-27T09:01:00+00:00', kind: 'Citrix VDI', files: ['SingleSessionMachines (1).csv'], result: 'applied', message: '2 VDIs.' }],
  };
  const applied = { ...held, status: { state: 'synced', message: 'Up to date.' }, held: null,
    groups: { ...held.groups, directory: { result: 'applied', message: '2 users.' } },
    history: [{ at: '2026-10-27T09:02:00+00:00', kind: 'Users & devices', files: ['sys_user.csv', 'alm_asset.csv'], result: 'applied', message: '2 users.' }, ...held.history] };
  let current = held, statusReads = 0;
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const f = await fixture({ html: 'frontend/database.html', url: 'http://localhost/manage-database', fetch: async (url, options = {}) => {
    if (url === '/api/session') return response({ token: 't' });
    if (url === '/api/import-folder') return response(current);
    if (url.startsWith('/api/import-folder/')) {
      posts.push([url, JSON.parse(options.body || '{}')]);
      if (url.endsWith('/apply')) return response(current = applied);
      return response(current);
    }
    if (url === '/api/database/status') statusReads++;
    return response({ counts: { users: 1, machines: 1, assignments: 1 }, history: [] });
  } });
  const { w, run } = f, get = (id) => w.document.getElementById(id);
  w.confirm = () => true;
  run(fs.readFileSync(path.join(root, 'frontend/assets/database.js'), 'utf8'));
  run(fs.readFileSync(path.join(root, 'frontend/assets/import-folder.js'), 'utf8'));
  await sleep(30);
  assert.equal(get('import-folder-state').textContent, 'Waiting for review');
  assert.equal(get('import-folder-path').value, 'C:\\AtlasXL');
  const rows = [...get('import-folder-files').children].map((li) => [li.textContent, li.className, li.dataset.muted || '']);
  assert.match(rows[0][0], /^Notes\.xlsx · Other · .* · not an export Atlas reads$/);
  assert.equal(rows[0][2], 'true');
  assert.match(rows[1][0], /SingleSessionMachines \(1\)\.csv · Citrix VDI · .* · imported · 2 VDIs\./);
  assert.equal(rows[1][1], 'status-ok');
  assert.match(rows[2][0], /older copy, not used/);
  assert.match(rows[3][0], /alm_asset\.csv · Devices · .* · waiting for review$/, 'The review reason is shown once, below');
  assert.match(rows[5][0], /not imported · CSV headers must be unique/);
  assert.equal(rows[5][1], 'status-bad');
  assert(!get('import-folder-held').hidden);
  assert.match(get('import-folder-held-reason').textContent, /^sys_user\.csv \+ alm_asset\.csv: This snapshot removes/);
  const lines = [...get('import-folder-held-counts').children].map((li) => [li.textContent, li.className]);
  assert.deepEqual(lines[0], ['Users: 18,739 → 2 (+2 / −18,739)', 'status-bad']);
  assert.deepEqual(lines[1], ['Devices: 50 → 49 (+2 / −1)', '']);
  assert.match(lines[2][0], /1 desk links point at accounts this snapshot removes/);
  // Typed settings survive the periodic refresh, then save as typed.
  get('import-folder-path').value = '"D:\\Exports"';
  get('import-folder-path').dispatchEvent(new w.Event('input'));
  get('import-folder-review').checked = false;
  get('import-folder-review').dispatchEvent(new w.Event('change'));
  get('import-folder-check').click();
  await sleep(20);
  assert.equal(get('import-folder-path').value, '"D:\\Exports"');
  get('import-folder-save').click();
  await sleep(20);
  assert.deepEqual(posts.at(-1), ['/api/import-folder/settings', { folder: '"D:\\Exports"', enabled: true, review_large: false }]);
  const before = statusReads;
  get('import-folder-apply').click();
  await sleep(30);
  assert.deepEqual(posts.at(-1), ['/api/import-folder/apply', { id: 'review-1' }], 'Apply names the review on screen');
  assert(get('import-folder-held').hidden);
  assert(get('import-folder-apply').disabled);
  assert.equal(get('import-folder-state').textContent, 'Up to date');
  assert.match(get('import-folder-history').children[0].textContent, /Users & devices · sys_user\.csv \+ alm_asset\.csv · imported: 2 users\./);
  assert(statusReads > before, 'The directory counts refresh after a folder import');
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Import folder card lists recognised, older and other files with each result, shows one held review with its counts, keeps typed settings, applies the review on screen and refreshes the directory counts');
})().catch((error) => { console.error(error); process.exitCode = 1; });
