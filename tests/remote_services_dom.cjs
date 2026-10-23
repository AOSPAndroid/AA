const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { fixture, root } = require("./ui_fixture.cjs");
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const identity = (letter) => letter.repeat(64);
function record(name, changes = {}) {
  const state = changes.state || "Running",
    stopped = state === "Stopped",
    running = ["Running", "Paused"].includes(state);
  return {
    name,
    display_name: `Display ${name}`,
    state,
    start_mode: "Auto",
    pid: stopped ? 0 : 1234,
    can_start: stopped,
    start_reason: stopped ? "" : "Service is not stopped",
    can_stop: running,
    stop_reason: running ? "" : "Service is not running or paused",
    can_restart: state === "Running",
    restart_reason: state === "Running" ? "" : "Service is not running",
    identity: identity("a"),
    ...changes,
  };
}
const outcome = (computer, item, value, message) => ({
  computer,
  name: item.name,
  outcome: value,
  state: item.state,
  item,
  message,
});
(async () => {
  const requests = [],
    f = await fixture(),
    { w, run } = f;
  const get = (id) => w.document.getElementById(id);
  const button = (action, index = 0) =>
    get("servicesBody").querySelector(`[data-service-${action}="${index}"]`);
  const actionButtons = (index) => [
    ...button("stop", index)
      .closest("tr")
      .querySelectorAll("[data-service-action]"),
  ];
  const assertState = (state, pid, index = 0) => {
    const cells = button("stop", index).closest("tr").cells;
    assert.equal(cells[1].textContent, state);
    assert.equal(cells[3].textContent, String(pid));
  };
  const changeTarget = (pc) => {
    get("adminPc").value = pc;
    get("adminPc").dispatchEvent(new w.Event("input"));
  };
  const filter = (value) => {
    get("servicesFilter").value = value;
    get("servicesFilter").dispatchEvent(new w.Event("input"));
  };
  w.AtlasClient.request = (url, options) =>
    new Promise((resolve, reject) =>
      requests.push({
        url,
        payload: JSON.parse(options.body),
        resolve,
        reject,
      }),
    );
  run(
    fs.readFileSync(
      path.join(root, "frontend/assets/remote-services.js"),
      "utf8",
    ),
  );
  await settle();
  const beginList = (id = "refreshServices") => {
    const previous = requests.length;
    get(id).click();
    assert.equal(requests.length, previous + 1);
    assert.equal(requests.at(-1).url, "/api/services");
    return requests.at(-1);
  };
  const list = async (items, pc = get("adminPc").value.toUpperCase()) => {
    const request = beginList();
    request.resolve({ computer: pc, items });
    await settle();
    return request;
  };
  const invoke = async (action, index = 0) => {
    const previous = requests.length;
    button(action, index).click();
    if (action !== "start") {
      assert(get("serviceControlDialog").open);
      assert.equal(requests.length, previous);
      assert.equal(
        get("serviceControlTitle").textContent,
        `${action === "stop" ? "Stop" : "Restart"} service?`,
      );
      assert.equal(w.document.activeElement.id, "cancelServiceControl");
      get("confirmServiceControl").click();
      get("confirmServiceControl").click();
    } else
      assert(
        !get("serviceControlDialog").open,
        "Start executes without a second confirmation",
      );
    await settle();
    assert.equal(requests.length, previous + 1);
    assert.equal(requests.at(-1).url, `/api/services/${action}`);
    return requests.at(-1);
  };

  assert(get("adminServices").disabled);
  assert.equal(requests.length, 0);
  changeTarget("testpc");
  assert(!get("adminServices").disabled);
  assert.equal(requests.length, 0, "Choosing a target never queries services");
  const initial = beginList("adminServices");
  get("adminServices").click();
  assert.equal(requests.length, 1);
  assert(get("servicesDialog").open && get("refreshServices").disabled);
  assert.deepEqual(initial.payload, { computer: "TESTPC" });
  initial.resolve({
    computer: "TESTPC",
    items: [
      record("A180"),
      record("OpenFin"),
      record("RpcSs", {
        can_start: false,
        start_reason: "Required for Windows",
        can_stop: false,
        stop_reason: "Required for Windows",
        can_restart: false,
        restart_reason: "Required for Windows",
      }),
      record("<img src=x onerror=bad()>"),
    ],
  });
  await settle();
  assert.equal(get("servicesCount").textContent, "4 of 4 services");
  assert.equal(
    get("servicesBody").querySelectorAll("img").length,
    0,
    "Service metadata is text",
  );
  assert.equal(
    get("servicesBody").querySelectorAll(".services-row-actions").length,
    4,
  );
  for (const action of ["start", "stop", "restart"])
    assert(
      button(action, 2).disabled &&
        button(action, 2).title.includes("Required for Windows"),
    );
  assert(button("start").disabled);
  assert(!button("stop").disabled && !button("restart").disabled);
  const unavailable = requests.length;
  button("start").disabled = false;
  button("start").click();
  for (const action of ["start", "stop", "restart"]) {
    button(action, 2).disabled = false;
    button(action, 2).click();
  }
  await settle();
  assert.equal(
    requests.length,
    unavailable,
    "Unavailable capabilities cannot be forced through disabled buttons",
  );
  button("stop", 3).click();
  assert(
    get("serviceControlQuestion").textContent.includes(
      "<img src=x onerror=bad()>",
    ),
  );
  assert(
    !get("serviceControlDialog").querySelector("img"),
    "Confirmation metadata is also safe text",
  );
  get("cancelServiceControl").click();
  await settle();
  filter("a180");
  assert.equal(get("servicesCount").textContent, "1 of 4 services");
  button("stop").focus();
  button("stop").click();
  assert(get("serviceControlDialog").open);
  assert.equal(get("serviceControlTitle").textContent, "Stop service?");
  assert(
    get("serviceControlQuestion").textContent.includes("A180") &&
      get("serviceControlQuestion").textContent.includes("TESTPC"),
  );
  assert.equal(get("confirmServiceControl").textContent, "Stop service");
  assert(get("confirmServiceControl").classList.contains("danger"));
  assert.equal(w.document.activeElement.id, "cancelServiceControl");
  assert(get("adminServices").disabled && get("refreshServices").disabled);
  assert(actionButtons(0).every((item) => item.disabled));
  get("cancelServiceControl").click();
  await settle();
  assert.equal(requests.length, 1);
  assert.equal(
    w.document.activeElement,
    button("stop"),
    "Cancel restores the same available service action",
  );

  // The selected service/action is immutable even when the visible filter changes.
  button("stop").click();
  filter("openfin");
  get("confirmServiceControl").click();
  get("confirmServiceControl").click();
  await settle();
  const stop = requests.at(-1);
  assert.equal(requests.length, 2);
  assert.equal(stop.url, "/api/services/stop");
  assert.deepEqual(stop.payload, {
    computer: "TESTPC",
    name: "A180",
    expected_identity: identity("a"),
  });
  assert(get("refreshServices").disabled && button("stop", 1).disabled);
  filter("");
  stop.resolve(
    outcome(
      "TESTPC",
      record("A180", { state: "Stopped", display_name: "Refreshed A180" }),
      "stopped",
      "Service stopped.",
    ),
  );
  await settle();
  assertState("Stopped", 0);
  assert(!button("start").disabled);
  assert(button("stop").disabled && button("restart").disabled);
  assert(get("servicesStatus").textContent.includes("Service stopped."));
  assert(
    button("start").getAttribute("aria-label").includes("Refreshed A180"),
    "A verified outcome applies the fresh item",
  );
  assert.equal(
    w.document.activeElement,
    button("start"),
    "Stop restores focus to the newly available Start action",
  );
  button("start").focus();
  const start = await invoke("start");
  button("start").disabled = false;
  button("start").click();
  assert.deepEqual(start.payload, {
    computer: "TESTPC",
    name: "A180",
    expected_identity: identity("a"),
  });
  assert.equal(
    requests.length,
    3,
    "Repeated Start activation cannot duplicate a mutation",
  );
  assert(
    get("adminServices").disabled &&
      get("refreshServices").disabled &&
      actionButtons(1).every((item) => item.disabled),
  );
  start.resolve(
    outcome(
      "TESTPC",
      record("A180", { pid: 9876 }),
      "started",
      "Service started.",
    ),
  );
  await settle();
  assertState("Running", 9876);
  assert(button("start").disabled);
  assert(!button("stop").disabled && !button("restart").disabled);
  assert.equal(
    w.document.activeElement,
    button("stop"),
    "Start restores focus to an available action in the same row",
  );
  button("restart").click();
  assert(get("serviceControlWarning").textContent.includes("interrupted"));
  assert.equal(get("confirmServiceControl").textContent, "Restart service");
  get("cancelServiceControl").click();
  await settle();
  const restart = await invoke("restart");
  assert.deepEqual(restart.payload, {
    computer: "TESTPC",
    name: "A180",
    expected_identity: identity("a"),
  });
  restart.resolve(
    outcome(
      "TESTPC",
      record("A180", { pid: 9988 }),
      "restarted",
      "Service restarted.",
    ),
  );
  await settle();
  assertState("Running", 9988);
  assert(!button("stop").disabled && !button("restart").disabled);
  assert.equal(
    w.document.activeElement,
    button("restart"),
    "Restart retains the same available action after row replacement",
  );

  // Idempotent terminal results carry verified state and fresh capabilities too.
  await list([record("A180", { state: "Stopped", identity: identity("b") })]);
  const alreadyRunning = await invoke("start");
  assert.equal(alreadyRunning.payload.expected_identity, identity("b"));
  alreadyRunning.resolve(
    outcome(
      "TESTPC",
      record("A180", { identity: identity("b"), pid: 455 }),
      "already_running",
      "Already running.",
    ),
  );
  await settle();
  assertState("Running", 455);
  assert(!button("restart").disabled);
  const alreadyStopped = await invoke("stop");
  alreadyStopped.resolve(
    outcome(
      "TESTPC",
      record("A180", { identity: identity("b"), state: "Stopped" }),
      "already_stopped",
      "Already stopped.",
    ),
  );
  await settle();
  assertState("Stopped", 0);
  assert(!button("start").disabled);

  await list([record("A180", { state: "Stopped" })]);
  button("start").focus();
  const filterFocusedStart = await invoke("start");
  get("servicesFilter").focus();
  filterFocusedStart.resolve(
    outcome(
      "TESTPC",
      record("A180", { pid: 225 }),
      "started",
      "Service started.",
    ),
  );
  await settle();
  assert.equal(
    w.document.activeElement,
    get("servicesFilter"),
    "Completion never steals focus after the user moves to the filter",
  );

  // Restart failures retain their observed final state/PID and require Refresh.
  for (const [state, pid] of [
    ["Stopped", 0],
    ["Start Pending", 112],
  ]) {
    await list([record("A180")]);
    const failed = await invoke("restart"),
      previous = requests.length;
    failed.resolve(
      outcome(
        "TESTPC",
        record("A180", { state, pid }),
        "failed",
        "Restart failed after stop: access denied.",
      ),
    );
    await settle();
    assertState(state, pid);
    assert(actionButtons(0).every((item) => item.disabled));
    assert(
      get("servicesStatus").textContent.includes("access denied") &&
        get("servicesStatus").textContent.includes("Refresh"),
    );
    assert(!get("servicesStatus").textContent.includes("Service restarted."));
    assert.equal(
      w.document.activeElement,
      get("refreshServices"),
      "An unverified operation leaves focus on its required Refresh action",
    );
    for (const action of ["start", "stop", "restart"]) {
      button(action).disabled = false;
      button(action).click();
    }
    await settle();
    assert.equal(
      requests.length,
      previous,
      "An unverified failure never retries or permits a forced control",
    );
  }
  await list([record("A180")]);
  const pendingStop = await invoke("stop");
  pendingStop.resolve(
    outcome(
      "TESTPC",
      record("A180", { state: "Stop Pending", pid: 1234 }),
      "pending",
      "Stop was accepted but not verified.",
    ),
  );
  await settle();
  assertState("Stop Pending", 1234);
  assert(actionButtons(0).every((item) => item.disabled));
  await list([record("A180")]);
  const denied = await invoke("stop");
  denied.reject(Error("Access denied"));
  await settle();
  assertState("Running", 1234);
  assert(actionButtons(0).every((item) => item.disabled));
  assert(get("servicesStatus").textContent.includes("Access denied"));

  // Target, exact name, configuration identity, state, PID and capabilities are
  // trust boundaries; an invalid response cannot turn a stale row into a target.
  const invalidResults = [
    { computer: "OTHERPC" },
    { name: "OtherService" },
    { item: null },
    { item: record("A180", { identity: identity("c"), pid: 444 }) },
    { item: record("OtherService", { pid: 444 }) },
    { item: record("A180", { state: "Stopped", pid: 0 }) },
    { item: record("A180", { pid: -1 }) },
    { item: record("A180", { can_restart: "true", pid: 444 }) },
  ];
  for (const changes of invalidResults) {
    await list([record("A180", { state: "Stopped" })]);
    const request = await invoke("start");
    request.resolve({
      ...outcome(
        "TESTPC",
        record("A180", { pid: 444 }),
        "started",
        "Windows response requires verification.",
      ),
      ...changes,
    });
    await settle();
    assertState("Stopped", 0);
    assert(actionButtons(0).every((item) => item.disabled));
    assert(get("servicesStatus").textContent.includes("Refresh"));
  }

  // A late list response cannot overwrite a newer target or release its busy UI.
  const oldList = beginList();
  changeTarget("PC2");
  const newList = beginList();
  oldList.resolve({ computer: "TESTPC", items: [record("OldService")] });
  await settle();
  assert(!get("servicesBody").textContent.includes("OldService"));
  assert(get("refreshServices").disabled);
  newList.resolve({ computer: "PC2", items: [record("TestService")] });
  await settle();
  assert.equal(get("servicesTarget").textContent, "PC2");
  button("restart").click();
  changeTarget("PC3");
  await settle();
  assert(!get("serviceControlDialog").open);
  const canceled = requests.length;
  get("confirmServiceControl").disabled = false;
  get("confirmServiceControl").click();
  await settle();
  assert.equal(
    requests.length,
    canceled,
    "Changing target cancels the old confirmation",
  );
  await list([record("TestService")]);
  button("stop").click();
  get("confirmServiceControl").click();
  changeTarget("PC4");
  await settle();
  assert.equal(
    requests.length,
    canceled + 1,
    "A target switch before the accepted dialog resumes cannot issue control",
  );
  await list([record("TestService", { state: "Stopped" })]);
  const oldStart = await invoke("start");
  changeTarget("PC5");
  get("refreshServices").disabled = false;
  get("refreshServices").click();
  assert.equal(
    requests.at(-1),
    oldStart,
    "An in-flight mutation keeps new control/list requests disabled",
  );
  oldStart.resolve(
    outcome("PC4", record("TestService"), "started", "Old target started."),
  );
  await settle();
  assert(!get("servicesStatus").textContent.includes("Old target"));
  assert(!get("servicesBody").textContent.includes("TestService"));
  assert(!get("refreshServices").disabled);
  await list([record("NewService", { state: "Stopped" })]);
  const closedStart = await invoke("start");
  get("closeServices").click();
  get("adminPc").focus();
  closedStart.resolve(
    outcome("PC5", record("NewService"), "started", "Closed view started."),
  );
  await settle();
  assert(!get("servicesDialog").open);
  assert(!get("servicesBody").textContent.includes("NewService"));
  assert(!get("servicesStatus").textContent.includes("Closed view"));
  assert.equal(
    w.document.activeElement,
    get("adminPc"),
    "A closed-view response cannot restore service-control focus",
  );
  const closedList = beginList("adminServices");
  get("closeServices").click();
  closedList.resolve({ computer: "PC5", items: [record("ClosedResponse")] });
  await settle();
  assert(
    !get("servicesDialog").open &&
      !get("servicesBody").textContent.includes("ClosedResponse"),
  );
  const wrongList = beginList("adminServices");
  wrongList.resolve({ computer: "WRONGPC", items: [record("WrongService")] });
  await settle();
  assert(!get("servicesBody").textContent.includes("WrongService"));
  assert(get("servicesStatus").textContent.includes("did not match"));

  // All action and listing paths enforce read-only independently of disabled UI.
  await list([
    record("RunningService"),
    record("StoppedService", { state: "Stopped" }),
  ]);
  button("stop").click();
  w.AtlasReadOnly = { reason: "Read-only" };
  const readOnlyCount = requests.length;
  get("confirmServiceControl").disabled = false;
  get("confirmServiceControl").click();
  await settle();
  assert.equal(requests.length, readOnlyCount);
  get("cancelServiceControl").click();
  await settle();
  for (const id of ["adminServices", "refreshServices"]) {
    get(id).disabled = false;
    get(id).click();
  }
  for (const item of get("servicesBody").querySelectorAll(
    "[data-service-action]",
  )) {
    item.disabled = false;
    item.click();
  }
  await settle();
  assert.equal(
    requests.length,
    readOnlyCount,
    "Read-only cannot list, start, stop or restart through forced controls",
  );
  filter("");
  assert(
    [...get("servicesBody").querySelectorAll("[data-service-action]")].every(
      (item) => item.disabled,
    ),
  );
  assert(
    requests.every((item) =>
      [
        "/api/services",
        "/api/services/start",
        "/api/services/stop",
        "/api/services/restart",
      ].includes(item.url),
    ),
  );
  assert.equal(f.errors.length, 0, f.errors.join("\n"));
  w.close();
  console.log(
    "PASS: exact verified service Start/Stop/Restart lifecycle, confirmations, safe text, observed failure state/PID, fresh capabilities, no duplicate/background controls, stale target/modal isolation and forced read-only guards.",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
