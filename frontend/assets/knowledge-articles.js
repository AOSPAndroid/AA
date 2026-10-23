/* Knowledge Base articles: Markdown runbooks with live preview, tags, issue categories and
   Mermaid diagrams, plus "search everything" across articles, diagrams, Live Inbox requests and
   deployments. Draw.io diagrams stay available under the Diagrams tab. Markdown is rendered with
   marked and sanitised with DOMPurify; Mermaid loads only for articles that contain a diagram. */
(() => {
  const root = () => document.getElementById("knowledge");
  const meta = document.querySelector('meta[name="atlas-kb-assets"]');
  if (!root() || !meta || !window.AtlasKnowledge) return;
  const assets = meta.content.split(/\s+/).filter(Boolean);
  const asset = (name) => assets.find((url) => url.includes("/" + name + "-"));
  const readonly = () => !!window.AtlasReadOnly;
  const MODE_KEY = "atlas.kb.mode";
  const state = { articles: [], categories: [], current: null, editing: false, tag: "", query: "", everything: false, serial: 0 };
  const loaded = {};
  let ui = null, mermaidId = 0, searchTimer = 0, previewTimer = 0;

  const TEMPLATES = [
    ["Software install request", ["software"], [], "## When to use\nA user asks for an application to be installed.\n\n## Steps\n1. Check the request is approved.\n2. Find the package in **Packages** and confirm the Install script.\n3. Deploy from **Live Inbox → Install…** or add it to the queue.\n4. Ask the user to restart the application.\n\n## Notes\n- "],
    ["Slow or freezing PC", ["performance"], ["slow"], "## Checks\n- [ ] Health check: disk space and uptime\n- [ ] Performance scan: top CPU and memory processes\n- [ ] Pending reboot?\n\n## Fix\n1. \n\n## Escalate when\n- "],
    ["Outlook problem", ["outlook", "email"], ["outlook"], "## Symptoms\n- \n\n## Fix\n1. Close Outlook.\n2. Start it once with `outlook.exe /safe`.\n3. \n\n## Escalate when\n- "],
    ["VPN or network", ["network", "vpn"], ["network"], "## Checks\n- [ ] Machine replies to ping\n- [ ] VPN group in **Machine's AD groups**\n\n## Fix\n1. \n\n```mermaid\nflowchart TD\n  A[User cannot connect] --> B{Ping OK?}\n  B -->|Yes| C[Check VPN group]\n  B -->|No| D[Check network cable / Wi-Fi]\n```\n"],
    ["Printer", ["printing"], ["printer"], "## Checks\n- [ ] Printer queue\n- [ ] User's AD printer groups\n\n## Fix\n1. "],
    ["Locked account or password", ["account"], ["account"], "## Checks\n- [ ] **User's AD groups** → Account health: locked out? password expired?\n\n## Fix\n1. "],
    ["Blank article", [], [], ""],
  ];

  function load(url) {
    return (loaded[url] ||= new Promise((resolve, reject) => {
      const script = Object.assign(document.createElement("script"), { src: url });
      script.onload = resolve;
      script.onerror = () => { delete loaded[url]; reject(Error("Could not load " + url)); };
      document.head.append(script);
    }));
  }
  const markdownReady = () => window.marked && window.DOMPurify ? Promise.resolve()
    : Promise.all([load(asset("marked")), load(asset("dompurify"))]);
  async function mermaidReady() {
    if (!window.mermaid) await load(asset("mermaid"));
    // Re-initialised when the theme changes so diagrams match light or dark mode.
    const theme = window.AtlasUI?.theme?.() === "dark" ? "dark" : "neutral";
    if (mermaidReady.done !== theme) {
      // Plain SVG text labels (no embedded HTML), so the sanitiser keeps them.
      window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme, htmlLabels: false, flowchart: { htmlLabels: false } });
      mermaidReady.done = theme;
    }
  }

  const el = (tag, props = {}, ...children) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const child of children) if (child != null) node.append(child);
    return node;
  };
  const button = (label, onclick, extra = {}) => el("button", { type: "button", textContent: label, onclick, ...extra });
  // Search highlights arrive as \u0002…\u0003 markers; build <mark> elements instead of parsing HTML.
  function marked_(text) {
    const span = el("span");
    String(text || "").split(/(\u0002[^\u0003]*\u0003)/).forEach((part) => {
      if (part.startsWith("\u0002")) span.append(el("mark", { textContent: part.slice(1, -1) }));
      else if (part) span.append(document.createTextNode(part));
    });
    return span;
  }
  const date = (value) => value ? new Date(value).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "";
  const label = (id) => state.categories.find((c) => c.id === id)?.label || id;
  const api = (url, options) => window.AtlasClient.request(url, options);
  const slug = (title) => (String(title).toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-").slice(0, 60) || "article") + "-" + Date.now().toString(36);

  async function render(markdown, target) {
    await markdownReady();
    target.innerHTML = window.DOMPurify.sanitize(window.marked.parse(String(markdown || ""), { gfm: true }));
    for (const link of target.querySelectorAll("a[href]")) Object.assign(link, { target: "_blank", rel: "noopener noreferrer" });
    const blocks = [...target.querySelectorAll("pre > code.language-mermaid")];
    if (!blocks.length) return;
    try { await mermaidReady(); }
    catch { blocks.forEach((code) => code.parentElement.before(el("p", { className: "kb-note", textContent: "Diagram viewer unavailable; showing its text." }))); return; }
    for (const code of blocks) {
      try {
        const { svg } = await window.mermaid.render("kb-mermaid-" + ++mermaidId, code.textContent);
        const figure = el("div", { className: "kb-mermaid" });
        figure.innerHTML = window.DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
        if (code.isConnected) code.parentElement.replaceWith(figure);
      } catch (error) {
        code.parentElement.before(el("p", { className: "kb-note", textContent: "Diagram error: " + String(error.message || error).split("\n")[0] }));
      }
    }
  }

  function setMode(mode) {
    root().dataset.kbMode = mode;
    try { localStorage.setItem(MODE_KEY, mode); } catch {}
    ui?.tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.mode === mode)));
    if (mode === "diagrams") window.dispatchEvent(new Event("resize"));
  }

  function install() {
    const host = root();
    if (!host || host.querySelector(".kb-articles")) return;
    const tabs = [button("Articles", () => setMode("articles")), button("Diagrams", () => setMode("diagrams"))];
    tabs[0].dataset.mode = "articles"; tabs[1].dataset.mode = "diagrams";
    tabs.forEach((tab) => tab.setAttribute("role", "tab"));
    const bar = el("div", { className: "kb-modes", role: "tablist" }, ...tabs);
    bar.setAttribute("aria-label", "Knowledge Base views");
    const search = el("input", { type: "search", placeholder: "Search articles…", maxLength: 300 });
    search.setAttribute("aria-label", "Search the Knowledge Base");
    const everything = el("input", { type: "checkbox" });
    const scope = el("label", { className: "kb-scope", title: "Also search past Live Inbox requests, deployments and diagrams" }, everything, " Everything");
    const templates = el("select");
    templates.setAttribute("aria-label", "New article from template");
    templates.append(el("option", { value: "", textContent: "New article…" }), ...TEMPLATES.map(([name], i) => el("option", { value: String(i), textContent: name })));
    templates.disabled = readonly();
    const tagsBox = el("div", { className: "kb-tag-filter" });
    const list = el("ul", { className: "kb-article-results" });
    list.setAttribute("aria-label", "Articles");
    const status = el("p", { className: "kb-note", role: "status" });
    const view = el("article", { className: "kb-article-view" });
    view.setAttribute("aria-live", "polite");
    const aside = el("aside", { className: "kb-article-list" }, el("div", { className: "kb-article-search" }, search, scope), templates, tagsBox, status, list);
    const section = el("section", { className: "kb-articles" }, aside, view);
    host.prepend(bar, section);
    ui = { tabs, search, everything, templates, tagsBox, list, status, view };
    search.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = search.value.trim(); refreshList(); }, 200); });
    everything.onchange = () => { state.everything = everything.checked; search.placeholder = everything.checked ? "Search articles, requests, deployments…" : "Search articles…"; refreshList(); };
    templates.onchange = () => { const t = TEMPLATES[Number(templates.value)]; templates.value = ""; if (t) edit({ title: t[0] === "Blank article" ? "" : t[0], tags: t[1], categories: t[2], markdown: t[3], revision: 0 }, true); };
    let mode = "articles";
    try { mode = localStorage.getItem(MODE_KEY) || "articles"; } catch {}
    setMode(mode);
    if (readonly()) {
      view.replaceChildren(el("p", { className: "kb-note", textContent: "Articles are stored in Atlas Admin. Use the Diagrams tab for local drafts here." }));
      return;
    }
    refresh();
  }

  async function refresh(select) {
    try {
      const [{ articles }, { categories }] = await Promise.all([api("/api/knowledge/articles"), state.categories.length ? { categories: state.categories } : api("/api/knowledge/article-categories")]);
      state.articles = articles || []; state.categories = categories || [];
    } catch (error) { ui.status.textContent = error.message; return; }
    renderTags(); refreshList();
    if (select) open(select);
    else if (!state.current && !state.editing) welcome();
  }

  function welcome() {
    ui.view.replaceChildren(el("div", { className: "kb-welcome" },
      el("h2", { textContent: "Knowledge Base" }),
      el("p", { textContent: state.articles.length ? "Choose an article, search, or start a new one from a template." : "Write your first runbook: choose New article… and pick a template." }),
      el("p", { className: "kb-note", textContent: "Articles linked to an issue category are suggested automatically in Live Inbox for matching requests." })));
  }

  function renderTags() {
    const counts = {};
    for (const a of state.articles) for (const t of a.tags) counts[t] = (counts[t] || 0) + 1;
    const tags = Object.keys(counts).sort((a, b) => a.localeCompare(b));
    ui.tagsBox.replaceChildren(...tags.map((tag) => {
      const b = button(`${tag} ${counts[tag]}`, () => { state.tag = state.tag === tag ? "" : tag; renderTags(); refreshList(); });
      b.setAttribute("aria-pressed", String(state.tag === tag));
      return b;
    }));
  }

  async function refreshList() {
    const serial = ++state.serial;
    if (!state.query) {
      const shown = state.articles.filter((a) => !state.tag || a.tags.includes(state.tag));
      ui.status.textContent = `${shown.length} article${shown.length === 1 ? "" : "s"}${state.tag ? " tagged " + state.tag : ""}`;
      ui.list.replaceChildren(...shown.map((a) => item("article", a.id, a.title, a.excerpt, a.updated, a.tags)));
      return;
    }
    const kinds = state.everything ? "article,diagram,inbox,deployment" : "article";
    try {
      const { results } = await api(`/api/search-everything?q=${encodeURIComponent(state.query)}&kinds=${kinds}&limit=40`);
      if (serial !== state.serial) return;
      ui.status.textContent = `${results.length} result${results.length === 1 ? "" : "s"} for “${state.query}”`;
      ui.list.replaceChildren(...results.map((r) => item(r.kind, r.ref, r.title, r.snippet, r.at, r.extra?.tags || [], r)));
    } catch (error) { if (serial === state.serial) ui.status.textContent = error.message; }
  }

  const KIND = { article: "Article", diagram: "Diagram", inbox: "Request", deployment: "Deployment" };
  function item(kind, ref, title, text, at, tags, result) {
    const open_ = button("", () => openResult(kind, ref, result));
    open_.className = "kb-result";
    open_.append(el("span", { className: "kb-result-top" }, el("span", { className: "kb-kind kb-kind-" + kind, textContent: KIND[kind] }), el("strong", {}, marked_(title)), el("small", { textContent: date(at) })),
      el("span", { className: "kb-result-text" }, marked_(text)));
    if (tags?.length) open_.append(el("span", { className: "kb-result-tags", textContent: tags.join(" · ") }));
    if (kind === "article" && state.current?.id === ref) open_.setAttribute("aria-current", "true");
    return el("li", {}, open_);
  }

  function openResult(kind, ref, result) {
    if (kind === "article") return open(ref);
    if (kind === "diagram") { setMode("diagrams"); return original.show(ref); }
    if (kind === "inbox") { page("inbox"); return window.dispatchEvent(new CustomEvent("atlas:inbox-open", { detail: { id: Number(ref) } })); }
    const x = result?.extra || {};
    state.current = null;
    ui.view.replaceChildren(el("div", { className: "kb-deployment" },
      el("h2", {}, marked_(result?.title || "Deployment")),
      el("dl", {}, ...[["Machine", x.target], ["Package", x.package], ["Action", x.action], ["State", x.state], ["Started", result?.at], ["Finished", x.finished]]
        .flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: v || "—" })])),
      x.target && !readonly() ? button("Select this machine in Workspace", () => { page("workspace"); setTarget(x.target, "Knowledge Base search", false); }) : null));
  }

  async function open(id) {
    if (state.editing && !confirm("Discard the changes to this article?")) return;
    state.editing = false;
    let article;
    try { article = await api("/api/knowledge/articles/" + encodeURIComponent(id)); }
    catch (error) { ui.status.textContent = error.message; return; }
    state.current = article;
    const body = el("div", { className: "kb-markdown" });
    const actions = el("div", { className: "kb-article-actions" },
      button("Edit", () => edit(article)), button("Copy text", () => navigator.clipboard?.writeText(article.markdown).then(() => toast?.("Article copied"))),
      button("Delete", () => remove(article)));
    ui.view.replaceChildren(el("header", { className: "kb-article-head" },
      el("h2", { textContent: article.title }),
      el("p", { className: "kb-article-meta" },
        ...article.categories.map((c) => el("span", { className: "kb-category", textContent: label(c) })),
        ...article.tags.map((t) => el("span", { className: "kb-tag", textContent: t })),
        el("small", { textContent: "Updated " + date(article.updated) })), actions), body);
    refreshList();
    await render(article.markdown, body);
  }

  function edit(article, isNew = false) {
    state.editing = true;
    const draft = { ...article, id: article.id || null };
    const title = el("input", { value: draft.title || "", maxLength: 180, placeholder: "Article title", required: true });
    title.setAttribute("aria-label", "Article title");
    const tags = el("input", { value: (draft.tags || []).join(", "), placeholder: "Tags, separated by commas" });
    tags.setAttribute("aria-label", "Tags");
    const cats = el("fieldset", { className: "kb-categories" }, el("legend", { textContent: "Suggest in Live Inbox for" }),
      ...state.categories.map((c) => el("label", {}, el("input", { type: "checkbox", value: c.id, checked: (draft.categories || []).includes(c.id) }), " " + c.label)));
    const text = el("textarea", { value: draft.markdown || "", spellcheck: true, placeholder: "Write in Markdown: ## headings, - lists, 1. steps, `code`, ```mermaid diagrams" });
    text.setAttribute("aria-label", "Article text (Markdown)");
    const preview = el("div", { className: "kb-markdown kb-preview" });
    preview.setAttribute("aria-label", "Preview");
    const message = el("p", { className: "kb-note", role: "status" });
    const update = () => { clearTimeout(previewTimer); previewTimer = setTimeout(() => render(text.value, preview), 250); };
    text.addEventListener("input", update);
    const wrap = (before, after = before, placeholder = "text") => () => {
      const { selectionStart: s, selectionEnd: e, value } = text, chosen = value.slice(s, e) || placeholder;
      text.setRangeText(before + chosen + after, s, e, "end"); text.focus(); update();
    };
    const line = (prefix) => () => {
      const s = text.value.lastIndexOf("\n", text.selectionStart - 1) + 1;
      text.setRangeText(prefix, s, s, "end"); text.focus(); update();
    };
    const insert = (snippet) => () => { text.setRangeText(snippet, text.selectionStart, text.selectionEnd, "end"); text.focus(); update(); };
    const tools = el("div", { className: "kb-md-tools", role: "toolbar" },
      button("H2", line("## "), { title: "Heading" }), button("B", wrap("**"), { title: "Bold" }), button("I", wrap("_"), { title: "Italic" }),
      button("• List", line("- ")), button("1. Steps", line("1. ")), button("☐ Check", line("- [ ] ")), button("Code", wrap("`")),
      button("Table", insert("\n| Check | Result |\n| --- | --- |\n|  |  |\n")),
      button("Diagram", insert("\n```mermaid\nflowchart TD\n  A[Problem] --> B{Check}\n  B -->|Yes| C[Fix]\n  B -->|No| D[Escalate]\n```\n")),
      button("Link", wrap("[", "](https://)", "link text")));
    tools.setAttribute("aria-label", "Formatting");
    const save = async () => {
      const payload = { title: title.value.trim(), markdown: text.value, revision: draft.revision || 0,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        categories: [...cats.querySelectorAll("input:checked")].map((c) => c.value) };
      if (!payload.title) { message.textContent = "Give the article a title."; title.focus(); return; }
      const id = draft.id || slug(payload.title);
      try {
        const saved = await api("/api/knowledge/articles/" + encodeURIComponent(id), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        Object.assign(draft, payload, { id, revision: saved.revision });
        state.editing = false;
        toast?.("Article saved");
        await refresh(id);
      } catch (error) { message.textContent = error.message; }
    };
    const cancel = () => { state.editing = false; draft.id ? open(draft.id) : (state.current = null, welcome()); };
    const form = el("form", { className: "kb-article-editor", onsubmit: (e) => { e.preventDefault(); save(); } },
      el("div", { className: "kb-editor-fields" }, title, tags), cats, tools,
      el("div", { className: "kb-editor-split" }, text, preview),
      el("div", { className: "kb-article-actions" }, el("button", { type: "submit", className: "primary", textContent: isNew ? "Create article" : "Save" }), button("Cancel", cancel), message));
    form.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });
    ui.view.replaceChildren(form);
    update();
    (draft.title ? text : title).focus();
  }

  async function remove(article) {
    if (!confirm(`Delete the article “${article.title}”? This cannot be undone.`)) return;
    try {
      await api(`/api/knowledge/articles/${encodeURIComponent(article.id)}?revision=${article.revision}`, { method: "DELETE" });
      state.current = null; toast?.("Article deleted"); await refresh(); welcome();
    } catch (error) { ui.status.textContent = error.message; }
  }

  // Wrap the existing Knowledge Base entry points; diagrams keep working exactly as before.
  const original = { open: window.AtlasKnowledge.open, show: window.AtlasKnowledge.show };
  window.AtlasKnowledge.open = async (...args) => { const result = await original.open(...args); install(); return result; };
  window.AtlasKnowledge.show = async (id) => {
    if (String(id).startsWith("article:")) {
      page("knowledge"); await window.AtlasKnowledge.open(); setMode("articles");
      return open(String(id).slice(8));
    }
    setMode("diagrams");
    return original.show(id);
  };
  window.AtlasKnowledgeArticles = { install, open, edit, refresh, render, setMode, state };
})();
