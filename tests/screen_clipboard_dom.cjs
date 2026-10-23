// The whole clipboard from the browser: screenshots go to OCR, text and copied HTML are analysed,
// a blocked clipboard falls back to Atlas's own read, and Ctrl+V works without any permission.
const assert = require('node:assert/strict'), fs = require('node:fs');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 6000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(20)) if (check()) return;
  throw Error('Clipboard reader did not update in time');
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
const analysis = { kind: 'issue', action: null, packages: [], categories: [], tools: [], machines: [], knowledge: [], warnings: [], search: '' };
const result = (source, title, text) => ({ source, title, text, process: '', truncated: false, match: { kind: 'unmatched', user: null, candidates: [] }, machines: [], analysis });

(async () => {
  const posts = [];
  const f = await fixture({ fetch: async (url, options = {}) => {
    const path = new URL(url, 'http://localhost').pathname;
    if (path === '/api/session') return response({ token: 'fixture-token' });
    if (path === '/api/inbox/control') return response({ configured: true, state: 'running', desired: { running: true, outlook: true, notifications: false } });
    if (path === '/api/inbox/messages') return response({ items: [], total: 0, newest_id: 0, next_after: 0, has_more: false, watcher: { running: true, state: 'watching' } });
    if (path === '/api/screen/image') { posts.push({ path, type: new Headers(options.headers).get('Content-Type'), size: options.body.size }); return response(result('image', 'Pasted screenshot', 'VPN fails on LAPTOP-0001')); }
    if (path.startsWith('/api/screen/')) {
      const body = JSON.parse(options.body); posts.push({ path, body });
      return response(path === '/api/screen/read' ? result('clipboard', 'Notepad', 'from the Atlas session') : { title: body.title, text: body.text, match: { kind: 'unmatched', user: null, candidates: [] }, machines: [], analysis });
    }
    return response({});
  } });
  const { w, run } = f, d = w.document;
  w.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  w.AtlasUI.motion.isReduced = () => true;
  // The browser's clipboard and its permission, scripted per step.
  let items = [], blocked = false;
  const permission = { state: 'prompt', onchange: null };
  Object.defineProperty(w.navigator, 'permissions', { value: { query: async () => permission }, configurable: true });
  Object.defineProperty(w.navigator, 'clipboard', { value: { read: async () => { if (blocked) { const e = Error('Read permission denied.'); e.name = 'NotAllowedError'; throw e; } return items; }, writeText: async () => {} }, configurable: true });
  const item = (type, value) => ({ types: [type], getType: async () => typeof value === 'string' ? new w.Blob([value], { type }) : value });
  run(fs.readFileSync('frontend/assets/atlas-interactions.js', 'utf8'));
  d.getElementById('workspace').classList.remove('active'); d.getElementById('inbox').classList.add('active');
  await until(() => d.querySelector('.screen-reader-bar'));
  const button = label => [...d.querySelectorAll('.screen-reader button')].find(b => b.textContent.startsWith(label));
  const badge = () => d.querySelector('.screen-reader-permission');
  await until(() => badge());
  assert.equal(badge().textContent, 'Clipboard: asks once');
  permission.state = 'granted'; permission.onchange();
  await until(() => badge().textContent === 'Clipboard allowed');
  assert.equal(badge().dataset.tone, 'good');

  // A copied screenshot (Win+Shift+S) goes to OCR as an image.
  items = [item('image/png', new w.Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }))];
  button('Clipboard').click();
  await until(() => d.querySelector('.screen-reader-text textarea')?.value === 'VPN fails on LAPTOP-0001');
  assert.deepEqual(posts.at(-1), { path: '/api/screen/image', type: 'image/png', size: 4 });

  // Copied HTML (Teams, Outlook) becomes plain text; tags never reach the page.
  items = [item('text/html', '<p>Printer <b>jammed</b> on floor 3</p>')];
  button('Clipboard').click();
  await until(() => posts.at(-1).path === '/api/screen/analyse');
  assert.deepEqual(posts.at(-1).body, { title: 'Clipboard', text: 'Printer jammed on floor 3' });

  // Blocked in the browser: Atlas reads its own session's clipboard instead and says how to allow it.
  blocked = true;
  button('Clipboard').click();
  await until(() => posts.at(-1).path === '/api/screen/read');
  assert.deepEqual(posts.at(-1).body, { source: 'clipboard', delay: 0 });
  await until(() => badge().textContent === 'Clipboard blocked');
  assert.equal(badge().dataset.tone, 'bad');

  // Ctrl+V on the page reads what was pasted, with no permission at all; typing into a box is left alone.
  const paste = (target, data) => { const e = new w.Event('paste', { bubbles: true, cancelable: true }); e.clipboardData = data; target.dispatchEvent(e); return e; };
  const before = posts.length;
  const typed = paste(d.querySelector('.screen-reader-text textarea'), { files: [], getData: t => t === 'text/plain' ? 'my own edit' : '' });
  assert(!typed.defaultPrevented, 'Pasting into the text box stays a normal paste');
  await sleep(50); assert.equal(posts.length, before);
  const screenshot = new w.File([new Uint8Array([137, 80, 78, 71, 13])], 'image.png', { type: 'image/png' });
  assert(paste(d.body, { files: [screenshot], getData: () => '' }).defaultPrevented);
  await until(() => posts.length === before + 1);
  assert.deepEqual(posts.at(-1), { path: '/api/screen/image', type: 'image/png', size: 5 });
  paste(d.body, { files: [], getData: t => t === 'text/plain' ? 'Teams keeps crashing, alex@example.test' : '' });
  await until(() => posts.length === before + 2);
  assert.deepEqual(posts.at(-1).body, { title: 'Clipboard', text: 'Teams keeps crashing, alex@example.test' });
  // Another page: Ctrl+V does nothing here.
  d.getElementById('inbox').classList.remove('active');
  paste(d.body, { files: [], getData: () => 'ignored' }); await sleep(50);
  assert.equal(posts.length, before + 2);
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: browser clipboard screenshots go to OCR, copied HTML becomes text, a blocked clipboard falls back and says so, Ctrl+V works on the Live Inbox page only');
  process.exit(0);
})().catch(error => { console.error(error); process.exit(1); });
