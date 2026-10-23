let deploymentExpanded = false;
let packageChoice = null,
  packageBusy = false,
  currentDeployment = null;
const packageLabels = new Map();
function syncDeploymentPanel({ selection = false } = {}) {
  const workspace = $("#workspace"),
    panel = $("#deploymentPanel"),
    toggle = $("#deploymentToggle");
  if (!workspace || !panel || !toggle) return;
  // The panel lives in Workspace, or beside a Live Inbox message while its Deploy tool is open.
  const available = !!S.target && !!panel.closest(".page")?.classList.contains("active"),
    compact = window.matchMedia("(max-width: 760px)").matches;
  if (!available) deploymentExpanded = false;
  else if (selection) deploymentExpanded = true;
  const wasHidden = panel.hidden;
  workspace.classList.toggle("has-target", !!S.target);
  panel.hidden = !available || (compact && !deploymentExpanded);
  toggle.hidden = !available || !compact;
  $("#deploymentToggleLabel").textContent = "Deployment · " + S.target;
  toggle.setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden && (wasHidden || selection)) AtlasUI.motion.slideUp(panel);
  if (!available && packageChoice) cancelPackageChoice();
  syncDeploymentProgress();
  refreshConsoleSummary();
}
function openDeploymentPanel() {
  if (!S.target) return toast("Select a target first");
  deploymentExpanded = true;
  syncDeploymentPanel();
  $("#deploymentPanel").scrollIntoView({ block: "nearest" });
}
function installDeploymentPanel() {
  if ($("#deploymentPanel").dataset.installed) return;
  $("#deploymentPanel").dataset.installed = "true";
  $("#deploymentToggle").onclick = () => {
    deploymentExpanded = !deploymentExpanded;
    syncDeploymentPanel();
    if (deploymentExpanded)
      $("#packagePickerButton").focus({ preventScroll: true });
  };
  $("#closeDeploymentPanel").onclick = () => {
    deploymentExpanded = false;
    syncDeploymentPanel();
    $("#deploymentToggle").focus({ preventScroll: true });
  };
  $("#deploymentPanel").addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      window.matchMedia("(max-width: 760px)").matches
    ) {
      event.stopPropagation();
      $("#closeDeploymentPanel").click();
    }
  });
  window.addEventListener("resize", syncDeploymentPanel, { passive: true });
  installPackagePicker();
  syncDeploymentPanel();
}
function updatePackageSelection() {
  const option = $("#pkg").selectedOptions[0];
  $("#packageSelection").textContent =
    option?.textContent || "Choose a package";
  $("#packagePickerButton").title = option?.textContent || "Search packages";
  refreshConsoleSummary();
}
function commitPackageChoice() {
  clearTimeout(window.pt);
  packageRequest();
  packageBusy = false;
  packageChoice = null;
  $("#packagePicker").open = false;
  $("#pkg").disabled = false;
  updatePackageSelection();
}
function cancelPackageChoice() {
  // Closing the picker never rolls back a selected package.
  commitPackageChoice();
}
function installPackagePicker() {
  const picker = $("#packagePicker"),
    select = $("#pkg");
  picker.addEventListener("toggle", () => {
    if (picker.open && !packageChoice) {
      packageChoice = true;
      $("#pkgSearch").focus({ preventScroll: true });
      if (!select.options.length && !packageBusy) packages();
    } else if (!picker.open && packageChoice) cancelPackageChoice();
    refreshConsoleSummary();
  });
  const choose = () => {
    if (packageBusy || !select.value) return;
    commitPackageChoice();
    $("#packagePickerButton").focus({ preventScroll: true });
  };
  select.addEventListener("change", choose);
  select.ondblclick = choose;
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && picker.open) {
      event.preventDefault();
      event.stopPropagation();
      cancelPackageChoice();
      $("#packagePickerButton").focus({ preventScroll: true });
    } else if (event.key === "Enter" && event.target.matches("input, select")) {
      event.preventDefault();
      choose();
    } else if (event.key === "ArrowDown" && event.target === $("#pkgSearch")) {
      event.preventDefault();
      select.focus();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (picker.open && !picker.contains(event.target)) cancelPackageChoice();
  });
  document.querySelectorAll("[data-deploy-action]").forEach((button) => {
    button.onclick = () => {
      $("#action").value = button.dataset.deployAction;
      $("#action").dispatchEvent(new Event("change", { bubbles: true }));
    };
  });
}
async function openConsoleCatalogue(folder = "") {
  const { openCatalogue } = await import("/catalogue.js");
  return openCatalogue({
    folder,
    api,
    toast,
    onSave: async (metadata) => {
      const label =
        (metadata.display_name.trim() || metadata.folder) +
        (metadata.version.trim() ? " · " + metadata.version.trim() : "");
      packageLabels.set(metadata.folder, label);
      for (const option of document.querySelectorAll(
        "#pkg option, #bulkPkg option",
      )) {
        if (option.value === metadata.folder) option.textContent = label;
      }
      renderRecent();
      updatePackageSelection();
      await refreshConsolePackage();
    },
  });
}
async function packages() {
  const request = packageRequest();
  packageBusy = true;
  $("#pkg").disabled = true;
  $("#packageSearchStatus").textContent = "Searching…";
  refreshConsoleSummary();
  try {
    const d = await api(
      "/api/catalog?term=" + encodeURIComponent($("#pkgSearch").value),
      { signal: request.signal },
    );
    if (!request.current()) return;
    const previous = $("#pkg").value;
    const previousLabel = $("#pkg").selectedOptions[0]?.textContent;
    for (const item of d.items)
      packageLabels.set(
        item.folder,
        item.display_name + (item.version ? " · " + item.version : "") + (item.state ? " · " + item.state : ""),
      );
    $("#pkg").innerHTML = d.items
      .map(
        (x) =>
          `<option value="${esc(x.folder)}">${esc(x.display_name)}${x.version ? " · " + esc(x.version) : ""}${x.state ? " · " + esc(x.state) : ""}</option>`,
      )
      .join("");
    if (previous && !d.items.some(item => item.folder === previous))
      $("#pkg").add(new Option(previousLabel || previous, previous));
    $("#pkg").value = previous || d.items[0]?.folder || "";
    $("#packageSearchStatus").textContent =
      d.available === false
        ? d.error || "Package repository unavailable. Check Settings."
        : d.truncated
          ? `Showing ${d.items.length} of ${d.total} packages. Refine your search.`
          : d.items.length
            ? `${d.items.length} packages`
            : "No matching packages";
    if (!packageChoice) updatePackageSelection();
    await scripts();
  } catch (e) {
    if (e.name !== "AbortError" && request.current()) {
      $("#packageSearchStatus").textContent =
        "Packages unavailable: " + e.message;
      toast(e.message);
    }
  } finally {
    if (request.current()) {
      packageBusy = false;
      $("#pkg").disabled = false;
      refreshConsoleSummary();
    }
  }
}
async function scripts() {
  const request = scriptRequest(),
    folder = $("#pkg").value,
    action = $("#action").value,
    control = $("#script");
  control.innerHTML = "";
  control.disabled = true;
  refreshConsoleSummary();
  try {
    if (folder) {
      const data = await api(
        `/api/scripts?package=${encodeURIComponent(folder)}&action=${encodeURIComponent(action)}`,
        { signal: request.signal },
      );
      if (
        !request.current() ||
        folder !== $("#pkg").value ||
        action !== $("#action").value
      )
        return;
      control.innerHTML = data.scripts
        .map((x) => `<option>${esc(x)}</option>`)
        .join("");
    }
    renderFav();
  } catch (e) {
    if (e.name !== "AbortError" && request.current()) toast(e.message);
  } finally {
    if (request.current()) {
      control.disabled = false;
      refreshConsoleSummary();
    }
  }
}
async function preflight() {
  if (!S.target) return;
  const pc = S.target;
  let d = await api("/api/preflight/" + pc);
  if (S.target !== pc) return;
  $("#preflight").innerHTML = `<div class=checks>${Object.entries(d)
    .map(
      ([k, v]) =>
        `<span class="check ${v ? "ok" : ""}">${v ? "✓" : "✕"} ${esc(k)}</span>`,
    )
    .join("")}</div>`;
}
async function deploy(mode = "full") {
  if (deploySubmitting) return;
  if (packageBusy || $("#packagePicker").open)
    return toast("Choose a package first");
  if ($("#script").disabled || !$("#script").value)
    return toast("Wait for an action script to load");
  if (!S.target) return toast("Select a target");
  const target = S.target;
  let pkg = $("#pkg").value,
    p = prefs();
  p.recent = [pkg, ...p.recent.filter((x) => x !== pkg)].slice(0, 5);
  save(p);
  renderRecent();
  deploySubmitting = true;
  refreshConsoleSummary();
  let d;
  const payload = {
    computer: target,
    folder: pkg,
    script: $("#script").value,
    action: $("#action").value,
    fresh: $("#fresh").checked,
    threads: +$("#threads").value,
    mode,
  };
  try {
    d = await api("/api/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    toast(error.message);
    return;
  } finally {
    deploySubmitting = false;
    refreshConsoleSummary();
  }
  S.job = d.job;
  poll(d.job, target, payload);
}
// Retry and re-queue: any past deployment can run again with the same machine, package and options.
function queuePayload(payload) {
  if (activeQueueId) return toast("Finish or clear the saved queue first");
  deploymentQueue.push({ ...payload, state: "waiting" });
  renderQueue();
  toast(`Added to queue: ${PathName(payload.folder)} on ${payload.computer}`);
}
async function queueDeployment(jobId) {
  try { queuePayload(await api("/api/deploy/" + encodeURIComponent(jobId) + "/payload")); }
  catch (error) { toast(error.message); }
}
async function retryDeployment(jobId) {
  try {
    const d = await api("/api/deploy/" + encodeURIComponent(jobId) + "/retry", { method: "POST" });
    toast(`Retrying ${d.package} on ${d.target}`);
    if (d.target === S.target) poll(d.job, d.target);
    else openDeploymentMonitor("active");
    return d;
  } catch (error) { toast(error.message); }
}
function syncDeploymentProgress() {
  const host = $("#deploymentProgress");
  if (host)
    host.hidden = !currentDeployment || currentDeployment.target !== S.target;
}
function poll(id, target = S.target, payload = null) {
  currentDeployment = { id, target, payload };
  $("#deploymentRetry").hidden = true;
  $("#deploymentJobTarget").textContent = target;
  $("#deploymentState").textContent = "Starting";
  $("#deploymentMessage").textContent = "Waiting for the first update…";
  $("#deploymentLog").open = false;
  $("#log").textContent = "";
  syncDeploymentProgress();
  return AtlasClient.watch(
    "console-deployment",
    "/api/job/" + id,
    (data) => {
      const failure = ["failed", "interrupted", "unknown"].includes(data.state);
      $("#deploymentState").textContent = String(
        !AtlasClient.terminal.has(data.state) && data.events.some((e) => e.pid)
          ? "launched"
          : (data.state || "running"),
      ).replace(/^./, (letter) => letter.toUpperCase());
      $("#deploymentState").className = statusAccent(data.state);
      $("#deploymentMessage").textContent = data.events.at(-1)?.message || "";
      if (failure) $("#deploymentLog").open = true;
      $("#deploymentRetry").hidden = !failure;
      $("#log").textContent = data.events
        .map(
          (e) =>
            `[${e.time}] ${e.message}${e.log ? "\n" + e.log.join("\n") : ""}`,
        )
        .join("\n");
      if (AtlasClient.terminal.has(data.state)) toast(data.state);
    },
    {
      onError: (e) => {
        $("#deploymentState").textContent = "Updates unavailable";
        $("#deploymentMessage").textContent = e.message;
        $("#deploymentLog").open = true;
      },
    },
  );
}
function renderFav() {
  let p = prefs(),
    pkg = $("#pkg").value;
  const favourite = p.favs.includes(pkg);
  const button = $("#favBtn"), text = favourite ? "★" : "☆",
    pressed = String(favourite), disabled = !pkg || packageBusy || $("#packagePicker").open;
  if (button.textContent !== text) button.textContent = text;
  if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
  if (button.disabled !== disabled) button.disabled = disabled;
}
function toggleFav() {
  let p = prefs(),
    pkg = $("#pkg").value;
  p.favs = p.favs.includes(pkg)
    ? p.favs.filter((x) => x !== pkg)
    : [...p.favs, pkg];
  save(p);
  renderFav();
  renderRecent();
}
function renderRecent() {
  let p = prefs(),
    vals = [...p.favs, ...p.recent].filter((x, i, a) => a.indexOf(x) === i);
  $("#recent").innerHTML = vals
    .map(
      (x) =>
        `<button data-recent="${esc(x)}">${p.favs.includes(x) ? "★ " : "↶ "}${esc(packageLabels.get(x) || x)}</button>`,
    )
    .join("");
  $$("[data-recent]").forEach(
    (b) =>
      (b.onclick = () => {
        if (
          ![...$("#pkg").options].some(
            (option) => option.value === b.dataset.recent,
          )
        )
          $("#pkg").add(
            new Option(
              packageLabels.get(b.dataset.recent) || b.dataset.recent,
              b.dataset.recent,
            ),
          );
        $("#pkg").value = b.dataset.recent;
        commitPackageChoice();
        $("#pkg").dispatchEvent(new Event("change", { bubbles: true }));
      }),
  );
}

function bulkTargets() {
  return [
    ...new Set(
      $("#bulkTargets")
        .value.split(/[,;\s]+/)
        .map((x) => x.trim().toUpperCase())
        .filter(Boolean),
    ),
  ];
}
let bulkBusy = false, bulkSubmitting = false, bulkCatalogueLoaded = false;
async function bulkPackages() {
  const request = bulkPackageRequest();
  bulkBusy = true;
  $("#bulkPkg").disabled = true;
  refreshBulkSelection();
  try {
    const d = await api(
      "/api/catalog?term=" + encodeURIComponent($("#bulkSearch").value),
      { signal: request.signal },
    );
    if (!request.current()) return;
    const previous = $("#bulkPkg").value, label = $("#bulkPkg").selectedOptions[0]?.textContent;
    $("#bulkPkg").innerHTML = d.items
      .map(
        (x) =>
          `<option value="${esc(x.folder)}">${esc(x.display_name)}${x.version ? " · " + esc(x.version) : ""}${x.state ? " · " + esc(x.state) : ""}</option>`,
      )
      .join("");
    if (previous && !d.items.some(item => item.folder === previous))
      $("#bulkPkg").add(new Option(label || previous, previous));
    $("#bulkPkg").value = previous || d.items[0]?.folder || "";
    bulkCatalogueLoaded = true;
    await bulkScripts();
  } catch (e) {
    if (e.name !== "AbortError" && request.current()) toast(e.message);
  } finally {
    if (request.current()) { bulkBusy = false; $("#bulkPkg").disabled = false; refreshBulkSelection(); }
  }
}
function refreshBulkSelection() {
  const action = $("#bulkAction").value, count = bulkTargets().length;
  document.querySelectorAll("[data-bulk-action]").forEach(button =>
    button.setAttribute("aria-pressed", String(button.dataset.bulkAction === action)));
  $("#targetCount").textContent = `${count} targets`;
  $("#bulkStart").textContent = bulkSubmitting ? "Starting…" : `${action} on ${count} machine${count === 1 ? "" : "s"}`;
  $("#bulkStart").disabled = !!window.AtlasReadOnly || bulkBusy || bulkSubmitting || !count || !$("#bulkPkg").value || $("#bulkScript").disabled || !$("#bulkScript").value;
  $("#bulkSelectionStatus").textContent = bulkBusy ? "Loading packages…" : $("#bulkScript").disabled ? "Loading scripts…" : !$("#bulkScript").value ? "No script available for this action." : `${$("#bulkPkg").selectedOptions[0]?.textContent || ""} · ${action}`;
}
async function bulkScripts() {
  const request = bulkScriptRequest(), folder = $("#bulkPkg").value,
    action = $("#bulkAction").value, control = $("#bulkScript");
  control.innerHTML = "";
  control.disabled = true;
  refreshBulkSelection();
  try {
    if (folder) {
      const d = await api(`/api/scripts?package=${encodeURIComponent(folder)}&action=${encodeURIComponent(action)}`, { signal: request.signal });
      if (!request.current() || folder !== $("#bulkPkg").value || action !== $("#bulkAction").value) return;
      control.innerHTML = d.scripts.map(x => `<option>${esc(x)}</option>`).join("");
    }
  } catch (e) {
    if (e.name !== "AbortError" && request.current()) toast(e.message);
  } finally {
    if (request.current()) { control.disabled = false; refreshBulkSelection(); }
  }
}
async function startBulk() {
  if (bulkSubmitting || bulkBusy) return;
  const pcs = bulkTargets();
  if (!pcs.length) return toast("Enter targets");
  if (!$("#bulkPkg").value || $("#bulkScript").disabled || !$("#bulkScript").value)
    return toast("Choose a package with an available action script");
  const payload = { computers: pcs, folder: $("#bulkPkg").value,
    script: $("#bulkScript").value, action: $("#bulkAction").value,
    fresh: $("#bulkFresh").checked, threads: +$("#bulkThreads").value,
    concurrency: +$("#concurrency").value };
  bulkSubmitting = true;
  refreshBulkSelection();
  try {
    const d = await api("/api/bulk/deploy", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    S.bulk = d.job;
    bulkPoll(d.job);
  } catch (e) { toast(e.message); }
  finally { bulkSubmitting = false; refreshBulkSelection(); }
}
function bulkPoll(id) {
  return AtlasClient.watch(
    "console-bulk",
    "/api/bulk/job/" + id,
    (data) => {
      S.rows = data.results || [];
      renderBulk(data);
      if (AtlasClient.terminal.has(data.state)) toast("Bulk " + data.state);
    },
    { onError: (e) => toast("Monitoring: " + e.message) },
  );
}
function renderBulk(j) {
  const r = S.rows,
    failed = r.filter((x) => x.copy === "Failed" || x.completion === "Failed").length;
  $("#copyFailed").disabled = !failed;
  $("#exportCsv").disabled = !r.length;
  const done = r.filter((x) => ["Complete", "Launched"].includes(x.completion)).length;
  $("#bulkSummary").innerHTML =
    `<div class=summary><div>Phase<b>${esc(j.phase || j.state || "Waiting")}</b></div><div>Total<b>${r.length}</b></div><div${failed ? ' class="status-bad"' : ""}>Failed<b>${failed}</b></div><div${done ? ' class="status-ok"' : ""}>Launched / complete<b>${done}</b></div></div>`;
  $("#bulkBody").innerHTML = r.length ? r
    .map(
      (x) =>
        `<tr${x.completion === "Failed" || x.copy === "Failed" ? ' data-state="failed"' : ""}><td><b>${esc(x.machine)}</b></td><td><span class="${statusAccent(x.copy)}">${esc(x.copy)}</span></td><td><span class="${statusAccent(x.launch)}">${esc(x.launch)}</span></td><td>${esc(x.pid)}</td><td><span class="${statusAccent(x.completion)}">${esc(x.completion)}</span></td><td><span class="${exitTone(x.exit_code)}">${esc(x.exit_code)}</span></td><td>${esc(
          String(x.details || "")
            .split("\n")
            .slice(-1)[0],
        )}</td></tr>`,
    )
    .join("") : `<tr class="atlas-table-empty"><td colspan="7"><b>${AtlasClient.terminal.has(j.state) ? "No per-device results returned" : "Waiting for device results…"}</b><span>${AtlasClient.terminal.has(j.state) ? "This run has no rows to copy or export." : "Results appear here as this run reports progress."}</span></td></tr>`;
}
// Exit code 0 is good news, any other number bad; blank stays neutral.
function exitTone(code) {
  const text = String(code ?? "").trim();
  return !text || !/^-?\d+$/.test(text) ? "status-neutral" : Number(text) === 0 ? "status-ok" : "status-bad";
}
let deploymentHistorySequence = 0;
async function loadDeploymentHistory() {
  const sequence = ++deploymentHistorySequence,
    body = $("#historyBody"), status = $("#historyStatus"), refresh = $("#refreshHistory");
  const empty = (title, message) => `<tr class="atlas-table-empty"><td colspan="8"><b>${esc(title)}</b><span>${esc(message)}</span></td></tr>`;
  if (window.AtlasReadOnly) {
    body.innerHTML = empty("History is not included in this read-only view", "Open Atlas Admin to review recent deployment operations.");
    body.setAttribute("aria-busy", "false");
    status.textContent = "Deployment history is available in Atlas Admin.";
    status.dataset.state = "readonly";
    refresh.disabled = true;
    return;
  }
  body.setAttribute("aria-busy", "true");
  refresh.disabled = true;
  status.textContent = "Loading recent operations…";
  status.dataset.state = "loading";
  if (!body.querySelector("tr:not(.atlas-table-empty)"))
    body.innerHTML = empty("Loading history…", "Retrieving recorded deployment operations.");
  try {
    const records = await api("/api/history");
    if (sequence !== deploymentHistorySequence) return;
    if (!Array.isArray(records)) throw Error("Invalid history response");
    // State badges and a machine link: open the target in Workspace from its history row.
    body.innerHTML = records.length ? records.map((x) =>
      `<tr data-state="${esc(x.state)}"><td>${esc(x.started)}</td><td><button type="button" class="history-target" data-history-target="${esc(x.target)}" title="Select in Workspace">${esc(x.target)}</button></td><td>${esc(x.package)}</td><td>${esc(x.action)}</td><td>${esc(x.mode)}</td><td><span class="history-state" data-state="${esc(x.state)}">${esc(x.state)}</span></td><td><span class="${exitTone(x.exit_code)}">${esc(x.exit_code)}</span></td><td class="history-actions">${["failed", "interrupted", "unknown"].includes(x.state) ? `<button type="button" data-history-retry="${esc(x.id)}">Retry</button>` : ""}<button type="button" data-history-queue="${esc(x.id)}">Queue</button></td></tr>`
    ).join("") : empty("No recent operations", "Deployment operations will appear here when they are recorded. Use Refresh to check again.");
    const failures = records.filter((x) => x.state === "failed").length;
    status.textContent = records.length ? `${records.length} recorded operation${records.length === 1 ? "" : "s"}${failures ? ` · ${failures} failed` : ""}` : "No recorded deployment operations returned.";
    filterDeploymentHistory();
    status.dataset.state = "ready";
  } catch (error) {
    if (sequence !== deploymentHistorySequence) return;
    status.textContent = "History unavailable · " + (body.querySelector("tr:not(.atlas-table-empty)") ? "previous results shown · " : "") + error.message;
    status.dataset.state = "error";
    if (!body.querySelector("tr:not(.atlas-table-empty)"))
      body.innerHTML = empty("History unavailable", "Use Refresh to try again.");
  } finally {
    if (sequence === deploymentHistorySequence) {
      body.setAttribute("aria-busy", "false");
      refresh.disabled = false;
    }
  }
}
function filterDeploymentHistory() {
  const words = ($("#historyFilter")?.value || "").toLowerCase().split(/\s+/).filter(Boolean);
  $("#historyBody").querySelectorAll("tr:not(.atlas-table-empty)").forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.hidden = !words.every((word) => text.includes(word));
  });
}
$("#historyFilter")?.addEventListener("input", filterDeploymentHistory);
$("#historyBody")?.addEventListener("click", (event) => {
  const machine = event.target.closest("[data-history-target]")?.dataset.historyTarget;
  if (!machine || window.AtlasReadOnly) return;
  page("workspace");
  setTarget(machine, "Deployment history", false);
});
function exportCsv() {
  if (!S.rows.length) return;
  let k = [
      "machine",
      "copy",
      "launch",
      "pid",
      "completion",
      "exit_code",
      "details",
    ],
    csv = [
      k.join(","),
      ...S.rows.map((r) =>
        k
          .map((x) => AtlasUI.csvCell(r[x]))
          .join(","),
      ),
    ].join("\n"),
    a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "bulk.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
async function openTargetTool(tool) {
  if (!S.target) return toast("Select a target");
  const d = await api(
    `/api/open-tool/${encodeURIComponent(tool)}/${encodeURIComponent(S.target)}`,
    { method: "POST" },
  );
  toast(`${tool} opened for ${d.computer}`);
}
async function cleanPackages() {
  const context = AtlasClient.snapshot({ computer: S.target });
  if (!context.computer) return toast("Select a target");
  const info = await api(
    "/api/package-folder/" + encodeURIComponent(context.computer),
  );
  if (S.target !== context.computer)
    return toast(
      "Target changed. Open cleanup again for the selected machine.",
    );
  if (!info.exists)
    return toast("The package folder does not exist on " + context.computer);
  if (
    !confirm(
      `Delete ALL contents of ${context.computer} C:\\Temp\\Packages?\n${info.folders} folders, ${info.files} files, ${(info.bytes / 1048576).toFixed(1)} MB`,
    )
  )
    return;
  const result = await api(
    "/api/cleanup-packages/" + encodeURIComponent(context.computer),
    { method: "POST" },
  );
  toast(
    `${context.computer}: deleted ${result.deleted}; failed ${result.failed}`,
  );
}
function currentPackagePayload(mode = "full") {
  const pkg = document.querySelector("#pkg").value;
  return {
    computer: S.target,
    folder: pkg,
    script: document.querySelector("#script").value,
    action: document.querySelector("#action").value,
    fresh: document.querySelector("#fresh").checked,
    threads: Number(document.querySelector("#threads").value),
    mode,
  };
}
async function loadFreshness() {
  if (window.AtlasReadOnly) {
    $("#dbFreshness").textContent =
      "Read-only · Database updates are managed in Atlas Admin.";
    return;
  }
  const d = await api("/api/database-freshness");
  const el = document.querySelector("#dbFreshness");
  if (!el) return;
  el.innerHTML = `<b>${d.excel_newer ? "NEWER EXCEL AVAILABLE" : "DATABASE CURRENT"}</b><span>DB: ${esc(d.database_modified || "missing")}</span><span>Excel: ${esc(d.excel_modified || "missing")}</span>`;
  el.classList.toggle("stale", d.excel_newer);
}
function refreshTargetHealth(scan = true) {
  if (window.AtlasReadOnly) {
    const host = $("#healthLine");
    host.classList.remove("hidden");
    host.textContent = "Live health · " + AtlasReadOnly.reason;
    return Promise.resolve();
  }
  const pc = S.target;
  return pc
    ? AtlasHealth[scan === "quick" ? "quick" : scan ? "scan" : "mount"](
        $("#healthLine"),
        pc,
        () => S.target === pc,
      )
    : Promise.resolve();
}
function renderQueue() {
  document.querySelector("#queueCount").dataset.deployments = activeQueueId ? 0 : deploymentQueue.length;
  document.querySelector("#queueCount").textContent = deploymentQueue.length;
  window.AtlasReboots?.updateCount();
  window.AtlasActions?.updateCount();
  document.querySelector("#queueItems").innerHTML = deploymentQueue.length
    ? deploymentQueue
        .map(
          (x, i) =>
            `<div class="queue-row"><b>${i + 1}. ${esc(x.computer)}</b><span>${esc(PathName(x.folder))} · ${esc(x.action)} · ${esc(x.state || "waiting")}</span><button data-remove-queue="${i}">Remove</button></div>`,
        )
        .join("")
    : '<p class="empty">Queue is empty</p>';
  document.querySelectorAll("[data-remove-queue]").forEach(
    (b) =>
      (b.onclick = () => {
        if (activeQueueId)
          return toast("Clear the saved queue before changing its items.");
        deploymentQueue.splice(+b.dataset.removeQueue, 1);
        renderQueue();
      }),
  );
}
function PathName(path) {
  return (
    String(path || "")
      .split(/[\\/]/)
      .filter(Boolean)
      .pop() || ""
  );
}
function addQueue() {
  if (activeQueueId) return toast("Finish or clear the saved queue first");
  if (!S.target) return toast("Select a target");
  deploymentQueue.push({ ...currentPackagePayload("full"), state: "waiting" });
  renderQueue();
  toast("Added to queue");
}
async function startDeploymentQueue() {
  if (queueRunning) return toast("Queue is already running");
  if (!deploymentQueue.length) return toast("Queue is empty");
  queueRunning = true;
  try {
    const d = activeQueueId
      ? await api("/api/queue/" + activeQueueId + "/resume", { method: "POST" })
      : await api("/api/queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: deploymentQueue }),
        });
    activeQueueId = d.queue;
    pollQueue(activeQueueId);
  } catch (e) {
    queueRunning = false;
    throw e;
  }
}
function pollQueue(id) {
  return AtlasClient.watch(
    "console-queue",
    "/api/queue/" + id,
    (q) => {
      deploymentQueue = q.items.map((x) => ({
        ...x.payload,
        computer: x.target,
        folder: x.package,
        action: x.action,
        state: x.state,
      }));
      renderQueue();
      if (q.state === "paused" || AtlasClient.terminal.has(q.state)) {
        queueRunning = false;
        if (q.state !== "paused") {
          activeQueueId = null;
          deploymentQueue = [];
          renderQueue();
        }
        toast("Queue " + q.state);
      }
    },
    {
      done: (q) => q.state === "paused" || AtlasClient.terminal.has(q.state),
      onError: (e) => toast("Queue monitoring: " + e.message),
    },
  );
}
async function clearDeploymentQueue() {
  if (activeQueueId)
    await api("/api/queue/" + activeQueueId + "/cancel", { method: "POST" });
  if (queueRunning) return toast("Queue will stop after its current item.");
  activeQueueId = null;
  deploymentQueue = [];
  renderQueue();
}
async function pauseDeploymentQueue() {
  if (activeQueueId)
    await api("/api/queue/" + activeQueueId + "/pause", { method: "POST" });
}
function terminalLines(events) {
  return (
    (events || [])
      .map(
        (event) =>
          `[${event.time || "--:--:--"}] ${event.message || ""}${event.log ? "\n" + event.log.join("\n") : ""}`,
      )
      .join("\n") || "Waiting for terminal output..."
  );
}
function deploymentCard(item) {
  if (item.kind === "queue") {
    const rows = (item.items || [])
      .map(
        (row) =>
          `<div class="deployment-queue-item"><b>${esc(row.target || "Unknown target")}</b><span>${esc(row.package || "")} · ${esc(row.action || "")}</span><i class="${statusAccent(row.state)}">${esc(row.state || "waiting")}</i><details><summary>Terminal</summary><pre>${esc(terminalLines(row.events))}</pre></details></div>`,
      )
      .join("");
    return `<article class="deployment-monitor-card"><header><b>Queue</b><span class="${statusAccent(item.state)}">${esc(item.state)}</span></header>${rows || '<p class="empty">Queue has no items</p>'}</article>`;
  }
  const failed = ["failed", "interrupted", "unknown"].includes(item.state);
  const actions = item.retry ? `<div class="deployment-card-actions">${failed ? `<button type="button" class="primary" data-deployment-retry="${esc(item.id)}">Retry</button>` : ""}<button type="button" data-deployment-queue="${esc(item.id)}">Add to queue</button></div>` : "";
  return `<article class="deployment-monitor-card"><header><b>${esc(item.target || "Machine not recorded")}</b><span class="${statusAccent(item.state)}">${esc(item.state)}</span></header><p class="deployment-package"><strong>${esc(item.package || "Package not recorded")}</strong>${item.action ? " · " + esc(item.action) : ""}</p>${item.script ? `<small class="deployment-script">${esc(item.script)}</small>` : ""}<p>${esc(item.last_message || "")}</p>${actions}<pre>${esc(terminalLines(item.events))}</pre></article>`;
}
function renderDeploymentMonitor(data) {
  const list = document.querySelector("#deploymentsList");
  const count =
    data.count ??
    (data.deployments || []).filter((x) =>
      ["queued", "running", "monitoring", "paused"].includes(
        x.state,
      ),
    ).length;
  document.querySelector("#deploymentsCount").textContent = count;
  document
    .querySelector("#deploymentsToggle")
    .classList.toggle("has-active", count > 0);
  list.innerHTML = (data.deployments || []).length
    ? (data.deployments || []).map(deploymentCard).join("")
    : '<p class="empty">No ongoing deployments</p>';
  list
    .querySelectorAll("pre")
    .forEach((pre) => (pre.scrollTop = pre.scrollHeight));
}
function refreshDeploymentMonitor(mode = deploymentMonitorMode) {
  if (window.AtlasReadOnly) {
    renderDeploymentMonitor({ deployments: [], count: 0 });
    $("#deploymentsState").textContent = "Read-only";
    $("#deploymentsList").textContent =
      "Deployment history and active jobs are available in Atlas Admin.";
    return;
  }
  deploymentMonitorMode = mode;
  deploymentMonitorTimer?.();
  const visible = () => $("#deploymentsDrawer").classList.contains("open");
  deploymentMonitorTimer = AtlasClient.watch(
    "deployment-monitor",
    mode === "recent" ? "/api/deployments/recent" : "/api/deployments/active",
    (data) => {
      renderDeploymentMonitor(data);
      $("#deploymentsState").textContent =
        mode === "recent" ? "Recent" : "Live";
    },
    {
      done: () => !visible() || !$("#autoDeployments").checked,
      onError: (e) => {
        $("#deploymentsList").textContent = e.message;
      },
    },
  );
}
function openDeploymentMonitor(mode = "active") {
  document.querySelector("#deploymentsDrawer").classList.add("open");
  refreshDeploymentMonitor(mode);
}
function closeDeploymentMonitor() {
  $("#deploymentsDrawer").classList.remove("open");
  deploymentMonitorTimer?.();
  deploymentMonitorTimer = null;
}
function normaliseSoftwareName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}
function softwareRows() {
  const q = normaliseSoftwareName(
    document.querySelector("#softwareFilter").value,
  );
  return softwareState.currentSoftware.filter(
    (x) =>
      !q ||
      normaliseSoftwareName(
        [x.Name, x.Version, x.Publisher].join(" "),
      ).includes(q),
  );
}
function renderSoftware() {
  return AtlasSoftware.render();
}
function loadSoftware(pc, force = false) {
  return AtlasSoftware.load(pc, force);
}
function updatePackagePresence() {
  const host = document.querySelector("#packagePresence");
  if (!host) return;
  const packageName = document.querySelector("#pkg")?.value;
  if (!packageName || !S.target) {
    host.innerHTML = "";
    return;
  }
  const cached = softwareState.software.get(S.target);
  if (!cached) {
    host.innerHTML =
      '<span class="status-neutral">Software status not collected</span><button id="checkPackagePresence">Check</button>';
    document.querySelector("#checkPackagePresence").onclick = () =>
      loadSoftware(S.target);
    return;
  }
  const p = normaliseSoftwareName(packageName),
    matches = (cached.software || []).filter((x) => {
      const n = normaliseSoftwareName(x.Name);
      return n && p && (n.includes(p) || p.includes(n));
    });
  host.innerHTML = matches.length
    ? `<span class="status-ok">INSTALLED</span><b>${matches
        .slice(0, 3)
        .map((x) => esc(`${x.Name} ${x.Version || ""}`))
        .join(" · ")}</b>`
    : '<span class="status-warn">NOT FOUND IN REGISTRY INVENTORY</span>';
}
function softwareReport(rows = softwareRows()) {
  const data = softwareState.software.get(softwareState.softwareTarget) || {};
  return [
    `Target: ${softwareState.softwareTarget}`,
    `Collected: ${data.collected_at || ""}`,
    `Method: ${data.method || "WMI StdRegProv Core"}`,
    `Applications: ${rows.length}`,
    "",
    ...rows.map((x) =>
      [x.Name, x.Version, x.Publisher].filter(Boolean).join(" | "),
    ),
  ].join("\n");
}
function exportSoftwareCsv() {
  const rows = softwareRows(),
    headers = ["Name", "Version", "Publisher"];
  const csv = [
    headers.join(","),
    ...rows.map((row) =>
      headers
        .map((h) => AtlasUI.csvCell(row[h]))
        .join(","),
    ),
  ].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `${softwareState.softwareTarget}_installed_software_core.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
async function refreshConsolePackage() {
  const folder = document.querySelector("#pkg")?.value,
    host = document.querySelector("#console-package-details"),
    v = ++consoleCatalogueRequest;
  if (!host) return;
  host.textContent = "";
  if (!folder) return;
  try {
    const d = await api(
      "/api/catalog/details?folder=" + encodeURIComponent(folder),
    );
    if (
      v !== consoleCatalogueRequest ||
      folder !== document.querySelector("#pkg").value
    )
      return;
    host.textContent = `${d.display_name || folder} · ${d.version || "Version not recorded"} · ${d.availability} · ${d.files_checked} files checked${d.complete ? "" : " · scan incomplete"}. External script dependencies are not checked.`;
  } catch (e) {
    if (v === consoleCatalogueRequest)
      host.textContent = "Package inspection unavailable: " + e.message;
  }
}
function refreshConsoleSummary() {
  const host = document.querySelector("#console-deploy-summary");
  const choosing = $("#packagePicker").open,
    script = $("#script"),
    unavailable =
      !!window.AtlasReadOnly ||
      !S.target ||
      packageBusy ||
      choosing ||
      !$("#pkg").value ||
      script.disabled ||
      !script.value ||
      deploySubmitting;
  for (const button of [$("#deploy"), $("#copyOnly"), $("#execOnly")])
    if (button.disabled !== unavailable) button.disabled = unavailable;

  const label = deploySubmitting ? "Starting…" : $("#action").value + " on " + (S.target || "machine");
  if ($("#deploy").textContent !== label) $("#deploy").textContent = label;
  for (const button of document.querySelectorAll("[data-deploy-action]")) {
    const pressed = String(button.dataset.deployAction === $("#action").value);
    if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
  }
  if (host) {
    const text = packageBusy
      ? "Loading packages…"
      : choosing
        ? "Choose a package to continue."
        : !$("#pkg").value
          ? "Choose a package."
          : script.disabled
            ? "Loading scripts…"
            : !script.value
              ? "No script for this action."
              : "";
    if (host.textContent !== text) host.textContent = text;
  }
  renderFav();
}
