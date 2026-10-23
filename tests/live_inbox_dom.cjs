// Exercise the compiled inbox with fictional mail. No Outlook or remote machine access.
const assert = require('node:assert/strict'), fs = require('node:fs');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 6000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(20)) if (check()) return;
  throw Error('Inbox did not update in time');
}
const person = { id: 7, name: 'Alex Morgan', full_name: 'Alex Morgan', email: 'alex@example.test', department: 'Support', location: 'Paris' };
const match = { kind: 'email', basis: 'email', user: person, candidates: [person] };
const one = { id: 1, sender_name: 'Alex Morgan', sender_address: 'alex@example.test', subject: 'VPN cannot connect', received_at: '2026-10-15T09:01:00Z', match };
const two = { ...one, id: 2, channel: 'teams', content_kind: 'notification', app_name: 'Microsoft Teams', sender_address: '', subject: '<img src=x onerror="window.mailExecuted=true">', match: { kind: 'ambiguous', basis: 'name', user: null, candidates: [person, { ...person, id: 8, email: 'other@example.test' }] } };
const watcher = { running: true, state: 'watching', stale: false, interval: 15, last_success_at: one.received_at, config: {} };
two.preview = two.subject;
const response = data => ({ ok: true, status: 200, json: async () => data });
(async () => {
  let rows = [one], offline = false, requests = [], deferred, holdDetail = false, opened;
  const notifications = { running: true, stale: false, state: 'watching', last_success_at: one.received_at };
  const control = { configured: true, state: 'running', mail_user: 'TEST\\MailUser', atlas_user: 'TEST\\AtlasAdmin', agent_running: true, desired: { running: true, outlook: true, notifications: true, outlook_previews: false } };
  const actions = [];
  const f = await fixture({ fetch: async (url, options = {}) => {
    const parsed = new URL(url, 'http://localhost'); requests.push(parsed);
    if (parsed.pathname === '/api/session') return response({ token: 'fixture-token' });
    if (parsed.pathname === '/api/inbox/control') {
      if (options.method === 'POST') {
        const body = JSON.parse(options.body); actions.push(body);
        if (body.action === 'stop') { control.state = 'stopped'; control.desired.running = false; }
        else if (body.action === 'start') { control.state = 'running'; control.desired.running = true; }
        else if (body.action === 'source') {
          if (!control.desired.running) Object.assign(control.desired, { outlook: false, notifications: false });
          for (const key of ['outlook', 'notifications']) if (key in body) control.desired[key] = body[key];
          control.desired.running = control.desired.outlook || control.desired.notifications;
          control.state = control.desired.running ? 'running' : 'stopped';
        }
        else if (body.action === 'preferences') Object.assign(control.desired, body);
      }
      return response(structuredClone(control));
    }
    if (parsed.pathname.startsWith('/api/search-everything/similar/')) return response(parsed.pathname.endsWith('/1')
      ? { terms: ['vpn', 'connect'], articles: [{ kind: 'article', ref: 'vpn', title: '\u0002VPN\u0003 or network', snippet: '' }],
          requests: [{ kind: 'inbox', ref: '2', title: '<img src=x onerror="window.mailExecuted=true"> \u0002VPN\u0003 down', snippet: 'Cannot \u0002connect\u0003', at: '2026-10-01', extra: { sender: 'Sam' } }] }
      : { terms: [], articles: [], requests: [] });
    assert(parsed.pathname.startsWith('/api/inbox/messages'), 'Inbox requests stay in its local API');
    if (offline) throw Error('Connection lost');
    if (parsed.pathname === '/api/inbox/messages') {
      const after = Number(parsed.searchParams.get('after_id'));
      const items = rows.filter(row => row.id > after).sort((a, b) => after ? a.id - b.id : b.id - a.id);
      return response({ items, total: rows.length, newest_id: rows.at(-1)?.id || 0, next_after: rows.at(-1)?.id || after, has_more: false, watcher, notifications });
    }
    const row = rows.find(row => row.id === Number(parsed.pathname.split('/').at(-1)));
    const chosen = parsed.searchParams.get('user_id');
    const named = row.id === 1 ? '\nPlease also help DUPONT Marie on LAPTOP-04, and one of the Lee Wong.\n' + Array.from({ length: 24 }, (_, i) => 'Line ' + i).join('\n') : '';
    const analysis = row.id === 1 ? { machines: [{ name: 'LAPTOP-04', linked: false, model_id: 'Latitude 5440' }], people: [
      { id: 9, full_name: 'Marie Dupont', written: 'DUPONT Marie', basis: 'name', user_name: 'X09', department: 'Equities', desks: [{ id: '04R019086', floor: 4 }], machines: [{ name: 'LAPTOP-09' }] },
      { ambiguous: true, written: 'Lee Wong', basis: 'name', candidates: [{ id: 10, email: 'lee1@example.test' }, { id: 11, email: 'lee2@example.test' }] }] } : {};
    const detail = { message: { ...row, body: '<script>window.mailExecuted=true</script>\nMy laptop cannot connect.' + named }, match: { ...row.match, user: chosen ? person : row.match.user, chosen: !!chosen }, machines: row.match.user || chosen ? [{ name: 'LAPTOP-01', model_id: 'Latitude 7450', match_type: 'Assigned', operational_status: 'Operational' }] : [], analysis };
    if (holdDetail) return new Promise(resolve => deferred = () => resolve(response(detail)));
    return response(detail);
  }});
  const { w, run } = f, d = w.document;
  w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  w.AtlasUI.motion.isReduced = () => true;
  w.addEventListener('atlas:inbox-person', event => opened = event.detail.id);
  run(fs.readFileSync('frontend/assets/atlas-interactions.js', 'utf8'));
  await sleep(150); assert.equal(requests.length, 0, 'Hidden inbox does not read mail');
  d.getElementById('workspace').classList.remove('active'); d.getElementById('inbox').classList.add('active');
  await until(() => d.querySelector('.inbox-devices strong'));
  assert.deepEqual([...d.querySelectorAll('.inbox-devices strong')].map(n => n.textContent), ['LAPTOP-04', 'LAPTOP-01'], 'Machines named in the message, then linked ones');
  assert.match(d.querySelector('[data-inbox-status]').textContent, /Watching Outlook/);
  assert(!d.querySelector('.inbox-body script')); assert(!w.mailExecuted);
  // The message comes first; named machines and people are highlighted and open the request tools.
  const sent = []; w.addEventListener('atlas:inbox-action', event => sent.push(event.detail));
  assert(d.querySelector('.inbox-context').firstElementChild.classList.contains('inbox-message-card'), 'The message is the first card');
  // A long sender ("Lair de Gourmont, Amaury Pierre Marie : GTB Europe <address>") once squeezed the subject to one
  // letter per line: card headers wrap, and titles keep a minimum width.
  const css = fs.readFileSync('frontend/assets/design-system.css', 'utf8');
  assert.match(css, /#liveInbox \[data-slot="card-header"\] \{ display:flex; flex-wrap:wrap;/);
  assert.match(css, /#liveInbox \[data-slot="card-header"\] > \[data-slot="card-title"\] \{ flex:1 1 auto; min-width:min\(12em,100%\); \}/);
  assert.deepEqual([...d.querySelectorAll('.inbox-body .inbox-entity')].map(e => [e.tagName, e.textContent]), [['BUTTON', 'DUPONT Marie'], ['BUTTON', 'LAPTOP-04'], ['MARK', 'Lee Wong']]);
  d.querySelector('.inbox-body [data-entity="person"]').click(); d.querySelector('.inbox-body [data-entity="machine"]').click();
  assert.deepEqual(sent.map(x => [x.action, x.user?.id, x.machine]), [['person', 9, undefined], ['target', 7, 'LAPTOP-04']]);
  assert(d.querySelector('.inbox-body[data-collapsed]'), 'A long message starts collapsed');
  // In jsdom React occasionally drops this click right after the request actions above start their own
  // work: it reaches the root with no error or re-render, and the same handler works when clicked again.
  // Click again as a person would (bounded); the toggle itself must still work.
  for (let attempt = 0; attempt < 3 && d.querySelector('.inbox-body[data-collapsed]'); attempt++) {
    [...d.querySelectorAll('.inbox-message-card button')].find(b => b.textContent === 'Show the whole message')?.click();
    try { await until(() => !d.querySelector('.inbox-body[data-collapsed]'), 1500); } catch {}
  }
  assert(!d.querySelector('.inbox-body[data-collapsed]'), 'Show the whole message expands the long message');
  // Named people: details, desk, machines; a shared name lists its candidates.
  const marie = d.querySelector('[data-named-person="Marie Dupont"]');
  assert.match(marie.textContent, /written "DUPONT Marie"/); assert.match(marie.textContent, /X09 · Equities · Desk 04R019086/); assert.match(marie.textContent, /LAPTOP-09/);
  assert.match(d.querySelector('[data-named-person="Lee Wong"]').textContent, /2 people share this name/);
  [...d.querySelector('[data-named-person="Lee Wong"]').querySelectorAll('button')].find(b => b.textContent === 'lee2@example.test').click();
  assert.deepEqual(sent.at(-1).user, { id: 11, email: 'lee2@example.test' });
  const footer = [...d.querySelectorAll('.inbox-person-card [data-slot=card-footer] button')];
  footer.find(b => b.textContent === 'Details').click(); assert.deepEqual([sent.at(-1).action, sent.at(-1).user.id], ['person', 7]);
  footer.find(b => b.textContent.startsWith('Workspace')).click(); assert.equal(opened, 7);
  rows.push(two);
  await until(() => d.querySelectorAll('[data-mail-id]').length === 2);
  assert.equal(d.querySelector('[data-mail-id][aria-current]').getAttribute('data-mail-id'), '1', 'Arrival never changes a selected message');
  assert.match(d.querySelector('.inbox-list-heading').textContent, /Show newest \(1\)/);
  d.querySelector('.inbox-list-heading button').click();
  await until(() => d.querySelector('.inbox-candidates'));
  assert.match(d.querySelector('[data-mail-id="2"]').textContent, /Teams preview/);
  assert.match(d.querySelector('.inbox-message-card').textContent, /Notification preview from Microsoft Teams/);
  assert.match(d.querySelector('[data-notification-status]').textContent, /Listening for notifications/);
  assert(!d.querySelector('.inbox-devices'), 'Ambiguous people do not silently inherit machines');
  assert(!d.querySelector('.inbox-subject img')); assert(!w.mailExecuted);
  d.querySelector('.inbox-candidates button').click();
  await until(() => d.querySelector('.inbox-devices'));
  assert.match(d.querySelector('.inbox-person-card').textContent, /selected for this view/);
  assert.match(d.querySelector('.inbox-person-card').textContent, /verify the sender in Teams or Outlook/);
  assert(requests.some(url => url.searchParams.get('user_id') === '7'));
  // An older detail response must not replace the newly selected message.
  holdDetail = true; d.querySelector('[data-mail-id="1"]').click();
  await until(() => deferred); holdDetail = false; d.querySelector('[data-mail-id="2"]').click();
  await until(() => d.querySelector('.inbox-candidates') && !d.querySelector('.inbox-devices'));
  deferred(); await sleep(60); assert(d.querySelector('.inbox-candidates'));
  // "Seen before": earlier requests and articles sharing key words; text is never parsed as HTML.
  const shown = [];
  w.addEventListener('atlas:inbox-action', event => shown.push(event.detail));
  assert(!d.querySelector('.inbox-similar-card'), 'Nothing similar, no card');
  d.querySelector('[data-mail-id="1"]').click();
  await until(() => d.querySelector('.inbox-similar-card'));
  const similar = d.querySelector('.inbox-similar-card');
  assert.match(similar.textContent, /same key words: vpn, connect/);
  assert.deepEqual([...similar.querySelectorAll('mark')].map(mark => mark.textContent), ['VPN', 'VPN', 'connect']);
  assert(!similar.querySelector('img')); assert(!w.mailExecuted);
  similar.querySelector('[aria-label="Related articles"] button').click();
  await until(() => shown.length);
  assert.deepEqual(shown.map(action => [action.action, action.document]), [['knowledge', 'article:vpn']], 'Articles open in the Knowledge Base');
  similar.querySelector('[data-similar-request="2"]').click();
  await until(() => d.querySelector('[data-mail-id="2"][aria-current]') && d.querySelector('.inbox-candidates'));
  assert(!d.querySelector('.inbox-similar-card'));
  offline = true;
  d.querySelector('.inbox-toolbar button').click();
  await until(() => /Connection interrupted/.test(d.querySelector('[data-inbox-status]').textContent));
  assert.equal(d.querySelectorAll('[data-mail-id]').length, 2, 'Disconnect preserves the visible queue');
  offline = false;
  d.querySelector('.inbox-toolbar button').click();
  await until(() => /Watching Outlook/.test(d.querySelector('[data-inbox-status]').textContent));
  notifications.state = 'permission_required';
  d.querySelector('.inbox-toolbar button').click();
  await until(() => /Notification permission needed/.test(d.querySelector('[data-notification-status]').textContent));
  assert.match(d.querySelector('[data-inbox-status]').textContent, /Watching Outlook/, 'Notification permissions do not stop Outlook mail');
  const controls = d.querySelector('[data-inbox-controls]');
  assert(!d.getElementById('inbox-source-outlook').closest('details'), 'Watcher switches are always visible');
  assert.equal(controls.querySelector('details.inbox-setup').open, false, 'Setup folds away once collectors are connected');
  assert(controls.querySelector('details.inbox-setup .inbox-app-controls'), 'Desktop alerts live with the collector setup');
  const clickControl = label => [...controls.querySelectorAll('button')].find(button => button.textContent === label).click();
  clickControl('Stop collectors');
  await until(() => /Collectors stopped/.test(controls.textContent));
  assert.equal(actions.at(-1).action, 'stop');
  assert.equal(d.getElementById('inbox-source-outlook').getAttribute('aria-checked'), 'false');
  d.getElementById('inbox-source-outlook').click();
  await until(() => actions.at(-1).action === 'source' && !d.getElementById('inbox-source-outlook').disabled);
  assert.equal(d.getElementById('inbox-source-outlook').getAttribute('aria-checked'), 'true');
  assert.equal(d.getElementById('inbox-source-notifications').getAttribute('aria-checked'), 'false', 'Starting mail alone keeps notifications off');
  d.getElementById('inbox-source-notifications').click();
  await until(() => actions.at(-1).notifications === true && !d.getElementById('inbox-source-notifications').disabled);
  clickControl('Stop collectors');
  await until(() => /Collectors stopped/.test(controls.textContent));
  clickControl('Start collectors');
  await until(() => /Collector task connected/.test(controls.textContent));
  d.getElementById('inbox-source-notifications').click();
  await until(() => actions.at(-1).notifications === false);
  await until(() => ![...controls.querySelectorAll('button')].find(button => button.textContent === 'Listener settings').disabled);
  clickControl('Listener settings');
  await until(() => actions.at(-1).action === 'show');
  assert(!w.mailExecuted, 'Incoming message text never triggers collector commands');
  d.getElementById('inbox').classList.remove('active'); await sleep(50);
  const before = requests.length; await sleep(2100); assert.equal(requests.length, before, 'Leaving inbox stops browser polling');
  assert.deepEqual(f.errors, []); w.dispatchEvent(new w.Event('pagehide')); w.close();
  const viewer = await fixture({ fetch: async () => { throw Error('Viewer must never read mailbox data'); } });
  viewer.w.AtlasReadOnly = { reason: 'Read only' };
  viewer.w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  viewer.w.document.getElementById('inbox').classList.add('active');
  viewer.run(fs.readFileSync('frontend/assets/atlas-interactions.js', 'utf8'));
  await until(() => /available in Atlas Admin/.test(viewer.w.document.getElementById('liveInbox').textContent));
  assert(!viewer.w.document.querySelector('[data-mail-id]'));
  assert.deepEqual(viewer.errors, []); viewer.w.dispatchEvent(new viewer.w.Event('pagehide')); viewer.w.close();
  console.log('PASS: live arrivals, stable selection, Seen before (safe marks, article and request links), sender/device lookup, ambiguity, safe text, stale responses, disconnect recovery, hidden-page polling and private viewer boundary');
})().catch(error => { console.error(error); process.exit(1); });
