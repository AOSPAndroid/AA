// Count-only PWA alerts: no real permission prompts, mail, network or OS notifications.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const { JSDOM } = require('jsdom');
const source = fs.readFileSync('frontend/assets/atlas-app.js', 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };
(async () => {
  const stored = new Map(), alerts = [], calls = [], worlds = [];
  let ids = [1, 2], permission = 'default', prompts = 0, locked = false, closes = 0;
  const storage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) };
  async function world({ viewer = false, admin = true, secure = true } = {}) {
    const dom = new JSDOM('<!doctype html><head>' + (viewer ? '<meta name="atlas-mode" content="viewer">' : '') + '</head><body><div id="inbox"></div></body>', { url: 'http://localhost:8770/installer', runScripts: 'outside-only' });
    const w = dom.window, timers = [], messages = new Map(); worlds.push(w);
    Object.defineProperty(w, 'localStorage', { value: storage });
    w.isSecureContext = secure; w.matchMedia = () => ({ matches: false });
    w.AbortSignal = AbortSignal; w.setTimeout = fn => timers.push(fn); w.clearTimeout = () => {};
    const registration = { showNotification: async (title, options) => alerts.push({ title, options }), getNotifications: async () => [{ close() { closes++; } }] };
    w.Notification = { get permission() { return permission; }, requestPermission: async () => { prompts++; return permission; } };
    Object.defineProperty(w.navigator, 'locks', { value: { request: async (name, options, task) => {
      if (locked) return task(null); locked = true;
      try { return await task({}); } finally { locked = false; }
    } } });
    Object.defineProperty(w.navigator, 'serviceWorker', { value: { register: async () => registration, ready: Promise.resolve(registration), addEventListener: (name, fn) => messages.set(name, fn) } });
    w.fetch = async url => {
      calls.push(url);
      if (url === '/api/app') return { ok: admin, json: async () => ({ mode: admin ? 'admin' : 'viewer' }) };
      const cursor = Number(new URL(url, w.location.href).searchParams.get('after_id'));
      return { ok: true, json: async () => ({ newest_id: ids.at(-1) || 0, count: ids.filter(id => id > cursor).length }) };
    };
    w.eval(source); await flush();
    return { w, messages, tick: async () => { assert(timers.length, 'poll scheduled'); await timers.shift()(); await flush(); } };
  }
  const one = await world();
  assert(one.w.AtlasApp.snapshot().available);
  assert.equal(one.w.document.querySelector('link[rel=manifest]').getAttribute('href'), '/atlas.webmanifest');
  assert.equal(prompts, 0, 'Permission is never requested on page load');
  assert(!calls.some(url => url.startsWith('/api/inbox')), 'No queue polling until opted in');
  permission = 'denied'; await one.w.AtlasApp.setAlerts(true);
  assert(!one.w.AtlasApp.snapshot().enabled); assert.match(one.w.AtlasApp.snapshot().error, /not allowed/);
  permission = 'granted'; await one.w.AtlasApp.setAlerts(true); await one.tick();
  assert.equal(alerts.length, 0, 'Existing messages are baselined without replay');
  const two = await world();
  ids.push(4, 7);
  await Promise.all([one.tick(), two.tick()]);
  assert.equal(alerts.length, 1, 'Parallel windows emit only one alert');
  assert.match(alerts[0].title, /2 new items/);
  assert.equal(alerts[0].options.body, 'Open Live Inbox to see the sender and linked machines.');
  assert(!JSON.stringify(alerts).includes('example.test'));
  let opened = false; one.w.addEventListener('atlas:open-inbox', () => opened = true);
  one.messages.get('message')({ data: { type: 'atlas-open-inbox' } }); assert(opened);
  await one.w.AtlasApp.setAlerts(false); ids.push(8); await two.tick();
  assert.equal(alerts.length, 1); assert.equal(closes, 1);
  const requestsBeforeViewer = calls.length;
  const viewer = await world({ viewer: true });
  assert(!viewer.w.AtlasApp.snapshot().available); assert.equal(calls.length, requestsBeforeViewer);
  const demoDesktop = await world({ admin: false }); assert(!demoDesktop.w.AtlasApp.snapshot().available);
  const insecure = await world({ secure: false }); assert(!insecure.w.AtlasApp.snapshot().available);
  await one.w.AtlasApp.setAlerts(true); await one.tick(); ids = [1]; await one.tick();
  assert.equal(stored.get('atlas-alert-cursor'), '1', 'Queue reset resets cursor without an alert');
  await one.w.AtlasApp.install(); assert.match(one.w.AtlasApp.snapshot().status, /Apps/);
  for (const w of worlds) { w.dispatchEvent(new w.Event('pagehide')); w.close(); }

  const events = new Map(), focused = [], posted = [], windows = [];
  const self = { location: { origin: 'http://localhost:8770' }, addEventListener: (name, fn) => events.set(name, fn), skipWaiting: async () => {}, clients: { claim: async () => {}, matchAll: async () => windows, openWindow: async url => posted.push(url) } };
  vm.runInNewContext(fs.readFileSync('frontend/atlas-sw.js', 'utf8'), { self, URL, Response, fetch: async () => { throw Error('Server stopped'); } });
  let offline;
  events.get('fetch')({ request: { url: 'http://localhost:8770/installer', mode: 'navigate' }, respondWith: promise => offline = promise });
  const response = await offline; assert.equal(response.status, 503); assert.match(await response.text(), /Start AA\.bat/);
  events.get('fetch')({ request: { url: 'http://localhost:8770/api/inbox/messages', mode: 'cors' }, respondWith: () => assert.fail('Never intercept or cache mail API') });
  windows.push({ url: 'http://localhost:8770/installer', frameType: 'nested', focus: () => assert.fail('Do not target iframe') });
  windows.push({ url: 'http://localhost:8770/installer?command=workspace', frameType: 'top-level', focus: async () => focused.push(true), postMessage: value => posted.push(value) });
  let clicked;
  const click = () => events.get('notificationclick')({ notification: { close() {}, data: { url: 'https://untrusted.test/' } }, waitUntil: promise => clicked = promise });
  click(); await clicked; assert.equal(focused.length, 1); assert.equal(posted[0].type, 'atlas-open-inbox');
  windows.length = 0; click(); await clicked; assert.equal(posted[1], '/installer?command=inbox');
  console.log('PASS: PWA opt-in, denied permission, no history replay, cross-window deduplication, generic alerts, stop/reset, viewer isolation, click routing and offline fallback');
})().catch(error => { console.error(error); process.exitCode = 1; });
