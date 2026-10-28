function atlasConsoleNavigate(url){if(!window.AtlasNavigate?.(url))location.assign(url);}
window.addEventListener("atlas:open-inbox", () => page("inbox"));
window.addEventListener("atlas:inbox-person", event => {
  const id = event.detail?.id;
  if (!Number.isSafeInteger(id) || id < 1) return;
  page("workspace");
  loadUser("id:" + id).catch(error => toast(error.message));
});
function toast(m) {
  let x = document.createElement("div");
  x.className = "toast";
  x.textContent = m;
  $("#toast").append(x);
  setTimeout(() => x.remove(), 2500);
}
async function copy(v, n = "Value") {
  if (!v) return toast(`${n} empty`);
  await navigator.clipboard.writeText(String(v));
  toast(`${n} copied`);
}
function page(id) {

  document.body.classList.toggle("knowledge-open",id === "knowledge");
  if(id === "knowledge" || location.hash === "#knowledge") {
    const url=new URL(location.href);url.hash=id === "knowledge" ? "knowledge" : "";
    window.history.replaceState(null,"",url);
  }
  if (id !== "admin")
    window.AtlasDiagnostics?.stop("Stopped — left Remote Admin");
  $$(".page,nav button").forEach((x) => x.classList.remove("active"));
  $("#" + id).classList.add("active");
  const navigation = $(`[data-page="${id}"]`);
  navigation?.classList.add("active");
  $("#pageTitle").textContent =
    navigation?.querySelector(".nav-label")?.textContent ||
    $("#" + id).getAttribute("aria-label") ||
    id;
  const descriptions = {
    workspace: "People, devices and the tools to support them.",
    inbox: "Incoming emails and Teams/Outlook notification previews, sender records and linked machines.",
    clipboard: "What you copied, with the machines, people, desks and tickets Atlas recognises.",
    "active-directory": "Explore accounts, memberships and directory objects.",
    packages: "Find software and prepare your next deployment.",
    admin: "Inspect device health and investigate performance.",
    bulk: "Prepare packages and actions across multiple devices.",
    personas: "The software each role needs, installed on a machine in one click.",
    history: "Review deployment activity and execution details.",
    terminal: "Write scripts and run commands from one place.",
    scripts: "Run saved PowerShell scripts against a list of machines.",
    psexec: "PsTools command templates and execution output.",
    knowledge: "Diagrams, notes and shared support knowledge."
  };
  const description = document.getElementById("pageDescription");
  if (description) description.textContent = descriptions[id] || "";
  // PsTools opens from Scripts, so Scripts stays highlighted there.
  const current = id === "psexec" ? "scripts" : id;
  document.querySelectorAll("nav [data-page]").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === current);
    if (b.dataset.page === current) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  document.querySelectorAll('[data-section]').forEach(link => {
    if(link.dataset.section === (id === 'knowledge' ? 'knowledge' : 'workspace'))link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  if (id === "knowledge") window.AtlasKnowledge?.open();
  if (id === "history") loadDeploymentHistory();
  if (id === "packages") window.dispatchEvent(new CustomEvent("atlas:packages-open"));
  if (id === "terminal") window.AtlasTerminal?.open();
  if (id === "psexec") window.AtlasPsExec?.open();
  if (id === "scripts") window.AtlasScripts?.open();
  if (id === "personas") window.AtlasPersonas?.open();
  if (id === "active-directory") window.AtlasAD?.open();
  if (id === "clipboard") window.AtlasClipboard?.shown();
  if (id === "bulk" && !bulkCatalogueLoaded && !bulkBusy) bulkPackages();
  syncDeploymentPanel();
}
async function init() {
  let h = await api("/api/health");
  $("#identity").textContent = h.identity;
  $("#health").innerHTML =
    `Version ${h.version}<br>${h.database ? "●" : "○"} Database · ${h.users.toLocaleString()} users<br>${h.machines.toLocaleString()} machines<br>${h.repository ? "●" : "○"} Repository`;
  await packages();
  renderRecent();
  $("#search").focus();
}
function bind() {
  document.querySelectorAll("[data-workspace-open]").forEach(button => {
    button.addEventListener("click", () => page(button.dataset.workspaceOpen));
  });
  $("#pkgSearch").oninput = () => {
    clearTimeout(window.pt);
    window.pt = setTimeout(packages, 250);
  };
  $("#pkg").onchange = () => {
    commitPackageChoice();
    scripts();
  };
  $("#action").onchange = scripts;
  $("#deploy").onclick = () => deploy("full");
  $("#deployQueue").onclick = () => addQueue();
  $("#deployOpenQueue").onclick = () => $("#queueDrawer").classList.add("open");
  $("#deploymentRetry").onclick = () => currentDeployment && retryDeployment(currentDeployment.id);
  $("#deploymentRequeue").onclick = () => currentDeployment && (currentDeployment.payload ? queuePayload(currentDeployment.payload) : queueDeployment(currentDeployment.id));
  $("#deploymentCopyLog").onclick = async () => {
    try { await navigator.clipboard.writeText($("#log").textContent); toast("Log copied"); }
    catch { toast("Clipboard unavailable"); }
  };
  // Retry / queue buttons on Deployments drawer cards and History rows.
  $("#deploymentsList").addEventListener("click", (event) => {
    const retry = event.target.closest("[data-deployment-retry]"), queue = event.target.closest("[data-deployment-queue]");
    if (retry) retryDeployment(retry.dataset.deploymentRetry).then(() => refreshDeploymentMonitor());
    if (queue) queueDeployment(queue.dataset.deploymentQueue);
  });
  $("#historyBody").addEventListener("click", (event) => {
    const retry = event.target.closest("[data-history-retry]"), queue = event.target.closest("[data-history-queue]");
    if (retry) retryDeployment(retry.dataset.historyRetry).then((d) => d && setTimeout(loadDeploymentHistory, 800));
    if (queue) queueDeployment(queue.dataset.historyQueue);
  });
  $("#copyOnly").onclick = () => deploy("copy");
  $("#execOnly").onclick = () => deploy("execute");
  $("#favBtn").onclick = toggleFav;
  $("#bulkTargets").oninput = refreshBulkSelection;
  $("#bulkSearch").oninput = () => {
    clearTimeout(window.bt);
    bulkPackageRequest();
    bulkBusy = true;
    refreshBulkSelection();
    window.bt = setTimeout(bulkPackages, 250);
  };
  $("#bulkPkg").onchange = bulkScripts;
  $("#bulkAction").onchange = bulkScripts;
  $("#bulkScript").onchange = refreshBulkSelection;
  document.querySelectorAll("[data-bulk-action]").forEach(button => {
    button.onclick = () => {
      $("#bulkAction").value = button.dataset.bulkAction;
      $("#bulkAction").dispatchEvent(new Event("change", { bubbles: true }));
    };
  });
  $("#bulkStart").onclick = startBulk;
  $("#copyFailed").onclick = () =>
    copy(
      S.rows
        .filter((x) => x.copy === "Failed" || x.completion === "Failed")
        .map((x) => x.machine)
        .join("\n"),
      "Failed machines",
    );
  $("#exportCsv").onclick = exportCsv;
  bindProcessControls();
  $("#refreshHistory").onclick = loadDeploymentHistory;
  $$("[data-preflight]").forEach((x) => (x.onclick = preflight));
  $$("[data-copy-target]").forEach(
    (x) => (x.onclick = () => copy(S.target, "Hostname")),
  );
  $$("[data-admin-target]").forEach((x) => (x.onclick = () => page("admin")));
  ["ping", "access", "disk"].forEach(
    (k) =>
      ($(`[data-${k}]`).onclick = () =>
        admin(k).catch((x) => toast(x.message))),
  );
  $("[data-reboot]").onclick = async () => {
    const computer = $("#adminPc").value.trim();
    if (!computer || !confirm("Reboot " + computer + "?")) return;
    const button = $("[data-reboot]");
    button.disabled = true;
    try { await window.AtlasReboots.start(computer); }
    catch (error) { toast(error.message); }
    finally { button.disabled = !!window.AtlasReadOnly; }
  };
}
function bindRemoteTools() {
  document
    .querySelectorAll("[data-tool]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          openTargetTool(b.dataset.tool).catch((e) => toast(e.message))),
    );
  document.querySelector("#copySupport").onclick = () =>
    copy(supportSummary(), "Support summary");
  document.querySelector("#cleanupPackages").onclick = () =>
    cleanPackages().catch((e) => toast(e.message));
  renderRecentTargets();
}
function openPalette() {
  return sharedPaletteReady
    ?.then((p) => p.open())
    .catch((e) => toast(e.message));
}
function closePalette() {
  sharedPalette?.close();
}

function bindQueueControls() {
  loadFreshness();
  renderQueue();
  $("#queueToggle").onclick = () => $("#queueDrawer").classList.toggle("open");
  $("#closeQueue").onclick = () => $("#queueDrawer").classList.remove("open");
  $("#startQueue").onclick = () =>
    startDeploymentQueue().catch((e) => toast(e.message));
  $("#pauseQueue").onclick = () =>
    pauseDeploymentQueue().catch((e) => toast(e.message));
  $("#clearQueue").onclick = () =>
    clearDeploymentQueue().catch((e) => toast(e.message));
  document.addEventListener("click", () =>
    $("#machineMenu").classList.add("hidden"),
  );
  window.addEventListener("resize", () =>
    $("#machineMenu").classList.add("hidden"),
  );
  document.addEventListener(
    "scroll",
    (event) => {
      const menu = $("#machineMenu");
      if (!menu.contains(event.target)) menu.classList.add("hidden");
    },
    true,
  );
}
function statusAccent(value) {
  const text = String(value ?? "")
    .trim()
    .toLowerCase();
  if (!text) return "status-neutral";
  if (/failed|failure|error|not started|unavailable|offline/.test(text))
    return "status-bad";
  if (/warning|reboot|unknown|not written/.test(text)) return "status-warn";
  if (
    [
      "ok",
      "online",
      "available",
      "operational",
      "complete",
      "completed",
      "success",
      "successful",
      "ready",
      "started",
      "launched",
      "running",
      "current",
      "true",
      "0",
    ].some(
      (x) => text === x || text.startsWith(x + " ") || text.includes(" " + x),
    )
  )
    return "status-ok";
  if (
    [
      "warning",
      "warn",
      "pending",
      "waiting",
      "queued",
      "checking",
      "monitoring",
      "paused",
      "not written",
      "completed with warning",
      "unknown",
    ].some((x) => text === x || text.includes(x))
  )
    return "status-warn";
  if (
    [
      "no",
      "offline",
      "unavailable",
      "failed",
      "failure",
      "error",
      "not started",
      "monitor failed",
      "missing",
      "false",
    ].some((x) => text === x || text.startsWith(x + " ") || text.includes(x))
  )
    return "status-bad";
  return "status-neutral";
}
function bindQoLActions() {
  const menu = document.querySelector("#targetActions");
  if (!menu) return;
  menu.addEventListener("click", (event) => {
    const button = event.target.closest("[data-qol-action]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const action = button.dataset.qolAction;
    if (action === "copy-host") copy(S.target, "Hostname");
    else if (action === "copy-summary")
      copy(supportSummary(), "Support summary");
    else if (action === "admin") page("admin");
    else if (action === "queue") addQueue();
    else if (action === "health") refreshTargetHealth();
    else if (action === "cleanup") cleanPackages();
  });
}
function bindDeploymentMonitor() {
  $("#deploymentsToggle").onclick = () => openDeploymentMonitor("active");
  $("#closeDeployments").onclick = closeDeploymentMonitor;
  $("#refreshDeployments").onclick = () => refreshDeploymentMonitor("active");
  $("#showRecentDeployments").onclick = () =>
    refreshDeploymentMonitor("recent");
  $("#autoDeployments").onchange = () =>
    refreshDeploymentMonitor(deploymentMonitorMode);
  refreshDeploymentMonitor("active");
}
import("/command-registry.js").then(({ COMMANDS }) => {
  shortcutRegistry = [
    { label: "Open command palette", keys: "Ctrl+K", run: openPalette },
    { label: "Focus search", keys: "/", run: () => $("#search").focus() },
    ...COMMANDS.filter((c) => c.shortcut).map((c) => ({
      label: c.title,
      keys: c.shortcut,
      run: () => runSharedCommand(c.id),
    })),
  ];
});
function normaliseKeys(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .toLowerCase();
}
function renderShortcutHelp() {
  const host = document.querySelector("#shortcutHelpList");
  if (!host) return;
  host.innerHTML = shortcutRegistry
    .map(
      (item) =>
        `<button data-shortcut-label="${esc(item.label)}"><span>${esc(item.label)}</span><kbd>${esc(item.keys)}</kbd></button>`,
    )
    .join("");
  host.querySelectorAll("[data-shortcut-label]").forEach(
    (button) =>
      (button.onclick = () => {
        const item = shortcutRegistry.find(
          (x) => x.label === button.dataset.shortcutLabel,
        );
        closeShortcutHelp();
        if (item) item.run();
      }),
  );
}
function openShortcutHelp() {
  renderShortcutHelp();
  document.querySelector("#shortcutHelp").classList.remove("hidden");
}
function closeShortcutHelp() {
  document.querySelector("#shortcutHelp").classList.add("hidden");
}
function closeAllOverlays() {
  closePalette();
  closeShortcutHelp();
  document.querySelector("#machineMenu")?.classList.add("hidden");
  document.querySelector("#queueDrawer")?.classList.remove("open");
  if (typeof closeDeploymentMonitor === "function") closeDeploymentMonitor();
}
function shortcutEventKey(event) {
  const parts = [];
  if (event.ctrlKey) parts.push("ctrl");
  if (event.shiftKey) parts.push("shift");
  if (event.altKey) parts.push("alt");
  let key = event.key.toLowerCase();
  if (key === " ") key = "space";
  if (key === "?" && !event.ctrlKey && !event.altKey && !event.metaKey)
    return "?";
  parts.push(key);
  return parts.join("+");
}
function bindPaletteShortcuts() {
  document.querySelector("#closeShortcutHelp").onclick = closeShortcutHelp;
  document.querySelector("#shortcutHelp").onclick = (event) => {
    if (event.target.id === "shortcutHelp") closeShortcutHelp();
  };
  document.addEventListener(
    "keydown",
    (event) => {
      if (
        event
          .composedPath()
          .some((node) => node.classList?.contains("atlas-palette-mount"))
      )
        return;
      if (event.key === "Escape") {
        closeAllOverlays();
        return;
      }
      if(document.querySelector('#knowledge')?.classList.contains('active') && document.activeElement?.closest('#knowledge') && !(event.ctrlKey && event.key.toLowerCase()==='k')) return;
      const active = document.activeElement;
      const isTyping =
        active && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName);
      if (isTyping && normaliseKeys(shortcutEventKey(event)) !== "ctrl+k")
        return;
      const pressed = normaliseKeys(shortcutEventKey(event));
      const item = shortcutRegistry.find(
        (x) => normaliseKeys(x.keys) === pressed,
      );
      if (item) {
        event.preventDefault();
        event.stopImmediatePropagation();
        Promise.resolve(item.run()).catch((e) => toast(e.message));
      }
    },
    true,
  );
}
function renderNavigationIcons() {
  document.querySelectorAll("nav [data-page]").forEach((button) => {
    const pageName = button.dataset.page;
    const label =
      button.querySelector(".nav-label")?.textContent ||
      button.title ||
      pageName;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = `<span class="nav-icon">${navigationIcons[pageName] || ""}</span><span class="nav-label">${esc(label)}</span>`;
  });
}

function bindSoftwareControls() {
  renderNavigationIcons();
  $("#closeSoftware").onclick = () =>
    $("#softwareDrawer").classList.remove("open");
  $("#refreshSoftware").onclick = () =>
    loadSoftware(softwareState.softwareTarget || S.target, true);
  $("#copySoftware").onclick = () => copy(softwareReport(), "Software report");
  $("#exportSoftware").onclick = exportSoftwareCsv;
  $("#softwareFilter").oninput = renderSoftware;
  $("#pkg").addEventListener("change", updatePackagePresence);
}
function bindConsolePolish() {
  document
    .querySelector("nav [data-page].active")
    ?.setAttribute("aria-current", "page");
  document
    .querySelectorAll(".nav-icon")
    .forEach((el) => el.setAttribute("aria-hidden", "true"));
  const menus = [...document.querySelectorAll(".toolmenu")];
  function closeMenu(m) {
    const content = m.querySelector(".toolmenu-content");
    m.classList.remove("menu-open");
    m.querySelector(".toolmenu-btn").setAttribute("aria-expanded", "false");
    if (content.hasAttribute("popover")) {
      try {
        content.hidePopover();
      } catch {}
    }
  }
  function closeMenus() {
    menus.forEach(closeMenu);
  }
  function openMenu(m) {
    closeMenus();
    const trigger = m.querySelector(".toolmenu-btn"),
      content = m.querySelector(".toolmenu-content"),
      gap = 8,
      separation = 4,
      width = window.innerWidth,
      height = window.innerHeight;
    m.classList.add("menu-open");
    trigger.setAttribute("aria-expanded", "true");
    // A native manual popover escapes stacking contexts without moving the
    // content away from its existing action and keyboard event handlers.
    if (content.hasAttribute("popover")) {
      try {
        content.showPopover();
      } catch {
        content.removeAttribute("popover");
      }
    }
    content.style.left = content.style.top = gap + "px";
    content.style.maxWidth = Math.max(0, width - gap * 2) + "px";
    content.style.maxHeight = Math.max(0, height - gap * 2) + "px";
    content.scrollTop = 0;
    const anchor = trigger.getBoundingClientRect(),
      initial = content.getBoundingClientRect(),
      below = Math.max(0, height - gap - anchor.bottom - separation),
      above = Math.max(0, anchor.top - gap - separation),
      useBelow = initial.height <= below || below >= above;
    content.style.maxHeight = (useBelow ? below : above) + "px";
    const bounds = content.getBoundingClientRect(),
      left = anchor.right - bounds.width,
      top = useBelow
        ? anchor.bottom + separation
        : anchor.top - separation - bounds.height;
    content.style.left =
      Math.max(gap, Math.min(left, width - bounds.width - gap)) + "px";
    content.style.top =
      Math.max(gap, Math.min(top, height - bounds.height - gap)) + "px";
  }
  menus.forEach((m) => {
    const trigger = m.querySelector(".toolmenu-btn"),
      content = m.querySelector(".toolmenu-content");
    content.id = m.id + "-content";
    if (
      typeof content.showPopover === "function" &&
      typeof content.hidePopover === "function"
    )
      content.setAttribute("popover", "manual");
    trigger.setAttribute("aria-controls", content.id);
    trigger.setAttribute("aria-expanded", "false");
    trigger.addEventListener("click", () => {
      const open = !m.classList.contains("menu-open");
      if (open) openMenu(m);
      else closeMenu(m);
    });
    trigger.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        openMenu(m);
        content
          .querySelector('button:not(:disabled):not([aria-disabled="true"])')
          ?.focus({ preventScroll: true });
      }
    });
    content.addEventListener("click", (e) => {
      if (e.target.closest("button")) closeMenus();
    });
    m.addEventListener("focusout", () =>
      queueMicrotask(() => {
        if (!m.contains(document.activeElement)) closeMenu(m);
      }),
    );
    content.addEventListener("toggle", (e) => {
      if (e.newState === "closed") closeMenu(m);
    });
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".toolmenu")) closeMenus();
  });
  document.addEventListener(
    "scroll",
    (e) => {
      const open = menus.find((m) => m.classList.contains("menu-open"));
      if (open && !open.querySelector(".toolmenu-content").contains(e.target))
        closeMenus();
    },
    true,
  );
  window.addEventListener("resize", closeMenus);
  const panels = [
    ...document.querySelectorAll(
      "#queueDrawer,#deploymentsDrawer,#softwareDrawer",
    ),
  ];
  let active = null,
    returnFocus = null;
  const toggles = {
    queueDrawer: "queueToggle",
    deploymentsDrawer: "deploymentsToggle",
  };
  panels.forEach((p) => {
    p.setAttribute("role", "dialog");
    p.setAttribute("aria-label", p.querySelector("b").textContent);
    p.setAttribute("tabindex", "-1");
    const close = p.querySelector('[id^="close"]');
    close.setAttribute(
      "aria-label",
      "Close " + p.getAttribute("aria-label").toLowerCase(),
    );
    close.title = close.getAttribute("aria-label");
    const t = document.getElementById(toggles[p.id]);
    if (t) {
      t.setAttribute("aria-controls", p.id);
      t.setAttribute("aria-expanded", "false");
    }
    p.inert = !p.classList.contains("open");
  });
  function closePanel(p) {
    if (p.id === "deploymentsDrawer") closeDeploymentMonitor();
    else p.classList.remove("open");
  }
  function syncPanels() {
    const opening = panels.find(
      (p) => p !== active && p.classList.contains("open"),
    );
    if (opening) {
      if (!active) returnFocus = document.activeElement;
      panels.filter((p) => p !== opening).forEach(closePanel);
      active = opening;
      opening.inert = false;
      opening.querySelector('[id^="close"]').focus();
    } else if (active && !active.classList.contains("open")) {
      active = null;
      if (returnFocus?.isConnected) returnFocus.focus();
      returnFocus = null;
    }
    panels.forEach((p) => {
      const open = p.classList.contains("open");
      p.inert = !open;
      p.setAttribute("aria-hidden", String(!open));
      document
        .getElementById(toggles[p.id])
        ?.setAttribute("aria-expanded", String(open));
    });
  }
  panels.forEach((p) =>
    new MutationObserver(syncPanels).observe(p, {
      attributes: true,
      attributeFilter: ["class"],
    }),
  );
  syncPanels();
  const live = document.querySelector("#deploymentsToggle");
  live.onclick = () => {
    if (document.querySelector("#deploymentsDrawer").classList.contains("open"))
      closeDeploymentMonitor();
    else openDeploymentMonitor("active");
  };
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape") {
        const m = menus.find((m) => m.classList.contains("menu-open"));
        closeMenus();
        m?.querySelector(".toolmenu-btn").focus();
        panels.forEach(closePanel);
      }
    },
    true,
  );
  document.querySelector("#toast").setAttribute("role", "status");
  document.querySelector("#toast").setAttribute("aria-live", "polite");
}
function bindCommandDiscovery() {
  document.querySelector("#openShortcuts").onclick = openShortcutHelp;
  document
    .querySelector("#closeShortcutHelp")
    .setAttribute("aria-label", "Close keyboard shortcuts");
}
async function openPaletteTarget() {
  if (location.hash === "#active-directory") page("active-directory");
  if (location.hash === "#psexec") page("psexec");
  if (location.hash === "#scripts") page("scripts");
  if (location.hash === "#personas") page("personas");
  if (location.hash === "#knowledge") page("knowledge");
  const params = new URLSearchParams(location.search),
    person = params.get("person"),
    machine = params.get("machine"),
    lookup = params.get("lookup");
  if (!person && !machine && !lookup) {
    await runInitialSharedCommand(params);
    return;
  }
  try {
    if (person) {
      if (!/^id:\d+$/.test(person)) throw Error("Invalid person link");
      clearLookup();
      await loadUser(person, ++lookupSequence);
    } else if (machine) {
      document.querySelector("#search").value = "machine:" + machine;
      await search();
      if (S.machines.some((m) => m.name === machine))
        setTarget(machine, "Selected from Atlas map");
    } else {
      document.querySelector("#search").value = lookup;
      await search();
    }
    await runInitialSharedCommand(params);
  } catch (error) {
    toast("Could not open palette result: " + error.message);
  }
}
async function runInitialSharedCommand(params) {
  const id = params.get("command");
  if (!id) return;
  const { COMMANDS } = await import("/command-registry.js");
  if (!COMMANDS.some((c) => c.id === id)) return;
  const url = new URL(location.href);
  url.searchParams.delete("command");
  window.history.replaceState(null, "", url);
  await runSharedCommand(id);
}
async function runSharedCommand(id) {

  if (window.AtlasReadOnly) {
    const { COMMANDS } = await import("/command-registry.js");
    if (!COMMANDS.some((c) => c.id === id && c.viewer))
      return toast(AtlasReadOnly.reason);
  }
  if (id === "knowledge" || id.startsWith("kb-")) {
    page("knowledge");
    if(id !== "knowledge") return AtlasKnowledge.command(id);
    return;
  }
  if(id==='ad-open'){const p=new URLSearchParams(location.search);return AtlasAD.show(p.get('adkind')==='user'?'user':'computer',p.get('adidentity')||S.target||'',true,p.get('adaction')||'groups');}
  if(id.startsWith('ad-'))return AtlasAD.command(id);
  if (id === "active-directory") { page("active-directory"); return; }
  if (["vlans","contacts","daas","vdi"].includes(id)) {
    const { openSiteInfo } = await import("/site-info.js?v=1");
    return openSiteInfo(id);
  }
  if (id === "animations") return AtlasUI.motion.toggle();
  if (id === "packages" || id === "inbox") { page(id); return; }
  if (id === "catalogue") return openConsoleCatalogue();
  const { MAP_COMMANDS, commandUrl } = await import("/command-registry.js");
  if (MAP_COMMANDS.has(id)) {
    atlasConsoleNavigate(commandUrl(id, S.target));
    return;
  }
  const focus = (selector, needsTarget = false) => {
    page("workspace");
    if (needsTarget && !S.target) {
      toast("Select a machine first, then open this command again.");
      document.querySelector("#search").focus();
      return;
    }
    const control = document.querySelector(selector);
    if (control?.closest("#deploymentPanel")) openDeploymentPanel();
    if (control?.closest("#packagePicker")) $("#packagePicker").open = true;
    for (
      let parent = control?.parentElement;
      parent;
      parent = parent.parentElement
    )
      if (parent.matches("details")) parent.open = true;
    control?.scrollIntoView({ block: "center" });
    if (control && !control.matches("button,input,select,textarea,a"))
      control.tabIndex = -1;
    control?.focus();
  };
  const toolMenu = (menuSelector, controlSelector) => {
    if (!S.target) {
      focus("#search", true);
      return;
    }
    page("workspace");
    const menu = document.querySelector(menuSelector);
    if (!menu.classList.contains("menu-open"))
      menu.querySelector(".toolmenu-btn").click();
    menu.querySelector(controlSelector)?.focus();
  };
  const showReport = () => {
    if (!S.target) {
      focus("#search", true);
      return;
    }
    const { body } = AtlasUI.dialog("Machine report");
    const report = document.createElement("pre");
    report.textContent = completeMachineReport();
    const button = document.createElement("button");
    button.textContent = "Copy report";
    button.onclick = () => copy(report.textContent, "Machine report");
    body.append(report, button);
  };
  const recover = async () => {
    const { body } = AtlasUI.dialog("Operation recovery");
    body.textContent = "Loading…";
    try {
      const data = await api("/api/operations/recovery");
      body.textContent = data.targets.length
        ? "Inspect the target and operation logs before acknowledging an interrupted operation."
        : "No unresolved operations.";
      for (const pc of data.targets) {
        const row = document.createElement("p"),
          label = document.createElement("label"),
          input = document.createElement("input"),
          button = document.createElement("button");
        label.textContent = pc + " — type hostname after checking: ";
        label.append(input);
        button.textContent = "Acknowledge";
        button.disabled = true;
        input.oninput = () => (button.disabled = input.value !== pc);
        button.onclick = async () => {
          button.disabled = true;
          try {
            await api("/api/operations/recovery/" + encodeURIComponent(pc), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ confirmation: input.value }),
            });
            row.remove();
          } catch (e) {
            toast(e.message);
            button.disabled = false;
          }
        };
        row.append(label, button);
        body.append(row);
      }
    } catch (e) {
      body.textContent = e.message;
    }
  };
  const actions = {
    "remote-registry": async () =>
      (await import("/service-actions.js")).openRemoteRegistry(S.target),
    lookup: () => focus("#search"),
    recovery: recover,
    workspace: () => page("workspace"),
    admin: () => page("admin"),
    bulk: () => page("bulk"),
    history: () => page("history"),
    terminal: () => page("terminal"),
    scripts: () => page("scripts"),
    personas: () => page("personas"),
    psexec: () => page("psexec"),
    active: () => openDeploymentMonitor("active"),
    recent: () => openDeploymentMonitor("recent"),
    queue: () => document.querySelector("#queueDrawer").classList.add("open"),
    deploy: () => focus("#deploy", true),
    copy: () => focus("#copyOnly", true),
    "queue-add": () => toolMenu("#targetActions", '[data-qol-action="queue"]'),
    msra: () => toolMenu("#targetTools", '[data-tool="msra"]'),
    cshare: () => toolMenu("#targetTools", '[data-tool="cshare"]'),
    health: () => focus("#healthLine", true),
    cleanup: () => focus("#cleanupPackages", true),
    summary: () => focus("#copySupport", true),
    software: () => {
      page("admin");
      document.querySelector("#adminSoftware").focus();
    },
    report: showReport,
    shortcuts: openShortcutHelp,
  };
  if (actions[id]) return actions[id]();
}
sharedPaletteReady = import("/command-palette.js").then(
  ({ installCommandPalette }) => {
    let records = [];
    sharedPalette = installCommandPalette({
      readOnly: !!window.AtlasReadOnly,
      getRecords: () => records,
      prepare: async () => {
        records = await AtlasClient.deskIndex();
      },
      toast,
      runCommand: runSharedCommand,
      replaceTrigger: document.querySelector("#openCommands"),
      preferPersonDetails: true,
      onSelect: (id) =>
        atlasConsoleNavigate("/?" + new URLSearchParams({ desk: id })),
      openPerson: async (id) => {
        page("workspace");
        clearLookup();
        await loadUser(id, ++lookupSequence);
      },
      openMachine: async (machine) => {
        page("workspace");
        document.querySelector("#search").value = "machine:" + machine;
        await search();
        if (S.machines.some((m) => m.name === machine))
          setTarget(machine, "Selected from Atlas search");
      },
    });
    return sharedPalette;
  },
);
AtlasContext.configure({
  openPerson: async key => {page("workspace");await loadUser(key);},
  search: async term => {page("workspace");document.getElementById("search").value = term;await search();},
});
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll('[data-section]').forEach(link => link.addEventListener('click',event => {event.preventDefault();page(link.dataset.section);}));
  installSelectionSidebar();
  installDeploymentPanel();
  $("#openCatalogue").onclick = () => page("packages");
  window.addEventListener("atlas:package-inspect", event => {
    if (window.AtlasReadOnly || typeof event.detail?.folder !== "string") return;
    openConsoleCatalogue(event.detail.folder).catch(e => toast(e.message));
  });
  (() => {
    const searchInput = document.getElementById("search");
    searchInput.disabled = false;
    searchInput.readOnly = false;
    searchInput.removeAttribute("disabled");
    searchInput.removeAttribute("readonly");
    searchInput.setAttribute("tabindex", "0");
    searchInput.value = "";
    searchInput.addEventListener("pointerdown", () => searchInput.focus());
    searchInput.addEventListener("click", () => searchInput.focus());
    searchInput.addEventListener("input", clearDirectTarget);
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        search().catch((error) => toast(error.message));
      }
    });
    document
      .querySelectorAll("nav button")
      .forEach((button) =>
        button.addEventListener("click", () => page(button.dataset.page)),
      );
    bind();
    setTimeout(() => searchInput.focus(), 50);
    init().catch((error) => toast(error.message));
  })();
  bindRemoteTools();
  bindQueueControls();
  bindDeploymentMonitor();
  bindPaletteShortcuts();
  bindSoftwareControls();
  bindMasterDB();
  (() => {
    document.querySelector("#pkg").addEventListener("change", () => {
      refreshConsolePackage();
      refreshConsoleSummary();
    });
    document
      .querySelector("#action")
      .addEventListener("change", refreshConsoleSummary);
    document
      .querySelector("#script")
      .addEventListener("change", refreshConsoleSummary);
    new MutationObserver(() => {
      refreshConsolePackage();
      refreshConsoleSummary();
    }).observe(document.querySelector("#pkg"), { childList: true });
    new MutationObserver(refreshConsoleSummary).observe(
      document.querySelector("#deployTarget"),
      { childList: true },
    );
    new MutationObserver(refreshConsoleSummary).observe(
      document.querySelector("#script"),
      { childList: true },
    );
    refreshConsoleSummary();
  })();
  bindConsolePolish();
  bindCommandDiscovery();
  (() => queueMicrotask(openPaletteTarget))();
  bindQoLActions();
  $("#search").setAttribute(
    "aria-label",
    "Search users, email addresses or machines",
  );
});
