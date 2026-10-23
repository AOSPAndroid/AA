// Compact Active Directory list view: types, icons, object header, breadcrumb and double-click.
const fs = require('fs'), assert = require('assert/strict'), { JSDOM } = require('jsdom');
(async () => {
  const w = new JSDOM(fs.readFileSync('frontend/index.html', 'utf8'), { runScripts: 'outside-only', url: 'http://localhost/installer' }).window, d = w.document;
  w.S = { target: 'PC01', user: { user_name: 'alice' } }; w.page = () => {};
  const group = (name, scope, category) => ({ name, dn: `CN=${name},OU=Groups,DC=corp,DC=test`, description: 'About ' + name, scope, category, membership: 'Direct' });
  const lookup = { kind: 'user', queried_at: '2026-10-15T09:00:00Z', server: 'Default domain discovery',
    details: { Name: 'Alice Smith', Account: 'alice', Enabled: true, 'Locked out': true, 'Canonical path': 'corp.test/Paris/Users/Alice Smith', 'Distinguished name': 'CN=Alice Smith,OU=Users,DC=corp,DC=test' },
    groups: [group('APP_Paris', 'Global', 'Security'), group('DL_All', 'Universal', 'Distribution'), group('Broken', 'Unavailable', 'Unavailable')], warnings: [] };
  const browse = { base: 'OU=R\\,D,OU=Paris,DC=corp,DC=test', parent: 'OU=Paris,DC=corp,DC=test', items: [
    { name: 'Laptops', kind: 'organizationalUnit', dn: 'OU=Laptops,OU=R\\,D,OU=Paris,DC=corp,DC=test' },
    { name: 'PC01', kind: 'computer', account: 'PC01$', dn: 'CN=PC01,OU=Paris,DC=corp,DC=test' }] };
  const requests = [];
  w.AtlasClient = { request: async (url, options) => { const body = JSON.parse(options.body); requests.push(body); return url.includes('browse') ? browse : lookup; } };
  w.eval(fs.readFileSync('frontend/assets/active-directory.js', 'utf8'));
  d.getElementById('adKind').value = 'user'; d.getElementById('adIdentity').value = 'alice';
  await d.querySelector('#adForm').onsubmit({ preventDefault() {} });

  const header = d.querySelector('.ad-object-header');
  assert.match(header.textContent, /Alice Smith/); assert.match(header.textContent, /corp\.test\/Paris\/Users\/Alice Smith/);
  assert.match(header.textContent, /Lockout: Locked/, 'Account health is visible without expanding anything');
  assert(header.querySelector('.ad-icon svg'));
  assert.deepEqual([...d.querySelectorAll('.ad-groups thead th')].map(th => th.textContent), ['Name', 'Type', 'Membership', 'Description', 'Actions']);
  const types = Object.fromEntries([...d.querySelectorAll('.ad-groups tbody tr')].map(r => [r.querySelector('.ad-object-link').textContent, r.querySelector('.ad-type').textContent]));
  assert.deepEqual(types, { APP_Paris: 'Security Group - Global', Broken: 'Group', DL_All: 'Distribution Group - Universal' });
  const first = d.querySelector('.ad-groups tbody tr');
  assert(first.querySelector('td .ad-icon svg'), 'Each group has an icon');
  assert.equal(first.title, 'CN=APP_Paris,OU=Groups,DC=corp,DC=test');
  assert.equal(first.querySelector('.ad-group-record summary').getAttribute('aria-label'), 'Group details for APP_Paris');

  let opened; w.AtlasAD.browseMembers = dn => { opened = dn; };
  first.querySelector('.ad-type').dispatchEvent(new w.MouseEvent('dblclick', { bubbles: true }));
  assert.equal(opened, 'CN=APP_Paris,OU=Groups,DC=corp,DC=test', 'Double-click opens the group like the Windows console');
  opened = null; first.querySelector('.ad-row-actions button').dispatchEvent(new w.MouseEvent('dblclick', { bubbles: true }));
  assert.equal(opened, null, 'Double-clicking a button does not also open the row');

  const host = d.getElementById('adBrowser');
  await host.querySelector('[data-root]').onclick();
  assert.equal(host.querySelector('.ad-browser-path').textContent, 'corp.test › Paris › R,D', 'Breadcrumb unescapes commas');
  assert.equal(host.querySelector('.ad-browser-path').title, browse.base);
  const rows = host.querySelectorAll('tbody tr');
  assert.deepEqual([...rows].map(r => r.querySelector('.ad-type').textContent), ['Organizational Unit', 'Computer']);
  assert.equal(rows[1].querySelector('.ad-account').textContent, 'PC01$');
  rows[0].querySelector('.ad-type').dispatchEvent(new w.MouseEvent('dblclick', { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual([requests.at(-1).operation, requests.at(-1).base], ['children', 'OU=Laptops,OU=R\\,D,OU=Paris,DC=corp,DC=test']);
  w.close();
  console.log('PASS: AD console view shows object summary, group types and icons, breadcrumb paths, friendly object types and double-click open');
})().catch(e => { console.error(e); process.exit(1); });
