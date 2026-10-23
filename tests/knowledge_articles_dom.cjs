// Knowledge Base articles: Articles/Diagrams modes, list and tags, safe search highlights, Markdown + Mermaid
// rendering, template editor payload, article links from Live Inbox, and the read-only Demo.
const assert = require('node:assert/strict');
const { fixture } = require('./ui_fixture.cjs');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const ARTICLE = { id: 'outlook', title: 'Outlook keeps freezing', tags: ['outlook', 'email'], categories: ['outlook'], revision: 3,
  created: '2026-10-01T09:00:00Z', updated: '2026-10-02T09:00:00Z',
  markdown: '## Fix\n[Wiki](https://wiki.example)\n\n```mermaid\nflowchart TD\n A --> B\n```\n<script>bad()</script>' };
const LISTED = [{ ...ARTICLE, markdown: undefined, excerpt: 'Fix Wiki' }, { id: 'vpn', title: 'VPN', tags: ['network'], categories: [], revision: 1, updated: '2026-10-01T09:00:00Z', excerpt: 'Checks' }];

function api(requests) {
  return async (url, o = {}) => {
    requests.push({ url, method: o.method || 'GET', body: o.body, token: o.headers && (o.headers['X-Atlas-Token'] || o.headers.get?.('X-Atlas-Token')) });
    let data = {};
    if (url === '/api/session') data = { token: 'test' };
    else if (url === '/api/knowledge') data = { documents: [] };
    else if (url === '/api/knowledge/article-categories') data = { categories: [{ id: 'outlook', label: 'Outlook or email' }, { id: 'network', label: 'Network, VPN or Wi-Fi' }] };
    else if (url === '/api/knowledge/articles') data = { articles: LISTED };
    else if (url.startsWith('/api/knowledge/articles/') && o.method === 'PUT') data = { revision: JSON.parse(o.body).revision + 1, updated: '2026-10-03T09:00:00Z' };
    else if (url.startsWith('/api/knowledge/articles/')) data = { ...ARTICLE, id: decodeURIComponent(url.split('/').pop()) };
    else if (url.startsWith('/api/search-everything')) data = { results: [
      { kind: 'article', ref: 'outlook', title: 'Outlook keeps \u0002freezing\u0003', snippet: '<img src=x onerror=bad()> \u0002freezes\u0003', at: '', extra: { tags: ['outlook'] } },
      { kind: 'inbox', ref: '7', title: 'Outlook \u0002freezes\u0003', snippet: 'Hi', at: '2026-10-01', extra: {} },
      { kind: 'deployment', ref: '9', title: 'Install Teams on LT-PAR-0042', snippet: 'Done', at: '2026-10-01', extra: { target: 'LT-PAR-0042', package: 'Teams', action: 'Install', state: 'Done' } }] };
    else if (url.includes('/catalog')) data = { items: [] };
    else if (url.includes('/scripts')) data = { scripts: [] };
    else if (url.includes('/deployments')) data = { deployments: [] };
    return { ok: true, status: 200, headers: { get: () => null }, json: async () => data };
  };
}

function fakeLibraries(w, calls) {
  w.marked = { parse: (text) => { calls.marked.push(text); return text.replace(/^## (.*)$/m, '<h2>$1</h2>').replace(/\[(.*?)\]\((.*?)\)/, '<a href="$2">$1</a>')
    .replace(/```mermaid\n([\s\S]*?)```/, '<pre><code class="language-mermaid">$1</code></pre>'); } };
  w.DOMPurify = { sanitize: (html) => { calls.sanitize++; return html.replace(/<script[\s\S]*?<\/script>/g, ''); } };
  w.mermaid = { initialize: (config) => calls.mermaidConfig.push(config), render: async (id, code) => { calls.mermaid.push(code); return { svg: `<svg id="${id}"><text>A</text></svg>` }; } };
}

(async () => {
  const requests = [], calls = { marked: [], sanitize: 0, mermaid: [], mermaidConfig: [] };
  const f = await fixture({ fetch: api(requests) });
  fakeLibraries(f.w, calls);
  await f.console();
  const { w } = f, d = w.document, A = w.AtlasKnowledge, K = w.AtlasKnowledgeArticles;
  assert(K, 'The articles script loads with the console');
  assert.equal(d.querySelector('.kb-articles'), null, 'Nothing is built until the Knowledge Base opens');
  await A.open(); await sleep(20);
  const kb = d.getElementById('knowledge');
  assert.equal(kb.dataset.kbMode, 'articles', 'Articles are the default view');
  const [articlesTab, diagramsTab] = kb.querySelectorAll('.kb-modes [role="tab"]');
  assert.equal(articlesTab.getAttribute('aria-selected'), 'true');
  assert.deepEqual([...kb.querySelectorAll('.kb-result strong')].map((s) => s.textContent), ['Outlook keeps freezing', 'VPN']);
  assert.deepEqual([...kb.querySelectorAll('.kb-tag-filter button')].map((b) => b.textContent), ['email 1', 'network 1', 'outlook 1']);
  kb.querySelector('.kb-tag-filter button:nth-child(2)').click();
  assert.deepEqual([...kb.querySelectorAll('.kb-result strong')].map((s) => s.textContent), ['VPN'], 'Tag chips filter the list');
  assert.match(kb.querySelector('.kb-article-list [role="status"]').textContent, /1 article tagged network/);
  kb.querySelector('.kb-tag-filter button:nth-child(2)').click();
  assert.equal(kb.querySelectorAll('.kb-result').length, 2, 'Clicking the chip again clears the filter');

  // Viewing: Markdown is sanitised, links open outside Atlas, Mermaid draws with plain-text labels.
  kb.querySelector('.kb-result').click(); await sleep(20);
  const view = kb.querySelector('.kb-article-view');
  assert.equal(view.querySelector('.kb-article-head h2').textContent, 'Outlook keeps freezing');
  assert.deepEqual([...view.querySelectorAll('.kb-category')].map((c) => c.textContent), ['Outlook or email']);
  assert.equal(view.querySelector('.kb-markdown h2').textContent, 'Fix');
  assert.equal(view.querySelector('.kb-markdown script'), null);
  assert.equal(view.querySelector('.kb-markdown a').target, '_blank');
  assert.equal(view.querySelector('.kb-markdown a').rel, 'noopener noreferrer');
  assert.equal(view.querySelector('.kb-mermaid svg text').textContent, 'A');
  assert.equal(view.querySelector('code.language-mermaid'), null, 'The diagram replaces its code block');
  assert.equal(calls.mermaidConfig[0].securityLevel, 'strict');
  assert.equal(calls.mermaidConfig[0].htmlLabels, false, 'No HTML labels, which the sanitiser would strip');
  assert.equal(calls.sanitize, 2, 'Both the Markdown and the diagram SVG are sanitised');
  assert.equal(kb.querySelector('.kb-result[aria-current="true"] strong').textContent, 'Outlook keeps freezing');

  // Search: highlights become <mark> elements; result text is never parsed as HTML.
  const search = kb.querySelector('.kb-article-search input[type="search"]');
  search.value = 'freez'; search.dispatchEvent(new w.Event('input')); await sleep(260);
  assert.match(requests.at(-1).url, /\/api\/search-everything\?q=freez&kinds=article&limit=40/);
  kb.querySelector('.kb-scope input').click(); await sleep(20);
  assert.match(requests.at(-1).url, /kinds=article,diagram,inbox,deployment/, 'Everything adds requests, deployments and diagrams');
  assert.equal(kb.querySelectorAll('.kb-result').length, 3);
  assert.deepEqual([...kb.querySelectorAll('.kb-result mark')].map((m) => m.textContent), ['freezing', 'freezes', 'freezes']);
  assert.equal(kb.querySelector('.kb-result img'), null, 'Snippet markup stays text');
  assert.match(kb.querySelector('.kb-result-text').textContent, /<img src=x/);
  assert.deepEqual([...kb.querySelectorAll('.kb-kind')].map((k) => k.textContent), ['Article', 'Request', 'Deployment']);

  let opened = null;
  w.addEventListener('atlas:inbox-open', (e) => { opened = e.detail.id; });
  kb.querySelector('.kb-kind-inbox').closest('button').click(); await sleep(10);
  assert.equal(opened, 7, 'A past request opens in Live Inbox');
  assert(d.getElementById('inbox').classList.contains('active'));
  kb.querySelector('.kb-kind-deployment').closest('button').click();
  assert.deepEqual([...view.querySelectorAll('.kb-deployment dd')].slice(0, 4).map((x) => x.textContent), ['LT-PAR-0042', 'Teams', 'Install', 'Done']);
  assert.match([...view.querySelectorAll('button')].at(-1).textContent, /Select this machine/);

  // Editor: a template fills the form; saving sends tags, categories and revision 0 with the session token.
  const templates = kb.querySelector('.kb-article-list select');
  templates.value = '3'; templates.dispatchEvent(new w.Event('change')); await sleep(300);
  const form = view.querySelector('.kb-article-editor');
  assert.equal(form.querySelector('input[aria-label="Article title"]').value, 'VPN or network');
  assert.equal(form.querySelector('input[value="network"]').checked, true);
  assert(form.querySelector('textarea').value.includes('```mermaid'));
  assert(form.querySelector('.kb-preview .kb-mermaid'), 'Live preview draws the template diagram');
  form.querySelector('input[aria-label="Tags"]').value = 'vpn, network, , remote';
  form.querySelector('.kb-md-tools button[title="Bold"]').click();
  assert(form.querySelector('textarea').value.includes('**text**'), 'Toolbar inserts Markdown');
  form.dispatchEvent(new w.KeyboardEvent('keydown', { key: 's', ctrlKey: true, bubbles: true })); await sleep(30);
  const put = requests.find((r) => r.method === 'PUT');
  assert.match(put.url, /^\/api\/knowledge\/articles\/vpn-or-network-[a-z0-9]+$/);
  const payload = JSON.parse(put.body);
  assert.deepEqual([payload.title, payload.tags, payload.categories, payload.revision], ['VPN or network', ['vpn', 'network', 'remote'], ['network'], 0]);
  assert.equal(put.token, 'test');
  assert.equal(K.state.editing, false);

  // Empty title is refused before any request.
  templates.value = '6'; templates.dispatchEvent(new w.Event('change'));
  const puts = requests.filter((r) => r.method === 'PUT').length;
  view.querySelector('.kb-article-editor').dispatchEvent(new w.Event('submit', { cancelable: true })); await sleep(10);
  assert.equal(requests.filter((r) => r.method === 'PUT').length, puts);
  assert.match(view.querySelector('.kb-article-editor [role="status"]').textContent, /title/);
  view.querySelector('.kb-article-editor .kb-article-actions button[type="button"]').click(); await sleep(10);

  // Live Inbox links: article ids open the article; anything else is a diagram.
  diagramsTab.click();
  assert.equal(kb.dataset.kbMode, 'diagrams');
  assert.equal(w.localStorage.getItem('atlas.kb.mode'), 'diagrams', 'The chosen view is remembered');
  await A.show('article:vpn'); await sleep(20);
  assert.equal(kb.dataset.kbMode, 'articles');
  assert(requests.some((r) => r.url === '/api/knowledge/articles/vpn'));
  await A.show('network-map').catch(() => {});
  assert.equal(kb.dataset.kbMode, 'diagrams');
  assert.deepEqual(f.errors, []);
  w.close();

  // Read-only Demo: no article requests, Diagrams remain.
  const demoRequests = [];
  const demo = await fixture({ fetch: api(demoRequests) });
  fakeLibraries(demo.w, { marked: [], sanitize: 0, mermaid: [], mermaidConfig: [] });
  demo.w.AtlasReadOnly = {};
  await demo.console();
  await demo.w.AtlasKnowledge.open(); await sleep(20);
  assert.match(demo.w.document.querySelector('.kb-article-view').textContent, /stored in Atlas Admin/);
  assert.equal(demo.w.document.querySelector('.kb-article-list select').disabled, true);
  assert(!demoRequests.some((r) => r.url.includes('/articles')), 'The Demo never asks for articles');
  demo.w.close();
  console.log('PASS: KB articles default view, tag filter, sanitised Markdown + Mermaid, safe search marks, Everything search to Live Inbox and deployments, template editor payload, title check, article links from Live Inbox, remembered mode, read-only Demo');
})().catch((e) => { console.error(e); process.exit(1); });
