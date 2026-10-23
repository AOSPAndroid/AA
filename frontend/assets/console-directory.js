function workspaceLookupPresentation(phase = "ready", message = "") {
  const column = $("#workspace .lookup-column"), empty = $("#workspace .lookup-empty"), status = $("#lookupStatus");
  const populated = !!S.user || S.users.length > 0 || S.machines.length > 0 || !!(S.selectedDevice || S.target);
  column.setAttribute("aria-busy", phase === "loading" ? "true" : "false");
  empty.hidden = populated || phase === "loading" || phase === "error";
  empty.querySelector("h3").textContent = phase === "ready" ? "No matching records" : "Find a user or machine";
  empty.querySelector("p").textContent = phase === "ready"
    ? "Try an account, email, name or hostname."
    : "Look up a colleague to see their linked devices, or search for a hostname directly.";
  if (!status) return;
  status.dataset.state = phase;
  status.hidden = phase === "idle";
  const capped = S.lookupSource !== "machine" && (S.users.length >= 100 || S.machines.length >= 100);
  status.textContent = message || (phase === "loading" ? "Searching directory…"
    : phase === "error" ? "Directory lookup unavailable. Try again."
    : S.user ? `User record · ${S.machines.length} linked ${S.machines.length === 1 ? "device" : "devices"}`
    : S.users.length || S.machines.length ? [
      S.users.length ? `${S.users.length} ${S.lookupSource === "machine" ? "linked " : ""}${S.users.length === 1 ? "user" : "users"}${capped ? " shown" : ""}` : "",
      S.machines.length ? `${S.machines.length} ${S.machines.length === 1 ? "device" : "devices"}${capped ? " shown" : ""}` : "",
    ].filter(Boolean).join(" · ") + (capped ? " · refine search" : S.lookupAmbiguousMachine ? " · choose the full device identity"
      : S.users.length ? " found · select a record" : S.selectedDevice || S.target ? " found · device selected" : " found · select a device")
    : S.target ? "Hostname target · no directory record" : "No matching directory records");
}
function syncMachineSelection() {
  const pc = S.selectedDevice || S.target;
  $$("#machines [data-machine]").forEach(card => {
    const selected = !!pc && String(S.machines[+card.dataset.machine]?.name || "").toUpperCase() === pc;
    card.classList.toggle("selected", selected);
    card.querySelector(".workspace-machine-select")?.setAttribute("aria-pressed", String(selected));
  });
}
function workspaceMachineRelationship(machine) {
  if (!S.user) return {text: AtlasUI.isCitrixVdi(machine) ? "Citrix inventory · assignment snapshot" : "Directory device · inventory record", title: "Stored device record; a user relationship has not been selected."};
  const assigned = !!Number(machine.assigned_relationship), logon = !!Number(machine.logon_relationship);
  return {text: assigned && logon ? "Assigned + last logged on · inventory"
    : assigned ? "Assigned to this user" + (AtlasUI.isCitrixVdi(machine) ? " · Citrix snapshot" : "")
    : logon ? "Last logged on only · inventory"
    : machine.desk_equipment ? "Recorded desk equipment" : machine.match_type || "Linked in directory export",
    title: "Relationship to " + (S.user.user_name || S.user.name || "the selected user") + ". Imported assignment and logon records do not confirm a current sign-in."};
}
function setTarget(pc, status = "", quick = true) {
  pc = String(pc || "")
    .trim()
    .toUpperCase();
  if (!pc) return;
  const record = S.machines.find(m => String(m.name || "").toUpperCase() === pc) || {name: pc};
  const citrix = AtlasUI.isCitrixVdi(record);
  if (citrix) {
    quick = false;
    status = ["Citrix snapshot", record.vdi_registration_state || record.vdi_state, record.vdi_power_state].filter(Boolean).join(" · ");
  }
  S.selectedDevice = pc;
  if (!AtlasUI.supportsWindows(record)) {
    S.target = "";
    window.AtlasPsExec?.syncTarget("");
    window.AtlasDiagnostics?.stop("Selected an inventory device");
    AtlasHealth.cancel($("#healthLine"));
    $("#adminPc").value = "";
    invalidateProcesses();
    syncDeploymentPanel();
    $("#deployTarget").textContent = "Select a PC";
    $("#targetBar").classList.add("hidden");
    $("#healthLine").classList.add("hidden");
    $("#preflight").innerHTML = "";
    $("#packagePresence").innerHTML = "";
    syncMachineSelection();
    workspaceLookupPresentation();
    refreshConsoleSummary();
    window.AtlasSelection?.refresh();
    return;
  }
  if (pc === S.target) {
    $("#barState").textContent = status;
    syncMachineSelection();
    workspaceLookupPresentation();
    if (quick) refreshTargetHealth("quick");
    window.AtlasSelection?.refresh();
    return;
  }
  S.target = pc;
  window.AtlasPsExec?.syncTarget(pc);
  syncDeploymentPanel({ selection: true });
  $("#deployTarget").textContent = pc;
  $("#adminPc").value = pc;
  invalidateProcesses();
  $("#barTarget").textContent = pc;
  $("#barState").textContent = status;
  $("#targetBar").classList.remove("hidden");
  syncMachineSelection();
  rememberTarget(pc);
  refreshTargetHealth(quick ? "quick" : false);
  if (citrix) {
    const note = $("#healthLine p");
    if (note) note.textContent = AtlasUI.machineSnapshotNote(record);
  }
  refreshConsoleSummary();
  updatePackagePresence();
  window.AtlasSelection?.refresh();
  workspaceLookupPresentation();
}
function clearLookup(invalidate = true) {
  if (invalidate) ++lookupSequence;
  clearDirectTarget();
  AtlasHealth.cancel($("#healthLine"));
  S.user = null;
  S.users = [];
  S.machines = [];
  S.target = "";
  S.selectedDevice = "";
  S.lookupSource = "";
  S.lookupAmbiguousMachine = false;
  window.AtlasPsExec?.syncTarget("");
  syncDeploymentPanel();
  masterState.resolution = null;
  $("#kyc").innerHTML = "";
  $("#users").innerHTML = "";
  $("#machines").innerHTML = "";
  $("#deployTarget").textContent = "Select a machine";
  $("#adminPc").value = "";
  invalidateProcesses();
  $("#targetBar").classList.add("hidden");
  $("#healthLine").classList.add("hidden");
  $("#preflight").innerHTML = "";
  $("#packagePresence").innerHTML = "";
  window.AtlasSelection?.refresh();
  workspaceLookupPresentation("idle");
}
function directHostname(term) {
  const pc = term.replace(/^machine:\s*/i, "").trim().toUpperCase();
  return /^[A-Z0-9_.-]{1,64}$/.test(pc) && !/^[-.]/.test(pc) && !pc.includes("..") ? pc : "";
}
function clearDirectTarget() {
  $("#useHostname").hidden = true;
  $("#useHostname").onclick = null;
  $("#unlistedTargetStatus").hidden = true;
  $("#workspace .lookup-empty").hidden = false;
}
function offerDirectTarget(term, sequence) {
  if (sequence !== lookupSequence || $("#search").value.trim() !== term) return;
  const pc = directHostname(term);
  if (!pc) return toast("No matching users or machines");
  const button = $("#useHostname"), status = $("#unlistedTargetStatus");
  status.textContent = `No directory record for ${pc}. You can use this hostname as a target.`;
  status.hidden = false;
  $("#workspace .lookup-empty").hidden = true;
  button.hidden = false;
  button.title = `Use ${pc} as target`;
  button.onclick = () => {
    if (button.hidden || sequence !== lookupSequence || $("#search").value.trim() !== term) return;
    clearDirectTarget();
    $("#workspace .lookup-empty").hidden = true;
    setTarget(pc, "Entered hostname · not in directory");
    openDeploymentPanel();
  };
}
async function search() {
  const term = $("#search").value.trim(),
    sequence = ++lookupSequence;
  clearLookup(false);
  if (!term) return toast("Enter a search");
  workspaceLookupPresentation("loading");
  try {
    let resolved = null;
    if (!term.includes(":"))
      resolved = await api("/api/master/resolve/" + encodeURIComponent(term));
    if (sequence !== lookupSequence) return;
    if (resolved?.matched) {
      await loadUser(resolved.user_key, sequence);
      if (sequence === lookupSequence && resolved.requested_machine)
        setTarget(resolved.requested_machine, "Database record");
      return;
    }
    const machineContext = !!resolved?.machine || Array.isArray(resolved?.machines) && resolved.machines.length > 0;
    const d = machineContext || resolved?.ambiguous && resolved?.users?.length
      ? {users: resolved.users || [], machines: resolved.machine ? [resolved.machine] : resolved.machines || []}
      : await api("/api/search?term=" + encodeURIComponent(term));
    if (sequence !== lookupSequence) return;
    S.users = d.users;
    S.machines = d.machines;
    S.lookupSource = machineContext ? "machine" : "";
    S.lookupAmbiguousMachine = machineContext && !resolved.machine && !!resolved.ambiguous;
    if (d.users.length === 1 && !d.machines.length)
      return loadUser(AtlasUI.personKey(d.users[0]), sequence);
    renderUsers();
    renderMachines();
    if (!d.users.length && !d.machines.length)
      offerDirectTarget(term, sequence);
  } catch (error) {
    if (sequence !== lookupSequence) return;
    workspaceLookupPresentation("error", "Directory lookup unavailable · " + error.message);
    throw error;
  }
}
function renderUsers() {
  if (!S.users.length) {$("#users").innerHTML = "";workspaceLookupPresentation();return;}
  const heading = S.lookupSource === "machine" ? "Linked users" : "Matching users";
  $("#users").innerHTML =
    `<section class="workspace-user-results" aria-label="${heading}"><div class="workspace-result-heading"><strong>${heading}</strong><small>${S.users.length} ${S.users.length === 1 ? "record" : "records"}${S.users.length >= 100 && S.lookupSource !== "machine" ? " shown" : ""}</small></div><ul class="workspace-user-result-list">${S.users.map((u, i) => `<li class="workspace-user-result"><button type="button" class="workspace-user-result-select" ${AtlasContext.attributes("user", u)} data-user="${i}"><span class="workspace-result-avatar" aria-hidden="true">${esc((u.full_name || u.name || u.user_name || "?").trim().split(/\s+/).slice(0,2).map(word => word[0]).join(""))}</span><span class="workspace-user-result-info"><strong>${esc(u.full_name || u.name || u.user_name || "Unnamed user")}</strong><span>${esc([u.user_name || u.user_id, u.location].filter(Boolean).join(" · ") || "Account details not supplied")}</span>${u.email ? '<small>' + esc(u.email) + '</small>' : ""}</span></button><button type="button" class="workspace-user-result-copy" data-email="${i}" ${String(u.email || "").trim() ? "" : "disabled"} aria-label="Copy email for ${esc(u.full_name || u.name || u.user_name || "this user")}" title="${String(u.email || "").trim() ? "Copy email" : "Email not supplied"}">${AtlasUI.icon("copy")}<span>Copy email</span></button></li>`).join("")}</ul></section>`;
  $$("[data-user]").forEach(
    (b) =>
      (b.onclick = () =>
        loadUser(AtlasUI.personKey(S.users[+b.dataset.user])).catch((e) =>
          toast(e.message),
        )),
  );
  $$("[data-email]").forEach(
    (b) => (b.onclick = () => copy(S.users[+b.dataset.email].email, "Email")),
  );
  workspaceLookupPresentation();
}
async function loadUser(id, sequence) {
  if (sequence === undefined) {
    sequence = ++lookupSequence;
    clearLookup(false);
  }
  workspaceLookupPresentation("loading", "Loading user record…");
  try {
    const d = await api("/api/user/" + encodeURIComponent(id));
    if (sequence !== lookupSequence) return;
    if (!d.user || !Array.isArray(d.machines)) throw Error("User record unavailable.");
    S.user = d.user;
    S.machines = d.machines;
    S.users = [];
    S.lookupSource = "";
    S.lookupAmbiguousMachine = false;
    $("#users").innerHTML = "";
    renderKyc();
    renderMachines();
    AtlasUI.motion.slideUp($("#kyc"));
    workspaceLookupPresentation();
  } catch (error) {
    if (sequence !== lookupSequence) return;
    workspaceLookupPresentation("error", "User record unavailable · " + error.message);
    throw error;
  }
}
function renderKyc() {
  const u = S.user;
  $("#kyc").innerHTML = AtlasUI.person(u);
  const title = $("#kyc h2"), select = document.createElement("button");
  select.type = "button";
  select.className = "workspace-user-select";
  select.textContent = title.textContent;
  select.setAttribute("aria-label", "Show groups for " + (u.user_name || u.name));
  select.onclick = () => window.AtlasAD?.show("user", u.user_name || u.email || "");
  title.replaceChildren(select);
  // Resolve the support summary on click so a newly selected PC is included.
  $("#kyc [data-copy-label='Summary']").atlasCopyValue = () => supportSummary();
  applyCompactWorkspace();
  window.AtlasSelection?.refresh();
}
function renderMachines() {
  if (!S.machines.length) {$("#machines").innerHTML = "";workspaceLookupPresentation();return;}
  $("#machines").innerHTML =
    `<div class=machinegrid>${S.machines.map((m, i) => `<div class="card machine ${String(m.name || "").toUpperCase() === (S.selectedDevice || S.target) ? "selected" : ""}" data-machine-kind="${AtlasUI.machineKind(m)}" data-machine="${i}"><button class=copyhost data-host="${i}" aria-label="Copy device identity for ${esc(m.name)}">${AtlasUI.icon("copy")}<span>Copy</span></button><h3>${esc(m.name)}</h3><p class="workspace-device-model"><span class="workspace-device-model-name">${esc(m.model_id || m.model_category || "Model not supplied")}</span>${m.asset_tag ? '<span class="workspace-device-asset">Asset: ' + esc(m.asset_tag) + '</span>' : ""}</p>${AtlasUI.supportsWindows(m) ? "" : '<p class="atlas-device-note">Inventory only · ' + (AtlasUI.isCitrixVdi(m) ? 'No safe Windows target supplied.' : 'Windows tools require a PC.') + '</p>'}<div class=facts><span>Match<b>${esc(m.match_type || "Device identity")}</b></span><span>Inventory discovered<b>${esc(m.last_discovered || "Not supplied")}</b></span><span>Record updated<b>${esc(m.updated_on || "Not supplied")}</b></span>${m.operational_status ? `<span>Inventory status<b>${esc(m.operational_status)}</b></span>` : ""}</div></div>`).join("")}</div>`;
  $$("[data-machine]").forEach(
    (x) =>
      (x.onclick = () =>
        setTarget(
          S.machines[+x.dataset.machine].name,
          S.machines[+x.dataset.machine].operational_status,
        )),
  );
  $$("[data-host]").forEach(
    (x) =>
      (x.onclick = (e) => {
        e.stopPropagation();
        copy(S.machines[+x.dataset.host].name, "Device identity");
      }),
  );
  if (S.machines.length === 1) {
    let m = S.machines[0];
    setTarget(m.name, m.operational_status, false);
  }
  AtlasUI.machineFilters($("#machines"), {linked: !!S.user});
  bindMachineContext();
  document.querySelectorAll("#machines [data-machine]").forEach((card) => {
    const m = S.machines[Number(card.dataset.machine)];
    card.insertAdjacentHTML("beforeend", AtlasHealth.badges(m));
    const relationship = workspaceMachineRelationship(m), relation = document.createElement("p");
    relation.className = "workspace-device-relationship";relation.textContent = relationship.text;relation.title = relationship.title;
    card.append(relation);
    card.insertAdjacentHTML("beforeend", AtlasUI.machineDetails(m));
    card.querySelector(".atlas-machine-details").onclick = (event) =>
      event.stopPropagation();
    const details = card.querySelector(".atlas-machine-details"), facts = card.querySelector(".facts");
    details.append(facts);
    const heading = card.querySelector("h3"), choose = document.createElement("button");
    choose.type = "button";choose.className = "workspace-machine-select";
    const symbol = document.createElement("span"), name = document.createElement("span");
    symbol.className = "workspace-device-icon";
    const kind = AtlasUI.machineKind(m);
    symbol.innerHTML = AtlasUI.icon(kind === "laptop" ? "laptop" : kind === "tablet" ? "tablet" : ["iphone", "phone"].includes(kind) ? "phone" : "admin");
    name.className = "workspace-device-name";name.textContent = m.name;
    choose.append(symbol, name);
    choose.setAttribute("aria-label", AtlasUI.supportsWindows(m) ? "Select machine " + m.name : "Select inventory device " + m.name);
    heading.replaceChildren(choose);
    card.classList.add("workspace-machine-row");
  });
  syncMachineSelection();
  workspaceLookupPresentation();
  applyCompactWorkspace();
}
// Reuse the selected records and existing health snapshot across console pages.
// Rendering this sidebar never starts a directory lookup or a remote check.
function installSelectionSidebar() {
  const context = $("#selectionContext"), summary = $("#selectionSummary");
  if (!context || !summary || window.AtlasSelection) return;
  context.open = window.innerWidth > 760;
  summary.innerHTML = `<p class="selection-empty">Select a user or device in Workspace to keep their details here.</p>
    <section class="selection-card selection-user" aria-label="Selected user" hidden>
      <small class="selection-label">User</small><button type="button" class="selection-name" data-selection-user><span class="selection-avatar" aria-hidden="true"></span><span class="selection-title"></span></button>
      <div class="selection-user-facts"></div>
    </section>
    <section class="selection-card selection-machine" aria-label="Selected device" hidden>
      <small class="selection-label">Device</small><button type="button" class="selection-name" data-selection-machine><span class="selection-device-icon" aria-hidden="true">${AtlasUI.icon("admin")}</span><span class="selection-title"></span></button>
      <div class="selection-device-facts"></div><div class="selection-readings"></div>
      <p class="selection-checked"></p><button type="button" class="selection-scan">Scan health</button>
    </section>`;
  const person = summary.querySelector(".selection-user"), device = summary.querySelector(".selection-machine"),
    personButton = summary.querySelector("[data-selection-user]"), deviceButton = summary.querySelector("[data-selection-machine]"),
    scan = summary.querySelector(".selection-scan"), caption = $("#selectionCaption"), empty = summary.querySelector(".selection-empty");
  const text = (element, value) => { if (element.textContent !== value) element.textContent = value; };
  const rendered = new WeakMap();
  const html = (element, value) => {
    if (rendered.get(element) !== value) {element.innerHTML = value; rendered.set(element, value);}
  };
  const back = (selector) => {
    page("workspace");
    const host = typeof selector === "string" ? $(selector) : selector;
    host.querySelector("details")?.setAttribute("open", "");
    host.scrollIntoView({block: "center", behavior: AtlasUI.motion.isReduced() ? "instant" : "smooth"});
    host.querySelector("button, summary")?.focus({preventScroll: true});
  };
  personButton.onclick = () => back("#kyc");
  deviceButton.onclick = () => {
    const card = $$("#machines [data-machine]").find(node => String(S.machines[+node.dataset.machine]?.name || "").toUpperCase() === (S.selectedDevice || S.target));
    back(card || "#healthLine");
  };
  scan.onclick = () => { if (S.target && !window.AtlasReadOnly) refreshTargetHealth(); };
  function refresh() {
    if (!context.isConnected) return;
    const user = S.user, pc = S.selectedDevice || S.target;
    const record = S.machines.find(m => String(m.name || "").toUpperCase() === pc) || {name: pc};
    const windows = !!S.target && AtlasUI.supportsWindows(record), host = $("#healthLine");
    person.hidden = !user; device.hidden = !pc; empty.hidden = !!user || !!pc;
    window.AtlasCopilot?.refresh();
    text(caption, [user?.full_name || user?.name || user?.user_name, pc].filter(Boolean).join(" · "));
    if (user) {
      const name = user.full_name || user.name || user.user_name || "Selected user";
      text(personButton.querySelector(".selection-title"), name); personButton.title = "Open details for " + name;
      const words = String(name).trim().split(/\s+/);
      text(personButton.querySelector(".selection-avatar"), ((words[0][0] || "?") + (words.length > 1 ? words.at(-1)[0] : "")).toUpperCase());
      html(summary.querySelector(".selection-user-facts"), `<b class="selection-account">${esc(user.user_name || "Account not supplied")}</b>${user.email ? `<span class="selection-email" title="${esc(user.email)}">${esc(user.email)}</span>` : ""}<dl class="selection-meta">${[["Team", user.department || user.business_unit], ["Office", user.location]].filter(([, value]) => value).map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`);
    }
    if (!pc) return;
    text(deviceButton.querySelector(".selection-title"), pc); deviceButton.title = "Open stored details for " + pc;
    const kind = AtlasUI.machineKind(record);
    html(deviceButton.querySelector(".selection-device-icon"), AtlasUI.icon(kind === "laptop" ? "laptop" : kind === "tablet" ? "tablet" : ["iphone", "phone"].includes(kind) ? "phone" : "admin"));
    html(summary.querySelector(".selection-device-facts"), `<p>${esc(record.model_id || record.model_category || "Model not supplied")}</p>${record.asset_tag ? `<dl class="selection-meta"><div><dt>Asset</dt><dd>${esc(record.asset_tag)}</dd></div></dl>` : ""}${S.machines.includes(record) ? AtlasUI.machineBadges(record) : '<small>Hostname target · no inventory record</small>'}`);
    scan.hidden = !windows;
    if (!windows) {
      html(summary.querySelector(".selection-readings"), '<p class="selection-note">Inventory device · PC health checks unavailable.</p>');
      text(summary.querySelector(".selection-checked"), ""); return;
    }
    const readings = AtlasHealth.compact(host, S.target), specs = AtlasHealth.specifications(host, S.target);
    html(summary.querySelector(".selection-readings"), `<div class="selection-health-grid">${readings.filter(row => ["ping", "cshare", "storage", "system"].includes(row.key)).map(row => `<div class="${row.warning ? "warning" : row.text === "Available" ? "ready" : ""}" title="${esc(row.title)}"><b>${esc(row.key === "system" ? "Uptime" : row.label)}</b><span>${esc(row.key === "system" ? row.text.replace(/ uptime$/, "") : row.text)}</span></div>`).join("")}</div>${specs.length ? `<dl class="selection-specs">${specs.map(row => `<div${row.label === "CPU model" ? ' class="selection-spec-wide"' : ""}><dt>${esc(row.label === "Windows" ? "OS" : row.label)}</dt><dd>${esc(row.text)}</dd></div>`).join("")}</dl>` : ""}`);
    const dates = readings.map(row => row.checkedAt).filter(value => value && Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(b) - Date.parse(a));
    const checking = !!host.querySelector("[data-health-refresh]:disabled");
    const checked = summary.querySelector(".selection-checked");
    text(checked, window.AtlasReadOnly ? "Stored inventory · live health requires Admin" : checking ? "Checking selected PC…" : dates.length ? "Last check · " + new Intl.DateTimeFormat(undefined, {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}).format(new Date(dates[0])) : "No successful health check yet");
    checked.title = dates.length ? "Last check: " + new Date(dates[0]).toLocaleString() : "";
    scan.disabled = !!window.AtlasReadOnly || checking;
    scan.title = window.AtlasReadOnly?.reason || "Manually check connectivity and retrieve this PC's specifications";
    text(scan, checking ? "Checking…" : "Scan health");
  }
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true; queueMicrotask(() => {queued = false; refresh();});
  };
  // Watch only the existing health host, including check completion and failures.
  const observer = new MutationObserver(schedule);
  observer.observe($("#healthLine"), {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["disabled", "class"]});
  window.addEventListener("pagehide", () => observer.disconnect(), {once: true});
  window.AtlasSelection = {refresh};
  refresh();
}
function targetPrefs() {
  return JSON.parse(localStorage.getItem("wmiTargetPrefs") || '{"recent":[]}');
}
function saveTargetPrefs(p) {
  localStorage.setItem("wmiTargetPrefs", JSON.stringify(p));
}
function rememberTarget(pc) {
  if (!pc) return;
  const p = targetPrefs();
  p.recent = [pc, ...p.recent.filter((x) => x !== pc)].slice(0, 10);
  saveTargetPrefs(p);
  renderRecentTargets();
}
function renderRecentTargets() {
  const host = document.querySelector("#recentTargets");
  if (!host) return;
  const values = targetPrefs().recent;
  host.innerHTML = values.length
    ? `<small>Recent targets</small><div class="recent-target-list">${values.map((x) => `<button data-recent-target="${esc(x)}">${esc(x)}</button>`).join("")}</div>`
    : "";
  document.querySelectorAll("[data-recent-target]").forEach(
    (b) =>
      (b.onclick = () => {
        setTarget(b.dataset.recentTarget, "Recent target");
        document.querySelector("#search").value = b.dataset.recentTarget;
      }),
  );
}
function supportSummary() {
  const u = S.user || {},
    m = (S.machines || []).find((x) => String(x.name || "").toUpperCase() === S.target) || {};
  return [
    `Timestamp: ${new Date().toLocaleString("en-GB")}`,
    `User: ${u.name || ""}`,
    `Username: ${u.user_name || ""}`,
    `Domain account: ${AtlasUI.domainAccount(u)}`,
    `Email: ${u.email || ""}`,
    `Location: ${u.location || ""}`,
    `Manager: ${u.manager || ""}`,
    `Target: ${S.target || ""}`,
    `Status: ${m.operational_status || ""}`,
    `Model: ${m.model_id || ""}`,
    `Serial: ${m.serial_number || ""}`,
    `Last discovered: ${m.last_discovered || ""}`,
  ].join("\n");
}
function machineContext(event, index) {
  event.preventDefault();
  event.stopPropagation();
  const m = S.machines[index],
    menu = document.querySelector("#machineMenu");
  if (!m || !menu) return;
  const windows = AtlasUI.supportsWindows(m);
  menu.replaceChildren();
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", "Actions for " + m.name);
  const close = () => menu.classList.add("hidden");
  const section = (label) => {
    const heading = document.createElement("div");
    heading.className = "atlas-context-section";
    heading.setAttribute("role", "presentation");
    heading.textContent = label;
    menu.append(heading);
  };
  const add = (cmd, label, run, select = true) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.cmd = cmd;
    button.setAttribute("role", "menuitem");
    button.tabIndex = -1;
    button.textContent = label;
    button.onclick = async () => {
      close();
      try {
        if (select) setTarget(m.name, m.operational_status, false);
        await run();
      } catch (error) {
        toast(error.message);
      }
    };
    menu.append(button);
    if (!windows && select) { button.disabled = true; button.title = "Windows tools require a PC"; }
    return button;
  };
  section("Active Directory");
  for (const action of AtlasContext.groupActions("computer", m.name, windows)) {
    const button = add(action.id, action.label, action.run, false);
    button.disabled = action.disabled;
    if (button.disabled) button.title = action.reason;
    if (action.id === "ad-groups") button.dataset.readonlyAllowed = "";
  }
  section("Target & inventory");
  add("target", "Set as target", () => {});
  add("health", "Refresh health", () => refreshTargetHealth());
  add("copy", "Copy device identity", () => copy(m.name, "Device identity"), false);
  add("details", "Copy machine details", () =>
    copy(JSON.stringify(m, null, 2), "Device details"), false,
  );
  add("inventory", "View inventory details", () => AtlasContext.inventory(m), false).dataset.readonlyAllowed = "";
  for (const [cmd, label, value] of [["copy-asset", "Copy asset tag", m.asset_tag], ["copy-serial", "Copy serial number", m.serial_number]]) {
    const button = add(cmd, label, () => AtlasContext.copy(value, label.slice(5)), false);
    button.dataset.readonlyAllowed = "";
    button.disabled = !value;
    if (!value) button.title = "Not supplied in this record";
  }
  section("Remote support");
  for (const [tool, label] of [
    ["msra", "Open MSRA"],
    ["rdp", "Remote Desktop"],
    ["compmgmt", "Computer Management"],
    ["eventvwr", "Event Viewer"],
    ["cshare", "Open C$"],
    ["temp", "Open C:\\Temp"],
    ["packages", "Open Packages"],
  ])
    add(tool, label, () => openTargetTool(tool));
  add(
    "remote-registry",
    "Enable Remote Registry",
    async () =>
      (await import("/service-actions.js")).openRemoteRegistry(m.name),
    false,
  );
  menu.querySelector('[data-cmd="remote-registry"]').disabled =
    !!window.AtlasReadOnly || !windows;
  add("admin", "Remote Admin", () => page("admin"));
  add("cpu", "Scan CPU & processes", () => {page("admin");selectPerformanceView("cpu");return admin("cpu");});
  add("memory", "Scan memory", () => {page("admin");selectPerformanceView("memory");return admin("memory");});
  add("services", "List services…", () => {page("admin");document.getElementById("adminServices").click();});
  section("Deployment");
  add("deploy", "Deploy software…", () => {page("workspace");openDeploymentPanel();document.getElementById("pkgSearch").focus();});
  add("queue", "Add deployment to queue", () => addQueue());
  add("clean", "Clean package folder", () => cleanPackages());
  section("Reports & diagnostics");
  add("specs", "View specifications", () => AtlasHealth.specs(m.name), false);
  menu.lastElementChild.disabled = !windows;
  add("software", "Software inventory", () => loadSoftware(m.name));
  add("report", "Copy device report", () =>
    copy(windows ? completeMachineReport() : AtlasUI.machineReport(m), "Device report"), windows,
  );
  menu.classList.remove("hidden");
  menu.scrollTop = 0;
  const gap = 8;
  menu.style.left = menu.style.top = gap + "px";
  // Measure after all actions are present, including the constrained height.
  const bounds = menu.getBoundingClientRect();
  const anchor = document.querySelector(`[data-machine="${index}"] .copyhost`)?.getBoundingClientRect();
  const x = Number.isFinite(event.clientX) ? event.clientX : anchor?.left || gap;
  const y = Number.isFinite(event.clientY) ? event.clientY : anchor?.bottom || gap;
  menu.style.left =
    Math.max(
      gap,
      Math.min(x, window.innerWidth - bounds.width - gap),
    ) + "px";
  menu.style.top =
    Math.max(
      gap,
      Math.min(y, window.innerHeight - bounds.height - gap),
    ) + "px";
  window.AtlasReadOnly?.enforce?.();
  const enabledButtons = () => [...menu.querySelectorAll("button")].filter(button => !button.disabled && button.getAttribute("aria-disabled") !== "true");
  menu.onkeydown = (e) => {
    const buttons = enabledButtons();
    const current = buttons.indexOf(document.activeElement);
    let next;
    if (e.key === "ArrowDown") next = (current + 1) % buttons.length;
    if (e.key === "ArrowUp")
      next = (current - 1 + buttons.length) % buttons.length;
    if (e.key === "Home") next = 0;
    if (e.key === "End") next = buttons.length - 1;
    if (next !== undefined) {
      e.preventDefault();
      e.stopPropagation();
      buttons[next].focus({ preventScroll: true });
      buttons[next].scrollIntoView({ block: "nearest", behavior: "instant" });
    }
    if (e.key === "Escape" || e.key === "Tab") {
      close();
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        const card = document.querySelector(`[data-machine="${index}"]`);
        card?.querySelector(".copyhost")?.focus({ preventScroll: true });
      }
    }
  };
  const first = enabledButtons()[0];
  first?.focus({ preventScroll: true });
  first?.scrollIntoView({ block: "nearest", behavior: "instant" });
  window.AtlasInteractions?.animateMenu(menu);
}
function bindMachineContext() {
  document
    .querySelectorAll("[data-machine]")
    .forEach(
      (card) => {
        card.oncontextmenu = e => machineContext(e, Number(card.dataset.machine));
        card.onkeydown = e => {
          if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))
            machineContext(e, Number(card.dataset.machine));
        };
      },
    );
}
function completeMachineReport() {
  const m = S.machines.find((x) => String(x.name || "").toUpperCase() === S.target) || {},
    u = S.user || {},
    inventory = softwareState.software.get(S.target);
  return [
    "Atlas machine report",
    "Generated: " + new Date().toLocaleString(),
    "Target: " + S.target,
    "User: " + (u.name || ""),
    "Account: " + (u.user_name || ""),
    "Domain account: " + AtlasUI.domainAccount(u),
    "Email: " + (u.email || ""),
    AtlasUI.machineReport({ ...m, name: S.target }),
    "Software inventory: " +
      (inventory
        ? inventory.software.length + " applications"
        : "not collected"),
    ...AtlasHealth.report($("#healthLine"), S.target),
  ].join("\n");
}
async function loadMasterStatus() {
  try {
    const d = await api("/api/master/status");
    masterState.status = d;
    const el = document.querySelector("#masterDbStatus");
    if (el)
      el.innerHTML = d.available
        ? `<b class="status-ok">MASTER DB ONLINE</b><span>${d.users.toLocaleString()} users</span><span>${d.machines.toLocaleString()} machines</span><span>${d.assignments.toLocaleString()} links</span>`
        : '<b class="status-bad">MASTER DB ERROR</b>';
  } catch (e) {
    console.warn("MasterDB status failed", e);
  }
}
function bindMasterDB() {
  loadMasterStatus();
}
function applyCompactWorkspace() {
  document.body.classList.add("compact-main-v301");

  const workspace = document.querySelector(
    '[data-page-content="workspace"], #workspace',
  );
  if (workspace) workspace.classList.add("compact-workspace");

  document
    .querySelectorAll("#kyc details, #machines details")
    .forEach((details) => {
      if (!details.hasAttribute("data-user-opened")) details.open = false;
      if (details.dataset.compactBound) return;
      details.dataset.compactBound = "1";
      details.addEventListener("toggle", () => {
        if (details.open) details.setAttribute("data-user-opened", "1");
      });
    });
}
