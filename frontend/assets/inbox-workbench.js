/* Live Inbox request tools: the person, their PCs (health, performance, groups, deployment,
   software, services, remote tools), group comparisons and Knowledge Base articles, shown beside
   the message instead of switching page. Anyone in the request is one click away, anyone else
   one lookup away. Nothing runs without a click; ending a process and rebooting still ask first.
   Remote Admin, Active Directory, Workspace and diagrams stay one click away, with a button back
   to Live Inbox. */
(() => {
  // [id, label, what it needs]
  const TABS = [
    ["person", "Person", "user"],
    ["health", "Health", "machine"],
    ["performance", "Performance", "machine"],
    ["machine-groups", "PC groups", "machine"],
    ["user-groups", "User groups", "account"],
    ["deploy", "Deploy", "machine"],
    ["knowledge", "Knowledge", "document"],
  ];
  const MISSING = {
    user: "No Atlas person is selected. Choose someone in this request or look them up above.",
    machine: "No Windows PC is selected. Choose one in this request, in Person, or look it up above.",
    account: "This person has no AD account or email in Atlas.",
    document: "Choose an article under Knowledge Base or Seen before in the message.",
  };
  const TOOLS = [["msra", "MSRA"], ["cshare", "C$"], ["rdp", "Remote Desktop"], ["compmgmt", "Computer Management"]];
  const RECORD = [["Account", "user_name"], ["Email", "email"], ["Department", "department"], ["Job role", "job_role"], ["Location", "location"],
    ["Manager", "manager"], ["Business unit", "business_unit"], ["Employee number", "employee_number"], ["Start date", "start_date"], ["Last login", "last_login"]];
  const MEMBERSHIP = { Direct: 0, Primary: 1, Nested: 2 };
  const state = { machine: "", user: null, tab: "health", done: {}, performance: null, groups: {}, docked: false,
    request: null, person: null, document: "", article: null, results: null };
  let dock = null, home = null, back = null, inboxClick = false, lookupGeneration = 0;

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const account = (user) => user?.user_name || user?.email || "";
  const fullName = (user) => user?.full_name || user?.name || account(user);
  const machineName = (machine) => String(machine?.name || machine?.machine_name || "").toUpperCase();
  const windows = (machine) => window.AtlasUI?.supportsWindows ? window.AtlasUI.supportsWindows(machine) : true;
  const inbox = () => document.getElementById("inbox");
  const pane = (tab) => dock.querySelector(`[data-work-pane="${tab}"]`);
  const number = (value) => (value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value));
  const percent = (value) => (number(value) === null ? "–" : Math.round(number(value)) + "%");
  const gib = (bytes) => (number(bytes) === null ? "–" : (number(bytes) / 1024 ** 3).toFixed(1));
  const tone = (value, warn, high) => (number(value) === null ? "" : value >= high ? "bad" : value >= warn ? "warn" : "good");
  const busy = (host, text) => { host.setAttribute("aria-busy", "true"); host.innerHTML = `<p class="inbox-work-muted" role="status">${esc(text)}</p>`; };
  const failed = (host, error) => { host.innerHTML = `<p class="inbox-work-error" role="alert">${esc(error.message)}</p><button type="button" data-work-rescan>Try again</button>`; };
  const post = (url, body) => window.AtlasClient.request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function build() {
    dock = document.createElement("aside");
    dock.id = "inboxWork";
    dock.className = "inbox-work";
    dock.hidden = true;
    dock.setAttribute("aria-label", "Request tools");
    dock.innerHTML = `<div class="inbox-work-head"><div><small>Request tools · without leaving Live Inbox</small><h2 data-work-title></h2></div><button type="button" class="inbox-work-close" data-work-close aria-label="Close request tools" title="Close">×</button></div>
<div class="inbox-work-request" data-work-request hidden></div>
<form class="inbox-work-lookup" data-work-lookup role="search"><input type="search" name="term" placeholder="Look up anyone: name, account, email or PC" aria-label="Look up a person or PC" autocomplete="off" spellcheck="false" /><button type="submit">Find</button></form>
<div class="inbox-work-results" data-work-results hidden></div>
<div class="inbox-work-quick" role="group" aria-label="PC tools">${TOOLS.map(([id, label]) => `<button type="button" data-work-tool="${id}" data-needs="machine">${label}</button>`).join("")}<button type="button" data-work-software data-needs="machine">Software…</button><button type="button" data-work-services data-needs="machine">Services…</button><button type="button" data-work-specs data-needs="machine">Specs</button><button type="button" data-work-reboot data-needs="machine">Reboot…</button><button type="button" data-work-workspace>Workspace ↗</button></div>
<div class="inbox-work-tabs" role="tablist" aria-label="Request tools">${TABS.map(([id, label]) => `<button type="button" role="tab" id="inboxWorkTab-${id}" data-work-tab="${id}" aria-controls="inboxWorkPane-${id}" aria-selected="false">${label}</button>`).join("")}</div>
${TABS.map(([id]) => `<section class="inbox-work-pane" role="tabpanel" id="inboxWorkPane-${id}" data-work-pane="${id}" aria-labelledby="inboxWorkTab-${id}" hidden></section>`).join("")}`;
    pane("health").innerHTML = "<div data-work-health></div>";
    dock.addEventListener("click", (event) => click(event).catch((error) => toast(error.message)));
    dock.addEventListener("input", (event) => { if (event.target.matches("[data-work-filter]")) filterGroups(event.target); });
    dock.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.target;
      if (form.matches("[data-work-lookup]")) lookup(form.elements.term.value).catch((error) => toast(error.message));
      if (form.matches("[data-work-compare-form]")) compare(form.elements.other.value).catch((error) => toast(error.message));
    });
  }

  /** Opens the tools beside the message; false when Live Inbox is not on screen (callers then use
   *  Workspace). A missing machine or user keeps the current one; a different person without a
   *  machine gets their own PC once their record has loaded. */
  function open(detail = {}, tab = "health", mode = "show") {
    const grid = document.querySelector("#liveInbox .inbox-grid");
    if (!grid || !inbox()?.classList.contains("active")) return false;
    if (!dock) build();
    // React owns .inbox-grid's two columns and never re-orders them, so the panel stays the last child.
    if (dock.parentNode !== grid) grid.append(dock);
    const user = detail.user === undefined ? state.user : detail.user;
    const samePerson = (user?.id ?? account(user)) === (state.user?.id ?? account(state.user));
    const machine = detail.machine === undefined ? (samePerson ? state.machine : "") : String(detail.machine || "").toUpperCase();
    if (detail.document) state.document = detail.document;
    use(machine, user);
    dock.hidden = false;
    renderRequest();
    show(tab, mode);
    // Their record, desk and PCs, ready in Person; it also picks their PC when none was given.
    if (user?.id && tab !== "person" && state.done.person !== user.id) loadPerson();
    return true;
  }

  function use(machine, user) {
    invalidateLookup();
    if (machine !== state.machine) {
      const host = dock.querySelector("[data-work-health]");
      if (host) window.AtlasHealth?.cancel(host);
      state.machine = machine;
      state.performance = null;
      for (const tab of ["health", "performance", "machine-groups"]) delete state.done[tab];
      pane("health").innerHTML = "<div data-work-health></div>";
      pane("performance").replaceChildren();
      pane("machine-groups").replaceChildren();
    }
    if ((user?.id ?? account(user)) !== (state.user?.id ?? account(state.user))) {
      delete state.done["user-groups"];
      delete state.done.person;
      state.person = null;
      pane("user-groups").replaceChildren();
      pane("person").replaceChildren();
    }
    state.user = user;
    dock.querySelector("[data-work-title]").textContent = [machine || "No Windows PC", fullName(user)].filter(Boolean).join(" · ");
    const have = { machine: !!machine, user: !!user?.id, account: !!account(user), document: !!state.document };
    for (const [tab, , needs] of TABS) {
      const button = dock.querySelector(`[data-work-tab="${tab}"]`);
      button.disabled = !have[needs];
      button.title = have[needs] ? "" : MISSING[needs];
    }
    dock.querySelectorAll('[data-needs="machine"]').forEach((button) => { button.disabled = !machine; });
    renderRequest();
  }

  function show(tab, mode = "show") {
    const needs = TABS.find(([id]) => id === tab)?.[2];
    if (!needs) return;
    state.tab = tab;
    dock.querySelectorAll("[data-work-tab]").forEach((button) => {
      const selected = button.dataset.workTab === tab;
      button.setAttribute("aria-selected", String(selected));
      button.classList.toggle("active", selected);
    });
    dock.querySelectorAll("[data-work-pane]").forEach((section) => { section.hidden = section.dataset.workPane !== tab; });
    const have = { machine: state.machine, user: state.user?.id, account: account(state.user), document: state.document }[needs];
    if (!have) return note(tab, MISSING[needs]);
    if (tab === "person") return mode === "scan" || state.done.person !== state.user.id ? loadPerson() : undefined;
    if (tab === "health") return health(mode);
    if (tab === "performance") return mode === "scan" || state.done.performance !== state.machine ? performance() : undefined;
    if (tab === "machine-groups" || tab === "user-groups") {
      const kind = tab === "user-groups" ? "user" : "computer", id = kind === "user" ? account(state.user) : state.machine;
      return mode === "scan" || state.done[tab] !== kind + ":" + id ? groups(kind, id) : undefined;
    }
    if (tab === "knowledge") return mode === "scan" || state.done.knowledge !== state.document ? knowledge() : undefined;
    if (tab === "deploy") { target(); return dockDeployment(); }
  }

  function note(tab, text) {
    pane(tab).innerHTML = `<p class="inbox-work-muted">${esc(text)}</p>`;
  }

  // Atlas's current target follows the panel, so Workspace, Remote Admin and deployment agree.
  function target() {
    if (!state.machine) throw Error("No Windows PC is selected for this request.");
    if (S.target !== state.machine) setTarget(state.machine, "Live inbox request", false);
    if (S.target !== state.machine) throw Error(`${state.machine} is inventory only; Windows tools need a PC.`);
  }

  // Everyone and every PC in the selected message, one click each.
  function requestEntries() {
    const detail = state.request;
    if (!detail) return { people: [], machines: [] };
    const sender = detail.match?.user, named = (detail.analysis?.people || []).filter((p) => !p.ambiguous);
    const people = [...(sender ? [{ user: sender, label: fullName(sender), role: "sender" }] : []), ...named.map((p) => ({ user: p, label: fullName(p), role: "named" }))];
    const machines = [];
    const add = (machine, owner) => {
      const name = machineName(machine);
      if (name && windows(machine) && !machines.some((m) => m.name === name)) machines.push({ name, owner });
    };
    (detail.analysis?.machines || []).forEach((m) => add(m, m.linked ? sender : undefined));
    (detail.machines || []).forEach((m) => add(m, sender));
    named.forEach((p) => (p.machines || []).forEach((m) => add(m, p)));
    return { people, machines };
  }

  function renderRequest() {
    const host = dock?.querySelector("[data-work-request]");
    if (!host) return;
    const { people, machines } = requestEntries();
    host.hidden = people.length + machines.length < 2;
    host.innerHTML = `<small>In this request</small>${people.map((p, i) => `<button type="button" data-work-person="${i}" aria-pressed="${p.user.id === state.user?.id}" title="${p.role === "sender" ? "Sender" : "Named in the message"}">${esc(p.label)}${p.role === "sender" ? " · sender" : ""}</button>`).join("")}${machines.map((m, i) => `<button type="button" data-work-machine="${i}" aria-pressed="${m.name === state.machine}" data-kind="machine">${esc(m.name)}</button>`).join("")}`;
  }

  async function loadPerson() {
    const user = state.user, host = pane("person"), id = user?.id;
    if (!id) return;
    state.done.person = id;
    busy(host, `Loading ${fullName(user)}…`);
    try {
      const data = await window.AtlasClient.request(`/api/inbox/person/${encodeURIComponent(id)}`);
      if (state.done.person !== id) return;
      if (!data?.user) throw Error(`${fullName(user)} is no longer in the Atlas directory.`);
      state.person = data;
      state.user = { ...user, ...data.user };
      renderPerson();
      // A person opened without a PC gets their own.
      const pc = (data.machines || []).find(windows);
      if (!state.machine && pc) {
        use(machineName(pc), state.user);
        if (state.tab !== "person" && TABS.find(([tab]) => tab === state.tab)[2] === "machine") show(state.tab);
      }
    } catch (error) {
      if (state.done.person !== id) return;
      delete state.done.person;
      failed(host, error);
    } finally {
      host.removeAttribute("aria-busy");
    }
  }

  function renderPerson() {
    const { user, machines = [], desks = [] } = state.person, host = pane("person");
    const rows = RECORD.filter(([, key]) => user[key]).map(([label, key]) => [label, user[key]]);
    if (desks.length) rows.splice(Math.min(rows.length, 5), 0, ["Desk", desks.map((desk) => `${desk.id} (floor ${desk.floor})${/name/.test(desk.match || "") ? " · name match" : ""}`).join(", ")]);
    host.innerHTML = `<div class="inbox-work-toolbar"><b>${esc(fullName(user))}</b><span><button type="button" data-work-copy-person>Copy summary</button><button type="button" data-work-tab-link="user-groups"${account(user) ? "" : " disabled"}>User groups</button></span></div>
<dl class="inbox-work-record">${rows.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join("")}</dl>
<div class="inbox-work-toolbar"><b>PCs and devices (${machines.length})</b></div>
${machines.length ? `<ul class="inbox-work-machines">${machines.map((m) => {
      const name = machineName(m), pc = windows(m);
      return `<li data-work-device="${esc(name)}"${name === state.machine ? ' aria-current="true"' : ""}><span><b>${esc(name)}</b><small>${esc([m.device_kind, m.model_id || m.model_category, m.match_type, m.operational_status].filter(Boolean).join(" · "))}</small></span>${pc
        ? `<span><button type="button" data-work-use="${esc(name)}" data-then="health">Health</button><button type="button" data-work-use="${esc(name)}" data-then="performance">Performance</button><button type="button" data-work-use="${esc(name)}" data-then="deploy">Deploy</button></span>`
        : '<small>Inventory only</small>'}</li>`;
    }).join("")}</ul>` : '<p class="inbox-work-muted">No linked device in Atlas.</p>'}`;
  }

  function health(mode) {
    const host = pane("health").querySelector("[data-work-health]"), pc = state.machine;
    const current = () => state.machine === pc && !dock.hidden;
    if (mode === "scan") { state.done.health = pc; return window.AtlasHealth.scan(host, pc, current); }
    if (state.done.health === pc && mode !== "quick") return;
    state.done.health = pc;
    return window.AtlasHealth.quick(host, pc, current);
  }

  async function performance() {
    const host = pane("performance"), pc = state.machine;
    state.done.performance = pc;
    busy(host, `Sampling CPU, memory, disk and processes on ${pc}… this can take up to a minute.`);
    try {
      const data = await window.AtlasClient.request(`/api/performance/${encodeURIComponent(pc)}?kind=overview`);
      if (state.machine !== pc) return;
      if (!data || data.ok === false || !Array.isArray(data.items)) throw Error(data?.error || `Atlas could not read performance counters on ${pc}.`);
      state.performance = { pc, data, sort: "CPU" };
      renderPerformance();
    } catch (error) {
      if (state.machine !== pc) return;
      delete state.done.performance;
      failed(host, error);
    } finally {
      host.removeAttribute("aria-busy");
    }
  }

  function renderPerformance() {
    const { pc, data, sort } = state.performance, s = data.summary || {}, host = pane("performance");
    const volume = (s.volumes || []).find((v) => /^C:/i.test(v.name || "")) || (s.volumes || [])[0];
    const disk = (s.disks || [])[0], latency = disk ? Math.max(number(disk.read_ms) || 0, number(disk.write_ms) || 0) : null;
    const used = number(s.total_memory_bytes) !== null && number(s.available_memory_bytes) !== null ? s.total_memory_bytes - s.available_memory_bytes : null;
    const uptime = number(s.uptime_seconds);
    const tiles = [
      ["CPU", percent(s.cpu_percent), s.logical_processors ? s.logical_processors + " logical processors" : "", tone(s.cpu_percent, 70, 85)],
      ["Memory", percent(s.memory_percent), used === null ? "" : `${gib(used)} of ${gib(s.total_memory_bytes)} GiB in use`, tone(s.memory_percent, 70, 80)],
      ["C: free", volume ? percent(volume.free_percent) : "–", volume ? `${gib(volume.free_bytes)} of ${gib(volume.total_bytes)} GiB free` : "", volume ? tone(100 - volume.free_percent, 80, 90) : ""],
      ["Disk", latency === null ? "–" : latency.toFixed(0) + " ms", disk ? `Read ${number(disk.read_ms)?.toFixed(0) ?? "–"} ms · write ${number(disk.write_ms)?.toFixed(0) ?? "–"} ms · queue ${disk.queue ?? "–"}` : "", tone(latency, 10, 20)],
      ["Uptime", uptime === null ? "–" : `${Math.floor(uptime / 86400)}d ${Math.floor((uptime % 86400) / 3600)}h`, s.os || "", uptime === null ? "" : uptime > 8 * 86400 ? "warn" : "good"],
    ];
    const notes = typeof performanceInsights === "function" ? performanceInsights(s) : [];
    const key = sort === "Memory" ? "MemoryBytes" : "CPU";
    const rows = [...data.items].sort((a, b) => (number(b[key]) ?? -1) - (number(a[key]) ?? -1)).slice(0, 12);
    host.innerHTML = `<div class="inbox-work-toolbar"><small>${esc(pc)} · sampled ${esc(new Date(data.checked_at || Date.now()).toLocaleTimeString())} · ${esc(data.total_processes ?? data.items.length)} processes</small><span><button type="button" data-work-rescan>Scan again</button><button type="button" data-work-admin>Remote Admin ↗</button></span></div>
<div class="inbox-work-tiles">${tiles.map(([label, value, detail, level]) => `<div class="inbox-work-tile" data-tone="${level}" title="${esc(detail)}"><small>${esc(label)}</small><b>${esc(value)}</b><span>${esc(detail)}</span></div>`).join("")}</div>
${notes.length ? `<details class="inbox-work-details" open><summary>What stands out (${notes.length})</summary><ul class="inbox-work-notes">${notes.map((text) => `<li>${esc(text)}</li>`).join("")}</ul></details>` : '<p class="inbox-work-muted">No pressure found in this sample.</p>'}
<div class="inbox-work-toolbar"><b>Top processes</b><span role="group" aria-label="Sort processes">${["CPU", "Memory"].map((label) => `<button type="button" data-work-sort="${label}" aria-pressed="${sort === label}">By ${label === "CPU" ? label : label.toLowerCase()}</button>`).join("")}</span></div>
<table class="inbox-work-processes"><thead><tr><th scope="col">Process</th><th scope="col">PID</th><th scope="col">CPU</th><th scope="col">Memory</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows.map((row) => `<tr><td title="${esc(row.CommandLine || row.Process)}">${esc(row.Process)}</td><td>${esc(row.PID)}</td><td data-tone="${tone(row.CPU, 10, 25)}">${number(row.CPU) === null ? "–" : number(row.CPU).toFixed(1) + "%"}</td><td>${number(row.MemoryBytes) === null ? "–" : (row.MemoryBytes / 1024 ** 2 >= 1024 ? gib(row.MemoryBytes) + " GiB" : Math.round(row.MemoryBytes / 1024 ** 2) + " MB")}</td><td>${row.CanTerminate === false ? `<small title="${esc(row.BlockReason || "Protected process")}">Protected</small>` : `<button type="button" data-work-end="${esc(row.PID)}" aria-label="End ${esc(row.Process)} (PID ${esc(row.PID)})">End…</button>`}</td></tr>`).join("")}</tbody></table>
${(data.warnings || []).map((text) => `<p class="inbox-work-muted">${esc(text)}</p>`).join("")}`;
  }

  async function endProcess(pid) {
    const sample = state.performance, row = sample?.data.items.find((item) => String(item.PID) === pid);
    if (!row || sample.pc !== state.machine) return toast("The process list changed. Scan again first.");
    if (!confirm(`End ${row.Process} (PID ${row.PID}) on ${sample.pc}? Unsaved work in it will be lost.`)) return;
    const result = await post("/api/kill", { computer: sample.pc, value: String(row.PID), created: row.CreatedAt, name: row.Process });
    const problems = (result.results || []).filter((item) => item.state !== "terminated");
    toast(`${sample.pc}: ${result.count || 0} ended${problems.length ? "; " + problems.map((item) => `${item.Process} (${item.PID}): ${item.message}`).join("; ") : result.count ? "" : "; it is no longer running"}`);
    if (result.count && state.machine === sample.pc) await performance();
  }

  const adLookup = (kind, identity) => post("/api/active-directory/lookup", { kind, identity, server: document.getElementById("adServer")?.value.trim() || "" });

  async function groups(kind, id) {
    const tab = kind === "user" ? "user-groups" : "machine-groups", host = pane(tab), key = kind + ":" + id;
    state.done[tab] = key;
    busy(host, `Looking up ${id} in Active Directory…`);
    try {
      const result = await adLookup(kind, id);
      if (state.done[tab] !== key) return;
      state.groups[tab] = { kind, id, result };
      renderGroups(tab);
    } catch (error) {
      if (state.done[tab] !== key) return;
      delete state.done[tab];
      failed(host, error);
    } finally {
      host.removeAttribute("aria-busy");
    }
  }

  const shown = (value) => (value === true ? "Yes" : value === false ? "No" : value === null || value === undefined || value === "" ? "–" : typeof value === "object" ? JSON.stringify(value) : String(value));
  const groupList = (list) => `<ul class="inbox-work-groups">${list.map((group) => `<li data-group="${esc(String(group.name).toLowerCase())}" title="${esc(group.description || group.dn || "")}"><span>${esc(group.name)}</span><small data-membership="${esc(group.membership)}">${esc(group.membership || "")}</small><small>${esc([group.category, group.scope].filter(Boolean).join(" · "))}</small></li>`).join("")}</ul>`;

  function renderGroups(tab) {
    const { kind, id, result } = state.groups[tab], details = result.details || {}, host = pane(tab);
    // Only the checks AD returned are reported; computers have no lock-out or password fields.
    const checks = [
      ["Enabled", (v) => v === false, "Disabled", "enabled"],
      ["Locked out", (v) => v === true, "Locked out", "not locked"],
      ["Password expired", (v) => v === true, "Password expired", "password valid"],
      ["Account expiration", (v) => !!v && Date.parse(v) < Date.now(), "Account expired", "not expired"],
    ].filter(([field]) => field in details);
    const problems = checks.filter(([field, bad]) => bad(details[field])).map(([, , label]) => label);
    const list = [...(result.groups || [])].sort((a, b) => (MEMBERSHIP[a.membership] ?? 3) - (MEMBERSHIP[b.membership] ?? 3) || String(a.name).localeCompare(String(b.name)));
    const count = (type) => list.filter((group) => group.membership === type).length;
    // Colleagues in the request are offered for "same access as…".
    const others = kind === "user" ? requestEntries().people.filter((p) => account(p.user) && account(p.user) !== account(state.user)) : [];
    host.innerHTML = `<div class="inbox-work-toolbar"><small>${esc(kind === "user" ? "Account" : "Computer")} ${esc(details.Account || details.Name || id)} · ${esc(result.server || "default domain")}</small><span><button type="button" data-work-rescan>Look up again</button><button type="button" data-work-ad>Active Directory ↗</button></span></div>
<p class="inbox-work-chips">${problems.length ? problems.map((label) => `<span data-tone="bad">${esc(label)}</span>`).join("") : checks.length ? `<span data-tone="good">${esc(checks.map(([, , , good]) => good).join(" · "))}</span>` : ""}</p>
<details class="inbox-work-details"><summary>${kind === "user" ? "Account" : "Computer"} details (${Object.keys(details).length})</summary><dl>${Object.entries(details).map(([field, value]) => `<dt>${esc(field)}</dt><dd>${esc(shown(value))}</dd>`).join("")}</dl></details>
${kind === "user" ? `<form class="inbox-work-compare" data-work-compare-form><b>Compare with</b>${others.map((p) => `<button type="button" data-work-compare-with="${esc(account(p.user))}">${esc(p.label)}</button>`).join("")}<input name="other" placeholder="Account or email" aria-label="Compare groups with" autocomplete="off" /><button type="submit">Compare</button></form><div data-work-compare-result></div>` : ""}
<div class="inbox-work-toolbar"><b>${list.length} groups</b><small>${count("Direct")} direct · ${count("Primary")} primary · ${count("Nested")} nested</small></div>
<div class="inbox-work-filter"><input type="search" data-work-filter placeholder="Filter groups" aria-label="Filter groups" autocomplete="off" /><button type="button" data-work-copy>Copy names</button></div>
${groupList(list)}
<p class="inbox-work-muted" data-work-hidden hidden></p>
${(result.warnings || []).map((text) => `<p class="inbox-work-muted">${esc(text)}</p>`).join("")}`;
  }

  // "Same access as…": groups the colleague has that this person lacks, and the other way round.
  async function compare(identity) {
    identity = String(identity || "").trim();
    const base = state.groups["user-groups"], host = pane("user-groups").querySelector("[data-work-compare-result]");
    if (!identity || !base || !host) return;
    busy(host, `Looking up ${identity} in Active Directory…`);
    try {
      const other = await adLookup("user", identity);
      if (state.groups["user-groups"] !== base) return;
      const names = (result) => new Set((result.groups || []).map((group) => String(group.name).toLowerCase()));
      const mine = names(base.result), theirs = names(other);
      const missing = (other.groups || []).filter((group) => !mine.has(String(group.name).toLowerCase()) && group.membership !== "Primary");
      const extra = (base.result.groups || []).filter((group) => !theirs.has(String(group.name).toLowerCase()) && group.membership !== "Primary");
      const label = other.details?.Name || other.details?.Account || identity, me = fullName(state.user);
      host.innerHTML = `<div class="inbox-work-toolbar"><b>${esc(label)} has, ${esc(me)} lacks (${missing.length})</b>${missing.length ? '<button type="button" data-work-copy-missing>Copy</button>' : ""}</div>
${missing.length ? groupList(missing).replace('class="inbox-work-groups"', 'class="inbox-work-groups" data-compare="missing"') : '<p class="inbox-work-muted">Nothing missing.</p>'}
<details class="inbox-work-details"><summary>Only ${esc(me)} has (${extra.length})</summary>${groupList(extra)}</details>
<p class="inbox-work-muted">${mine.size - extra.length} group${mine.size - extra.length === 1 ? "" : "s"} in common.</p>`;
      state.missing = missing.map((group) => group.name);
    } catch (error) {
      host.innerHTML = `<p class="inbox-work-error" role="alert">${esc(error.message)}</p>`;
    } finally {
      host.removeAttribute("aria-busy");
    }
  }

  function filterGroups(input) {
    const host = input.closest("[data-work-pane]"), term = input.value.trim().toLowerCase();
    let hidden = 0;
    host.querySelectorAll(":scope > .inbox-work-groups [data-group]").forEach((row) => { row.hidden = !!term && !row.dataset.group.includes(term); hidden += row.hidden; });
    const note = host.querySelector("[data-work-hidden]");
    note.hidden = !hidden;
    note.textContent = hidden ? `${hidden} group${hidden === 1 ? "" : "s"} hidden by the filter.` : "";
  }

  async function knowledge() {
    const id = state.document, host = pane("knowledge");
    state.done.knowledge = id;
    if (!String(id).startsWith("article:")) {
      host.innerHTML = '<p class="inbox-work-muted">This Knowledge Base entry is a diagram; it opens in the diagram viewer.</p><button type="button" data-work-kb-open>Open diagram ↗</button>';
      return;
    }
    busy(host, "Opening the article…");
    try {
      const article = await window.AtlasClient.request("/api/knowledge/articles/" + encodeURIComponent(id.slice(8)));
      if (state.done.knowledge !== id) return;
      state.article = article;
      const tags = Array.isArray(article.tags) ? article.tags : [];
      host.innerHTML = `<div class="inbox-work-toolbar"><b>${esc(article.title)}</b><span><button type="button" data-work-kb-copy>Copy text</button><button type="button" data-work-kb-open>Knowledge Base ↗</button></span></div>${tags.length ? `<p class="inbox-work-muted">${esc(tags.join(" · "))}</p>` : ""}<div class="kb-markdown inbox-work-article"></div>`;
      const body = host.querySelector(".inbox-work-article");
      if (window.AtlasKnowledgeArticles?.render) await window.AtlasKnowledgeArticles.render(article.markdown, body);
      else body.textContent = article.markdown;
    } catch (error) {
      if (state.done.knowledge !== id) return;
      delete state.done.knowledge;
      failed(host, error);
    } finally {
      host.removeAttribute("aria-busy");
    }
  }

  function invalidateLookup() {
    lookupGeneration++;
    state.results = null;
    const host = dock?.querySelector("[data-work-results]");
    if (host) { host.hidden = true; host.removeAttribute("aria-busy"); }
  }

  // Anyone in Atlas: only the latest lookup in the current request can select a result.
  async function lookup(term) {
    invalidateLookup();
    const generation = lookupGeneration;
    const current = () => generation === lookupGeneration && !dock.hidden && inbox()?.classList.contains("active");
    term = String(term || "").trim();
    const host = dock.querySelector("[data-work-results]");
    if (!term) { host.hidden = true; return; }
    host.hidden = false;
    busy(host, `Looking up ${term}…`);
    try {
      const result = await window.AtlasClient.request("/api/search?term=" + encodeURIComponent(term));
      if (!current()) return;
      const users = (result.users || []).slice(0, 8), machines = (result.machines || []).slice(0, 8);
      state.results = { users, machines };
      if (users.length + machines.length === 1) {
        host.hidden = true;
        return users.length ? open({ user: users[0] }, "person") : open({ machine: machineName(machines[0]) }, "health", "quick");
      }
      host.innerHTML = users.length + machines.length
        ? `${users.map((u, i) => `<button type="button" data-work-pick-user="${i}"><b>${esc(fullName(u))}</b><small>${esc([u.user_name, u.email, u.department].filter(Boolean).join(" · "))}</small></button>`).join("")}${machines.map((m, i) => `<button type="button" data-work-pick-machine="${i}"><b>${esc(machineName(m))}</b><small>${esc([m.device_kind, m.model_id].filter(Boolean).join(" · "))}</small></button>`).join("")}${(result.users || []).length + (result.machines || []).length > users.length + machines.length ? '<p class="inbox-work-muted">More matches: refine the search.</p>' : ""}`
        : `<p class="inbox-work-muted">Nobody and no PC in Atlas matches "${esc(term)}".</p>`;
    } catch (error) {
      if (!current()) return;
      host.innerHTML = `<p class="inbox-work-error" role="alert">${esc(error.message)}</p>`;
    } finally {
      if (current()) host.removeAttribute("aria-busy");
    }
  }

  // The Workspace deployment panel moves here once Deploy is opened and stays while the tools
  // are open, so every deployment control (package, script, Install/Repair/Uninstall, queue,
  // progress) works unchanged and a half-chosen package survives switching tools.
  function dockDeployment() {
    const panel = document.getElementById("deploymentPanel");
    if (!panel) return;
    if (!home) home = { parent: panel.parentNode, next: panel.nextSibling };
    if (panel.parentNode !== pane("deploy")) pane("deploy").append(panel);
    state.docked = true;
    syncDeploymentPanel({ selection: true });
  }

  // sync=false when leaving Live Inbox: page() syncs once the next page is active.
  function undock(sync = true) {
    const panel = document.getElementById("deploymentPanel");
    if (!home || !panel || panel.parentNode === home.parent) return;
    home.parent.insertBefore(panel, home.next?.parentNode === home.parent ? home.next : null);
    if (sync) syncDeploymentPanel();
  }

  function close() {
    invalidateLookup();
    undock();
    state.docked = false;
    const host = dock.querySelector("[data-work-health]");
    if (host) window.AtlasHealth?.cancel(host);
    dock.hidden = true;
  }

  // Switching PC keeps the same PC tool on screen.
  function switchMachine(name, owner) {
    const user = owner === undefined ? state.user : owner;
    use(name, user);
    const needs = TABS.find(([tab]) => tab === state.tab)[2];
    show(needs === "machine" ? state.tab : "health", "show");
  }

  async function click(event) {
    const button = event.target.closest("button");
    if (!button || button.disabled || !dock.contains(button) || button.type === "submit") return;
    const data = button.dataset, detail = { machine: state.machine, user: state.user };
    if ("workClose" in data) return close();
    if (data.workTab) return show(data.workTab);
    if (data.workTabLink) return show(data.workTabLink);
    if ("workRescan" in data) return show(state.tab, "scan");
    if (data.workPerson) return open({ user: requestEntries().people[Number(data.workPerson)].user }, state.tab === "user-groups" ? "user-groups" : "person");
    if (data.workMachine) {
      const entry = requestEntries().machines[Number(data.workMachine)];
      return switchMachine(entry.name, entry.owner);
    }
    if (data.workPickUser) { dock.querySelector("[data-work-results]").hidden = true; return open({ user: state.results.users[Number(data.workPickUser)] }, "person"); }
    if (data.workPickMachine) { dock.querySelector("[data-work-results]").hidden = true; return open({ machine: machineName(state.results.machines[Number(data.workPickMachine)]) }, "health", "quick"); }
    if (data.workUse) { use(data.workUse, state.user); return show(data.then || "health", data.then === "health" ? "quick" : "show"); }
    if (data.workSort) { state.performance.sort = data.workSort; return renderPerformance(); }
    if (data.workEnd) return endProcess(data.workEnd);
    if (data.workTool) { target(); return openTargetTool(data.workTool); }
    if ("workSoftware" in data) { target(); return loadSoftware(state.machine); }
    if ("workServices" in data) { target(); return window.AtlasServices?.load(); }
    if ("workSpecs" in data) return window.AtlasHealth.specs(state.machine);
    if ("workReboot" in data) return window.AtlasInboxActions.run({ ...detail, action: "reboot" });
    if ("workCompareWith" in data) return compare(data.workCompareWith);
    if ("workCopy" in data) {
      const names = [...button.closest("[data-work-pane]").querySelectorAll(":scope > .inbox-work-groups [data-group]:not([hidden]) > span:first-child")].map((node) => node.textContent);
      return copy(names.join("\n"), names.length + " group names");
    }
    if ("workCopyMissing" in data) return copy((state.missing || []).join("\n"), (state.missing || []).length + " missing groups");
    if ("workCopyPerson" in data) {
      const { user, machines = [], desks = [] } = state.person;
      return copy([fullName(user), ...RECORD.filter(([, key]) => user[key]).map(([label, key]) => `${label}: ${user[key]}`),
        desks.length ? "Desk: " + desks.map((desk) => desk.id).join(", ") : "", machines.length ? "PCs: " + machines.map(machineName).join(", ") : ""].filter(Boolean).join("\n"), "Person summary");
    }
    if ("workKbCopy" in data) return copy(state.article?.markdown || "", "Article");
    if ("workKbOpen" in data) return window.AtlasKnowledge.show(state.document);
    if ("workAd" in data) {
      const { kind, id } = state.groups[state.tab];
      return window.AtlasAD.show(kind, id);
    }
    if ("workAdmin" in data) { target(); return page("admin"); }
    if ("workWorkspace" in data) {
      if (state.machine) target();
      page("workspace");
      if (state.user?.id && S.user?.id !== state.user.id) await loadUser("id:" + state.user.id);
    }
  }

  // The message on screen in Live Inbox (sent by live-inbox.jsx), for "In this request".
  window.addEventListener("atlas:inbox-detail", (event) => {
    if (event.detail?.message?.id !== state.request?.message?.id) invalidateLookup();
    state.request = event.detail;
    renderRequest();
  });

  // "Back to Live Inbox" after a Live Inbox button opened another page (Knowledge Base, Workspace,
  // Active Directory, Remote Admin). The sidebar does not show it.
  function returnButton(visible) {
    if (!back && !visible) return;
    if (!back) {
      back = document.createElement("button");
      back.type = "button";
      back.id = "inboxReturn";
      back.className = "inbox-return";
      back.textContent = "← Back to Live Inbox";
      back.onclick = () => page("inbox");
      document.body.append(back);
    }
    back.hidden = !visible;
  }
  // True only while a click inside Live Inbox is being handled, so page changes it causes are known.
  window.addEventListener("click", (event) => {
    inboxClick = !!event.target.closest?.("#inbox");
    if (inboxClick) setTimeout(() => { inboxClick = false; });
  }, true);
  window.addEventListener("click", () => { inboxClick = false; });

  const original = window.page;
  window.page = function (id) {
    const leaving = id !== "inbox" && !!inbox()?.classList.contains("active");
    // Back in Workspace before the switch, so the panel is never hidden with a package half chosen.
    if (leaving) { invalidateLookup(); undock(false); }
    const result = original.apply(this, arguments);
    if (id === "inbox") {
      returnButton(false);
      try {
        // Deploy on screen takes the request's machine back; otherwise only re-dock when the target is unchanged.
        if (dock && !dock.hidden && state.docked) state.tab === "deploy" ? show("deploy") : S.target === state.machine && dockDeployment();
      } catch (error) {
        toast(error.message);
      }
    } else if (leaving && inboxClick) returnButton(true);
    return result;
  };

  window.AtlasInboxWork = { open, close, show, isOpen: () => !!dock && !dock.hidden && dock.isConnected, state: () => ({ machine: state.machine, tab: state.tab, user: state.user?.id }) };
})();
