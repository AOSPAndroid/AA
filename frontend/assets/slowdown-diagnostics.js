/* Bounded, read-only capture. Findings describe observations, not proven causes. */
(() => {
  const duration = 60000,
    interval = 10000,
    maxSamples = 6;
  const number = (value) =>
    value == null || value === "" || !Number.isFinite(Number(value))
      ? null
      : Number(value);
  const known = (value) => number(value) != null;
  const fmt = (value, unit = "%") =>
    known(value) ? `${Math.round(value * 10) / 10}${unit}` : "Not measured";
  const mean = (values) =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const identity = (row) => `${row.PID}|${row.CreatedAt}|${row.Process}`;
  const diskDelay = (sample) => {
    const values = (sample.summary?.disks || [])
      .flatMap((disk) => [
        disk.read_bytes_sec > 0 && known(disk.read_ms) ? disk.read_ms : null,
        disk.write_bytes_sec > 0 && known(disk.write_ms) ? disk.write_ms : null,
      ])
      .filter(known);
    return values.length ? Math.max(...values) : null;
  };
  function leader(samples, field) {
    const groups = new Map();
    for (const sample of samples)
      for (const row of sample.items || []) {
        if (!known(row[field])) continue;
        // Unknown creation times cannot establish identity across samples.
        const key = identity(row) + (row.CreatedAt ? "" : `|${sample.elapsed}`);
        if (!groups.has(key)) groups.set(key, { row, values: [] });
        groups.get(key).values.push(Number(row[field]));
      }
    return [...groups.values()]
      .map((g) => ({ ...g, value: mean(g.values) }))
      .sort((a, b) =>
        ["CPU", "GPU"].includes(field)
          ? b.value * b.values.length - a.value * a.values.length
          : b.value - a.value,
      )[0];
  }
  function analyze(samples) {
    const findings = [];
    function add(id, title, eligible, hits, evidence, next, priority, process) {
      if (!hits.length) return;
      const repeated =
        hits.length >= 3 &&
        hits.length / eligible.length >= 0.6 &&
        hits.at(-1).elapsed - hits[0].elapsed >= 8;
      const support = repeated
        ? "Repeated evidence"
        : hits.length === 1 && eligible.length >= 3
          ? "Brief spike"
          : "Limited evidence";
      findings.push({
        id,
        title,
        evidence,
        next,
        support,
        repeated,
        process,
        priority: priority + (repeated ? 100 : 0),
        observations: `${hits.length} of ${eligible.length} measured samples`,
      });
    }
    const cpu = samples.filter((s) => known(s.summary?.cpu_percent));
    const busyCpu = cpu.filter((s) => s.summary.cpu_percent >= 85);
    const topCpu = leader(busyCpu, "CPU");
    add(
      "cpu",
      "CPU capacity is heavily used",
      cpu,
      busyCpu,
      `Machine CPU peaked at ${fmt(Math.max(...busyCpu.map((s) => s.summary.cpu_percent)))}.${topCpu ? ` Leading observed CPU consumer: ${topCpu.row.Process} (PID ${topCpu.row.PID}), averaging ${fmt(topCpu.value)} of the machine across ${topCpu.values.length} of these ${busyCpu.length} samples.` : ""}`,
      "Inspect the busiest process and its threads. Check whether its work coincides with the reported slowdown.",
      90,
      topCpu?.row,
    );

    {
      const cores = cpu.filter((s) =>
        s.summary.cores?.some((core) => known(core.percent)),
      );
      const busyCore = cores.filter(
        (s) =>
          s.summary.cpu_percent < 70 &&
          s.summary.cores.some((core) => core.percent >= 90),
      );
      add(
        "core",
        "One logical CPU is heavily used",
        cores,
        busyCore,
        "At least one logical processor reached 90% while machine CPU was below 70% in these samples.",
        "Inspect CPU threads in the busiest processes. A single busy thread may limit responsiveness; per-processor counters alone cannot identify the responsible application.",
        70,
      );
    }

    const memory = samples.filter((s) => known(s.summary?.memory_percent));
    const highMemory = memory.filter((s) => s.summary.memory_percent >= 90);
    const paging = memory.filter((s) => known(s.summary.page_reads_sec));
    const pressure = paging.filter(
      (s) => s.summary.memory_percent >= 90 && s.summary.page_reads_sec >= 10,
    );
    const topMemory = leader(highMemory, "MemoryBytes");
    const memoryEvidence = highMemory.length
      ? `RAM use reached ${fmt(Math.max(...highMemory.map((s) => s.summary.memory_percent)))}.${topMemory ? ` Largest observed resident process: ${topMemory.row.Process} (PID ${topMemory.row.PID}), averaging ${perfBytes(topMemory.value)}; this does not prove it caused the pressure.` : ""}`
      : "";
    if (pressure.length)
      add(
        "memory-paging",
        "Memory pressure coincides with paging reads",
        paging,
        pressure,
        memoryEvidence +
          ` Paging reads reached ${fmt(Math.max(...pressure.map((s) => s.summary.page_reads_sec)), "/s")}.`,
        "Check whether responsiveness improves when unnecessary applications are closed after saving work. Paging reads also include mapped files; use a trace to confirm paging-related stalls.",
        85,
        topMemory?.row,
      );
    else
      add(
        "memory",
        "Little physical memory headroom",
        memory,
        highMemory,
        memoryEvidence,
        "Check paging activity and commit pressure before blaming memory. A large working set alone is not proof of the slowdown.",
        50,
        topMemory?.row,
      );

    const disks = samples.filter((s) => known(diskDelay(s))),
      slowDisks = disks.filter((s) => diskDelay(s) >= 30);
    add(
      "disk",
      "Disk responses are elevated during I/O",
      disks,
      slowDisks,
      `The slowest active disk averaged up to ${fmt(Math.max(...slowDisks.map(diskDelay)), " ms")} per read or write in a sample.`,
      "Compare the sample with opening, saving or paging. Check storage latency and the file location. Process I/O includes network and device traffic, so it cannot identify the responsible disk by itself.",
      80,
    );

    const gpu = samples.filter((s) => known(s.summary?.gpu_percent)),
      busyGpu = gpu.filter((s) => s.summary.gpu_percent >= 90);
    const topGpu = leader(busyGpu, "GPU");
    add(
      "gpu",
      "A GPU engine is heavily used",
      gpu,
      busyGpu,
      `The busiest GPU engine reached ${fmt(Math.max(...busyGpu.map((s) => s.summary.gpu_percent)))}.${topGpu ? ` Leading observed process GPU reading: ${topGpu.row.Process} (PID ${topGpu.row.PID}), averaging ${fmt(topGpu.value)} on its busiest engine across ${topGpu.values.length} of these ${busyGpu.length} samples.` : ""}`,
      "Compare with scrolling, video or redraw delays. Check the active GPU engine and Citrix graphics/session metrics; GPU activity alone does not explain formula calculation time.",
      65,
      topGpu?.row,
    );

    const commit = samples.filter((s) => known(s.summary?.commit_percent));
    add(
      "commit",
      "Committed memory is close to its limit",
      commit,
      commit.filter((s) => s.summary.commit_percent >= 90),
      `Commit use peaked at ${fmt(Math.max(...commit.map((s) => s.summary.commit_percent)))}.`,
      "Inspect private committed memory and its trend. Commit is different from resident RAM; this is capacity pressure, not proof of a memory leak.",
      55,
    );
    return findings.sort((a, b) => b.priority - a.priority);
  }

  function coverage(samples) {
    const count = (test) => samples.filter(test).length;
    return [
      ["CPU", count((s) => known(s.summary?.cpu_percent))],
      ["Memory", count((s) => known(s.summary?.memory_percent))],
      ["Paging", count((s) => known(s.summary?.page_reads_sec))],
      ["Active disk latency", count((s) => known(diskDelay(s)))],
    ];
  }
  const limits =
    "Light capture measures CPU, memory and disk activity. GPU and individual CPU threads are checked only when you choose them. Citrix session latency, file-share response, VDI host contention and exact Excel formulas/add-ins are not measured. No finding means the cause is not established.";
  function probePolicy(data) {
    const s = data.summary || {},
      elapsed = data.collection?.duration_ms || 0;
    const wmiCpu = (data.items || [])
      .filter((row) => /^wmiprvse\.exe$/i.test(row.Process) && known(row.CPU))
      .reduce((sum, row) => sum + Number(row.CPU), 0);
    if (
      wmiCpu >= 5 ||
      (s.logical_processors > 0 && wmiCpu * s.logical_processors >= 50)
    )
      return {
        stop: "Stopped — WMI provider activity is elevated; pause checks to avoid adding load",
      };
    if (elapsed >= 10000)
      return {
        stop: "Stopped — collection is slow; pause checks before trying again",
      };
    return {
      delay:
        elapsed >= 5000 || s.cpu_percent >= 90 || s.memory_percent >= 95
          ? 20000
          : interval,
    };
  }
  let capture = null;
  function compact(data, elapsed) {
    const fields = [
      "PID",
      "Process",
      "CreatedAt",
      "CPU",
      "GPU",
      "MemoryBytes",
      "MemoryPercent",
    ];
    return {
      elapsed,
      checked_at: data.checked_at,
      summary: data.summary || {},
      warnings: data.warnings || [],
      collection: data.collection || {},
      items: (data.items || []).map((row) =>
        Object.fromEntries(fields.map((key) => [key, row[key]])),
      ),
    };
  }
  function stop(reason = "Stopped") {
    if (!capture?.active) return;
    capture.active = false;
    capture.reason = reason;
    window.AtlasActions?.put({id:"diagnostics",title:"Slowness capture",target:capture.computer,state:reason === "Capture complete" ? "complete" : "cancelled",message:reason,view:"admin",expires:Date.now()+10000});
    clearTimeout(capture.nextTimer);
    clearTimeout(capture.deadlineTimer);
    capture.controller?.abort();
    render();
    updatePerformanceControls();
  }
  function clear() {
    stop();
    capture = null;
    $("#slowdownPanel").hidden = true;
    $("#slowdownFindings").replaceChildren();
    $("#diagnoseSlowness").disabled = false;
  }
  async function start() {
    const pc = adminComputer();
    if (!pc) return toast("Enter a computer first");
    invalidateProcesses();
    selectPerformanceView("overview");
    const run = (capture = {
      computer: pc,
      active: true,
      started: performance.now(),
      startedAt: new Date().toISOString(),
      samples: [],
      errors: [],
    });
    window.AtlasActions?.put({id:"diagnostics",title:"Slowness capture",target:pc,state:"running",message:"Collecting samples for up to 60 seconds",view:"admin",controls:[{label:"Stop capture",run:()=>{if(capture===run)stop("Stopped by operator");}}]});
    updatePerformanceControls();
    run.deadlineTimer = setTimeout(() => {
      if (capture === run) stop("Capture complete");
    }, duration);
    render();
    await tick(run);
  }
  async function tick(run) {
    const current = () =>
      capture === run && run.active && run.computer === adminComputer();
    if (!current()) {
      if (capture === run && run.computer !== adminComputer()) clear();
      return;
    }
    run.controller = new AbortController();
    try {
      const data = await api(
        `/api/performance/${encodeURIComponent(run.computer)}?kind=diagnose`,
        { signal: run.controller.signal },
      );
      if (!current()) return;
      if (
        !data.ok ||
        data.computer?.toUpperCase() !== run.computer ||
        !Array.isArray(data.items)
      )
        throw Error("Invalid diagnostic sample; refresh and try again.");
      run.samples.push(compact(data, (performance.now() - run.started) / 1000));
      run.policy = probePolicy(data);
      window.AtlasActions?.put({id:"diagnostics",title:"Slowness capture",target:run.computer,state:"running",message:run.samples.length+" samples collected",view:"admin",controls:[{label:"Stop capture",run:()=>{if(capture===run)stop("Stopped by operator");}}]});
      const expanded = [...$("#adminOverview").querySelectorAll("details")].map(
        (detail) => detail.open,
      );
      acceptPerformanceSnapshot(run.computer, "overview", data);
      [...$("#adminOverview").querySelectorAll("details")].forEach(
        (detail, index) => {
          detail.open = !!expanded[index];
        },
      );
      renderProcesses();
      if (run.policy.stop) return stop(run.policy.stop);
    } catch (error) {
      if (!current() || error.name === "AbortError") return;
      run.errors.push(error.message);
      return stop("Stopped — collection failed; no automatic retries");
    }
    if (!current()) return;
    if (
      run.samples.length >= maxSamples ||
      performance.now() - run.started >= duration
    )
      return stop("Capture complete");
    render();
    // Never overlap requests or keep polling after the bounded capture ends.
    run.nextTimer = setTimeout(() => tick(run), run.policy?.delay || interval);
  }
  function sampleRows(samples) {
    return samples.map((s) => {
      return [
        `+${fmt(s.elapsed, "s")}`,
        fmt(s.summary.cpu_percent),
        fmt(s.summary.memory_percent),
        fmt(s.summary.page_reads_sec, "/s"),
        fmt(diskDelay(s), " ms"),
        fmt(s.collection?.duration_ms / 1000, "s"),
      ];
    });
  }
  function render() {
    if (!capture || capture.computer !== adminComputer()) return;
    const { samples, active, computer, errors } = capture,
      findings = analyze(samples);
    const expanded = $("#slowdownFindings details")?.open;
    $("#slowdownPanel").hidden = false;
    $("#diagnoseSlowness").disabled = active;
    $("#stopDiagnosis").hidden = !active;
    $("#copyDiagnosis").disabled = !samples.length;
    $("#slowdownTitle").textContent = active
      ? "Reproduce the slowdown now"
      : findings[0]?.title || "Cause not established";
    $("#slowdownStatus").textContent =
      `${computer} · ${active ? "Light capture · up to 60 seconds" : capture.reason} · ${samples.length} ${samples.length === 1 ? "sample" : "samples"}${samples.length ? ` · last received +${fmt(samples.at(-1).elapsed, "s")}` : ""}${active && capture.policy?.delay ? ` · resting ${capture.policy.delay / 1000}s between checks` : ""}${errors.length ? ` · ${errors.length} failed requests` : ""}`;
    $("#slowdownFindings").innerHTML =
      `<p class="muted">${active ? "Findings update as samples arrive. Repeated evidence is stronger than a brief spike." : "These are investigation leads from the measured samples. Several bottlenecks can coexist."}</p>
      <div class="slowdown-cards">${findings.map((f, index) => `<article class="slowdown-finding ${f.repeated ? "repeated" : ""}"><div class="slowdown-label"><span>${esc(f.support)}</span><small>${esc(f.observations)}</small></div><h4>${esc(f.title)}</h4><p>${esc(f.evidence)}</p><p class="slowdown-next"><b>Next check</b> ${esc(f.next)}</p>${f.process?.CreatedAt ? `<button data-diagnosis-process="${index}">Inspect ${esc(f.process.Process)} threads</button>` : ""}</article>`).join("") || `<p class="slowdown-empty">${samples.length ? "No clear resource bottleneck in the available samples. If the slowdown happened during capture, check Citrix/session performance, file or data-source delays, then an Excel trace." : active ? "Waiting for the first sample. Atlas checks CPU, RAM and active disks. GPU and individual threads stay on demand." : "No sample was completed. Check access to the machine and try again."}</p>`}</div>
      <p class="slowdown-limits">${esc(limits)}</p>
      <details class="perf-details" ${expanded ? "open" : ""}><summary>Sample timeline & measurement coverage</summary><p class="muted">At most six samples, with at least 10 seconds of rest after each check (20 seconds if busy or responding slowly). Collection stops on failure, a slow response or elevated WMI provider CPU. Samples are separate observations, not a continuous trace. Thresholds are investigation cues: CPU 85%, RAM 90%, paging reads 10/s with high RAM, active disk response 30 ms, or one logical CPU at 90% with machine CPU below 70%. Repeated evidence needs at least three matching observations spanning eight seconds and 60% of measured samples.</p>
      <div class="perf-facts">${coverage(samples)
        .map(
          ([name, count]) =>
            `<span>${esc(name)} <b>${count}/${samples.length} samples</b></span>`,
        )
        .join("")}</div>
      <p class="muted">Missing counters and inactive disks are not treated as zero. Process consumers are selected across CPU, memory and I/O; not every process is retained. Thread counts do not require enumerating individual threads. Monitoring has a cost; this capture cannot guarantee zero impact.</p>
      <div class="tablewrap"><table><thead><tr>${["Received", "CPU", "RAM used", "Paging reads", "Disk response", "Check duration"].map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${sampleRows(
        samples,
      )
        .map(
          (row) =>
            `<tr>${row.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`,
        )
        .join("")}</tbody></table></div>
      ${[...new Set([...errors, ...samples.flatMap((s) => s.warnings)])].map((message) => `<p class="muted">${esc(message)}</p>`).join("")}</details>`;
  }
  function report(pc = adminComputer()) {
    const computer = String(pc || "").trim().toUpperCase();
    if (!computer || !capture ||
      String(capture.computer || "").trim().toUpperCase() !== computer) return "";
    const findings = analyze(capture.samples);
    return [
      `${capture.computer} — Slowness capture`,
      `Started: ${capture.startedAt}`,
      `${capture.active ? "Capture in progress" : capture.reason} · ${capture.samples.length} samples`,
      ...(findings.length
        ? findings.flatMap((f) => [
            `\n${f.title} — ${f.support} (${f.observations})`,
            f.evidence,
            `Next check: ${f.next}`,
          ])
        : ["Cause not established from available samples."]),
      "\nMeasurement coverage: " +
        coverage(capture.samples)
          .map(([name, count]) => `${name} ${count}/${capture.samples.length}`)
          .join(" · "),
      limits,
      "Light capture: at most 6 samples with 10–20 seconds rest between checks. Repeated evidence needs 3 observations spanning 8s and 60% of measured samples; these are investigation cues, not a proven cause.",
      "\nReceived\tCPU\tRAM used\tPaging reads\tActive disk response\tCheck duration",
      ...sampleRows(capture.samples).map((row) => row.join("\t")),
      ...new Set([
        ...capture.errors,
        ...capture.samples.flatMap((s) => s.warnings),
      ]),
    ].join("\n");
  }
  function snapshot(pc) {
    const computer = String(pc || "").trim().toUpperCase();
    const matching = computer && capture &&
      String(capture.computer || "").trim().toUpperCase() === computer;
    const last = matching ? capture.samples.at(-1) : null;
    return {
      computer,
      state: !matching ? "not_scanned" : capture.active ? "running"
        : capture.errors.length ? "failed"
          : capture.reason === "Capture complete" ? "complete" : "stopped",
      startedAt: matching ? capture.startedAt : null,
      checkedAt: typeof last?.checked_at === "string" &&
        Number.isFinite(Date.parse(last.checked_at)) ? last.checked_at : null,
      sampleCount: matching ? capture.samples.length : 0,
      reason: matching ? capture.reason || "" : "",
      report: matching ? report(computer) : "",
    };
  }
  window.AtlasDiagnostics = {
    isRunning: () => !!capture?.active,
    start,
    stop,
    clear,
    analyze,
    report,
    snapshot,
    probePolicy,
  };
  $("#diagnoseSlowness").onclick = start;
  $("#stopDiagnosis").onclick = () => stop();
  $("#copyDiagnosis").onclick = () => copy(report(), "Slowness findings");
  $("#slowdownFindings").addEventListener("click", (event) => {
    const button = event.target.closest("[data-diagnosis-process]");
    if (!button || !capture) return;
    const finding = analyze(capture.samples)[
      Number(button.dataset.diagnosisProcess)
    ];
    const index = S.processes.findIndex(
      (row) => identity(row) === identity(finding?.process || {}),
    );
    if (index < 0)
      return toast(
        "This process is no longer in the latest sample. Refresh processes before inspecting it.",
      );
    showProcessThreads(index);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop("Stopped — tab hidden");
  });
  window.addEventListener("pagehide", () => stop());
})();
