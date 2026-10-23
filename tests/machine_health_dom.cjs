const assert = require("node:assert/strict");
const { fixture } = require("./ui_fixture.cjs");
const settle = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  const requests = [];
  const f = await fixture({
    fetch: (url, options) =>
      new Promise((resolve) => requests.push({ url, options, resolve })),
  });
  const { w } = f,
    A = w.AtlasHealth;
  const host = w.document.getElementById("healthLine");
  const metric = (key) => host.querySelector(`[data-metric="${key}"]`);
  const button = () => host.querySelector("[data-health-refresh]");
  const reply = (request, pc) =>
    request.resolve({
      ok: true,
      json: async () => ({
        computer: pc,
        metric: request.url.split("/").pop(),
        state: "ready",
        data: { available: true },
        checked_at: "2026-09-08T10:00:00Z",
      }),
    });

  A.mount(host, "A");
  await settle();
  assert.equal(
    requests.length,
    0,
    "mounting the widget must not query the target",
  );
  assert.equal(metric("wmi").textContent, "Not scanned");
  assert.equal(button().textContent, "Scan health");
  assert.equal(button().disabled, false);
  assert.equal(host.querySelector('.atlas-health-details').open, false);
  assert.equal(host.querySelectorAll('.atlas-health-mini > span').length, 4);
  assert(A.compact(host, "A").every((item) => item.text === "Not scanned"));

  button().click();
  assert.equal(requests.length, 8, "one click starts one health pass");
  button().click();
  assert.equal(
    requests.length,
    8,
    "the scan button is disabled while checking",
  );
  assert.equal(metric("wmi").textContent, "Loading…");
  A.mount(host, "B");
  assert.equal(
    requests.length,
    8,
    "changing target does not start another pass",
  );
  assert(requests.every((request) => request.options.signal.aborted));
  button().click();
  assert.equal(requests.length, 16);
  requests.slice(0, 8).forEach((request) => reply(request, "A"));
  await settle();
  assert.equal(
    metric("wmi").textContent,
    "Loading…",
    "old responses cannot replace the selected target",
  );
  reply(requests[8], "B");
  await settle();
  assert.equal(metric("wmi").textContent, "Available");
  assert.equal(metric("cpu").textContent, "Loading…");
  requests.slice(9).forEach((request) => reply(request, "B"));
  await settle();
  assert.equal(button().disabled, false);
  assert.equal(button().textContent, "Refresh health");

  A.mount(host, "STALE", () => false);
  button().click();
  await settle();
  const detached = w.document.createElement("div");
  await A.scan(detached, "DETACHED");
  A.specs("B");
  assert(w.document.querySelector(".atlas-spec-dialog").open);
  assert.equal(
    requests.length,
    16,
    "stale targets, detached panels and opening specifications do not scan",
  );
  w.document.querySelector(".atlas-spec-dialog").close();

  const delay = () => new Promise((resolve) => setTimeout(resolve, 300));
  A.quick(host, "QUICK-A");
  A.quick(host, "QUICK-B");
  await delay();
  assert.equal(
    requests.length,
    20,
    "rapid selection skips the previous machine",
  );
  assert.deepEqual(
    requests
      .slice(16)
      .map((r) => r.url.split("/").pop())
      .sort(),
    ["cshare", "ping", "storage", "system"],
  );
  assert(requests.slice(16).every((r) => r.url.includes("/QUICK-B/")));
  assert.equal(metric("cpu").textContent, "Not scanned");
  requests.slice(16).forEach((r) => reply(r, "QUICK-B"));
  await settle();
  assert(host.querySelector('.atlas-health-mini').textContent.includes('Ping Available'));
  assert(!host.querySelector('.atlas-health-mini').textContent.includes('CPU'));
  A.quick(host, "QUICK-B");
  await delay();
  assert.equal(
    requests.length,
    24,
    "clicking the same target refreshes the quick checks",
  );
  requests.slice(20).forEach((r) => reply(r, "QUICK-B"));
  await settle();
  button().click();
  assert.equal(
    requests.length,
    32,
    "full health remains a separate explicit action",
  );
  requests.slice(24).forEach((r) => reply(r, "QUICK-B"));
  await settle();
  A.quick(host, "CANCELLED");
  A.cancel(host);
  await delay();
  assert.equal(
    requests.length,
    32,
    "leaving before the delay makes no request",
  );
  w.AtlasReadOnly = { reason: "Read-only" };
  A.quick(host, "VIEWER");
  await delay();
  assert.equal(
    requests.length,
    32,
    "viewer never performs automatic health checks",
  );

  assert(
    A.badges({ assigned_relationship: 1, logon_relationship: 1 }).includes(
      "Last logged-on",
    ),
  );
  assert(
    A.badges({ assigned_relationship: 1, logon_relationship: 1 }).includes(
      "Assigned",
    ),
  );
  assert(
    A.badges({
      assigned_relationship: 0,
      logon_relationship: 0,
      assigned_to: "other",
    }).includes("Assigned to other"),
  );
  assert(A.badges({ assigned_to: "<unsafe>" }).includes("&lt;unsafe&gt;"));
  assert(
    A.format("cpu", {
      processors: [{ Name: "CPU", LoadPercentage: 0 }],
    }).includes("0%"),
  );
  assert(
    A.format("ram", { usable_kib: null, free_kib: null }).includes(
      "Usage unavailable",
    ),
  );
  assert.equal(f.errors.length, 0, f.errors.join("\n"));
  w.close();
  console.log(
    "PASS: explicit health button, idle specifications, progressive rendering, stale-target isolation, relationships and missing versus zero metrics",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
