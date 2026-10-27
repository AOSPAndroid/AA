/* Demo presentation for the map and console: the same pages as Admin, with changes, live checks and
   Axis greyed out rather than hidden. The viewer server independently rejects remote operations. */
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
    'a[href^="/manage-database"]',
    "#openDatabase",
    "#refreshDirectory",
    '[data-page="clipboard"]',
    "#clipboardToggle",
    "#axis-chat-toggle",
    // Map header, desk inspector and desk menu.
    "#ops-audit",
    "#ops-settings",
    "#ops-history",
    "#import",
    "#ops-import-atlas",
    "#backup-db",
    "#add",
    "#map-previous",
    "#previous-person",
    "#record-form button",
    "[data-link-user]",
    "#ops-preview",
    "#ops-deploy",
    "[data-health-refresh]",
    ".desk-menu [data-action]",
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
    /^\/api\/(?:package-data|health|capabilities|master\/status|master\/resolve\/[^/]+|search|user\/[^/]+|machine\/[^/]+|directory\/record|vdi-data\/record\/[^/]+|palette\/desks|palette\/person\/[^/]+|desks\/[^/]+\/context|script-library)$/;
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
    const autoDeployments = document.querySelector("#autoDeployments");
    if (autoDeployments) autoDeployments.checked = false;
    const pxHost = document.querySelector("#pxHost");
    if (pxHost) pxHost.textContent = "Read-only · remote execution disabled";
    enforce();
    // Map name tags move constantly and never hold a blocked control.
    new MutationObserver((records) => {
      if (records.some((r) => !r.target.closest?.("#map-labels, #label-lines")))
        enforce();
    }).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["disabled"],
    });
  });
})();
