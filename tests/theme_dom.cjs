const assert = require('node:assert/strict');
const { fixture } = require('./ui_fixture.cjs');
(async () => {
  // The fixture's matchMedia matches every query, so "system" means dark here.
  const f = await fixture({ fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }) });
  const { w } = f, d = w.document, html = d.documentElement;
  assert.equal(html.dataset.theme, 'dark', 'Follows the Windows setting until a choice is made');
  const toggle = d.querySelector('.atlas-header-actions > .atlas-theme-toggle');
  assert(toggle, 'The theme button sits in the header, not inside More');
  assert.equal(toggle.getAttribute('aria-pressed'), 'true');
  assert.equal(toggle.getAttribute('aria-label'), 'Switch to light mode');
  toggle.click();
  assert.equal(html.dataset.theme, 'light');
  assert.equal(html.style.colorScheme, 'light');
  assert.equal(w.localStorage.getItem('atlas-theme'), 'light', 'The choice is remembered');
  assert.equal(toggle.getAttribute('aria-label'), 'Switch to dark mode');
  w.AtlasUI.setTheme('dark');
  assert.equal(html.dataset.theme, 'dark');
  assert.equal(toggle.getAttribute('aria-pressed'), 'true');
  w.localStorage.setItem('atlas-theme', 'light');
  w.dispatchEvent(new w.StorageEvent('storage', { key: 'atlas-theme' }));
  assert.equal(html.dataset.theme, 'light', 'Other Atlas tabs follow a change');
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: theme follows Windows by default, header toggle switches and remembers light/dark, other tabs follow');
})().catch((error) => { console.error(error); process.exit(1); });
