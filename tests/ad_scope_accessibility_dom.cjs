// Fictional AD responses only; no directory or Windows transport is used.
const fs = require('node:fs'), assert = require('node:assert/strict'), {JSDOM} = require('jsdom');
const code = fs.readFileSync('frontend/assets/active-directory.js', 'utf8');
const html = fs.readFileSync('frontend/index.html', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture(request) {
  const w = new JSDOM(html, {runScripts: 'outside-only', url: 'http://localhost/installer'}).window;
  w.S = {};w.page = () => {};
  w.HTMLElement.prototype.scrollIntoView = function () {};
  w.AtlasClient = {request};
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async () => {}}});
  w.eval(code);
  return w;
}
const group = name => ({name, dn: `CN=${name},OU=Apps,DC=example,DC=invalid`, membership: 'Direct'});
const result = (server, groups, details = {}) => ({server, groups, details: {Account: 'fictional.user', ...details}, warnings: [], queried_at: '2026-10-07T12:00:00Z'});
const findButton = (root, text) => [...root.querySelectorAll('button')].find(button => button.textContent === text);

(async () => {
  const requests = [];
  const w = fixture(async (url, options) => {
    requests.push(JSON.parse(options.body));
    return requests.length === 1 ? result('dc-primary.example.invalid', [group('Primary'), group('Shared')])
      : result('dc-secondary.example.invalid', [group('Secondary'), group('Shared')]);
  });
  const d = w.document;
  d.getElementById('adServer').value = 'requested-primary.example.invalid';
  await d.getElementById('adForm').onsubmit({preventDefault() {}});
  assert.equal(d.querySelector('[aria-label="Comparison domain or controller"]').value, 'dc-primary.example.invalid');
  d.querySelector('[aria-label="Compare AD object"]').value = 'fictional.other';
  d.querySelector('[aria-label="Comparison domain or controller"]').value = 'requested-secondary.example.invalid';
  await d.querySelector('#adResults form').onsubmit({preventDefault() {}});
  const opened = [];
  w.AtlasAD.browseMembers = (dn, server) => opened.push({dn, server});
  // A form change or re-filter cannot redirect actions from an existing result.
  d.getElementById('adServer').value = 'unrelated.example.invalid';
  d.querySelector('[aria-label="Comparison domain or controller"]').value = 'unrelated-comparison.example.invalid';
  d.querySelector('[aria-label="Membership comparison"]').value = 'all';
  d.querySelector('[aria-label="Filter AD groups"]').oninput();
  for (const name of ['Primary', 'Secondary', 'Shared']) findButton(d.querySelector('.ad-groups'), name).click();
  assert.deepEqual(opened.map(item => item.server), ['dc-primary.example.invalid', 'dc-secondary.example.invalid', 'dc-primary.example.invalid']);
  assert.equal(requests[1].server, 'requested-secondary.example.invalid');
  w.close();

  const defaultWindow = fixture(async () => result('Default domain discovery', [group('DefaultGroup')], {'Password expired': false, 'Password expires': '2026-10-06T12:00:00Z'}));
  defaultWindow.document.getElementById('adKind').value = 'user';
  await defaultWindow.document.getElementById('adForm').onsubmit({preventDefault() {}});
  let defaultScope;
  defaultWindow.AtlasAD.browseMembers = (dn, server) => {defaultScope = server;};
  findButton(defaultWindow.document.querySelector('.ad-groups'), 'DefaultGroup').click();
  assert.equal(defaultScope, '', 'The display label for default discovery must not become a controller hostname');
  const health = [...defaultWindow.document.querySelectorAll('.ad-health-strip > span')].find(badge => badge.textContent.startsWith('Password:'));
  assert(health.textContent.startsWith('Password: Expired '), health.textContent);
  assert(health.classList.contains('ad-health-bad'));
  defaultWindow.close();

  const browseRequests = [];
  const browserWindow = fixture(async (url, options) => {
    browseRequests.push(JSON.parse(options.body));
    return {server: 'dc-resolved.example.invalid', base: 'DC=example,DC=invalid', parent: '', more: false,
      items: [{kind: 'organizationalUnit', name: 'Fictional OU', dn: 'OU=Fictional,DC=example,DC=invalid'},
        {kind: 'group', name: 'Fictional group', dn: 'CN=Fictional,DC=example,DC=invalid'},
        {kind: 'user', name: 'Fictional user', account: 'fictional.user', guid: '00000000-0000-0000-0000-000000000001', dn: 'CN=User,DC=example,DC=invalid'}]};
  });
  const browser = browserWindow.document.getElementById('adBrowser');
  browser.querySelector('[name="server"]').value = 'requested.example.invalid';
  await browser.querySelector('[data-root]').onclick();
  await findButton(browser, 'Open').onclick();
  assert.equal(browseRequests.at(-1).server, 'dc-resolved.example.invalid');
  browser.querySelector('[name="query"]').value = 'Fictional';
  await browser.querySelector('form').onsubmit({preventDefault() {}});
  // Submit delegates asynchronously, so wait for the mock response to render.
  await tick();
  assert.equal(browseRequests.at(-1).server, 'dc-resolved.example.invalid');
  assert.equal(browseRequests.at(-1).base, 'DC=example,DC=invalid', 'Scoped searches keep the captured browser base');
  let memberServer, userServer;
  browserWindow.AtlasAD.browseMembers = (dn, server) => {memberServer = server;};
  browserWindow.AtlasAD.show = () => {userServer = browserWindow.document.getElementById('adServer').value;};
  findButton(browser, 'See members').click();findButton(browser, 'See groups').click();
  assert.equal(memberServer, 'dc-resolved.example.invalid');assert.equal(userServer, 'dc-resolved.example.invalid');
  await findButton(browser, 'Properties').onclick();assert.equal(browseRequests.at(-1).server, 'dc-resolved.example.invalid');
  browserWindow.close();

  const keyboardWindow = fixture(async () => {throw new Error('Keyboard navigation must not request AD');});
  const kd = keyboardWindow.document, row = kd.createElement('tr'), name = kd.createElement('td'), actions = kd.createElement('td');
  row.append(name, actions);kd.body.append(row);
  let reads = 0;
  keyboardWindow.AtlasADRows.attach(row, name, actions, {kind: 'group', name: 'FictionalGroup'}, 'captured', () => reads++);
  const origin = name.querySelector('button');origin.focus();
  const key = (element, value, extra = {}) => element.dispatchEvent(new keyboardWindow.KeyboardEvent('keydown', {key: value, bubbles: true, cancelable: true, ...extra}));
  key(origin, 'F10', {shiftKey: true});
  const menu = () => kd.querySelector('.atlas-ad-context[role="menu"]');
  assert.equal(kd.activeElement.textContent, 'Copy group name');
  key(kd.activeElement, 'ArrowDown');assert.equal(kd.activeElement.textContent, 'See members');
  key(kd.activeElement, 'ArrowDown');assert.equal(kd.activeElement.textContent, 'Copy group name');
  key(kd.activeElement, 'End');assert.equal(kd.activeElement.textContent, 'See members');
  key(kd.activeElement, 'Home');assert.equal(kd.activeElement.textContent, 'Copy group name');
  key(kd.activeElement, 'ArrowUp');assert.equal(kd.activeElement.textContent, 'See members');
  key(kd.activeElement, 'Escape');assert.equal(menu(), null);assert.equal(kd.activeElement, origin);assert.equal(reads, 0);
  key(row, 'ContextMenu');assert(menu());key(kd.activeElement, 'Tab');assert.equal(menu(), null);assert.equal(kd.activeElement, row);
  const dialog = kd.createElement('dialog');dialog.open = true;kd.body.append(dialog);dialog.append(row);
  key(origin, 'F10', {shiftKey: true});assert(dialog.contains(menu()), 'Menus from modal rows stay in the same top layer');
  key(kd.activeElement, 'Escape');assert.equal(kd.activeElement, origin);
  kd.body.append(row);dialog.remove();
  keyboardWindow.AtlasReadOnly = true;
  key(row, 'ContextMenu');assert.equal(kd.activeElement.textContent, 'Copy group name');
  key(kd.activeElement, 'ArrowDown');assert.equal(kd.activeElement.textContent, 'Copy group name', 'Disabled AD requests are skipped');
  findButton(menu(), 'See members').click();assert.equal(reads, 0);
  key(kd.activeElement, 'Escape');await tick();keyboardWindow.close();
  console.log('PASS: captured AD controller scopes, default discovery, past password expiry, context keyboard navigation and focus return');
})().catch(error => {console.error(error);process.exit(1);});
