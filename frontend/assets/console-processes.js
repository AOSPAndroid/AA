/* Remote Admin snapshots keep every process action bound to its original machine. */
const adminRequest = AtlasClient.latest();
const utilityRequest = AtlasClient.latest();
const threadRequest = AtlasClient.latest();
const performanceViews = {
  overview: {
    label: "Overview",
    title: "Performance overview",
    description: "CPU, GPU, RAM and disk pressure in one manual scan.",
  },
  cpu: {
    label: "CPU",
    title: "CPU & processes",
    description:
      "Total usage, every logical processor and the busiest processes in one snapshot.",
  },
  gpu: {
    label: "GPU",
    title: "GPU activity",
    description:
      "Graphics engines and GPU process usage only. No CPU, memory or disk checks.",
  },
  memory: {
    label: "Memory",
    title: "Memory pressure",
    description:
      "RAM, committed memory and paging, with the largest resident processes first.",
  },
};
const performanceCache = new Map(),
  performanceErrors = new Map(),
  performanceErrorTargets = new Map();
let activePerformance = "overview",
  performanceInFlight = null;
let processSnapshot = null,
  processActionPending = false,
  threadSelection = null;
const adminComputer = () => $("#adminPc").value.trim().toUpperCase();
function closeProcessMenu() {
  $("#processMenu").classList.add("hidden");
}
function closeProcessSelection() {
  threadRequest();
  threadSelection = null;
  if ($("#threadDialog").open) $("#threadDialog").close();
  if ($("#processKillDialog").open) $("#processKillDialog").close();
  closeProcessMenu();
}
function invalidateProcesses() {
  window.dispatchEvent(new Event("atlas:admin-target-change"));
  window.AtlasDiagnostics?.clear();
  adminRequest();
  utilityRequest();
  performanceInFlight = null;
  performanceCache.clear();
  performanceErrors.clear();
  performanceErrorTargets.clear();
  $("#cpuProcessScope").value = "all";
  $("#cpuProcessSort").value = "cpu";
  $("#adminUtility").replaceChildren();
  $("#adminUtility").hidden = true;
  $("#quickKillStatus").textContent = "";
  $("#quickKillStatus").hidden = true;
  selectPerformanceView(activePerformance);
}
function selectPerformanceView(kind) {
  if (!performanceViews[kind]) return;
  window.AtlasDiagnostics?.stop();
  closeProcessSelection();
  activePerformance = kind;
  $("#admin").dataset.performanceView = kind;
  $("#cpuProcessControls").hidden = kind !== "cpu";
  processSnapshot = performanceCache.get(kind) || null;
  if (processSnapshot?.computer !== adminComputer()) processSnapshot = null;
  S.processes = processSnapshot?.data.items || [];
  document.querySelectorAll("button[data-performance]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.performance === kind),
    );
  });
  $("#performanceTitle").textContent = performanceViews[kind].title;
  $("#performanceDescription").textContent = performanceViews[kind].description;
  $("#processHint").textContent =
    kind === "cpu"
      ? "Right-click for process actions · Click a thread count for a manual CPU thread sample."
      : kind === "overview"
      ? "Right-click a process for actions, or click its thread count to inspect CPU usage. Thread inspection is a separate manual scan."
      : "Right-click a process for actions. Values reflect the last scan; refresh to check for changes.";
  $("#processHint").hidden = !processSnapshot;
  $("#processFilter").disabled = !processSnapshot;
  $("#processCount").textContent = "No scan";
  if (processSnapshot) {
    renderPerformance();
  } else {
    $("#adminOverview").innerHTML =
      `<div class="perf-empty"><b>${esc(performanceViews[kind].title)}</b><p>${window.AtlasReadOnly ? esc(AtlasReadOnly.reason) : `No ${esc(performanceViews[kind].label)} scan for this machine yet. Select a machine and click Scan ${esc(performanceViews[kind].label)} when you need a reading.`}</p><small>Changing views makes no remote requests.</small></div>`;
    $("#adminOut").replaceChildren();
  }
  updatePerformanceControls();
}
function updatePerformanceControls() {
  const label = performanceViews[activePerformance].label,
    busy = performanceInFlight;
  const capturing = window.AtlasDiagnostics?.isRunning();
  const state = $("#performanceState");
  state.textContent = window.AtlasReadOnly
    ? "Read-only"
    : busy
      ? `Scanning ${performanceViews[busy.kind].label}…`
      : capturing
        ? "Capturing slowness…"
        : !adminComputer()
          ? "Choose a target"
          : performanceErrors.has(activePerformance)
            ? processSnapshot ? "Previous scan" : "Scan failed"
            : processSnapshot ? "Snapshot" : "Not scanned";
  state.dataset.state = busy || capturing
    ? "busy"
    : performanceErrors.has(activePerformance) ? "error" : "idle";
  $("#refreshProcesses").textContent = busy
    ? `Scanning ${performanceViews[busy.kind].label}…`
    : `${processSnapshot ? "Refresh" : "Scan"} ${label}`;
  $("#refreshProcesses").disabled =
    !!window.AtlasReadOnly || !adminComputer() || !!busy || !!capturing;
  $("#diagnoseSlowness").disabled =
    !!window.AtlasReadOnly || !adminComputer() || !!busy || !!capturing;
  $("#copyPerformance").disabled = !processSnapshot;
  $("#cpuProcessScope").disabled = !processSnapshot;
  $("#cpuProcessSort").disabled = !processSnapshot;
  updateProcessActionControls();
  $("#adminOut").setAttribute("aria-busy", String(!!busy));
  if (processSnapshot) renderProcesses();
  else
    $("#processStatus").textContent =
      window.AtlasReadOnly?.reason ||
      performanceErrors.get(activePerformance) ||
      (busy
        ? `Scanning ${performanceViews[busy.kind].label} on ${busy.computer}…`
        : capturing
          ? "Slowness capture running. Waiting for a sample…"
          : "");
}
function acceptPerformanceSnapshot(computer, kind, raw) {
  const data = Array.isArray(raw) ? { items: raw, summary: {} } : raw;
  if (
    !data ||
    data.ok === false ||
    !Array.isArray(data.items) ||
    (data.computer && data.computer.toUpperCase() !== computer) ||
    (data.kind &&
      data.kind !== kind &&
      !(kind === "overview" && data.kind === "diagnose"))
  )
    throw Error("Invalid performance sample; refresh and try again.");
  const previous = performanceCache.get(kind),
    at = new Date(data.checked_at || Date.now());
  const snapshot = Object.freeze({
    computer,
    kind,
    checked: Number.isNaN(at.getTime())
      ? new Date().toLocaleString()
      : at.toLocaleString(),
    data,
    previous:
      previous &&
      previous.computer === computer &&
      previous.data.collection?.profile === data.collection?.profile
        ? { summary: previous.data.summary, checked: previous.checked }
        : null,
  });
  // Map order records acceptance order without inventing a measurement time.
  performanceCache.delete(kind);
  performanceCache.set(kind, snapshot);
  performanceErrors.delete(kind);
  performanceErrorTargets.delete(kind);
  if (kind === activePerformance && computer === adminComputer()) {
    closeProcessSelection();
    processSnapshot = snapshot;
    S.processes = data.items;
    $("#processHint").hidden = false;
    $("#processFilter").disabled = false;
    renderPerformance();
    updatePerformanceControls();
  }
  return snapshot;
}
// Detached, target-specific cached data for manual diagnostic handoffs.
window.AtlasPerformance = {
  snapshot(pc) {
    const computer = String(pc || "").trim().toUpperCase();
    const views = [];
    let latestKind = null;
    for (const [kind, cached] of performanceCache) {
      if (!computer || String(cached.computer || "").trim().toUpperCase() !== computer)
        continue;
      const checkedAt = typeof cached.data.checked_at === "string" &&
        Number.isFinite(Date.parse(cached.data.checked_at))
          ? cached.data.checked_at : null;
      const error = performanceErrorTargets.get(kind) === computer
        ? performanceErrors.get(kind) : null;
      views.push({
        computer,
        kind,
        checkedAt,
        data: JSON.parse(JSON.stringify(cached.data)),
        ...(error ? {error} : {}),
      });
      latestKind = kind;
    }
    for (const [kind, error] of performanceErrors) {
      if (!computer || performanceErrorTargets.get(kind) !== computer ||
        views.some(view => view.kind === kind)) continue;
      views.push({computer, kind, checkedAt: null, data: null, error});
    }
    const scanningKind = computer && performanceInFlight?.computer === computer
      ? performanceInFlight.kind : null;
    return {
      computer,
      state: scanningKind ? "checking"
        : views.some(view => view.error) ? "failed"
          : latestKind ? "ready" : "not_scanned",
      scanningKind,
      views,
      latestKind,
    };
  },
};
async function admin(kind) {
  const pc = adminComputer();
  if (!pc) return toast("Enter a computer first");
  if (!performanceViews[kind]) {
    const request = utilityRequest(),
      out = $("#adminUtility");
    out.hidden = false;
    out.textContent = `Checking ${kind} on ${pc}…`;
    try {
      const data = await api(`/api/${kind}/${encodeURIComponent(pc)}`, {
        signal: request.signal,
      });
      if (request.current() && pc === adminComputer())
        out.innerHTML = `<details open><summary>${esc(kind.toUpperCase())} · ${esc(pc)}</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;
    } catch (error) {
      if (
        error.name !== "AbortError" &&
        request.current() &&
        pc === adminComputer()
      )
        out.textContent = error.message;
    }
    return;
  }
  if (performanceInFlight)
    return toast(
      "A performance scan is already running. Wait for it to finish.",
    );
  selectPerformanceView(kind);
  const request = adminRequest(),
    scan = { computer: pc, kind };
  const current = () => request.current() && pc === adminComputer();
  performanceInFlight = scan;
  performanceErrors.delete(kind);
  performanceErrorTargets.delete(kind);
  updatePerformanceControls();
  try {
    const data = await api(
      `/api/performance/${encodeURIComponent(pc)}?kind=${kind}`,
      { signal: request.signal },
    );
    if (current()) acceptPerformanceSnapshot(pc, kind, data);
  } catch (error) {
    if (error.name !== "AbortError" && current()) {
      performanceErrors.set(
        kind,
        `Scan failed: ${error.message}${performanceCache.has(kind) ? " · Showing the previous scan." : ""}`,
      );
      performanceErrorTargets.set(kind, pc);
      toast(error.message);
    }
  } finally {
    if (performanceInFlight === scan) {
      performanceInFlight = null;
      updatePerformanceControls();
    }
  }
}
function performanceColumns(kind) {
  const columns = {
    cpu: {
      label: "CPU %",
      text: (r) => perfValue(r.CPU, "%"),
      html: (r) => perfMeter(r.CPU, 10, 25),
    },
    gpu: {
      label: "GPU %",
      text: (r) => perfValue(r.GPU, "%"),
      html: (r) => perfMeter(r.GPU, 50, 80),
    },
    engine: {
      label: "Busiest engine",
      text: (r) => r.Engine || "Not reported",
    },
    memory: {
      label: "Memory / RAM %",
      text: (r) =>
        `${perfValue(r.MemoryPercent, "%")} · ${perfBytes(r.MemoryBytes ?? (r.MemoryMB == null ? null : r.MemoryMB * 1048576))} resident`,
      html: (r) =>
        `${perfMeter(r.MemoryPercent, 10, 20)}<small>${perfBytes(r.MemoryBytes ?? (r.MemoryMB == null ? null : r.MemoryMB * 1048576))} resident</small>`,
    },
    private: {
      label: "Private commit",
      text: (r) => perfBytes(r.PrivateBytes),
    },
    faults: {
      label: "Page faults / sec",
      text: (r) => perfValue(r.PageFaultsPerSec),
    },
    handles: { label: "Handles", text: (r) => perfValue(r.Handles) },
    threads: {
      label: "Threads",
      text: (r) => perfValue(r.Threads),
      html: (r, i) =>
        `<button class="thread-link ${perfNumber(r.Threads) >= 500 ? "perf-warn" : ""}" data-process-threads="${i}" ${r.CreatedAt ? "" : "disabled"} title="Inspect CPU usage per thread; thread count alone does not indicate overload">${perfValue(r.Threads)} ↗</button>`,
    },
    io: { label: "I/O / sec", text: (r) => perfBytes(r.IOBytesPerSec) },
  };
  const keys = {
    overview: ["cpu", "gpu", "memory", "threads", "io"],
    cpu: ["cpu", "threads"],
    gpu: ["gpu", "engine"],
    memory: ["memory", "private", "faults", "handles"],
  }[kind];
  return keys.map((key) => columns[key]);
}
function renderProcesses() {
  closeProcessMenu();
  if (!processSnapshot || processSnapshot.computer !== adminComputer()) return;
  const kind = processSnapshot.kind,
    q = $("#processFilter").value.trim().toLowerCase(),
    scope = kind === "cpu" ? $("#cpuProcessScope").value : "all",
    sort = kind === "cpu" ? $("#cpuProcessSort").value : "";
  const rows = S.processes
    .map((row, index) => ({ row, index }))
    .filter(({ row }) =>
      [row.PID, row.Process, row.SessionId, row.CommandLine].some((v) =>
        String(v ?? "")
          .toLowerCase()
          .includes(q),
      ),
    )
    .filter(({ row }) => scope === "all" || (perfNumber(row.CPU) != null && row.CPU >= (scope === "busy" ? 10 : 1)));
  if (kind === "cpu") {
    rows.sort((a, b) => {
      if (sort === "name") return String(a.row.Process || "").localeCompare(String(b.row.Process || ""), undefined, { sensitivity: "base" }) || a.index-b.index;
      if (sort === "pid") return (perfNumber(a.row.PID) ?? Infinity)-(perfNumber(b.row.PID) ?? Infinity) || a.index-b.index;
      const field = sort === "threads" ? "Threads" : "CPU";
      return (perfNumber(b.row[field]) ?? -Infinity)-(perfNumber(a.row[field]) ?? -Infinity) || a.index-b.index;
    });
  }
  const error = performanceErrors.get(kind),
    busy = performanceInFlight,
    total = processSnapshot.data.total_processes ?? S.processes.length,
    ordering = kind === "cpu" ? ({cpu:"CPU",threads:"threads",name:"process name",pid:"PID"}[sort] || "CPU") : kind === "memory" ? "resident memory" : kind === "overview" ? "CPU" : kind.toUpperCase();
  $("#processStatus").textContent =
    `${processSnapshot.computer} · ${S.processes.length} of ${total} ${kind === "cpu" ? "returned" : `processes returned · Sorted by ${ordering}`} · Checked ${processSnapshot.checked}${q || scope !== "all" ? ` · ${rows.length} matching` : ""}${busy ? ` · Scanning ${performanceViews[busy.kind].label}… Previous result shown.` : window.AtlasDiagnostics?.isRunning() ? " · Slowness capture running." : kind === "cpu" ? "" : " · Snapshot; no scan running."}${error ? ` · ${error}` : ""}`;
  const columns = performanceColumns(kind);
  $("#processCount").textContent =
    `${rows.length} of ${processSnapshot.data.total_processes ?? S.processes.length}`;
  $("#adminOut").innerHTML = rows.length
    ? `<table class="process-table"><thead><tr><th>Process / PID</th>${columns.map((c) => `<th>${c.label}</th>`).join("")}<th>Actions</th></tr></thead><tbody>${rows.map(({ row, index }) => `<tr data-process-index="${index}" tabindex="0" aria-label="${esc(row.Process)}, PID ${esc(row.PID)}" title="${esc(row.CommandLine || row.Process)}"><td><b>${esc(row.Process)}</b><small>PID ${esc(row.PID)} · Session ${esc(row.SessionId ?? "—")}</small></td>${columns.map((c) => `<td>${c.html ? c.html(row, index) : esc(c.text(row))}</td>`).join("")}<td><button data-process-actions="${index}" aria-label="Actions for ${esc(row.Process)}, PID ${esc(row.PID)}">•••</button></td></tr>`).join("")}</tbody></table>`
    : `<p class="empty">${kind === "gpu" && !q ? "No GPU process counters were reported in this scan." : "No matching processes."}</p>`;
}
const perfNumber = (value) =>
  value == null || value === "" || !Number.isFinite(Number(value))
    ? null
    : Number(value);
const perfValue = (value, suffix = "") =>
  perfNumber(value) == null
    ? "—"
    : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) +
      suffix;
function perfBytes(value) {
  const number = perfNumber(value);
  if (number == null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"],
    unit = Math.min(
      4,
      Math.max(0, Math.floor(Math.log2(Math.max(1, number)) / 10)),
    );
  return perfValue(number / 1024 ** unit, " " + units[unit]);
}
function perfTone(value, warning, high) {
  return perfNumber(value) == null
    ? "perf-unknown"
    : value >= high
      ? "perf-high"
      : value >= warning
        ? "perf-warn"
        : "perf-normal";
}
function perfMeter(value, warning, high) {
  const number = perfNumber(value),
    tone = perfTone(number, warning, high);
  return `<span class="perf-meter ${tone}"><b>${perfValue(number, "%")}</b>${tone === "perf-high" ? "<em>High</em>" : ""}<i style="--usage:${number == null ? 0 : Math.min(100, Math.max(0, number))}%" aria-hidden="true"></i></span>`;
}
function perfGauge(label, value, detail, warning, high) {
  const number = perfNumber(value),
    tone = perfTone(number, warning, high);
  return `<article class="perf-card ${tone}"><div class="perf-donut" style="--usage:${number == null ? 0 : Math.min(100, Math.max(0, number))}%" role="img" aria-label="${esc(label)}: ${number == null ? "unavailable" : perfValue(number, "% used")}"><b>${perfValue(number, "%")}</b></div><div><h3>${esc(label)}</h3><p>${esc(detail)}</p><small>${number == null ? "Counter unavailable" : tone === "perf-high" ? "High usage" : tone === "perf-warn" ? "Elevated usage" : "Current sample"}</small></div></article>`;
}
function performanceInsights(summary) {
  const notes = [],
    cores = summary.cores || [];
  if (summary.cpu_percent >= 85)
    notes.push(
      "CPU is busy across the machine. Start with the highest CPU processes and inspect their threads.",
    );
  if (
    cores.some((core) => core.percent >= 90) &&
    perfNumber(summary.cpu_percent) != null &&
    summary.cpu_percent < 85
  )
    notes.push(
      "A logical processor is nearly saturated while overall CPU is lower. A single busy thread may be limiting responsiveness.",
    );
  if (summary.memory_percent >= 80)
    notes.push(
      "RAM pressure is elevated. Compare large resident working sets with available RAM and paging reads.",
    );
  if (summary.commit_percent >= 90)
    notes.push(
      "Committed memory is near its limit. Inspect private committed memory in process details.",
    );
  if (summary.page_reads_sec > 20 && summary.memory_percent >= 80)
    notes.push(
      "Paging reads and high RAM use occur together in this sample. Repeat the sample to see whether the pressure persists.",
    );
  if (
    summary.logical_processors > 0 &&
    summary.processor_queue > summary.logical_processors
  )
    notes.push(
      "More threads are queued for CPU than there are logical processors. Repeat the sample to check for sustained CPU contention.",
    );
  if (
    (summary.disks || []).some(
      (disk) => disk.read_ms >= 20 || disk.write_ms >= 20,
    )
  )
    notes.push(
      "Disk responses are elevated in this sample. Compare latency, queue depth and I/O activity below.",
    );
  if (
    (summary.volumes || []).some(
      (volume) =>
        perfNumber(volume.free_percent) != null && volume.free_percent < 10,
    )
  )
    notes.push("A volume has less than 10% free space.");
  if (summary.gpu_percent >= 85)
    notes.push(
      "A GPU engine is busy. Check GPU-heavy processes; different engines cannot be added together as a single process-share pie.",
    );
  return notes;
}
function performanceSummary(snapshot) {
  const s = snapshot.data.summary || {},
    kind = snapshot.kind;
  if (kind === "overview") return s;
  const fields = {
    cpu: [
      "cpu_percent",
      "logical_processors",
      "cores",
      "processor_queue",
      "context_switches_sec",
      "thread_count",
    ],
    gpu: [
      "gpu_percent",
      "gpu_engine",
      "gpu_engine_count",
      "gpu_engines",
      "gpu_process_count",
    ],
    memory: [
      "memory_percent",
      "total_memory_bytes",
      "available_memory_bytes",
      "commit_percent",
      "committed_bytes",
      "commit_limit_bytes",
      "page_reads_sec",
    ],
  }[kind];
  return Object.fromEntries(fields.map((key) => [key, s[key]]));
}
function performanceComparison(snapshot) {
  if (!snapshot.previous) return "";
  const s = performanceSummary(snapshot),
    before = snapshot.previous.summary || {};
  const fields = [
    ["cpu_percent", "CPU", " pp"],
    ["gpu_percent", "GPU", " pp"],
    ["memory_percent", "RAM", " pp"],
    ["commit_percent", "Commit", " pp"],
  ];
  const changes = fields.flatMap(([key, label, unit]) => {
    if (perfNumber(s[key]) == null || perfNumber(before[key]) == null)
      return [];
    const delta = Math.round((s[key] - before[key]) * 10) / 10;
    return [
      `<span>${label} <b>${delta > 0 ? "+" : ""}${perfValue(delta, unit)}</b></span>`,
    ];
  });
  return changes.length
    ? `<div class="perf-comparison"><small>Change since ${esc(snapshot.previous.checked)} · pp = percentage points</small><div class="perf-facts">${changes.join("")}</div></div>`
    : "";
}
function perfStat(label, value, detail, tone = "") {
  return `<article class="perf-card ${tone}"><div><h3>${esc(label)}</h3><strong class="perf-big">${esc(value)}</strong><p>${esc(detail)}</p></div></article>`;
}
function renderCPUPerformance(snapshot) {
  const s = performanceSummary(snapshot), cores = s.cores || [],
    measured = cores.map(core => ({core, value:perfNumber(core.percent)})).filter(c => c.value != null),
    busiest = measured.reduce((best, current) => !best || current.value > best.value ? current : best, null),
    queue = perfNumber(s.processor_queue), logical = perfNumber(s.logical_processors),
    notes = performanceInsights(s), warnings = snapshot.data.warnings || [];
  const stat = (label, value, detail = "", tone = "") => `<div class="cpu-stat ${tone}"><span>${esc(label)}</span><b>${esc(value)}</b>${detail ? `<small>${esc(detail)}</small>` : ""}</div>`;
  const summary = `<div class="cpu-summary" aria-label="CPU summary">
    <div class="cpu-stat cpu-total ${perfTone(s.cpu_percent,70,85)}"><span>Total CPU</span>${perfMeter(s.cpu_percent,70,85)}<small>Across all logical processors</small></div>
    ${stat("Busiest logical CPU",perfValue(busiest?.value,"%"),busiest ? `CPU ${busiest.core.name}` : "Counter unavailable",perfTone(busiest?.value,70,90))}
    ${stat("Queued threads",perfValue(queue),logical == null ? "Logical CPU count unavailable" : `${perfValue(logical)} logical CPUs`,queue != null && logical > 0 && queue > logical ? "perf-warn" : "")}
    ${stat("Threads",perfValue(s.thread_count))}
    ${stat("Context switches / s",perfValue(s.context_switches_sec))}
    ${stat("Logical CPUs",perfValue(logical),`${measured.length} usable counters`)}
  </div>`;
  const activity = `<section class="cpu-core-panel" aria-label="Logical processor activity"><div class="cpu-core-heading"><b>Logical processor activity</b><small>${cores.length ? `${measured.length} of ${cores.length} returned counters available` : "Counters unavailable"}</small></div>
    ${cores.length ? `<div class="perf-cores cpu-core-grid" tabindex="0" aria-label="All returned logical processor readings">${cores.map(core => {const value=perfNumber(core.percent);return `<div class="cpu-core ${perfTone(value,70,90)}" aria-label="Logical CPU ${esc(core.name)}: ${value == null ? "unavailable" : perfValue(value,"%")}"><span>CPU ${esc(core.name)}</span><b>${perfValue(value,"%")}</b><i style="--usage:${value == null ? 0 : Math.min(100,Math.max(0,value))}%" aria-hidden="true"></i></div>`}).join("")}</div>` : '<p class="perf-unavailable">Windows did not return logical processor counters for this scan.</p>'}
  </section>`;
  const evidence = `<details class="cpu-reading-details"><summary>CPU interpretation${notes.length ? ` · ${notes.length} cues` : ""}${warnings.length ? ` · Partial scan: ${warnings.length} counter groups unavailable` : ""}</summary>
    ${notes.length ? `<ul>${notes.map(note => `<li>${esc(note)}</li>`).join("")}</ul>` : '<p>No CPU warning threshold crossed among available counters in this sample.</p>'}
    <p>Process CPU % is relative to all logical processors. A busy logical CPU can indicate a single saturated thread even when total CPU is low. Use a process's thread count to sample its threads. Queue depth and thread counts need comparison across scans to establish sustained pressure.</p>
    <p>These are sampled readings. CPU ≥85%, logical CPU ≥90% and process CPU ≥25% are investigation cues. Missing counters remain unavailable. Compare manual scans while reproducing the issue.</p>
    ${warnings.length ? `<ul>${warnings.map(warning => `<li>${esc(warning)}</li>`).join("")}</ul>` : ""}
  </details>`;
  $("#adminOverview").innerHTML = `<div class="cpu-results">${summary}${activity}${performanceComparison(snapshot)}${evidence}</div>`;
}
function renderPerformance() {
  if (processSnapshot.kind === "cpu") return renderCPUPerformance(processSnapshot);
  const data = processSnapshot.data,
    kind = processSnapshot.kind,
    s = performanceSummary(processSnapshot);
  const notes = performanceInsights(s),
    cores = s.cores || [],
    disks = s.disks || [],
    volumes = s.volumes || [],
    warnings = data.warnings || [];
  const latency = disks
    .flatMap((d) => [d.read_ms, d.write_ms])
    .filter((v) => perfNumber(v) != null);
  const slowest = latency.length ? Math.max(...latency) : null;
  const cpu = () =>
    perfGauge(
      "CPU",
      s.cpu_percent,
      `${perfValue(s.logical_processors)} logical processors · ${perfValue(s.processor_queue)} queued threads`,
      70,
      85,
    );
  const memory = () =>
    perfGauge(
      "Memory",
      s.memory_percent,
      `${perfBytes(s.available_memory_bytes)} available of ${perfBytes(s.total_memory_bytes)} usable RAM`,
      80,
      90,
    );
  const gpu = () =>
    perfGauge(
      "GPU",
      s.gpu_percent,
      "Busiest physical GPU engine · not a sum of processes",
      70,
      85,
    );
  const coreGrid = `<div class="perf-cores">${cores.map((core) => `<div title="Logical processor ${esc(core.name)}"><small>CPU ${esc(core.name)}</small>${perfMeter(core.percent, 70, 90)}</div>`).join("") || "<p>Per-processor counters unavailable.</p>"}</div>`;
  const facts = (pairs) =>
    `<div class="perf-facts">${pairs.map(([label, value]) => `<span>${esc(label)} <b>${esc(value)}</b></span>`).join("")}</div>`;
  let cards = "",
    detail = "",
    extra = "";
  if (kind === "gpu") {
    const engines = s.gpu_engines || [],
      adapters = [...new Set(engines.map((e) => e.adapter))].sort();
    cards =
      gpu() +
      perfStat(
        "Engines reported",
        perfValue(s.gpu_engine_count),
        "3D, Copy, Video Decode and other engines, when Windows exposes them.",
      ) +
      perfStat(
        "Active GPU processes",
        perfValue(s.gpu_process_count),
        "Processes with a reported engine above 0% during this scan.",
      );
    detail = `<details class="perf-details perf-resource-detail"><summary>GPU engine activity</summary>${engines.length ? `<div class="perf-engine-grid">${engines.map((e) => `<div class="perf-engine" title="${esc(e.name)}"><span><b>${esc(e.engine)}</b><small>Adapter ${adapters.indexOf(e.adapter) + 1} · Engine ${esc((e.name.match(/_eng_(\d+)/) || [])[1] || "—")}</small></span>${perfMeter(e.percent, 70, 85)}</div>`).join("")}</div><p class="muted">Showing ${engines.length} of ${perfValue(s.gpu_engine_count)} engines, busiest first. Adapter numbers identify counters within this snapshot.</p>` : '<p class="perf-unavailable">Windows did not expose GPU engine counters in this session. This can occur on virtual desktops. Unavailable does not mean 0% usage.</p>'}</details>`;
  } else if (kind === "memory") {
    cards =
      memory() +
      perfGauge(
        "Committed memory",
        s.commit_percent,
        `${perfBytes(s.committed_bytes)} committed of ${perfBytes(s.commit_limit_bytes)} limit`,
        80,
        90,
      ) +
      perfStat(
        "Available RAM",
        perfBytes(s.available_memory_bytes),
        `${perfValue(s.page_reads_sec, "/s")} paging reads. Compare paging with RAM pressure across scans.`,
      );
    extra = facts([
      ["Usable RAM", perfBytes(s.total_memory_bytes)],
      [
        "Resident RAM in use",
        perfNumber(s.total_memory_bytes) == null ||
        perfNumber(s.available_memory_bytes) == null
          ? "—"
          : perfBytes(s.total_memory_bytes - s.available_memory_bytes),
      ],
    ]);
  } else {
    cards =
      cpu() +
      memory() +
      (data.collection?.profile === "light"
        ? perfStat(
            "Deeper checks",
            "On demand",
            "Select GPU then Scan GPU, or inspect a process's threads. These checks stay outside the light capture.",
          )
        : gpu()) +
      perfStat(
        "Disk response",
        perfValue(slowest, " ms"),
        `Slowest average read / write in this sample · ${disks.length} disks reporting`,
        perfTone(slowest, 20, 50),
      );
    const uptime = perfNumber(s.uptime_seconds);
    extra = facts([
      [
        "Uptime",
        uptime == null
          ? "—"
          : `${Math.floor(uptime / 86400)}d ${Math.floor(uptime / 3600) % 24}h`,
      ],
      ["Commit", perfValue(s.commit_percent, "%")],
      ["Paging reads", perfValue(s.page_reads_sec, "/s")],
      ["Threads", perfValue(s.thread_count)],
      ["Context switches", perfValue(s.context_switches_sec, "/s")],
    ]);
    detail = `<details class="perf-details"><summary>Processor activity & disks</summary><p class="muted">${esc(s.os || "Windows version unavailable")} · ${esc(s.model || "Model unavailable")} · Console logon: ${esc(s.console_user || "Not reported")}</p>${coreGrid}<div class="tablewrap"><table><thead><tr><th>Physical disk</th><th>Read response</th><th>Write response</th><th>Queue</th><th>Read / sec</th><th>Write / sec</th></tr></thead><tbody>${disks.map((d) => `<tr><td>${esc(d.name)}</td><td class="${perfTone(d.read_ms, 20, 50)}">${perfValue(d.read_ms, " ms")}</td><td class="${perfTone(d.write_ms, 20, 50)}">${perfValue(d.write_ms, " ms")}</td><td>${perfValue(d.queue)}</td><td>${perfBytes(d.read_bytes_sec)}</td><td>${perfBytes(d.write_bytes_sec)}</td></tr>`).join("")}</tbody></table></div><div class="perf-facts">${volumes.map((v) => `<span class="${perfNumber(v.free_percent) != null && v.free_percent < 10 ? "perf-high" : ""}">${esc(v.name)} <b>${perfBytes(v.free_bytes)} / ${perfBytes(v.total_bytes)} free (${perfValue(v.free_percent, "%")})</b></span>`).join("")}</div></details>`;
  }
  const guides = {
    gpu: "GPU usage is each process's busiest reported engine. Overall usage is the busiest physical engine across processes; engines are not added together. Process GPU ≥80% is red, ≥50% amber. Missing process counters remain unknown, not zero. GPU memory is not measured by this scan. These readings do not measure Citrix connection latency.",
    memory:
      "Resident memory is physical RAM currently occupied by a process; RAM % divides it by usable RAM. Shared pages may occur in multiple processes, so do not sum working sets. Private commit is memory reserved for the process that must be backed by RAM or the page file, not necessarily resident RAM. Page faults include soft and hard faults; paging reads can include mapped files. Red process RAM ≥20%, amber ≥10%. A single large allocation does not establish a leak.",
    overview:
      "CPU percentages are relative to all logical processors. Process memory is the resident working set divided by usable RAM; shared pages can occur in more than one process, so do not sum process memory. GPU shows the busiest engine, not a sum of engines. Red process values: CPU ≥25%, GPU ≥80%, RAM ≥20%. Amber: CPU/RAM ≥10%, GPU ≥50%. Thread count alone does not establish overload. I/O includes files, network and devices.",
  };
  $("#adminOverview").innerHTML =
    `<div class="perf-summary ${kind === "overview" ? "" : "perf-focused"}">${cards}</div>${extra}${performanceComparison(processSnapshot)}<details class="perf-insights"><summary>Where to look${notes.length ? ` · ${notes.length} investigation cues` : " · No warning thresholds crossed"}</summary>${notes.length ? `<ul>${notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul>` : "<p>No warning threshold crossed among available counters. One sample cannot rule out intermittent slowness or network / Citrix latency.</p>"}</details>${detail}<details class="perf-details"><summary>How to read ${esc(performanceViews[kind].label)} readings</summary><p class="muted">${guides[kind]}</p><p class="muted">Investigation thresholds are cues, not proof of a fault. Ring charts show overall usage versus remaining capacity. Compare manual scans while the user reproduces the issue.</p></details>${warnings.length ? `<details class="perf-details perf-warnings"><summary>${warnings.length} counter groups unavailable — partial results shown</summary><ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}`;
}
async function showProcessThreads(index) {
  window.AtlasDiagnostics?.stop();
  const row = S.processes[index],
    snapshot = processSnapshot;
  if (!snapshot || snapshot.computer !== adminComputer() || !row?.CreatedAt)
    return toast("Refresh the process list first");
  threadSelection = { row, snapshot, focus: document.activeElement };
  $("#threadTitle").textContent =
    `${row.Process} · PID ${row.PID} · ${snapshot.computer}`;
  $("#threadDialog").showModal();
  await refreshProcessThreads();
}
async function refreshProcessThreads() {
  const selection = threadSelection;
  if (!selection) return;
  const { row, snapshot } = selection,
    request = threadRequest(),
    current = () =>
      request.current() &&
      threadSelection === selection &&
      snapshot === processSnapshot &&
      snapshot.computer === adminComputer() &&
      $("#threadDialog").open;
  $("#threadStatus").textContent =
    "Sampling thread CPU for at least one second…";
  $("#threadBody").replaceChildren();
  $("#refreshThreads").disabled = true;
  try {
    const data = await api(
      `/api/performance/${encodeURIComponent(snapshot.computer)}/threads/${row.PID}?` +
        new URLSearchParams({ created: row.CreatedAt, name: row.Process }),
      { signal: request.signal },
    );
    if (!current()) return;
    $("#threadStatus").textContent =
      `${data.items.length} of ${data.total_threads} threads · ${perfValue(data.logical_processors)} logical processors · Checked ${new Date().toLocaleTimeString()} · Sorted by CPU on one logical processor`;
    $("#threadBody").innerHTML =
      `<table class="process-table"><thead><tr><th>Thread ID</th><th>One logical CPU %</th><th>Whole machine %</th><th>State</th><th>Wait reason</th><th>Switches / sec</th><th>Priority</th></tr></thead><tbody>${data.items.map((thread) => `<tr><td>${esc(thread.TID)}</td><td>${perfMeter(thread.CoreCPU, 50, 80)}</td><td>${perfValue(thread.CPU, "%")}</td><td>${esc(thread.State)}</td><td>${esc(thread.WaitReason || "—")}</td><td>${perfValue(thread.ContextSwitches)}</td><td>${perfValue(thread.Priority)}</td></tr>`).join("")}</tbody></table>${data.warnings?.length ? `<p class="muted">${data.warnings.map(esc).join(" · ")}</p>` : ""}<p class="muted">— means a counter is unavailable or the thread was created or changed during sampling. This is a CPU sample, not a call stack or a measurement of time blocked.</p>`;
  } catch (error) {
    if (error.name !== "AbortError" && current())
      $("#threadStatus").textContent = error.message;
  } finally {
    if (current()) $("#refreshThreads").disabled = false;
  }
}
function copyPerformanceReport() {
  if (!processSnapshot || processSnapshot.computer !== adminComputer()) return;
  const s = performanceSummary(processSnapshot),
    kind = processSnapshot.kind,
    columns = performanceColumns(kind);
  const lines = [
    `${processSnapshot.computer} · ${performanceViews[kind].label} snapshot · ${processSnapshot.checked}`,
  ];
  if (kind === "cpu" || kind === "overview")
    lines.push(
      `CPU: ${perfValue(s.cpu_percent, "%")} · Logical processors: ${perfValue(s.logical_processors)} · Queue: ${perfValue(s.processor_queue)} · Threads: ${perfValue(s.thread_count)} · Context switches: ${perfValue(s.context_switches_sec, "/s")}`,
      ...(s.cores || []).map(
        (c) => `CPU ${c.name}: ${perfValue(c.percent, "%")}`,
      ),
    );
  if (kind === "memory" || kind === "overview")
    lines.push(
      `RAM: ${perfValue(s.memory_percent, "% used")} · ${perfBytes(s.available_memory_bytes)} available / ${perfBytes(s.total_memory_bytes)} usable`,
      `Commit: ${perfValue(s.commit_percent, "%")} · ${perfBytes(s.committed_bytes)} / ${perfBytes(s.commit_limit_bytes)} limit · Paging reads: ${perfValue(s.page_reads_sec, "/s")}`,
    );
  if (kind === "gpu" || kind === "overview")
    lines.push(
      `GPU busiest engine: ${perfValue(s.gpu_percent, "%")}`,
      ...(s.gpu_engines || []).map(
        (e) => `${e.name}: ${perfValue(e.percent, "%")}`,
      ),
    );
  if (kind === "overview")
    lines.push(
      `${s.os || "Windows version unavailable"} · ${s.model || "Model unavailable"} · Console logon: ${s.console_user || "Not reported"} · Uptime: ${perfValue(s.uptime_seconds == null ? null : s.uptime_seconds / 3600, " hours")}`,
      ...(s.disks || []).map(
        (d) =>
          `Disk ${d.name}: read ${perfValue(d.read_ms, " ms")}, write ${perfValue(d.write_ms, " ms")}, queue ${perfValue(d.queue)}, read ${perfBytes(d.read_bytes_sec)}/s, write ${perfBytes(d.write_bytes_sec)}/s`,
      ),
      ...(s.volumes || []).map(
        (v) =>
          `${v.name}: ${perfBytes(v.free_bytes)} / ${perfBytes(v.total_bytes)} free (${perfValue(v.free_percent, "%")})`,
      ),
    );
  lines.push(
    ...performanceInsights(s),
    ["Process", "PID", "Session", ...columns.map((c) => c.label)].join("\t"),
    ...S.processes.map((r) =>
      [
        r.Process,
        r.PID,
        r.SessionId ?? "—",
        ...columns.map((c) => c.text(r)),
      ].join("\t"),
    ),
    ...(processSnapshot.data.warnings || []),
    "Unavailable counters are unknown, not zero. Investigation thresholds only; one sample does not establish the cause of slowness.",
  );
  return copy(lines.join("\n"), `${performanceViews[kind].label} report`);
}
function confirmProcessKill(question, multiple = false) {
  const dialog = $("#processKillDialog");
  $("#processKillTitle").textContent = multiple ? "Kill processes?" : "Kill process?";
  $("#confirmProcessKill").textContent = multiple ? "Kill processes" : "Kill process";
  $("#processKillWarning").textContent = multiple
    ? "Unsaved work in these processes may be lost."
    : "Unsaved work in this process may be lost.";
  $("#processKillQuestion").textContent = question;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.onclose = () => resolve(dialog.returnValue === "kill");
    $("#cancelProcessKill").onclick = () => dialog.close();
    $("#confirmProcessKill").onclick = () => {
      dialog.returnValue = "kill";
      dialog.close();
    };
    dialog.showModal();
    $("#cancelProcessKill").focus();
  });
}
function updateProcessActionControls() {
  const disabled = !!window.AtlasReadOnly || !adminComputer() || processActionPending;
  document.querySelectorAll('#killBtn, [data-quick-kill], #killMatches').forEach(button => {
    button.disabled = disabled;
  });
}
function quickProcessKill(value, match = "exact") {
  const computer = adminComputer();
  value = value.trim();
  if (!computer) return toast("Enter a target machine first");
  if (match === "contains" && !/^[A-Za-z0-9][A-Za-z0-9_. -]{2,63}$/.test(value))
    return toast("Enter 3–64 characters of a process name, starting with a letter or number; wildcards are not supported");
  const scope = match === "contains"
    ? `all processes whose names contain "${value}" (case-insensitive)`
    : `all processes named ${value}`;
  return terminateProcess(
    { computer, value, match },
    `Kill ${scope} on ${computer}, across all sessions?`,
    processSnapshot,
  );
}
async function terminateProcess(payload, question, snapshot) {
  if (window.AtlasReadOnly) return toast(AtlasReadOnly.reason);
  if (processActionPending) return;
  if (
    payload.computer !== adminComputer() ||
    (snapshot && snapshot !== processSnapshot)
  )
    return toast("Target or process list changed. Select the process again.");
  processActionPending = true;
  updateProcessActionControls();
  try {
    if (!(await confirmProcessKill(question, !!payload.match || !/^\d+$/.test(payload.value)))) return;
    if (
      payload.computer !== adminComputer() ||
      (snapshot && snapshot !== processSnapshot)
    )
      return toast("Target or process list changed. Select the process again.");
    if (payload.match) {
      $("#quickKillStatus").textContent = payload.match === "contains"
        ? `Terminating process names containing "${payload.value}" on ${payload.computer}…`
        : `Terminating ${payload.value} on ${payload.computer}…`;
      $("#quickKillStatus").hidden = false;
    }
    const result = await api("/api/kill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const failures = (result.results || []).filter(
        (row) => row.state !== "terminated",
      ),
      message = `${payload.computer}: ${result.count} terminated${failures.length ? "; " + failures.map((row) => `${row.Process} (${row.PID}): ${row.message}`).join("; ") : result.count ? "" : "; no matching process is still running"}`;
    toast(message);
    if (payload.computer === adminComputer()) {
      if (result.count) {
        performanceCache.clear();
        performanceErrors.clear();
        performanceErrorTargets.clear();
        if (snapshot && snapshot === processSnapshot)
          await admin(snapshot.kind);
        else selectPerformanceView(activePerformance);
      }
      if (failures.length || !result.count)
        $("#processStatus").textContent = message;
      if (payload.match) {
        $("#quickKillStatus").textContent = message;
        $("#quickKillStatus").hidden = false;
      }
    }
  } catch (error) {
    toast(error.message);
    if (payload.computer === adminComputer()) {
      $("#processStatus").textContent = error.message;
      if (payload.match) {
        $("#quickKillStatus").textContent = error.message;
        $("#quickKillStatus").hidden = false;
      }
    }
  } finally {
    processActionPending = false;
    updateProcessActionControls();
  }
}
function processMenu(event, index) {
  const snapshot = processSnapshot,
    row = S.processes[index],
    menu = $("#processMenu");
  if (!snapshot || snapshot.computer !== adminComputer() || !row) return;
  event.preventDefault();
  const payload = Object.freeze({
    computer: snapshot.computer,
    value: String(row.PID),
    created: row.CreatedAt,
    name: row.Process,
  });
  menu.replaceChildren();
  menu.setAttribute("aria-label", `Actions for ${row.Process}, PID ${row.PID}`);
  const add = (label, action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitem");
    button.textContent = label;
    button.onclick = () => {
      closeProcessMenu();
      Promise.resolve(action()).catch((error) => toast(error.message));
    };
    menu.append(button);
    return button;
  };
  const kill = add("Kill process", () =>
    terminateProcess(
      payload,
      `Kill ${row.Process} (PID ${row.PID}) on ${snapshot.computer}?`,
      snapshot,
    ),
  );
  kill.className = "danger";
  kill.disabled =
    row.CanTerminate !== true || !row.CreatedAt || processActionPending;
  kill.title =
    row.BlockReason ||
    (kill.disabled
      ? "Process identity unavailable or an action is pending"
      : "Terminate this process only");
  if (snapshot.kind === "cpu" || snapshot.kind === "overview")
    add("Inspect CPU threads", () => {
      if (snapshot !== processSnapshot || snapshot.computer !== adminComputer())
        return toast("Process list changed. Select the process again.");
      return showProcessThreads(index);
    }).disabled = !row.CreatedAt;
  add("Copy PID", () => copy(row.PID, "PID"));
  add("Copy process details", () =>
    copy(
      `${snapshot.computer}\n${JSON.stringify(row, null, 2)}`,
      "Process details",
    ),
  );
  menu.classList.remove("hidden");
  menu.style.left = menu.style.top = "8px";
  const bounds = menu.getBoundingClientRect();
  menu.style.left =
    Math.max(8, Math.min(event.clientX, innerWidth - bounds.width - 8)) + "px";
  menu.style.top =
    Math.max(8, Math.min(event.clientY, innerHeight - bounds.height - 8)) +
    "px";
  menu.querySelector("button:not(:disabled)")?.focus({ preventScroll: true });
  menu.onkeydown = (e) => {
    const buttons = [...menu.querySelectorAll("button:not(:disabled)")],
      i = buttons.indexOf(document.activeElement);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      buttons[
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? buttons.length - 1
            : (i + (e.key === "ArrowUp" ? -1 : 1) + buttons.length) %
              buttons.length
      ]?.focus();
    }
    if (["Escape", "Tab"].includes(e.key)) {
      closeProcessMenu();
      if (e.key === "Escape") {
        e.preventDefault();
        $("#adminOut")
          ?.querySelector(`[data-process-index="${index}"]`)
          ?.focus({ preventScroll: true });
      }
    }
  };
}
function bindProcessControls() {
  $("#adminPc").addEventListener("input", invalidateProcesses);
  $("#processFilter").oninput = renderProcesses;
  $("#cpuProcessScope").onchange = renderProcesses;
  $("#cpuProcessSort").onchange = renderProcesses;
  document.querySelectorAll("button[data-performance]").forEach((button) => {
    button.onclick = () => selectPerformanceView(button.dataset.performance);
  });
  $("#refreshProcesses").onclick = () => admin(activePerformance);
  selectPerformanceView(activePerformance);
  $("#copyPerformance").onclick = copyPerformanceReport;
  document.querySelectorAll('[data-quick-kill]').forEach(button => {
    button.onclick = () => quickProcessKill(button.dataset.quickKill);
  });
  $("#killMatches").onclick = () => quickProcessKill($("#killMatchWord").value, "contains");
  $("#killMatchWord").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      $("#killMatches").click();
    }
  });
  $("#refreshThreads").onclick = refreshProcessThreads;
  $("#closeThreads").onclick = () => $("#threadDialog").close();
  $("#threadDialog").addEventListener("close", () => {
    threadRequest();
    const focus = threadSelection?.focus;
    threadSelection = null;
    focus?.focus({ preventScroll: true });
  });
  $("#killBtn").onclick = () => {
    const computer = adminComputer(),
      value = $("#kill").value.trim();
    if (!computer || !value)
      return toast("Enter a computer and a PID or executable name");
    return terminateProcess(
      { computer, value },
      `Kill ${/^\d+$/.test(value) ? "PID " + value : "all processes named " + value} on ${computer}?`,
      processSnapshot,
    );
  };
  $("#kill").addEventListener("keydown", (event) => {
    if(event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      $("#killBtn").click();
    }
  });
  $("#adminOut").addEventListener("contextmenu", (event) => {
    const row = event.target.closest("[data-process-index]");
    if (row) processMenu(event, Number(row.dataset.processIndex));
  });
  $("#adminOut").addEventListener("click", (event) => {
    const threads = event.target.closest("[data-process-threads]");
    if (threads)
      return showProcessThreads(Number(threads.dataset.processThreads));
    const button = event.target.closest("[data-process-actions]");
    if (!button) return;
    const rect = button.getBoundingClientRect();
    processMenu(
      { clientX: rect.left, clientY: rect.bottom, preventDefault() {} },
      Number(button.dataset.processActions),
    );
  });
  $("#adminOut").addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-process-index]");
    if (
      row &&
      (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10"))
    ) {
      event.preventDefault();
      const rect = row.getBoundingClientRect();
      processMenu(
        { clientX: rect.left + 12, clientY: rect.bottom, preventDefault() {} },
        Number(row.dataset.processIndex),
      );
    }
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("#processMenu")) closeProcessMenu();
  });
  window.addEventListener("resize", closeProcessMenu);
  window.addEventListener("blur", closeProcessMenu);
  window.addEventListener(
    "scroll",
    (e) => {
      if (e.target === window || !$("#processMenu").contains(e.target))
        closeProcessMenu();
    },
    true,
  );
}
