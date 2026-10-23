// Live floor plan card: settings, what Atlas read, held changes; responses are simulated.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { fixture, root } = require('./ui_fixture.cjs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const posts = [];
  const held = {
    folder: 'C:\\Plan', enabled: true, checked: '2026-10-20T09:01:00+00:00',
    status: { state: 'held', message: 'Hoche Project_20261020.xlsx: 52 changes in one save; review them before they reach the map.' },
    last: { file: 'Hoche Project_20261020.xlsx', modified: '2026-10-20T08:58:00+00:00', desks: 310,
      reader: { fixes: [{ written: '2R017069', desk: '02R017069', cell: '+2!J4' }], not_in_directory: [{ name: 'Sandrine Kone', desk: '02R019073', ambiguous: false }],
        unknown_desks: [{ desk: '02R999999', label: 'Ghost', cell: '+2!A1' }], conflicts: [],
        sheets: { 'R+2 (FINAL)': 120, 'R+4 (FINAL)': 118 }, hidden_sheets: ['R+4 (OLD)'], blank: [{ desk: '04R015090', cell: 'R+4 (FINAL)!C1' }] } },
    held: { id: 'review-1', reason: '52 changes in one save', file: 'Hoche Project_20261020.xlsx', report: { errors: [], changes: [
      { desk: '02R016079', kind: 'moved', from_desk: '02R015079', before: { name: 'Credit Sales' }, after: { name: 'Christophe Duriez' } },
      { desk: '02R015079', kind: 'vacated', from_desk: null, before: { name: 'Christophe Duriez' }, after: { name: 'Vacant desk' } }] } },
    history: [{ at: '2026-10-19T17:00:00+00:00', file: 'Hoche Project_20261002.xlsx', counts: { moved: 2, assigned: 1 }, backup: 'b1.db', desks: ['04R019086', '04R014086'] }],
    duplicates: [{ name: 'Example Person', desks: ['03R012074', '04R030088'] }],
  };
  const synced = { ...held, status: { state: 'synced', message: 'Updated from Hoche Project_20261020.xlsx: 1 moved, 1 freed.' }, held: null,
    history: [{ at: '2026-10-20T09:02:00+00:00', file: 'Hoche Project_20261020.xlsx', counts: { moved: 1, vacated: 1 } }, ...held.history] };
  let current = held, replaceOnApply = false;
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const f = await fixture({ html: 'frontend/database.html', url: 'http://localhost/manage-database', fetch: async (url, options = {}) => {
    if (url === '/api/session') return response({ token: 't' });
    if (url === '/api/seating-sync') return response(current);
    if (url.startsWith('/api/seating-sync/')) {
      posts.push([url, JSON.parse(options.body || '{}')]);
      if (url.endsWith('/apply') && replaceOnApply) {
        replaceOnApply = false;
        current = { ...held, held: { ...held.held, id: 'review-2', report: { ...held.held.report,
          changes: [{ ...held.held.report.changes[0], after: { name: 'New reviewed occupant' } }] } } };
        return response({ detail: 'This seating review is out of date. Review the latest changes before applying.' }, 409);
      }
      if (url.endsWith('/undo')) return response(current = { ...current, history: [{ at: '2026-10-20T09:05:00+00:00', file: 'Undo of Hoche Project_20261002.xlsx', counts: { restored: 2 } },
        ...current.history.map((h) => h.backup === 'b1.db' ? { ...h, undone: '2026-10-20T09:05:00+00:00' } : h)] });
      return response(url.endsWith('/apply') ? (current = synced) : current);
    }
    return response({ counts: { users: 1, machines: 1, assignments: 1 }, history: [] });
  } });
  const { w, run } = f, get = (id) => w.document.getElementById(id);
  run(fs.readFileSync(path.join(root, 'frontend/assets/seating-sync.js'), 'utf8'));
  await sleep(30);
  assert.equal(get('live-plan-state').textContent, 'Waiting for review');
  assert.equal(get('live-plan-state').className, 'status-warn');
  assert.equal(get('live-plan-folder').value, 'C:\\Plan');
  assert.match(get('live-plan-details').textContent, /Hoche Project_20261020\.xlsx · saved .* · 310 desks read/);
  assert.match(get('live-plan-details').textContent, /1 desk codes corrected/);
  assert.match(get('live-plan-details').textContent, /2R017069 → 02R017069/);
  assert.match(get('live-plan-details').textContent, /Sandrine Kone · 02R019073/);
  assert.match(get('live-plan-details').textContent, /02R999999 · Ghost/);
  assert.match(get('live-plan-details').textContent, /Tabs read: R\+2 \(FINAL\) \(120\) · R\+4 \(FINAL\) \(118\) · hidden tabs skipped: R\+4 \(OLD\)/);
  assert.match(get('live-plan-details').textContent, /1 desk codes with nothing written beside them/);
  assert.match(get('live-plan-details').textContent, /1 people on more than one desk now/);
  assert.match(get('live-plan-details').textContent, /Example Person · 03R012074, 04R030088/);
  assert(!get('live-plan-held').hidden);
  assert.deepEqual([...get('live-plan-changes').children].map((li) => li.textContent),
    ['02R016079 · moved from 02R015079: Credit Sales → Christophe Duriez', '02R015079 · freed: Christophe Duriez → Vacant desk']);
  get('live-plan-folder').value = '"C:\\Users\\me\\OneDrive\\02_Current_plan"';
  get('live-plan-folder').dispatchEvent(new w.Event('input'));
  await sleep(20);
  assert.equal(get('live-plan-folder').value, '"C:\\Users\\me\\OneDrive\\02_Current_plan"', 'Typing is not overwritten by refreshes');
  get('live-plan-save').onclick(); await sleep(20);
  assert.deepEqual(posts[0], ['/api/seating-sync/settings', { folder: '"C:\\Users\\me\\OneDrive\\02_Current_plan"', enabled: true, review_large: true }]);
  w.confirm = () => false; get('live-plan-apply').onclick(); await sleep(20);
  assert.equal(posts.length, 1, 'Cancelling the confirmation applies nothing');
  replaceOnApply = true;
  w.confirm = () => true; get('live-plan-apply').onclick(); await sleep(30);
  assert.deepEqual(posts[1], ['/api/seating-sync/apply', { id: 'review-1' }], 'Approval sends the proposal that was displayed');
  assert.match(get('live-plan-message').textContent, /out of date/);
  assert.match(get('live-plan-changes').textContent, /New reviewed occupant/);
  assert.equal(posts.length, 2, 'A stale review refreshes but never applies the replacement automatically');
  get('live-plan-apply').onclick(); await sleep(20);
  assert.deepEqual(posts[2], ['/api/seating-sync/apply', { id: 'review-2' }], 'The operator explicitly confirms the replacement review');
  assert.equal(get('live-plan-state').textContent, 'Synced');
  assert(get('live-plan-held').hidden);
  assert(get('live-plan-apply').disabled, 'No proposal remains to apply');
  assert.match(get('live-plan-history').textContent, /Hoche Project_20261020\.xlsx · 1 moved, 1 freed/);
  const undo = () => get('live-plan-history').querySelector('.atlas-live-plan-undo');
  let asked = '';
  w.confirm = (text) => { asked = text; return false; };
  undo().onclick(); await sleep(20);
  assert.match(asked, /Put 2 desks back as they were/);
  assert.equal(posts.length, 3, 'Cancelling Undo changes nothing');
  w.confirm = () => true; undo().onclick(); await sleep(20);
  assert.deepEqual(posts[3], ['/api/seating-sync/undo', { backup: 'b1.db' }]);
  assert.match(get('live-plan-history').textContent, /Undo of Hoche Project_20261002\.xlsx · 2 restored/);
  assert.match(get('live-plan-history').textContent, /Hoche Project_20261002\.xlsx · 2 moved, 1 assigned · undone/);
  assert.equal(undo(), null, 'An undone update cannot be undone twice');
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Live floor plan card shows reader notes, keeps typed settings, binds approval to the displayed proposal and refreshes stale reviews without applying them; tabs read and Undo');
  process.exit(0);
})().catch((error) => { console.error(error); process.exit(1); });
