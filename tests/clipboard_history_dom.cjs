// Clipboard page: capture, coloured entity chips, a list with the selected capture's machine/people
// tables, bulk actions, Ctrl+V on any page but Live Inbox, capture on returning to Atlas, right-click
// menus. Fictional data.
const assert = require('node:assert/strict'), fs = require('node:fs');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 4000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(15)) if (check()) return;
  throw Error('Clipboard history did not update in time');
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
const alex = { id: 1, full_name: 'Alex Morgan', user_name: 'X01000001', email: 'alex@example.test', department: 'Equities' };
const enrich = (text, source, id) => ({ id, at: '2026-10-20T15:40:00', source, text, times: 1,
  machines: text.includes('LAPTOP') ? [{ name: 'LAPTOP-0001', device_kind: 'laptop', model_id: 'Latitude 7450', operational_status: 'Operational', windows_remote_supported: 1, user: alex },
    { name: 'IPHONE-0007', device_kind: 'iphone', model_id: 'iPhone 15', operational_status: 'Operational', windows_remote_supported: 0, assigned_user: 'Alex Morgan', user: null }] : [],
  users: text.includes('@') ? [alex] : [], desks: text.includes('02R') ? [{ desk: '02R015079', name: 'Alex Morgan', team: 'Equities', floor: 2, occupancy: 'assigned' }] : [],
  tickets: text.includes('INC') ? ['INC0045678'] : [], ips: [], unknown_machines: text.includes('GHOST') ? ['GHOST-PC-9999'] : [] });

(async () => {
  const posts = [], deletes = [];
  let stored = [enrich('older note', 'paste', 'old')];
  let companion = { known: false, online: false, user: '', settings: { clipboard: true, mail: false }, clipboard: {}, mail: {} };
  const settings = [];
  const f = await fixture({ fetch: async (url, options = {}) => {
    const parsed = new URL(url, 'http://localhost'), path = parsed.pathname, method = options.method || 'GET';
    if (path === '/api/clipboard' && parsed.searchParams.get('summary')) return response({ count: stored.length, latest: stored[0] ? stored[0].id : '' });
    if (path === '/api/companion') return response(companion);
    if (path === '/api/companion/settings') { const body = JSON.parse(options.body); settings.push(body); companion = { ...companion, settings: { ...companion.settings, ...body } }; return response(companion); }
    if (path === '/api/session') return response({ token: 'fixture' });
    if (path === '/api/clipboard' && method === 'GET') return response({ items: stored });
    if (path === '/api/clipboard' && method === 'POST') {
      const body = JSON.parse(options.body); posts.push(body);
      const item = enrich(body.text, body.source, 'item' + posts.length); stored = [item, ...stored]; return response(item);
    }
    if (path.startsWith('/api/clipboard') && method === 'DELETE') { deletes.push(path); stored = path === '/api/clipboard' ? [] : stored.filter(i => !path.endsWith(i.id)); return response({ items: stored.length }); }
    if (path.startsWith('/api/ping/')) return response({ online: true });
    return response({});
  } });
  const { w, run } = f, d = w.document, $ = id => d.getElementById(id);
  let clip = { text: 'LAPTOP-0001 and IPHONE-0007 for alex@example.test, INC0045678, desk 02R015079, GHOST-PC-9999' }, state = 'granted';
  Object.defineProperty(w.navigator, 'permissions', { value: { query: async () => ({ state }) }, configurable: true });
  Object.defineProperty(w.navigator, 'clipboard', { value: {
    read: async () => [{ types: ['text/plain'], getType: async () => new w.Blob([clip.text], { type: 'text/plain' }) }],
    writeText: async text => { clip = { text }; } }, configurable: true });
  await f.console();
  run('function toast(){}');
  run(fs.readFileSync('frontend/assets/clipboard-history.js', 'utf8'));
  await until(() => $('clipboardCount').textContent === '1');
  assert(d.querySelector('#clipboardToggle [data-atlas-icon], #clipboardToggle svg') || $('clipboardToggle').dataset.atlasIcon === 'clipboard');

  // The Clipboard page has its own place in the sidebar, beside Workspace and Live Inbox.
  const nav = [...d.querySelectorAll('nav [data-page]')].map(b => b.dataset.page);
  assert.equal(nav[nav.indexOf('inbox') + 1], 'clipboard');
  assert.equal(w.eval('navigationIcons.clipboard'), w.AtlasUI.icon('clipboard'));
  run("page('clipboard')");
  assert($('clipboard').classList.contains('active'));
  assert.equal(d.querySelector('nav [data-page="clipboard"]').getAttribute('aria-current'), 'page');
  assert.equal($('pageTitle').textContent, 'Clipboard');
  run("page('workspace')");

  // Capture: stored with its source; the page opens with the new capture selected and coloured chips.
  $('clipboardCapture').click();
  await until(() => posts.length === 1 && d.querySelector('#clipboardDetail [data-clipboard-machine]'));
  assert.deepEqual(posts[0], { text: clip.text, source: 'button' });
  assert($('clipboard').classList.contains('active'));
  assert.equal($('clipboardCount').textContent, '2');
  const listed = d.querySelector('.clipboard-item');
  assert.equal(listed.getAttribute('aria-pressed'), 'true', 'The new capture is selected');
  assert.deepEqual([...listed.querySelectorAll('.clipboard-chips .clipboard-chip')].map(c => [c.className.split('-').pop(), c.textContent]),
    [['machine', '2 machines'], ['person', '1 person'], ['desk', '1 desk'], ['ticket', '1 ticket'], ['unknown', '1 not in Atlas']]);
  const first = $('clipboardDetail');
  assert.deepEqual([...first.querySelectorAll('[data-clipboard-machine]')].map(r => r.dataset.clipboardMachine), ['LAPTOP-0001', 'IPHONE-0007']);
  assert.match(first.querySelector('[data-clipboard-machine="IPHONE-0007"]').textContent, /Alex Morgan/, 'An unlinked owner name is still shown');
  assert.match($('clipboardStatus').textContent, /2 machines, 1 person, 1 desk/);

  // Bulk actions use only Windows machines; Ping all colours each row.
  first.querySelector('[data-bulk="ping"]').click();
  await until(() => first.querySelector('[data-online="LAPTOP-0001"] .status-ok'));
  assert.equal(first.querySelector('[data-online="IPHONE-0007"]').textContent, '', 'Phones are not pinged');
  first.querySelector('[data-bulk="deploy"]').click();
  assert.equal($('bulkTargets').value, 'LAPTOP-0001');
  assert($('bulk').classList.contains('active'));
  assert(!$('clipboard').classList.contains('active'));

  // Choosing another capture shows its own details; the header button returns to the page.
  $('clipboardToggle').click(); await sleep(20);
  assert($('clipboard').classList.contains('active'));
  d.querySelector('.clipboard-item[data-item="old"]').click();
  assert.equal(d.querySelector('.clipboard-item[aria-pressed="true"]').dataset.item, 'old');
  assert.match($('clipboardDetail').querySelector('.clipboard-text pre').textContent, /older note/);
  assert.equal($('clipboardDetail').querySelector('[data-clipboard-machine]'), null);
  // Ask Axis appears only with the Admin chat and attaches the capture by ID; the server reads its text.
  assert.equal($('clipboardDetail').querySelector('[data-ask-axis]'), null, 'No Ask Axis without the Axis chat');
  const asked = [];
  w.AxisChat = { attach: value => { asked.push(value); return true; } };
  d.querySelector('.clipboard-item[data-item="item1"]').click();
  $('clipboardDetail').querySelector('[data-ask-axis]').click();
  assert.deepEqual(JSON.parse(JSON.stringify(asked)), [{ kind: 'clipboard', id: 'item1', label: clip.text.slice(0, 80), prompt: 'What is this, and what should I do with it?' }]);

  // Right-click a machine: the shared menu plus the Workspace tools.
  const row = d.querySelector('[data-clipboard-machine="LAPTOP-0001"]');
  row.dispatchEvent(new w.MouseEvent('contextmenu', { bubbles: true, clientX: 5, clientY: 5 }));
  const menu = d.querySelector('.atlas-ad-context');
  assert(menu, 'A context menu opens');
  for (const label of ['See groups', 'Set as target', 'Open MSRA', 'Deploy software…']) assert(menu.textContent.includes(label), label);
  d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

  // Ctrl+V: recorded from any page except Live Inbox and text boxes.
  const paste = (target, text) => { const e = new w.Event('paste', { bubbles: true, cancelable: true }); e.clipboardData = { files: [], getData: t => (t === 'text/plain' ? text : '') }; target.dispatchEvent(e); return e; };
  paste($('clipboardFilter'), 'typed into the filter'); await sleep(30);
  assert.equal(posts.length, 1);
  run("page('workspace')");
  assert(paste(d.body, 'SPARE-PC-0042 is slow').defaultPrevented);
  await until(() => posts.length === 2);
  assert.deepEqual(posts[1], { text: 'SPARE-PC-0042 is slow', source: 'paste' });
  await until(() => $('clipboard').classList.contains('active'));
  run("page('inbox')"); paste(d.body, 'handled by Live Inbox'); await sleep(30);
  assert.equal(posts.length, 2, 'Live Inbox keeps its own clipboard reader');
  run("page('workspace')");

  // Returning to Atlas: new clipboard content is captured quietly, the same content only once.
  run("page('workspace')");
  clip = { text: 'LAPTOP-0001 copied in Excel' };
  w.dispatchEvent(new w.Event('focus'));
  await until(() => posts.length === 3);
  assert.deepEqual(posts[2], { text: 'LAPTOP-0001 copied in Excel', source: 'return' });
  assert($('workspace').classList.contains('active'), 'Automatic captures never change the page');
  await sleep(1600); w.dispatchEvent(new w.Event('focus')); await sleep(60);
  assert.equal(posts.length, 3, 'The same clipboard is not captured twice');
  $('clipboardAuto').click(); clip = { text: 'something new' }; await sleep(1600); w.dispatchEvent(new w.Event('focus')); await sleep(60);
  assert.equal(posts.length, 3, 'Turning the option off stops automatic captures');

  // The Companion row: not set up, then connected (browser auto-capture is not needed), then switched off.
  const row2 = () => $('clipboardCompanion').textContent;
  await until(() => /Companion not set up/.test(row2()));
  companion = { ...companion, known: true, online: true, user: 'EXAMPLE\\operator', mail: { state: 'watching' } };
  // Opening the page refreshes the Companion status straight away.
  $('clipboardToggle').click();
  await until(() => /Companion connected/.test(row2()));
  assert.match(row2(), /EXAMPLE\\operator · every copy is captured/);
  assert.match(row2(), /Outlook: watching/);
  assert($('clipboardAuto').disabled, 'Browser capture on return is covered by the Companion');
  $('companionClipboard').click();
  await until(() => settings.length === 1);
  assert.deepEqual(settings[0], { clipboard: false });
  await until(() => /clipboard capture is off/.test(row2()));
  assert(!$('clipboardAuto').disabled);
  companion = { ...companion, online: false, last_seen: '2026-10-20T15:00:00' };
  $('clipboardToggle').click();
  await until(() => /Companion not running/.test(row2()));

  // Delete one, then clear all after confirming.
  $('clipboardToggle').click(); await sleep(20);
  $('clipboardDetail').querySelector('[data-delete]').click();
  await until(() => deletes.length === 1);
  w.confirm = () => true; $('clipboardClear').click();
  await until(() => $('clipboardCount').textContent === '0');
  assert.equal(deletes.at(-1), '/api/clipboard');
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Clipboard page in the sidebar captures, colours and lists captures, shows the selected one\'s machines/people/desks, bulk deploy and ping, right-click tools, Ctrl+V outside Live Inbox, quiet capture on return (once, without changing page), Companion status and switch, delete and clear');
  process.exit(0);
})().catch(error => { console.error(error); process.exit(1); });
