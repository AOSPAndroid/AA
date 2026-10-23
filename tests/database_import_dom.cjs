// Directory import state and transport recovery; all responses are simulated.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => {let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve};};
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const counts = {before: 1, after: 2, added: 1, removed: 0, changed: 0, added_examples: [], removed_examples: []};
const preview = {id: 'stage-one', source: 'emea.xlsx', report: {
  users: counts, machines: counts, relationships: counts,
  warnings: [], unlinked_machine_references: 0, missing_desk_accounts: [],
  import_resolution: {user: {duplicate_rows: 2}, machine: {duplicate_rows: 3}, mobile_identity_rows: 4},
}};
(async () => {
  const startup = deferred(), upload = deferred(), requests = [];
  let sessions = 0, previews = 0, applications = 0, statusCalls = 0;
  const f = await fixture({html: 'frontend/database.html', url: 'http://localhost/manage-database#directory-import', fetch: async (url, options = {}) => {
    requests.push({url, options});
    if (url === '/api/database/status') {
      if (++statusCalls === 1) return startup.promise;
      throw Error('Status refresh unavailable');
    }
    if (url === '/api/session') {
      if (++sessions === 1) throw Error('Session connection failed');
      return response({token: 'token-' + sessions});
    }
    if (url === '/api/database/preview') {
      previews++;
      if (previews === 1) return upload.promise;
      if (previews === 2) return response({detail: 'Session expired'}, 403);
      assert.equal(options.headers.get('X-Atlas-Token'), 'token-3');
      return response(preview);
    }
    if (url === '/api/database/preview-pair') {
      const headers = options.headers;
      assert.deepEqual([headers.get('X-First-Size'), headers.get('X-First-Name'), headers.get('X-Second-Name')], ['10', 'devices.xlsx', 'users.csv']);
      return response({...preview, id: 'stage-two', source: 'users.csv + devices.xlsx', pair: {users_file: 'users.csv', devices_file: 'devices.xlsx', rows: {users: 5, devices: 7}}});
    }
    if (url === '/api/database/apply/stage-one') {
      assert.deepEqual(JSON.parse(options.body), {confirmation: 'APPLY', full_snapshot: true});
      if (++applications === 1) return response({detail: 'Jobs are active'}, 409);
      return response({backup: 'test-backup.db'});
    }
    throw Error('Unexpected request: ' + url);
  }});
  const {w, run} = f, get = id => w.document.getElementById(id);
  w.HTMLElement.prototype.getClientRects = function() {return this.closest('[hidden]') ? [] : [{}]};
  for (const file of ['database.js']) run(fs.readFileSync(path.join(root, 'frontend/assets', file), 'utf8'));
  await sleep(50);
  assert.equal(w.document.activeElement, get('directory-import'), 'The users/devices shortcut focuses its upload section');
  for (const id of ['package-data-import', 'floorplan-import', 'vdi-data-import']) {
    w.location.hash = id; await sleep(20);
    assert.equal(w.document.activeElement, get(id), 'Other update shortcuts focus their upload sections');
  }
  assert.equal(sessions + previews + applications, 0, 'Opening upload sections never starts an import');
  assert(!get('validate').disabled, 'Slow status loading does not disable validation');
  assert(!w.document.querySelector('.atlas-edge-panel'), 'Upload workflows never move into floating controls');
  assert(get('preview').hidden, 'Confirmation remains hidden before a valid preview');
  assert.equal(w.document.querySelectorAll('.atlas-upload-grid > section').length, 4);
  assert(get('full').closest('#preview'));
  assert(get('seating-file').closest('#seating-panel'));
  assert(get('seating-confirm').closest('#seating-result'));
  assert(get('moves-file').closest('#desk-moves-panel'));
  assert(get('moves-confirm').closest('#moves-result'));
  await get('validate').onclick();
  assert.match(get('directory-message').textContent, /Choose an Excel workbook/);
  assert.equal(sessions, 0);
  function select(name, size = 10) {
    Object.defineProperty(get('file'), 'files', {configurable: true, value: [{name, size}]});
    get('file').onchange();
  }
  select('wrong.csv'); await get('validate').onclick();
  assert.match(get('directory-message').textContent, /Use an .xlsx/);
  select('large.xlsx', 51 * 1024 * 1024); await get('validate').onclick();
  assert.match(get('directory-message').textContent, /50 MB/);
  assert.equal(sessions, 0, 'Invalid files do not start a request');
  select('emea.xlsx'); await get('validate').onclick();
  assert.match(get('directory-message').textContent, /Session connection failed/);
  assert(!get('validate').disabled && get('directory-progress').hidden);
  const pending = get('validate').onclick(); await sleep(20);
  assert.equal(get('validate').textContent, 'Validating…');
  assert(get('validate').disabled && get('file').disabled && !get('directory-progress').hidden);
  startup.resolve(response({counts: {users: 1, machines: 1, assignments: 1}, history: []}));
  await sleep(750);
  assert.equal(w.document.querySelector('[data-database-controls="directory"]').getAttribute('aria-busy'), 'true');
  assert.match(get('directory-message').textContent, /Validating emea.xlsx/);
  assert.match(get('message').textContent, /Validating emea.xlsx/, 'Late status cannot overwrite the active operation');
  await get('validate').onclick(); assert.equal(previews, 1, 'Repeated clicks never duplicate an upload');
  upload.resolve(response(preview)); await pending; await sleep(40);
  assert(!get('preview').hidden && !get('full').closest('[hidden]'), 'Successful validation opens inline review controls');
  assert.match(get('changes').textContent,/5 duplicate rows consolidated/);
  assert.match(get('changes').textContent,/4 mobile rows identified/);
  assert(get('apply').disabled);
  get('full').checked = true; get('full').onchange(); assert(get('apply').disabled);
  get('confirm').value = 'APPLY'; get('confirm').oninput(); assert(!get('apply').disabled);
  select('replacement.xlsx'); await sleep(40);
  assert(get('preview').hidden && get('apply').disabled);
  assert(!get('full').checked && get('confirm').value === '', 'A replacement file invalidates the old preview and consent');
  await get('validate').onclick();
  assert.match(get('directory-message').textContent, /Session expired/);
  assert.equal(sessions, 2);
  await get('validate').onclick(); assert.equal(sessions, 3, 'The next click gets a fresh session after 403');
  get('full').checked = true; get('confirm').value = 'APPLY'; get('confirm').oninput();
  await get('apply').onclick();
  assert.match(get('review-message').textContent, /Jobs are active/);
  assert(!get('preview').hidden && !get('apply').disabled, 'A rejected apply remains reviewable and can be retried');
  await get('apply').onclick();
  assert.match(get('directory-message').textContent, /Import completed. Backup: test-backup.db/);
  assert.match(get('directory-message').textContent, /Counts and history could not refresh/);
  assert(get('preview').hidden && get('apply').disabled);
  assert.equal(applications, 2);
  const selectMany = files => {Object.defineProperty(get('file'), 'files', {configurable: true, value: files}); get('file').onchange();};
  selectMany([{name: 'a.xlsx', size: 1}, {name: 'b.xlsx', size: 1}, {name: 'c.xlsx', size: 1}]); await get('validate').onclick();
  assert.match(get('directory-message').textContent, /exactly two exports/);
  selectMany([{name: 'devices.pdf', size: 1}, {name: 'users.csv', size: 1}]); await get('validate').onclick();
  assert.match(get('directory-message').textContent, /\.xlsx or \.csv exports/);
  selectMany([{name: 'devices.xlsx', size: 10}, {name: 'users.csv', size: 20}]);
  assert.match(get('directory-message').textContent, /devices.xlsx \+ users.csv selected/);
  await get('validate').onclick(); await sleep(20);
  assert(!get('preview').hidden, 'Two separate exports open the same review');
  assert.equal(get('source').textContent, 'Users: users.csv (5 rows) · Devices: devices.xlsx (7 rows)');
  assert.equal(f.errors.length, 0, f.errors.join('\n'));
  w.dispatchEvent(new w.Event('pagehide')); w.close();
  console.log('PASS: two separate exports (xlsx/csv) previewed together, visible import feedback, slow startup, upload progress, session recovery, scoped controls, stale-file invalidation and guarded apply retry.');
})().catch(error => {console.error(error); process.exitCode = 1;});
