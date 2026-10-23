// Read from screen panel in the compiled Live Inbox, with fictional captures only.
// No screenshot, OCR, clipboard or remote machine is used.
const assert = require('node:assert/strict'), fs = require('node:fs');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 6000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(20)) if (check()) return;
  throw Error('Screen reader did not update in time');
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
const sam = id => ({ id, name: 'Sam Green', full_name: 'Sam Green', user_name: 'U' + id, email: `sam${id}@example.test` });
const analysis = { kind: 'issue', action: null, packages: [], categories: [{ id: 'printer', label: 'Printing', matched: ['printer'], tools: ['health'] }], tools: ['health'], machines: [], knowledge: [], warnings: [], search: '' };
const capture = { source: 'window', title: 'Chat | Sam Green | Microsoft Teams', process: 'ms-teams', text: 'The printer <b>is</b> broken', language: 'en-GB', truncated: false,
  match: { kind: 'ambiguous', basis: 'name', user: null, candidates: [sam(2), sam(3)], chosen: false }, machines: [], analysis };

(async () => {
  const posts = []; let release, failNext = false;
  const f = await fixture({ fetch: async (url, options = {}) => {
    const parsed = new URL(url, 'http://localhost');
    if (parsed.pathname === '/api/session') return response({ token: 'fixture-token' });
    if (parsed.pathname === '/api/inbox/control') return response({ configured: true, state: 'running', desired: { running: true, outlook: true, notifications: false } });
    if (parsed.pathname === '/api/inbox/messages') return response({ items: [], total: 0, newest_id: 0, next_after: 0, has_more: false, watcher: { running: true, state: 'watching' } });
    if (parsed.pathname.startsWith('/api/screen/')) {
      const body = JSON.parse(options.body), token = new Headers(options.headers).get('X-Atlas-Token');
      posts.push({ path: parsed.pathname, body, token });
      if (failNext) { failNext = false; return response({ detail: 'Atlas was still in front.' }, 409); }
      if (parsed.pathname === '/api/screen/read') { await new Promise(resolve => release = resolve); return response(capture); }
      const user = body.user_id ? sam(body.user_id) : null;
      return response({ title: body.title, text: body.text, match: { ...capture.match, kind: user ? 'name' : 'ambiguous', user, chosen: !!user },
        machines: user ? [{ name: 'LAPTOP-0003', device_kind: 'laptop', windows_remote_supported: 1, match_type: 'Assigned' }] : [],
        analysis: body.text.includes('install') ? { ...analysis, kind: 'software', action: 'Install', packages: [{ folder: 'Example', display_name: 'Example', score: 1 }] } : analysis });
    }
    return response({});
  } });
  const { w, run } = f, d = w.document;
  w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  w.AtlasUI.motion.isReduced = () => true;
  run(fs.readFileSync('frontend/assets/atlas-interactions.js', 'utf8'));
  d.getElementById('workspace').classList.remove('active'); d.getElementById('inbox').classList.add('active');
  await until(() => d.querySelector('.screen-reader-bar'));
  const button = label => [...d.querySelectorAll('.screen-reader button')].find(b => b.textContent.startsWith(label));
  const status = () => d.querySelector('.screen-reader-bar [role="status"]').textContent;

  // A window read counts down, disables the buttons and sends only the source and delay.
  button('Window in').click();
  await until(() => /Switch to the ticket or chat now… 3/.test(status()));
  assert(button('Clipboard').disabled, 'No second capture while one is running');
  await until(() => posts.length === 1);
  assert.deepEqual(posts[0], { path: '/api/screen/read', body: { source: 'window', delay: 3 }, token: 'fixture-token' });
  release();
  await until(() => d.querySelector('.screen-reader-result'));
  assert.equal(d.querySelector('.screen-reader-text textarea').value, 'The printer <b>is</b> broken', 'Captured text is shown as plain text');
  assert.equal(d.querySelector('.screen-reader b'), null);
  assert.match(d.querySelector('.screen-reader [data-request-kind]').textContent, /Issue/);

  // Two people share the name in the title: choosing one re-analyses with that person.
  [...d.querySelectorAll('.screen-reader .inbox-candidates button')].find(b => b.textContent.includes('sam3@')).click();
  await until(() => d.querySelector('.screen-reader .inbox-person-card h3'));
  assert.deepEqual(posts.at(-1).body, { title: capture.title, text: capture.text, user_id: 3 });
  assert.equal(d.querySelector('.screen-reader .inbox-person-card h3').textContent, 'Sam Green');
  assert(d.querySelector('.screen-reader .inbox-machine-actions'), 'Linked machines get the usual actions');

  // Corrected OCR text is analysed again without another capture.
  const textarea = d.querySelector('.screen-reader-text textarea');
  Object.getOwnPropertyDescriptor(w.HTMLTextAreaElement.prototype, 'value').set.call(textarea, 'please install Example');
  textarea.dispatchEvent(new w.Event('input', { bubbles: true }));
  await sleep(50);
  button('Analyse again').click();
  await until(() => d.querySelector('.screen-reader [data-package="Example"]'));
  assert.equal(posts.at(-1).path, '/api/screen/analyse');
  assert.equal(posts.at(-1).body.text, 'please install Example');
  assert.equal(posts.filter(p => p.path === '/api/screen/read').length, 1);

  // Errors are shown; Close clears the result.
  failNext = true; button('Clipboard').click();
  await until(() => d.querySelector('.screen-reader [role="alert"]'));
  assert.equal(d.querySelector('.screen-reader [role="alert"]').textContent, 'Atlas was still in front.');
  assert.deepEqual(posts.at(-1).body, { source: 'clipboard', delay: 0 });
  button('Close').click(); await until(() => !d.querySelector('.screen-reader-result'));
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Read from screen counts down, blocks parallel captures, sends only source/delay with the session token, shows text safely, resolves shared names, re-analyses corrected text and reports errors');
})().catch(error => { console.error(error); process.exit(1); });
