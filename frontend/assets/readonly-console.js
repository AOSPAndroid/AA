/* Presentation mode only. The viewer server independently rejects remote operations. */
(() => {
  if (document.querySelector('meta[name="atlas-mode"]')?.content !== "viewer")
    return;
  const reason =
    "Requires Atlas Admin running from an elevated Windows account. Disabled in Demo and Preview.";
  const blocked = [
    "#deploy",
    "#deployQueue",
    "#deploymentRetry",
    "#deploymentRequeue",
    "[data-deployment-retry]",
    "[data-deployment-queue]",
    "[data-history-retry]",
    "[data-history-queue]",
    "#copyOnly",
    "#execOnly",
    "#bulkStart",
    "#startQueue",
    "#pauseQueue",
    "#cleanupPackages",
    "[data-preflight]",
    "[data-tool]",
    "[data-reboot]",
    "[data-ping]",
    "[data-access]",
    "[data-disk]",
    '#targetActions [data-qol-action="queue"]',
    '#targetActions [data-qol-action="health"]',
    '#targetActions [data-qol-action="cleanup"]',
    "#diagnoseSlowness",
    "#stopDiagnosis",
    "#refreshProcesses",
    "#adminSoftware",
    "#adminServices",
    "#refreshServices",
    "[data-service-start]",
    "[data-service-stop]",
    "[data-service-restart]",
    "#confirmServiceControl",
    "#refreshThreads",
    "#killBtn",
    "[data-quick-kill]",
    "#killMatches",
    "#confirmProcessKill",
    "#refreshSoftware",
    "#checkPackagePresence",
    "#softwarePreview",
    "#softwareExecute",
    "#softwareUninstall",
    "#softwareRepair",
    "#softwareCleanCache",
    "#pxRun",
    "#pxStop",
    "#pxSend",
    "#pxInput",
    "#pxElevated",
    "#pxReconnect",
    "#pxSessions",
    '#machineMenu [data-cmd]:not([data-readonly-allowed]):not([data-cmd="target"]):not([data-cmd="copy"]):not([data-cmd="details"]):not([data-cmd="admin"]):not([data-cmd="report"])',
    "#catalog-edit input",
    "#catalog-edit button",
    'a[href="/manage-database"]',
    "#openDatabase",
    "#refreshDirectory",
  ].join(",");
  // Empty local views: never enumerate a share, query a machine, or expose Admin history.
  const local = {
    "/api/catalog": {
      available: false,
      total: 0,
      truncated: false,
      items: [],
      error:
        "Package share is available in the Windows Admin app. Catalogue browsing is shown here without a connected share.",
    },
    "/api/packages": { packages: [] },
    "/api/scripts": { scripts: [] },
    "/api/history": [],
    "/api/psexec/runs": [],
    "/api/deployments/recent": [],
    "/api/deployments/active": { jobs: [], bulk: [], queues: [], count: 0 },
    "/api/operations/recovery": { targets: [] },
  };
  const stored =
    /^\/api\/(?:package-data|health|capabilities|master\/status|master\/resolve\/[^/]+|search|user\/[^/]+|machine\/[^/]+|directory\/record|vdi-data\/record\/[^/]+|palette\/desks|palette\/person\/[^/]+|desks\/[^/]+\/context)$/;
  function read(url, options = {}) {
    const parsed = new URL(url, location.href);
    if (
      parsed.origin !== location.origin ||
      (options.method || "GET").toUpperCase() !== "GET"
    )
      throw Error(reason);
    if (Object.hasOwn(local, parsed.pathname))
      return { data: JSON.parse(JSON.stringify(local[parsed.pathname])) };
    if (!stored.test(parsed.pathname)) throw Error(reason);
    return null;
  }
  function enforce() {
    for (const el of document.querySelectorAll(blocked)) {
      if ("disabled" in el && !el.disabled) el.disabled = true;
      if (el.getAttribute("aria-disabled") !== "true")
        el.setAttribute("aria-disabled", "true");
      if (el.title !== reason) el.title = reason;
    }
  }
  window.AtlasReadOnly = Object.freeze({ reason, enforce, read });
  document.addEventListener(
    "click",
    (event) => {
      if (event.target.closest(blocked)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true,
  );
  document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("atlas-readonly-console");
    for (const [selector, text] of [
      [
        "#workspace",
        "Browse users and stored machine details. Live health and deployment require elevated Atlas Admin.",
      ],
      [
        "#admin .performance-panel",
        "Explore Overview, CPU, GPU and Memory. Live scans and remote actions are disabled here; run Atlas Admin from an elevated Windows account to use them.",
      ],
      [
        "#bulk",
        "Deployment controls are shown for reference. Executing deployments requires elevated Atlas Admin.",
      ],
      [
        "#history",
        "Deployment history is not shared in this version. View local run history in Atlas Admin.",
      ],
      [
        "#psexec",
        "Browse commands, fill in options and copy the command. Running it and receiving terminal output requires elevated Atlas Admin.",
      ],
      ["#deploymentPanel", "Deployment requires elevated Atlas Admin."],
    ]) {
      const host = document.querySelector(selector);
      if (!host) continue;
      const note = document.createElement("p");
      note.className = "atlas-access-note";
      note.textContent = text;
      host.prepend(note);
    }
    document.querySelector("#autoDeployments").checked = false;
    document.querySelector("#pxHost").textContent =
      "Read-only · remote execution disabled";
    enforce();
    new MutationObserver(enforce).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["disabled"],
    });
  });
})();
