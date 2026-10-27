/* Quick selection checks fetch connectivity, disk and uptime only; full health stays explicit. */
(() => {
  "use strict";
  const esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const labels = {
    wmi: "WMI",
    cshare: "C$",
    ping: "Ping",
    cpu: "CPU",
    ram: "RAM",
    gpu: "GPU",
    storage: "Storage",
    system: "Windows / uptime",
  };
  const snapshots = new WeakMap();
  const active = new WeakMap(),
    num = (v) =>
      v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v))
        ? Number(v)
        : null;
  const gib = (v) =>
    num(v) === null
      ? "Unavailable"
      : (Number(v) / 1073741824).toFixed(1) + " GiB";
  function format(key, d) {
    if (["wmi", "cshare", "ping"].includes(key))
      return d.available === true
        ? "Available"
        : d.available === false
          ? key === "ping"
            ? "No ping reply"
            : "Unavailable"
          : "Unavailable";
    if (key === "cpu")
      return (
        (d.processors || [])
          .map(
            (x) =>
              `${x.Name || "Unknown CPU"} · ${num(x.LoadPercentage) === null ? "Utilisation unavailable" : x.LoadPercentage + "% utilisation"} · ${x.NumberOfCores ?? "?"} cores / ${x.NumberOfLogicalProcessors ?? "?"} threads`,
          )
          .join("; ") || "Unavailable"
      );
    if (key === "gpu")
      return (
        (d.adapters || []).map((x) => x.Name || "Unknown adapter").join("; ") ||
        "Unavailable"
      );
    if (key === "ram") {
      const total = num(d.usable_kib),
        free = num(d.free_kib);
      return `${gib(d.installed_bytes)} installed · ${total > 0 && free !== null && free >= 0 && free <= total ? ((total - free) / 1048576).toFixed(1) + " / " + (total / 1048576).toFixed(1) + " GiB usable in use (" + (((total - free) * 100) / total).toFixed(0) + "%)" : "Usage unavailable"}`;
    }
    if (key === "storage")
      return `C: ${gib(d.free_bytes)} free / ${gib(d.total_bytes)} total`;
    if (key === "system") {
      const n = num(d.uptime_seconds);
      return `${d.windows || "Windows unavailable"} ${d.version || ""} · Uptime ${n === null ? "unavailable" : Math.floor(n / 86400) + "d " + Math.floor((n % 86400) / 3600) + "h " + Math.floor((n % 3600) / 60) + "m"} · Boot ${d.last_boot || "unavailable"} (target local time)`;
    }
    return "Unavailable";
  }
  function badges(m) {
    return AtlasUI.machineBadges(m);
  }
  function cancel(host) {
    const old = active.get(host);
    if (old) {
      old.abort();
      active.delete(host);
    }
  }
  function render(host, pc, isCurrent, scanning) {
    host.classList.remove("hidden");
    host.classList.add("atlas-health");
    host.innerHTML = `<div class="atlas-health-heading"><b>${esc(pc)} · Machine health</b><button type="button" data-health-refresh ${scanning ? "disabled" : ""}>${scanning ? "Checking…" : "Scan health"}</button></div><p>Quick checks cover ping, C$ access, C: storage/free space and last boot/uptime. Scan health checks all readings manually. Citrix snapshot devices require a manual scan. No background polling.</p><div class="atlas-health-grid">${Object.entries(
      labels,
    )
      .map(
        ([key, label]) =>
          `<div class="atlas-health-item"><b>${label}</b><div data-metric="${key}">${scanning && scanning.includes(key) ? "Loading…" : "Not scanned"}</div><small data-time="${key}"></small></div>`,
      )
      .join("")}</div>`;
    if (host.id === "healthLine") {
      const details = document.createElement("details");
      details.className = "atlas-health-details";
      const summary = document.createElement("summary");
      summary.textContent = "Full health readings";
      details.append(summary, host.querySelector("p"), host.querySelector(".atlas-health-grid"));
      const mini = document.createElement("div");
      mini.className = "atlas-health-mini";
      mini.setAttribute("aria-live", "polite");
      host.append(mini, details);
      updateMini(host, pc);
    }
    const button = host.querySelector("[data-health-refresh]");
    button.onclick = () => scan(host, pc, isCurrent);
    return button;
  }
  function updateMini(host, pc) {
    const mini = host.querySelector(".atlas-health-mini");
    if (!mini) return;
    mini.innerHTML = compact(host, pc)
      .filter(row => [labels.ping, labels.cshare, labels.storage, labels.system].includes(row.label))
      .map(row => `<span class="${row.warning ? "warning" : ""}" title="${esc(row.title)}"><b>${esc(row.label === labels.system ? "Uptime" : row.label)}</b> ${esc(row.text)}</span>`)
      .join("");
  }
  function mount(host, pc, isCurrent = () => true) {
    if (!host) return;
    cancel(host);
    snapshots.set(host, { pc, metrics: {}, state: "idle" });
    render(host, pc, isCurrent, false);
  }
  function quick(host, pc, isCurrent = () => true) {
    if (!host?.isConnected || !isCurrent()) return;
    // Demo shows the same card with no checks; its Scan health is greyed out.
    if (window.AtlasReadOnly) return mount(host, pc, isCurrent);
    const previous = snapshots.get(host);
    if (
      previous?.pc === pc &&
      active.has(host) && previous.state !== "complete"
    )
      return;
    mount(host, pc, isCurrent);
    const controller = new AbortController();
    active.set(host, controller);
    const timer = setTimeout(() => {
      if (!controller.signal.aborted && host.isConnected && isCurrent())
        scan(host, pc, isCurrent, ["ping", "cshare", "storage", "system"]);
    }, 250);
    controller.signal.addEventListener("abort", () => clearTimeout(timer), {
      once: true,
    });
  }
  async function scan(
    host,
    pc,
    isCurrent = () => true,
    keys = Object.keys(labels),
  ) {
    if (!host?.isConnected || !isCurrent()) return;
    cancel(host);
    const controller = new AbortController();
    active.set(host, controller);
    const current = () =>
      active.get(host) === controller && host.isConnected && isCurrent();
    snapshots.set(host, {
      pc,
      metrics: {},
      state: "checking",
      checkingKeys: keys,
    });
    const button = render(host, pc, isCurrent, keys);
    await Promise.allSettled(
      keys.map(async (key) => {
        const timed = new AbortController();
        const stop = () => timed.abort();
        controller.signal.addEventListener("abort", stop, { once: true });
        const timer = setTimeout(stop, 24000);
        try {
          window.dispatchEvent(new CustomEvent("atlas:activity"));
          const r = await fetch(
            "/api/machine-health/" + encodeURIComponent(pc) + "/" + key,
            { signal: timed.signal },
          );
          if (!r.ok) throw Error("Health request failed");
          const d = await r.json();
          if (!current()) return;
          if (d.computer.toUpperCase() !== pc.toUpperCase() || d.metric !== key)
            throw Error("Target mismatch");
          const el = host.querySelector('[data-metric="' + key + '"]');
          el.textContent =
            d.state === "ready" ? format(key, d.data || {}) : "Unavailable";
          el.title = d.error || "";
          el.dataset.state = d.state;
          snapshots.get(host).metrics[key] = d;
          if (key === "system") {
            const overdue =
              d.state === "ready" &&
              num(d.data?.uptime_seconds) !== null &&
              Number(d.data.uptime_seconds) > 8 * 86400;
            el.classList.toggle("atlas-uptime-overdue", overdue);
            if (overdue)
              el.title =
                "Uptime exceeds 8 days. Weekend restart may have been missed.";
          }
          host.querySelector('[data-time="' + key + '"]').textContent =
            d.checked_at
              ? "Checked " + new Date(d.checked_at).toLocaleTimeString()
              : "";
        } catch (e) {
          if (current()) {
            const el = host.querySelector('[data-metric="' + key + '"]');
            el.textContent = "Unavailable";
            el.title = e.name === "AbortError" ? "Check timed out" : e.message;
            el.dataset.state = "unavailable";
            snapshots.get(host).metrics[key] = {
              state: "unavailable",
              error: el.title,
            };
          }
        } finally {
          if (current()) updateMini(host, pc);
          clearTimeout(timer);
          controller.signal.removeEventListener("abort", stop);
        }
      }),
    );
    if (current()) {
      snapshots.get(host).state = "complete";
      button.disabled = false;
      button.textContent =
        keys.length === Object.keys(labels).length
          ? "Refresh health"
          : "Scan health";
    }
  }
  function specs(pc) {
    document.querySelectorAll(".atlas-spec-dialog").forEach((x) => x.close());
    const d = document.createElement("dialog");
    d.className = "atlas-spec-dialog";
    d.innerHTML =
      '<div class="atlas-health-heading"><h2>Machine specifications</h2><button type="button" aria-label="Close specifications">Close</button></div><p>Click Scan health to retrieve current specifications. Missing or failed readings are unavailable.</p><div data-spec-health></div>';
    document.body.append(d);
    const host = d.querySelector("[data-spec-health]");
    d.querySelector("button").onclick = () => d.close();
    d.addEventListener(
      "close",
      () => {
        cancel(host);
        d.remove();
      },
      { once: true },
    );
    d.showModal();
    mount(host, pc, () => d.open);
  }
  function report(host, pc) {
    const snapshot = snapshots.get(host);
    return Object.entries(labels).map(([key, label]) => {
      const metric =
        snapshot && snapshot.pc === pc ? snapshot.metrics[key] : null;
      return (
        label +
        ": " +
        (!metric
          ? "Not collected / loading"
          : metric.state === "ready"
            ? format(key, metric.data || {})
            : "Unavailable") +
        (metric?.checked_at ? " [checked " + metric.checked_at + "]" : "")
      );
    });
  }
  function compact(host, pc) {
    const snapshot = snapshots.get(host);
    return Object.entries(labels).map(([key, label]) => {
      const metric = snapshot?.pc === pc ? snapshot.metrics[key] : null;
      const d = metric?.data || {};
      let text = !metric
        ? snapshot?.pc === pc &&
          snapshot.state === "checking" &&
          snapshot.checkingKeys.includes(key)
          ? "Checking…"
          : "Not scanned"
        : metric.state !== "ready"
          ? "Unavailable"
          : format(key, d);
      if (metric?.state === "ready") {
        if (key === "cpu")
          text =
            num(d.processors?.[0]?.LoadPercentage) === null
              ? "Unavailable"
              : d.processors[0].LoadPercentage + "%";
        if (key === "ram")
          text =
            num(d.usable_kib) > 0 &&
            num(d.free_kib) !== null &&
            num(d.free_kib) >= 0 &&
            num(d.free_kib) <= num(d.usable_kib)
              ? Math.round((1 - d.free_kib / d.usable_kib) * 100) + "% used"
              : "Unavailable";
        if (key === "storage")
          text =
            num(d.free_bytes) === null
              ? "Unavailable"
              : gib(d.free_bytes) + " free";
        if (key === "gpu")
          text = (d.adapters || []).length
            ? d.adapters.length + " adapter(s)"
            : "Unavailable";
        if (key === "system")
          text =
            num(d.uptime_seconds) === null
              ? "Unavailable"
              : Math.floor(d.uptime_seconds / 86400) +
                "d " +
                Math.floor((d.uptime_seconds % 86400) / 3600) +
                "h uptime";
      }
      return {
        key,
        label,
        text,
        checkedAt: metric?.checked_at || "",
        warning:
          text === "Unavailable" ||
          d.available === false ||
          (key === "system" && num(d.uptime_seconds) > 8 * 86400),
        title:
          (metric?.state === "ready" ? format(key, d) : metric?.error || text) +
          (metric?.checked_at
            ? " · Checked " + new Date(metric.checked_at).toLocaleString()
            : ""),
      };
    });
  }
  function specifications(host, pc) {
    const snapshot = snapshots.get(host);
    if (snapshot?.pc !== pc) return [];
    const readings = snapshot.metrics;
    return [
      ["CPU model", readings.cpu, d => (d.processors || []).map(x => x.Name).filter(Boolean).join("; ")],
      ["Memory", readings.ram, d => num(d.installed_bytes) === null ? "" : gib(d.installed_bytes)],
      ["Windows", readings.system, d => [d.windows, d.version].filter(Boolean).join(" ")],
    ].filter(([, metric]) => metric?.state === "ready")
      .map(([label, metric, value]) => ({label, text: value(metric.data || {}), checkedAt: metric.checked_at || ""}))
      .filter(row => row.text);
  }
  // Read the current cache only; copying diagnostics must never start a scan.
  function snapshot(host, pc) {
    const computer = String(pc || "").trim().toUpperCase();
    const cached = snapshots.get(host);
    const matching = computer &&
      String(cached?.pc || "").trim().toUpperCase() === computer;
    const controller = active.get(host);
    const checking = !!(matching && cached.state === "checking" &&
      controller && !controller.signal.aborted);
    const metrics = Object.entries(labels).map(([key, label]) => {
      const metric = matching ? cached.metrics[key] : null;
      const state = metric
        ? metric.state === "ready" ? "ready" : "unavailable"
        : checking && cached.checkingKeys?.includes(key)
          ? "checking" : "not_scanned";
      const checkedAt = typeof metric?.checked_at === "string" &&
        Number.isFinite(Date.parse(metric.checked_at)) ? metric.checked_at : null;
      return {
        key,
        label,
        state,
        checkedAt,
        text: state === "ready" ? format(key, metric.data || {})
          : state === "checking" ? "Checking…"
            : state === "unavailable" ? "Unavailable" : "Not scanned",
        ...(state === "ready"
          ? {data: JSON.parse(JSON.stringify(metric.data || {}))} : {}),
        ...(metric?.error ? {error: String(metric.error)} : {}),
      };
    });
    return {
      computer,
      state: checking ? "checking"
        : metrics.some(metric => metric.state === "ready") ? "ready"
          : metrics.some(metric => metric.state === "unavailable")
            ? "unavailable" : "not_scanned",
      metrics,
    };
  }
  window.AtlasHealth = {
    mount,
    quick,
    scan,
    cancel,
    specs,
    badges,
    format,
    report,
    compact,
    specifications,
    snapshot,
  };
})();
