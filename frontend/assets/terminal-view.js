/* Real terminal display (xterm.js) for the Terminal and PsTools pages.
   The existing <pre> stays the source of truth: Copy, Clear, tests and screen readers keep using it,
   and the terminal mirrors it, appending only new output. xterm loads the first time either page is
   opened, so the console starts as fast as before. Without it, the plain output is shown as before. */
(() => {
  const meta = document.querySelector('meta[name="atlas-terminal-assets"]');
  if (!meta) return;
  const assets = meta.content.split(/\s+/).filter(Boolean);
  const pages = [["terminal", "termOutput"], ["psexec", "pxOutput"]];
  const terminals = new Map();
  let loading = null;
  const theme = {
    background: "#172234", foreground: "#dce8f5", cursor: "#172234", selectionBackground: "#2f5f8f",
    black: "#172234", red: "#c50f1f", green: "#13a10e", yellow: "#c19c00", blue: "#0037da", magenta: "#881798",
    cyan: "#3a96dd", white: "#cccccc", brightBlack: "#767676", brightRed: "#e74856", brightGreen: "#16c60c",
    brightYellow: "#f9f1a5", brightBlue: "#3b78ff", brightMagenta: "#b4009e", brightCyan: "#61d6d6", brightWhite: "#f2f2f2",
  };

  function load() {
    if (window.Terminal && window.FitAddon && window.SearchAddon) return Promise.resolve();
    // Stylesheets and addons do not depend on each other; xterm itself loads first.
    const add = (url) => new Promise((resolve, reject) => {
      const node = url.endsWith(".css")
        ? Object.assign(document.createElement("link"), { rel: "stylesheet", href: url })
        : Object.assign(document.createElement("script"), { src: url });
      node.onload = resolve;
      node.onerror = () => reject(Error("Could not load " + url));
      document.head.append(node);
    });
    const main = assets.find((url) => /\/xterm-[\d.]+\.js$/.test(url));
    loading ||= add(main).then(() => Promise.all(assets.filter((url) => url !== main).map(add)));
    return loading.catch((error) => { loading = null; throw error; });
  }

  function searchBar(term, search) {
    const bar = document.createElement("div");
    bar.className = "atlas-xterm-search";
    bar.setAttribute("role", "search");
    const input = Object.assign(document.createElement("input"), { type: "search", placeholder: "Find in output" });
    input.setAttribute("aria-label", "Find in terminal output");
    const button = (label, title, fn) => {
      const b = Object.assign(document.createElement("button"), { type: "button", textContent: label, title });
      b.setAttribute("aria-label", title);
      b.onclick = fn;
      return b;
    };
    const status = document.createElement("small");
    status.setAttribute("role", "status");
    const find = (forward) => {
      const term_ = input.value;
      if (!term_) { search.clearDecorations?.(); term.clearSelection(); status.textContent = ""; return; }
      const found = forward ? search.findNext(term_, { caseSensitive: false }) : search.findPrevious(term_, { caseSensitive: false });
      status.textContent = found ? "" : "Not found";
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); find(!event.shiftKey); }
      if (event.key === "Escape") { input.value = ""; find(true); }
    });
    input.addEventListener("input", () => find(true));
    bar.append(input, button("↑", "Previous match", () => find(false)), button("↓", "Next match", () => find(true)),
      button("⤓", "Scroll to the end", () => term.scrollToBottom()), status);
    return bar;
  }

  function mount(pre) {
    if (pre.dataset.xterm) return;
    pre.dataset.xterm = "loading";
    let term, host, bar, outputObserver, resizeObserver;
    load().then(() => {
      host = document.createElement("div");
      host.className = "atlas-xterm";
      // The <pre> remains for screen readers; the drawn terminal duplicates it visually.
      host.setAttribute("aria-hidden", "true");
      term = new window.Terminal({
        convertEol: true, disableStdin: true, cursorBlink: false, cursorStyle: "bar", cursorInactiveStyle: "none",
        scrollback: 20000, fontSize: 12, lineHeight: 1.15, theme,
        fontFamily: '"Cascadia Mono", "Cascadia Code", Consolas, "Courier New", monospace',
      });
      const fit = new window.FitAddon.FitAddon(), search = new window.SearchAddon.SearchAddon();
      term.loadAddon(fit);
      term.loadAddon(search);
      pre.after(host);
      bar = searchBar(term, search);
      host.before(bar);
      term.open(host);
      let written = "";
      const sync = () => {
        const text = pre.textContent;
        if (text === written) return;
        if (written && text.startsWith(written)) term.write(text.slice(written.length));
        else { term.reset(); term.write(text); }
        written = text;
      };
      outputObserver = new MutationObserver(sync);
      outputObserver.observe(pre, { childList: true, characterData: true, subtree: true });
      sync();
      const resize = () => { if (host.offsetParent) try { fit.fit(); } catch {} };
      if (window.ResizeObserver) {
        resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(host);
      }
      resize();
      terminals.set(pre.id, { term, sync });
      pre.classList.add("atlas-xterm-source");
      pre.dataset.xterm = "ready";
    }).catch(() => {
      // Initialization can fail after loading; restore plain output and remove partial UI too.
      outputObserver?.disconnect();
      resizeObserver?.disconnect();
      try { term?.dispose(); } catch {}
      bar?.remove();
      host?.remove();
      pre.classList.remove("atlas-xterm-source");
      terminals.delete(pre.id);
      pre.dataset.xterm = "";
    });
  }

  function check() {
    for (const [page, id] of pages) {
      const section = document.getElementById(page), pre = document.getElementById(id);
      if (section?.classList.contains("active") && pre) mount(pre);
    }
  }
  for (const [page] of pages) {
    const section = document.getElementById(page);
    if (section) new MutationObserver(check).observe(section, { attributes: true, attributeFilter: ["class"] });
  }
  window.AtlasTerminalView = { terminals, check, load };
  check();
})();
