/* Clipboard page: everything copied into Atlas, with what Atlas knows about it.
   Capture with the button, Ctrl+V on any page (outside text boxes) or, when allowed, automatically
   when you come back to Atlas. The list shows each capture; the selected one lists its machines,
   people, desks, tickets and IPs, with their actions (right-click a machine or person for the full
   menu) and bulk actions for lists. */
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("clipboard")) return;
  const esc = (value) => window.AtlasUI.esc(value ?? "");
  const AUTO = "atlas-clipboard-auto", SEEN = "atlas-clipboard-seen";
  const sources = { button: "Captured", paste: "Pasted", return: "Copied before returning", screenshot: "Screenshot", inbox: "Live Inbox", companion: "Copied (Companion)" };
  let companion = null, latest = null;
  let items = [], loaded = false, busy = false, selected = null;
  const remember = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const recall = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
  const request = (url, options = {}) => window.AtlasClient.request(url, { atlasSilent: true, ...options });
  const json = (url, body, method = "POST") => request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const notify = (text) => (typeof toast === "function" ? toast(text) : null);

  function status(text, tone = "") {
    $("clipboardStatus").textContent = text;
    $("clipboardStatus").dataset.tone = tone;
  }
  function count() {
    $("clipboardCount").textContent = items.length;
  }
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  function chips(item) {
    const parts = [
      [item.machines?.length, "machine", "machine"],
      [item.users?.length, "person", "person"],
      [item.desks?.length, "desk", "desk"],
      [item.tickets?.length, "ticket", "ticket"],
      [item.ips?.length, "IP", "ip"],
      [item.unknown_machines?.length, "not in Atlas", "unknown"],
    ].filter(([n]) => n);
    return parts.map(([n, word, tone]) => `<span class="clipboard-chip clipboard-chip-${tone}">${tone === "unknown" ? `${n} ${word}` : plural(n, word === "person" ? "person" : word).replace("persons", "people")}</span>`).join("") ||
      '<span class="clipboard-chip">Text only</span>';
  }
  const when = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  };
  function machineRows(item) {
    return item.machines.map((m) => {
      const user = m.user ? `<span ${window.AtlasContext.attributes("user", m.user)} class="clipboard-person" tabindex="0">${esc(m.user.full_name || m.user.name || m.user.user_name)}</span>` : `<span class="clipboard-muted">${esc(m.assigned_user || m.last_logged_on_user || "No user recorded")}</span>`;
      return `<tr data-clipboard-machine="${esc(m.name)}"><td><b>${esc(m.name)}</b>${m.written_as ? `<small class="clipboard-muted" title="Found despite look-alike characters"> read as ${esc(m.written_as)}</small>` : ""}</td><td>${user}</td><td>${esc(m.model_id || m.device_kind || "")}</td><td><span class="${String(m.operational_status || "").toLowerCase() === "operational" ? "status-ok" : "status-warn"}">${esc(m.operational_status || "Unknown")}</span></td><td class="clipboard-online" data-online="${esc(m.name)}"></td><td class="clipboard-row-actions"><button type="button" data-select="${esc(m.name)}">Select</button></td></tr>`;
    }).join("");
  }
  function detail(item) {
    const sections = [];
    if (item.machines?.length) {
      const windows = item.machines.filter((m) => window.AtlasUI.supportsWindows(m)).map((m) => m.name);
      sections.push(`<section><h4>Machines <small>${item.machines.length}</small></h4><div class="clipboard-bulk">` +
        `<button type="button" data-bulk="deploy" ${windows.length ? "" : "disabled"}>Bulk deploy (${windows.length})</button>` +
        `<button type="button" data-bulk="script" ${windows.length ? "" : "disabled"}>Run a script</button>` +
        `<button type="button" data-bulk="ping" ${windows.length ? "" : "disabled"}>Ping all</button>` +
        `<button type="button" data-bulk="copy-machines">Copy names</button>` +
        `<button type="button" data-bulk="copy-users">Copy users</button></div>` +
        `<div class="clipboard-table"><table><thead><tr><th>Machine</th><th>User</th><th>Model</th><th>Inventory</th><th>Online</th><th></th></tr></thead><tbody>${machineRows(item)}</tbody></table></div></section>`);
    }
    if (item.users?.length)
      sections.push(`<section><h4>People <small>${item.users.length}</small></h4><div class="clipboard-bulk"><button type="button" data-bulk="copy-emails">Copy emails</button></div><div class="clipboard-table"><table><thead><tr><th>Name</th><th>Account</th><th>Email</th><th>Department</th><th></th></tr></thead><tbody>${item.users.map((u) =>
        `<tr ${window.AtlasContext.attributes("user", u)} tabindex="0"><td><b>${esc(u.full_name || u.name)}</b></td><td>${esc(u.user_name)}</td><td>${esc(u.email)}</td><td>${esc(u.department)}</td><td class="clipboard-row-actions"><button type="button" data-person="${esc(u.id)}">Open</button></td></tr>`).join("")}</tbody></table></div></section>`);
    if (item.desks?.length)
      sections.push(`<section><h4>Desks <small>${item.desks.length}</small></h4><div class="clipboard-table"><table><thead><tr><th>Desk</th><th>Occupant</th><th>Team</th><th>Floor</th><th></th></tr></thead><tbody>${item.desks.map((d) =>
        `<tr><td><b>${esc(d.desk)}</b></td><td>${d.occupancy === "vacant" ? '<span class="clipboard-muted">Vacant</span>' : esc(d.name)}</td><td>${esc(d.team)}</td><td>${esc(d.floor)}</td><td class="clipboard-row-actions"><a href="/?desk=${encodeURIComponent(d.desk)}" target="_blank" rel="noopener">Map</a></td></tr>`).join("")}</tbody></table></div></section>`);
    const plain = (title, list, tone) => list?.length ? `<section><h4>${title} <small>${list.length}</small></h4><div class="clipboard-tags">${list.map((value) => `<button type="button" class="clipboard-chip clipboard-chip-${tone}" data-copy="${esc(value)}" title="Copy">${esc(value)}</button>`).join("")}</div></section>` : "";
    sections.push(plain("Tickets", item.tickets, "ticket"), plain("IP addresses", item.ips, "ip"), plain("Not in Atlas", item.unknown_machines, "unknown"));
    return sections.join("") + `<details class="clipboard-text"><summary>Copied text</summary><pre>${esc(item.text)}</pre></details>` +
      `<div class="clipboard-item-actions">${window.AxisChat ? '<button type="button" data-ask-axis>Ask Axis</button>' : ""}<button type="button" data-copy-text>Copy text</button><button type="button" data-refresh>Refresh data</button><button type="button" data-delete>Delete</button></div>`;
  }
  const heading = (item) => `${esc(when(item.at))} · ${esc(sources[item.source] || item.source)}${item.times > 1 ? ` · ×${item.times}` : ""}`;
  function render() {
    count();
    const words = $("clipboardFilter").value.toLowerCase().split(/\s+/).filter(Boolean);
    const shown = items.filter((item) => words.every((word) => (item.text + " " + (item.machines || []).map((m) => (m.user?.full_name || "") + " " + (m.model_id || "")).join(" ")).toLowerCase().includes(word)));
    // The newest capture is selected until another is chosen; a filtered-out selection moves to the first match.
    if (!shown.some((item) => item.id === selected)) selected = shown[0]?.id ?? null;
    $("clipboardItems").innerHTML = shown.length ? shown.map((item) => `<button type="button" class="clipboard-item" data-item="${esc(item.id)}" aria-pressed="${item.id === selected}"><span class="clipboard-when">${heading(item)}</span><span class="clipboard-preview">${esc(item.text.split(/\r?\n/).filter(Boolean).slice(0, 2).join(" · ").slice(0, 140))}</span><span class="clipboard-chips">${chips(item)}</span></button>`).join("")
      : `<p class="empty">${items.length ? "Nothing matches the filter." : "Nothing captured yet. Copy machines, people, desks or tickets anywhere, then press Ctrl+V here or click Capture clipboard."}</p>`;
    const item = items.find((x) => x.id === selected);
    $("clipboardDetail").innerHTML = item ? `<article class="clipboard-selected" data-item="${esc(item.id)}"><header><span class="clipboard-when">${heading(item)}</span><span class="clipboard-chips">${chips(item)}</span></header><div class="clipboard-detail">${detail(item)}</div></article>`
      : `<p class="empty">${items.length ? "Select a capture to see its machines, people, desks and tickets." : "Captures appear here with what Atlas knows about them."}</p>`;
    if (item) bind($("clipboardDetail"), item);
  }
  // Machine rows get the full right-click menu (health, groups, deploy...) like everywhere in Atlas:
  // the shared directory actions plus the Workspace tools, each selecting the machine first.
  function machineActions(m) {
    const windows = window.AtlasUI.supportsWindows(m);
    const tool = (id, label, section, run) => ({ id, label, section, disabled: !windows, reason: "Windows tools require a PC",
      run: async () => { setTarget(m.name, m.operational_status, false); await run(); } });
    return [
      tool("target", "Set as target", "Target & tools", () => page("workspace")),
      tool("health", "Refresh health", "Target & tools", () => { page("workspace"); return refreshTargetHealth(); }),
      ...[["msra", "Open MSRA"], ["rdp", "Remote Desktop"], ["compmgmt", "Computer Management"], ["cshare", "Open C$"]]
        .map(([id, label]) => tool(id, label, "Remote support", () => openTargetTool(id))),
      tool("admin", "Remote Admin", "Remote support", () => page("admin")),
      tool("deploy", "Deploy software…", "Deployment", () => { page("workspace"); openDeploymentPanel(); document.getElementById("pkgSearch")?.focus(); }),
      tool("specs", "View specifications", "Reports", () => window.AtlasHealth.specs(m.name)),
      tool("software", "Software inventory", "Reports", () => loadSoftware(m.name)),
    ];
  }
  function bind(node, item) {
    node.querySelectorAll("[data-clipboard-machine]").forEach((row) => {
      const machine = item.machines.find((m) => m.name === row.dataset.clipboardMachine);
      if (machine && !row.dataset.atlasContext) window.AtlasContext.bindDevice(row, machine, machineActions(machine));
    });
  }
  async function load() {
    try { items = (await request("/api/clipboard")).items || []; loaded = true; render(); }
    catch (error) { status("Clipboard history unavailable: " + error.message, "bad"); }
  }
  async function store(text, source) {
    const item = await json("/api/clipboard", { text: text.slice(0, 20000), source });
    items = [item, ...items.filter((x) => x.id !== item.id)];
    return item;
  }
  function announce(item, quiet = false) {
    selected = item.id;
    render();
    const found = [item.machines?.length && plural(item.machines.length, "machine"), item.users?.length && (item.users.length === 1 ? "1 person" : item.users.length + " people"),
      item.desks?.length && plural(item.desks.length, "desk")].filter(Boolean).join(", ");
    status(`Captured ${when(item.at)}${found ? ": " + found : ""}.`, "good");
    // Leaving Remote Admin would stop a running slowness capture: stay, and say where the capture went.
    if (quiet || window.AtlasDiagnostics?.isRunning?.()) notify("Clipboard captured" + (found ? ": " + found : "") + (quiet ? "" : ". Open Clipboard to see it."));
    else open();
  }
  async function screenshot(blob) {
    // The screenshot is read with Windows text recognition; the server keeps it in the history.
    await request("/api/screen/image", { method: "POST", headers: { "Content-Type": blob.type || "image/png" }, body: blob });
    await load();
    if (items[0]) announce(items[0]);
  }
  const htmlText = (html) => { const doc = new DOMParser().parseFromString(html, "text/html"); return doc.body?.innerText || doc.body?.textContent || ""; };
  /** What the browser clipboard holds: {text} or {image}. */
  async function readClipboard() {
    const list = await navigator.clipboard.read();
    for (const item of list) {
      const type = item.types.find((t) => t.startsWith("image/"));
      if (type) return { image: await item.getType(type) };
    }
    for (const item of list) for (const type of ["text/plain", "text/html"]) {
      if (!item.types.includes(type)) continue;
      const raw = await (await item.getType(type)).text(), text = type === "text/html" ? htmlText(raw) : raw;
      if (text.trim()) return { text };
    }
    return {};
  }
  const signature = (found) => found.text ? "t:" + found.text.length + ":" + found.text.slice(0, 200) : found.image ? "i:" + found.image.size + ":" + found.image.type : "";
  async function capture(source = "button", quiet = false) {
    if (busy) return;
    busy = true; $("clipboardCapture").disabled = true;
    try {
      if (!navigator.clipboard?.read) throw Error("This browser cannot read the clipboard. Press Ctrl+V in Atlas instead.");
      const found = await readClipboard();
      const seen = signature(found);
      if (!seen) { if (!quiet) status("The clipboard is empty.", "bad"); return; }
      if (quiet && seen === recall(SEEN)) return;
      remember(SEEN, seen);
      if (found.image) await screenshot(found.image);
      else announce(await store(found.text, source), quiet);
    } catch (error) {
      if (!quiet) status(error.name === "NotAllowedError" ? "The browser blocked the clipboard. Allow it from the address bar, or run windows\\Allow-Atlas-Clipboard.bat. Ctrl+V in Atlas always works." : error.message, "bad");
    } finally { busy = false; $("clipboardCapture").disabled = false; }
  }
  /** Called by page() whenever the Clipboard page is shown. */
  function shown() {
    if (!loaded) load();
    companionStatus();
  }
  function open() {
    if (typeof page === "function") page("clipboard");
    else shown();
  }
  const machinesOf = (item) => item.machines.filter((m) => window.AtlasUI.supportsWindows(m)).map((m) => m.name);
  async function copy(text, label) {
    try { await navigator.clipboard.writeText(text); remember(SEEN, signature({ text })); notify(label + " copied"); }
    catch { notify("Clipboard unavailable"); }
  }
  async function ping(node, names) {
    const queue = [...names];
    const work = async () => {
      while (queue.length) {
        const name = queue.shift(), cell = [...node.querySelectorAll("[data-online]")].find((c) => c.dataset.online === name);
        if (cell) cell.innerHTML = '<span class="clipboard-muted">…</span>';
        try {
          const result = await request("/api/ping/" + encodeURIComponent(name));
          if (cell) cell.innerHTML = result.online ? '<span class="status-ok">Online</span>' : '<span class="status-bad">No reply</span>';
        } catch { if (cell) cell.innerHTML = '<span class="status-warn">Unknown</span>'; }
      }
    };
    await Promise.all(Array.from({ length: Math.min(6, queue.length) }, work));
  }
  $("clipboardItems").addEventListener("click", (event) => {
    const choice = event.target.closest("[data-item]");
    if (!choice || choice.dataset.item === selected) return;
    selected = choice.dataset.item;
    render();
    // Stacked on narrow screens: bring the chosen item's details into view.
    if (window.matchMedia?.("(max-width: 1100px)").matches) $("clipboardDetail").scrollIntoView?.({ block: "start" });
  });
  $("clipboardDetail").addEventListener("click", (event) => {
    const node = event.target.closest("[data-item]");
    const item = node && items.find((x) => x.id === node.dataset.item);
    if (!item) return;
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.select) { page("workspace"); setTarget(target.dataset.select); }
    else if (target.dataset.person) window.dispatchEvent(new CustomEvent("atlas:inbox-person", { detail: { id: Number(target.dataset.person) } }));
    else if (target.dataset.copy) copy(target.dataset.copy, target.dataset.copy);
    else if ("copyText" in target.dataset) copy(item.text, "Text");
    // Axis reads the capture itself by ID, as untrusted evidence; no copied text goes in the request.
    else if ("askAxis" in target.dataset)
      window.AxisChat?.attach({ kind: "clipboard", id: item.id, label: item.text.trim().split("\n")[0].slice(0, 80) || "Clipboard capture", prompt: "What is this, and what should I do with it?" });
    else if (target.dataset.bulk === "copy-machines") copy(item.machines.map((m) => m.name).join("\n"), plural(item.machines.length, "machine name"));
    else if (target.dataset.bulk === "copy-users") copy(item.machines.map((m) => `${m.name}\t${m.user?.full_name || m.assigned_user || ""}\t${m.user?.email || ""}`).join("\n"), "Machines and users");
    else if (target.dataset.bulk === "copy-emails") copy(item.users.map((u) => u.email).filter(Boolean).join("; "), "Emails");
    else if (target.dataset.bulk === "ping") ping(node, machinesOf(item));
    else if (target.dataset.bulk === "deploy") {
      $("bulkTargets").value = machinesOf(item).join("\n");
      $("bulkTargets").dispatchEvent(new Event("input", { bubbles: true }));
      page("bulk");
    } else if (target.dataset.bulk === "script") {
      $("scriptTargets").value = machinesOf(item).join("\n");
      $("scriptTargets").dispatchEvent(new Event("input", { bubbles: true }));
      page("scripts");
    } else if ("refresh" in target.dataset) {
      request(`/api/clipboard/${item.id}/refresh`, { method: "POST" }).then((fresh) => { items = items.map((x) => (x.id === fresh.id ? fresh : x)); render(); status("Data refreshed from Atlas.", "good"); }, (error) => status(error.message, "bad"));
    } else if ("delete" in target.dataset) {
      request(`/api/clipboard/${item.id}`, { method: "DELETE" }).then(() => { items = items.filter((x) => x.id !== item.id); render(); }, (error) => status(error.message, "bad"));
    }
  });
  $("clipboardToggle").onclick = open;
  $("clipboardCapture").onclick = () => capture("button");
  $("clipboardFilter").oninput = render;
  $("clipboardClear").onclick = () => {
    if (!items.length || !confirm(`Delete all ${items.length} clipboard items?`)) return;
    request("/api/clipboard", { method: "DELETE" }).then(() => { items = []; selected = null; render(); status("History cleared."); }, (error) => status(error.message, "bad"));
  };
  $("clipboardAuto").checked = recall(AUTO) !== "off";
  $("clipboardAuto").onchange = () => remember(AUTO, $("clipboardAuto").checked ? "on" : "off");
  // Ctrl+V on any page except Live Inbox (its own reader keeps those in the history) and text boxes.
  document.addEventListener("paste", async (event) => {
    if (event.target.closest?.("input,textarea,select,[contenteditable]") || $("inbox")?.classList.contains("active") || window.AtlasReadOnly) return;
    const data = event.clipboardData;
    const file = [...(data?.files || [])].find((f) => f.type.startsWith("image/"));
    const text = data?.getData("text/plain") || htmlText(data?.getData("text/html") || "");
    if (!file && !text.trim()) return;
    event.preventDefault();
    try {
      if (file) await screenshot(file);
      else announce(await store(text, "paste"));
    } catch (error) { status(error.message, "bad"); if (!window.AtlasDiagnostics?.isRunning?.()) open(); }
  });
  // Coming back to Atlas after copying something elsewhere: captured without a click, when the browser allows it.
  let last = 0;
  async function returned() {
    if (document.hidden || !$("clipboardAuto").checked || window.AtlasReadOnly || Date.now() - last < 1500 || covered()) return;
    last = Date.now();
    const state = await navigator.permissions?.query({ name: "clipboard-read" }).then((p) => p.state, () => "");
    if (state === "granted") capture("return", true);
  }
  window.addEventListener("focus", returned);
  document.addEventListener("visibilitychange", returned);
  // The Atlas Companion (normal Windows account) sends every copy in the background.
  const covered = () => !!(companion?.online && companion.settings?.clipboard);
  function renderCompanion() {
    const host = $("clipboardCompanion"), c = companion;
    if (!c) { host.replaceChildren(); return; }
    const mail = { watching: "Outlook: watching", off: "Outlook: off · switch on Email watcher in Live Inbox", waiting_for_outlook: "Outlook: waiting for classic Outlook" }[c.mail?.state] || (c.mail?.state ? "Outlook: " + c.mail.state.replace(/_/g, " ") : "");
    host.innerHTML = c.online
      ? `<span class="status-ok">Companion connected</span><span>${esc(c.user)} · ${c.settings.clipboard ? "every copy is captured, even with Atlas closed" : "clipboard capture is off"}${c.clipboard?.paused ? " · paused from the tray" : ""}</span><label><input type="checkbox" id="companionClipboard" ${c.settings.clipboard ? "checked" : ""}> Capture my clipboard</label><small>${esc(mail)}</small>`
      : c.known
        ? `<span class="status-warn">Companion not running</span><span>Start <b>windows\\Start-Atlas-Companion.bat</b> as yourself (not as administrator). Last seen ${esc(when(c.last_seen))}.</span>`
        : `<span class="clipboard-chip">Companion not set up</span><span>Run <b>windows\\Install-Atlas-Companion.bat</b> once as yourself to capture every copy from your normal account, even with Atlas closed.</span>`;
    const box = $("companionClipboard");
    if (box) box.onchange = () => json("/api/companion/settings", { clipboard: box.checked }).then((next) => { companion = next; renderCompanion(); }, (error) => status(error.message, "bad"));
    $("clipboardAuto").disabled = covered();
    $("clipboardAuto").closest("label").title = covered() ? "Not needed: the Atlas Companion captures every copy" : "When the browser allows the clipboard, what you copied elsewhere is captured as you come back to Atlas";
  }
  async function companionStatus() {
    try { companion = await request("/api/companion"); renderCompanion(); } catch { companion = null; }
  }
  async function watch() {
    if (!document.hidden) {
      await companionStatus();
      try {
        const summary = await request("/api/clipboard?summary=true");
        if (latest !== null && summary.latest !== latest) await load();
        else if (latest === null) $("clipboardCount").textContent = summary.count;
        latest = summary.latest;
      } catch {}
    }
    setTimeout(watch, $("clipboard").classList.contains("active") ? 5000 : 15000);
  }
  // Demo shows Clipboard greyed out (readonly-console.js) and never reads the history.
  if (window.AtlasReadOnly) return;
  load();
  watch();
  window.AtlasClipboard = { open, shown, capture, load, item: (id) => items.find((x) => x.id === id) };
})();
