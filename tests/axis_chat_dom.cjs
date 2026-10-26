// Exercise the real AA chat component against simulated local HTTP/SSE responses.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { JSDOM, VirtualConsole } = require("jsdom");

const sourcePath = path.join(
  __dirname,
  "..",
  "frontend",
  "assets",
  "axis-chat.js",
);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
async function until(condition, description) {
  for (let attempt = 0; attempt < 150; attempt++) {
    if (condition()) return;
    await tick();
  }
  assert.fail("Timed out: " + description);
}
function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function channel() {
  let controller,
    closed = false;
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(value) {
      controller = value;
    },
  });
  function raw(value) {
    if (!closed)
      controller.enqueue(
        typeof value === "string" ? encoder.encode(value) : value,
      );
  }
  function event(value) {
    raw("data: " + JSON.stringify(value) + "\r\n\r\n");
  }
  function end() {
    if (!closed) {
      closed = true;
      controller.close();
    }
  }
  return {
    response: new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    }),
    raw,
    event,
    end,
    finish() {
      if (!closed) {
        event({ type: "done" });
        end();
      }
    },
  };
}
function fixture(
  t,
  {
    viewer = false,
    route,
    selected = null,
    savedOpen = null,
    page = "atlas-map",
  } = {},
) {
  const consoleErrors = [],
    vc = new VirtualConsole();
  vc.on("jsdomError", (error) => consoleErrors.push(error.message));
  const dom = new JSDOM(
    `<!doctype html><html><head>${viewer ? '<meta name="atlas-mode" content="viewer">' : ""}</head><body class="${page}"><header class="atlas-app-header"><div class="atlas-header-actions"></div></header><main id="map">Map</main></body></html>`,
    {
      url: "http://127.0.0.1:8770/",
      runScripts: "outside-only",
      pretendToBeVisual: true,
      virtualConsole: vc,
    },
  );
  const w = dom.window,
    calls = [],
    streams = [];
  let currentSelection = selected;
  w.ResizeObserver = class {
    observe() {}
  };
  w.matchMedia = () => ({ matches: true });
  w.TextDecoder = TextDecoder;
  w.AbortController = AbortController;
  w.AtlasClient = { sessionToken: async () => "local-admin-token" };
  w.AtlasAxisSelection = () => currentSelection;
  if (savedOpen !== null)
    w.localStorage.setItem("aa-axis-chat-open", savedOpen);
  w.fetch = async (url, options = {}) => {
    const call = {
      url,
      ...options,
      payload: options.body ? JSON.parse(options.body) : null,
    };
    calls.push(call);
    if (url === "/api/axis/status")
      return json({ ready: true, model: "Fixture local model" });
    const response = await route?.(call, api);
    if (response) return response;
    if (url === "/api/axis/chat") {
      const stream = api.stream();
      stream.event({ type: "session", session_id: "session-one" });
      stream.event({ type: "answer", text: "Done." });
      stream.finish();
      return stream.response;
    }
    return json({ ok: true });
  };
  const api = {
    w,
    dom,
    calls,
    $: (selector) => w.document.querySelector(selector),
    stream() {
      const stream = channel();
      streams.push(stream);
      return stream;
    },
    select(value) {
      currentSelection = value;
      w.dispatchEvent(new w.Event("atlas:selection"));
    },
    submit(text) {
      api.$("#axis-chat-input").value = text;
      api
        .$("#axis-chat-form")
        .dispatchEvent(
          new w.Event("submit", { bubbles: true, cancelable: true }),
        );
    },
    idle() {
      return until(
        () => !api.$("#axis-chat-send").disabled,
        "chat to become idle",
      );
    },
    requests(url) {
      return calls.filter((call) => call.url === url);
    },
  };
  w.eval(fs.readFileSync(sourcePath, "utf8"));
  t.after(async () => {
    streams.forEach((stream) => stream.finish());
    await tick();
    w.dispatchEvent(new w.Event("pagehide"));
    w.close();
    assert.deepEqual(
      consoleErrors,
      [],
      "component must not throw browser errors",
    );
  });
  return api;
}

test("Viewer never creates chat controls or requests the Axis backend", async (t) => {
  const f = fixture(t, { viewer: true });
  await tick();
  assert.equal(f.$("#axis-chat"), null);
  assert.equal(f.$("#axis-chat-toggle"), null);
  assert.deepEqual(f.calls, []);
  assert.equal(f.w.localStorage.length, 0);
});

test("Axis can be reopened after the real shared shell organizes header actions", async (t) => {
  for (const shellAlreadyReady of [false, true]) {
    const dom = new JSDOM(
      fs.readFileSync(
        path.join(__dirname, "..", "atlas", "official-index.html"),
        "utf8",
      ),
      {
        url: "http://127.0.0.1:8770/",
        runScripts: "outside-only",
        pretendToBeVisual: true,
      },
    );
    const w = dom.window;
    t.after(() => {
      w.dispatchEvent(new w.Event("pagehide"));
      w.close();
    });
    w.matchMedia = () => ({ matches: true, addEventListener() {} });
    w.ResizeObserver = class {
      observe() {}
    };
    w.AtlasClient = { sessionToken: async () => "local-admin-token" };
    w.fetch = async () => json({ ready: true, model: "Fixture model" });
    w.eval(
      fs.readFileSync(
        path.join(__dirname, "..", "frontend", "assets", "shared-ui.js"),
        "utf8",
      ),
    );
    if (shellAlreadyReady) await tick();
    w.eval(fs.readFileSync(sourcePath, "utf8"));
    await tick();

    const toggle = w.document.querySelector("#axis-chat-toggle");
    const panel = w.document.querySelector("#axis-chat");
    assert(
      w.document.querySelector(".atlas-unified-header"),
      "real shell must initialize",
    );
    assert(
      toggle.closest(".atlas-primary-nav"),
      "chat stays alongside primary navigation",
    );
    assert.equal(
      toggle.closest(".atlas-header-menu"),
      null,
      "chat never enters collapsed More menu",
    );
    w.document.querySelector("#axis-chat-close").click();
    assert.equal(panel.hidden, true);
    toggle.click();
    assert.equal(panel.hidden, false);

    // Prove the real organizer still handles other late toolbar actions.
    const secondary = w.document.createElement("button");
    secondary.textContent = "Secondary action";
    w.document.querySelector(".atlas-header-actions").append(secondary);
    await tick();
    assert(secondary.closest(".atlas-header-menu"));
    assert.equal(toggle.closest(".atlas-header-menu"), null);
  }
});

test("split UTF-8 and CRLF events preserve full visible thinking, tool output and literal unsafe text", async (t) => {
  const unsafe = '<img src=x onerror="window.attacked=true">';
  const toolText =
    "Full tool result\n" +
    "all records remain visible\n".repeat(1000) +
    "<script>window.attacked=true</script>END";
  const f = fixture(t, {
    route(call, api) {
      if (call.url !== "/api/axis/chat") return;
      const stream = api.stream();
      const events = [
        { type: "session", session_id: "session-one" },
        { type: "thinking", text: "Résumé 🤖 " },
        { type: "thinking", text: unsafe },
        {
          type: "tool_start",
          name: "inspect_computer",
          args: { computer: unsafe },
        },
        {
          type: "tool_result",
          name: "inspect_computer",
          result: toolText,
          output_id: "output-one",
          elapsed: 0.2,
        },
        { type: "answer", text: "Result: " },
        { type: "answer", text: unsafe },
        { type: "done", session_id: "session-one" },
      ];
      const bytes = new TextEncoder().encode(
        events
          .map((event) => "data: " + JSON.stringify(event) + "\r\n\r\n")
          .join(""),
      );
      // Single-byte prefix splits a multibyte character, JSON and CR/LF boundaries.
      for (let offset = 0; offset < bytes.length;) {
        const size = offset < 1500 ? 1 : 137;
        stream.raw(bytes.slice(offset, offset + size));
        offset += size;
      }
      stream.end();
      return stream.response;
    },
  });
  f.submit("Show " + unsafe);
  await f.idle();
  assert.equal(
    f.$(".axis-message-thinking .axis-message-content").textContent,
    "Résumé 🤖 " + unsafe,
  );
  assert.equal(f.$(".axis-tool-result").textContent, toolText);
  assert.equal(
    f.$(".axis-message-assistant .axis-message-content").textContent,
    "Result: " + unsafe,
  );
  assert.equal(
    f.$(".axis-message-user .axis-message-content").textContent,
    "Show " + unsafe,
  );
  assert.equal(
    f.$("#axis-chat-messages img, #axis-chat-messages script"),
    null,
  );
  assert.equal(f.w.attacked, undefined);
  assert.equal(
    f.$(
      ".axis-message-thinking [hidden], .axis-message-tool [hidden], #axis-chat-messages details:not([open])",
    ),
    null,
  );
  assert.match(f.$(".axis-tool-saved").textContent, /output-one/);
  assert.equal(f.$("#axis-chat-activity").hidden, true);
  assert.equal(
    f.requests("/api/axis/chat")[0].headers["X-Atlas-Token"],
    "local-admin-token",
  );
});

test("the latest saved chat is shown again on load with decisions as history", async (t) => {
  const unsafe = '<img src=x onerror="window.attacked=true">';
  const f = fixture(t, {
    route(call) {
      if (call.url === "/api/axis/resume")
        return json({
          session_id: "saved-session-0123456789",
          transcript: [
            {
              type: "user",
              text: "Restart " + unsafe,
              context: { desk_id: "D-1", hostname: "PC1" },
            },
            { type: "thinking", text: "Checking" },
            {
              type: "tool_start",
              name: "inspect_computer",
              args: { computer: "PC1" },
            },
            {
              type: "tool_result",
              name: "inspect_computer",
              result: '{"ok":true}',
            },
            { type: "approval", action: "restart PC1", decision: "approved" },
            { type: "approval", action: "restart PC2" },
            { type: "assistant", text: "Restart queued." },
            { type: "error", text: "Later failure" },
          ],
        });
    },
  });
  await until(() => f.$(".axis-message-error"), "saved chat to render");
  const kinds = [...f.w.document.querySelectorAll(".axis-message")].map(
    (node) => node.className.replace("axis-message axis-message-", ""),
  );
  assert.deepEqual(kinds, [
    "user",
    "thinking",
    "tool",
    "approval",
    "approval",
    "assistant",
    "error",
  ]);
  assert.equal(
    f.$(".axis-message-user .axis-message-content").textContent,
    "Restart " + unsafe,
  );
  assert.match(f.$(".axis-attached-record").textContent, /D-1 · PC1/);
  assert.deepEqual(
    [...f.w.document.querySelectorAll(".axis-approval-note")].map(
      (node) => node.textContent,
    ),
    ["Approved.", "No approval submitted."],
  );
  assert.equal(
    f.$(".axis-approval-actions"),
    null,
    "Saved approvals have no controls",
  );
  assert.equal(f.$("#axis-chat-messages img"), null);
  assert.equal(f.w.attacked, undefined);
  assert.equal(
    Object.keys(f.w.localStorage).every((key) =>
      key.startsWith("aa-axis-chat-open"),
    ),
    true,
  );
  assert.equal(
    Object.keys(f.w.localStorage).some((key) =>
      /session|message|transcript/i.test(key),
    ),
    false,
    "Nothing about the chat is kept in the browser",
  );
  f.submit("And PC2?");
  await f.idle();
  assert.equal(
    f.requests("/api/axis/chat")[0].payload.session_id,
    "saved-session-0123456789",
  );
});

test("a chat started before the saved chat arrives is never replaced", async (t) => {
  let release;
  const f = fixture(t, {
    route(call) {
      if (call.url === "/api/axis/resume")
        return new Promise((resolve) => {
          release = () =>
            resolve(
              json({
                session_id: "saved-session-0123456789",
                transcript: [{ type: "assistant", text: "Old" }],
              }),
            );
        });
    },
  });
  await until(() => release, "resume request");
  f.submit("New question");
  await f.idle();
  release();
  await tick();
  await tick();
  assert.equal(
    f.$(".axis-message-assistant .axis-message-content").textContent,
    "Done.",
  );
  f.submit("Follow-up");
  await f.idle();
  assert.equal(
    f.requests("/api/axis/chat")[1].payload.session_id,
    "session-one",
  );
});

test("the memory panel lists facts and forgets one only after confirmation", async (t) => {
  const unsafe = '<img src=x onerror="window.attacked=true">';
  const path = "C:\\AA\\data\\axis\\state\\MEMORY.md";
  const f = fixture(t, {
    route(call) {
      if (call.url === "/api/axis/memory")
        return json({ path, entries: ["Keep this", unsafe] });
      if (call.url === "/api/axis/memory/forget")
        return json({
          path,
          entries: ["Keep this"],
          message: "Forgot: " + call.payload.entry,
        });
    },
  });
  assert.equal(f.$("#axis-chat-memory").hidden, true);
  f.$("#axis-chat-memory-toggle").click();
  await until(
    () =>
      f.w.document.querySelectorAll("#axis-chat-memory-list li").length === 2,
    "memory list",
  );
  assert.equal(
    f.$("#axis-chat-memory-toggle").getAttribute("aria-expanded"),
    "true",
  );
  assert.equal(f.$("#axis-chat-memory-status").textContent, path);
  const forget = () =>
    f.w.document.querySelectorAll("#axis-chat-memory-list button")[1];
  f.w.confirm = () => false;
  forget().click();
  await tick();
  assert.equal(
    f.requests("/api/axis/memory/forget").length,
    0,
    "Cancelling the confirmation changes nothing",
  );
  f.w.confirm = () => true;
  forget().click();
  await until(
    () =>
      f.w.document.querySelectorAll("#axis-chat-memory-list li").length === 1,
    "updated list",
  );
  assert.deepEqual(f.requests("/api/axis/memory/forget")[0].payload, {
    entry: unsafe,
  });
  assert.equal(
    f.requests("/api/axis/memory/forget")[0].headers["X-Atlas-Token"],
    "local-admin-token",
  );
  assert.equal(f.$("#axis-chat-memory img"), null);
  assert.equal(f.w.attacked, undefined);
});

test("console pages attach the current target, a Live Inbox message or a clipboard capture", async (t) => {
  const f = fixture(t, {
    page: "atlas-console",
    savedOpen: "yes",
    selected: { hostname: "PC1", name: "Alex Morgan" },
  });
  Object.assign(f.w.AtlasAxisSelection, {
    button: "Use current target",
    empty: "Select a target PC in Workspace",
  });
  f.select({ hostname: "PC1", name: "Alex Morgan" });
  assert.equal(
    f.$("#axis-chat").hidden,
    true,
    "Closed by default on console pages, whatever the map remembers",
  );
  assert.equal(f.w.localStorage.getItem("aa-axis-chat-open"), "yes");
  assert.equal(
    f.w.localStorage.getItem("aa-axis-chat-open-console"),
    null,
    "Loading a page saves nothing",
  );
  assert.equal(f.$("#axis-chat-use-desk").textContent, "Use current target");
  assert.equal(f.$("#axis-chat-selection").textContent, "PC1 · Alex Morgan");
  f.$("#axis-chat-use-desk").click();
  assert.equal(
    f.$("#axis-chat-attached span").textContent,
    "PC PC1 · Alex Morgan",
  );
  f.submit("Is it online?");
  await f.idle();
  assert.deepEqual(f.requests("/api/axis/chat")[0].payload.context, {
    hostname: "PC1",
    name: "Alex Morgan",
  });
  assert.equal(f.requests("/api/axis/chat")[0].payload.attachment, undefined);
  // Ask Axis from Live Inbox: opens the chat and attaches the message by ID; the prompt is only suggested.
  assert.equal(
    f.w.AxisChat.attach({
      kind: "inbox",
      id: 42,
      label: "VPN cannot connect",
      prompt: "Triage this request.",
    }),
    true,
  );
  assert.equal(f.$("#axis-chat").hidden, false);
  assert.equal(
    f.$("#axis-chat-attached span").textContent,
    "Live Inbox · VPN cannot connect",
  );
  assert.equal(f.$("#axis-chat-input").value, "Triage this request.");
  assert.equal(
    f.requests("/api/axis/chat").length,
    1,
    "Attaching sends nothing",
  );
  f.submit("Triage this request.");
  await f.idle();
  const second = f.requests("/api/axis/chat")[1].payload;
  assert.deepEqual(second.attachment, { kind: "inbox", id: "42" });
  assert.equal(second.context, undefined);
  assert.match(
    [...f.w.document.querySelectorAll(".axis-attached-record")].at(-1)
      .textContent,
    /Live Inbox · VPN cannot connect/,
  );
  assert.equal(
    f.$("#axis-chat-attached").hidden,
    true,
    "An attachment goes with one message",
  );
  // A typed draft is kept; only inbox messages and clipboard captures can be attached this way.
  f.$("#axis-chat-input").value = "My own question";
  f.w.AxisChat.attach({
    kind: "clipboard",
    id: "abc",
    label: "LAPTOP-0001",
    prompt: "What is this?",
  });
  assert.equal(f.$("#axis-chat-input").value, "My own question");
  assert.equal(
    f.$("#axis-chat-attached span").textContent,
    "Clipboard · LAPTOP-0001",
  );
  // An unedited suggestion follows the newest attachment.
  f.$("#axis-chat-input").value = "";
  f.w.AxisChat.attach({
    kind: "clipboard",
    id: "abc",
    prompt: "What is this?",
  });
  f.w.AxisChat.attach({ kind: "inbox", id: 7, prompt: "Triage this request." });
  assert.equal(f.$("#axis-chat-input").value, "Triage this request.");
  assert.equal(f.w.AxisChat.attach({ kind: "file", id: "x" }), false);
});

test("work Axis starts opens in Atlas's own views, and its PCs can be selected", async (t) => {
  const unsafe = '<img src=x onerror="window.attacked=true">';
  const stream = (api) => {
    const s = api.stream();
    s.event({ type: "session", session_id: "session-one" });
    s.event({ type: "tool_start", name: "deploy_package", args: {} });
    s.event({
      type: "tool_result",
      name: "deploy_package",
      result: JSON.stringify({
        jobs: [
          { computer: "PC1", job_id: "a".repeat(32), state: "queued" },
          { computer: unsafe, state: "not started" },
        ],
      }),
    });
    s.event({ type: "tool_start", name: "computer_action", args: {} });
    s.event({
      type: "tool_result",
      name: "computer_action",
      result: JSON.stringify({
        computer: "PC2",
        job_id: "b".repeat(32),
        state: "requested",
      }),
    });
    s.event({ type: "tool_start", name: "find_packages", args: {} });
    s.event({
      type: "tool_result",
      name: "find_packages",
      result: JSON.stringify({ packages: ["PC3"] }),
    });
    s.event({ type: "answer", text: "Queued." });
    s.finish();
    return s.response;
  };
  for (const page of ["atlas-console", "atlas-map"]) {
    const f = fixture(t, {
      page,
      route(call, api) {
        if (call.url === "/api/axis/chat") return stream(api);
      },
    });
    const calls = [];
    f.w.AtlasNavigate = (url) => (calls.push(["navigate", url]), true);
    if (page === "atlas-console") {
      f.w.openDeploymentMonitor = (mode) => calls.push(["deployments", mode]);
      f.w.page = (id) => calls.push(["page", id]);
      f.w.setTarget = (pc) => calls.push(["target", pc]);
      const drawer = f.w.document.createElement("aside");
      drawer.id = "queueDrawer";
      f.w.document.body.append(drawer);
    }
    f.submit("Install Example on PC1, then restart PC2");
    await f.idle();
    const buttons = [
      ...f.w.document.querySelectorAll(".axis-atlas-links button"),
    ];
    assert.deepEqual(
      buttons.map((button) => button.textContent),
      [
        "Show in Deployments",
        "Select PC1 in Workspace",
        "Show reboot monitor",
        "Select PC2 in Workspace",
      ],
      page +
        ": only real jobs and valid PC names become links; package names do not",
    );
    for (const button of buttons) button.click();
    assert.deepEqual(
      calls,
      page === "atlas-console"
        ? [
            ["deployments", "active"],
            ["page", "workspace"],
            ["target", "PC1"],
            ["page", "workspace"],
            ["target", "PC2"],
          ]
        : [
            ["navigate", "/installer?command=active"],
            ["navigate", "/installer?machine=PC1"],
            ["navigate", "/installer?command=queue"],
            ["navigate", "/installer?machine=PC2"],
          ],
    );
    if (page === "atlas-console")
      assert(
        f.w.document.querySelector("#queueDrawer").classList.contains("open"),
      );
    assert.equal(f.$("#axis-chat-messages img"), null);
    assert.equal(f.w.attacked, undefined);
  }
});

test("a finished deployment opens Atlas's recent list, a running one its live list", async (t) => {
  for (const [state, mode] of [
    ["launched", "recent"],
    ["running", "active"],
  ]) {
    const f = fixture(t, {
      page: "atlas-console",
      route(call, api) {
        if (call.url !== "/api/axis/chat") return;
        const s = api.stream();
        s.event({ type: "session", session_id: "session-one" });
        s.event({ type: "tool_start", name: "it_job_status", args: {} });
        s.event({
          type: "tool_result",
          name: "it_job_status",
          result: JSON.stringify({ kind: "deployment", state, target: "PC1" }),
        });
        s.finish();
        return s.response;
      },
    });
    const opened = [];
    f.w.openDeploymentMonitor = (value) => opened.push(value);
    f.submit("How did it go?");
    await f.idle();
    f.w.document.querySelector(".axis-atlas-links button").click();
    assert.deepEqual(opened, [mode], state);
  }
});

test("desks found by Axis open on the map without reloading the chat", async (t) => {
  const unsafe = '<img src=x onerror="window.attacked=true">';
  const f = fixture(t, {
    route(call, api) {
      if (call.url !== "/api/axis/chat") return;
      const stream = api.stream();
      stream.event({ type: "session", session_id: "session-one" });
      stream.event({
        type: "tool_start",
        name: "find_desk",
        args: { query: "marie" },
      });
      stream.event({
        type: "tool_result",
        name: "find_desk",
        result: JSON.stringify({
          items: [
            { desk_id: "02A000101" },
            { desk_id: "02A000101" },
            { desk_id: unsafe },
            { desk_id: 7 },
          ],
        }),
      });
      stream.event({
        type: "tool_start",
        name: "search_atlas",
        args: { query: "marie" },
      });
      stream.event({
        type: "tool_result",
        name: "search_atlas",
        result: JSON.stringify({ items: [{ desk_id: "X" }] }),
      });
      stream.event({ type: "answer", text: "Marie sits at 02A000101." });
      stream.finish();
      return stream.response;
    },
  });
  const opened = [];
  f.w.AtlasSelectDesk = (id) => {
    opened.push(id);
    return id === "02A000101";
  };
  f.submit("Where does Marie sit?");
  await f.idle();
  const buttons = [...f.w.document.querySelectorAll(".axis-desk-links button")];
  assert.deepEqual(
    buttons.map((button) => button.textContent),
    ["Show 02A000101 on map", "Show " + unsafe + " on map"],
    "One button per distinct desk, only for desk lookups, as plain text",
  );
  buttons[0].click();
  buttons[1].click();
  assert.deepEqual(opened, ["02A000101", unsafe]);
  assert.equal(buttons[1].textContent, unsafe + " is not on the current map");
  assert.equal(f.$("#axis-chat-messages img"), null);
  assert.equal(f.w.attacked, undefined);
  assert.equal(
    f.requests("/api/axis/chat").length,
    1,
    "Opening a desk sends nothing to Axis",
  );
});

test("desk context requires explicit attachment, captures that desk, and excludes extra record data", async (t) => {
  const original = {
    desk_id: "D-101",
    name: "Alice Example",
    hostname: "PC-101",
    floor: 4,
    notes: "private note",
    internal_id: 100,
  };
  const f = fixture(t, { selected: original });
  f.submit("List tasks");
  await f.idle();
  assert.equal(f.requests("/api/axis/chat")[0].payload.context, undefined);
  f.$("#axis-chat-use-desk").click();
  f.select({
    desk_id: "D-202",
    name: "Bob Example",
    hostname: "PC-202",
    floor: 5,
  });
  f.submit("Check this machine");
  await f.idle();
  assert.deepEqual(f.requests("/api/axis/chat")[1].payload, {
    message: "Check this machine",
    session_id: "session-one",
    context: {
      desk_id: original.desk_id,
      name: original.name,
      hostname: original.hostname,
      floor: String(original.floor),
    },
  });
  assert.match(f.$(".axis-attached-record").textContent, /D-101.*PC-101/);
  assert.equal(f.$("#axis-chat-attached").hidden, true);
  f.$("#axis-chat-use-desk").click();
  f.$("#axis-chat-attached button").click();
  f.submit("General question");
  await f.idle();
  assert.equal(f.requests("/api/axis/chat")[2].payload.context, undefined);
  assert.equal(
    Object.keys(f.w.localStorage).every((key) =>
      key.startsWith("aa-axis-chat-open"),
    ),
    true,
    "Only whether the chat is open is kept in the browser",
  );
  assert.equal(f.w.sessionStorage.length, 0);
});

test("approval and Stop bind to the active session, submit once, and retain the full action", async (t) => {
  let stream, finishApproval;
  const f = fixture(t, {
    route(call, api) {
      if (call.url === "/api/axis/chat") {
        stream = api.stream();
        stream.event({ type: "session", session_id: "approval-session" });
        stream.event({
          type: "approval",
          id: "approval-123",
          action:
            "Install package P on PC-101\nFull command: <literal command>",
        });
        return stream.response;
      }
      if (call.url === "/api/axis/approve")
        return new Promise((resolve) => {
          finishApproval = () => resolve(json({ approved: true }));
        });
      if (call.url === "/api/axis/cancel") {
        stream.event({
          type: "notice",
          text: "Stopped. Background job status remains available.",
        });
        stream.event({
          type: "done",
          cancelled: true,
          session_id: "approval-session",
        });
        stream.end();
        return json({ cancelled: true });
      }
    },
  });
  f.submit("Install P on PC-101");
  await until(() => f.$(".axis-approve"), "approval prompt");
  assert.equal(f.$("#axis-chat-reset").disabled, true);
  assert.equal(f.$("#axis-chat-send").disabled, true);
  assert.match(
    f.$(".axis-message-approval .axis-message-content").textContent,
    /Full command: <literal command>/,
  );
  const allow = f.$(".axis-approve"),
    deny = f.$(".axis-approval-actions button");
  allow.click();
  allow.click();
  deny.click();
  await until(() => finishApproval, "approval request");
  assert.equal(f.requests("/api/axis/approve").length, 1);
  assert.deepEqual(f.requests("/api/axis/approve")[0].payload, {
    session_id: "approval-session",
    approval_id: "approval-123",
    approved: true,
  });
  finishApproval();
  await until(
    () => /Approved/.test(f.$(".axis-approval-note").textContent),
    "approval acknowledgement",
  );
  f.$("#axis-chat-stop").click();
  await f.idle();
  assert.deepEqual(f.requests("/api/axis/cancel")[0].payload, {
    session_id: "approval-session",
  });
  allow.click();
  deny.click();
  assert.equal(f.requests("/api/axis/approve").length, 1);
  assert.equal(f.$("#axis-chat-stop").hidden, true);
});

test("declining an action sends false; pending approvals cannot execute after disconnect", async (t) => {
  let stream;
  const f = fixture(t, {
    route(call, api) {
      if (call.url === "/api/axis/chat") {
        stream = api.stream();
        stream.event({ type: "session", session_id: "deny-session" });
        stream.event({
          type: "approval",
          id: "deny-me",
          action: "Restart PC-404",
        });
        return stream.response;
      }
    },
  });
  f.submit("Restart");
  await until(() => f.$(".axis-approval-actions button"), "deny control");
  f.$(".axis-approval-actions button").click();
  await until(
    () => /Declined/.test(f.$(".axis-approval-note").textContent),
    "decline acknowledgement",
  );
  assert.deepEqual(f.requests("/api/axis/approve")[0].payload, {
    session_id: "deny-session",
    approval_id: "deny-me",
    approved: false,
  });
  stream.event({
    type: "approval",
    id: "still-pending",
    action: "A second action",
  });
  await until(
    () => f.w.document.querySelectorAll(".axis-message-approval").length === 2,
    "second approval",
  );
  stream.end();
  await f.idle();
  const pending = f.w.document.querySelectorAll(".axis-message-approval")[1];
  assert(
    [...pending.querySelectorAll("button")].every((button) => button.disabled),
  );
  pending.querySelector(".axis-approve").click();
  assert.equal(f.requests("/api/axis/approve").length, 1);
  assert.match(
    f.$(".axis-message-error").textContent,
    /connection ended.*Check job status/i,
  );
});

test("reading earlier history is not interrupted when new thinking streams in", async (t) => {
  let stream;
  const f = fixture(t, {
    route(call, api) {
      if (call.url !== "/api/axis/chat") return;
      stream = api.stream();
      stream.event({ type: "session", session_id: "scroll-session" });
      stream.event({ type: "thinking", text: "First thought. " });
      return stream.response;
    },
  });
  const messages = f.$("#axis-chat-messages");
  Object.defineProperties(messages, {
    scrollHeight: { value: 2000, configurable: true },
    clientHeight: { value: 400, configurable: true },
  });
  f.submit("Work");
  await until(() => f.$(".axis-message-thinking"), "thinking");
  await new Promise((resolve) => setTimeout(resolve, 25));
  messages.scrollTop = 100;
  messages.dispatchEvent(new f.w.Event("scroll"));
  stream.event({ type: "thinking", text: "Second thought." });
  await until(
    () => f.$(".axis-message-thinking").textContent.includes("Second thought."),
    "second thinking chunk",
  );
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(messages.scrollTop, 100);
  stream.finish();
  await f.idle();
});

test("Enter submits, Shift+Enter and composition do not, and Escape returns focus to the map toggle", async (t) => {
  const f = fixture(t, { savedOpen: "no" });
  assert.equal(f.$("#axis-chat").hidden, true);
  f.$("#axis-chat-toggle").click();
  assert.equal(f.$("#axis-chat").hidden, false);
  assert.equal(f.$("#axis-chat-toggle").getAttribute("aria-expanded"), "true");
  const input = f.$("#axis-chat-input");
  input.value = "Line one";
  input.dispatchEvent(
    new f.w.KeyboardEvent("keydown", {
      key: "Enter",
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    }),
  );
  input.dispatchEvent(
    new f.w.KeyboardEvent("keydown", {
      key: "Enter",
      isComposing: true,
      bubbles: true,
      cancelable: true,
    }),
  );
  await tick();
  assert.equal(f.requests("/api/axis/chat").length, 0);
  input.dispatchEvent(
    new f.w.KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    }),
  );
  await f.idle();
  assert.equal(f.requests("/api/axis/chat").length, 1);
  input.dispatchEvent(
    new f.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  );
  assert.equal(f.$("#axis-chat").hidden, true);
  assert.equal(f.$("#axis-chat-toggle").getAttribute("aria-expanded"), "false");
  assert.equal(f.w.document.activeElement, f.$("#axis-chat-toggle"));
  assert.equal(f.w.localStorage.getItem("aa-axis-chat-open"), "no");
});

test("a truncated SSE event reports failure and releases composer controls", async (t) => {
  const f = fixture(t, {
    route(call, api) {
      if (call.url !== "/api/axis/chat") return;
      const stream = api.stream();
      stream.event({ type: "session", session_id: "broken-session" });
      stream.raw('data: {"type":"answer","text":"partial');
      stream.end();
      return stream.response;
    },
  });
  f.submit("Check status");
  await f.idle();
  assert.match(
    f.$(".axis-message-error").textContent,
    /ended before the last event completed/i,
  );
  assert.equal(f.$("#axis-chat-reset").disabled, false);
  assert.equal(f.$("#axis-chat-activity").hidden, true);
});

test("an expired session preserves the draft and attachment without automatically retrying an action", async (t) => {
  let chatCount = 0;
  const desk = {
    desk_id: "D-404",
    name: "Example",
    hostname: "PC-404",
    floor: 4,
  };
  const f = fixture(t, {
    selected: desk,
    route(call) {
      if (call.url === "/api/axis/chat" && ++chatCount === 2)
        return json(
          {
            detail: "This conversation has expired. Start a new conversation.",
          },
          404,
        );
    },
  });
  f.submit("Hello");
  await f.idle();
  f.$("#axis-chat-use-desk").click();
  f.submit("Install P on this machine");
  await f.idle();
  assert.equal(
    f.requests("/api/axis/chat").length,
    2,
    "a change must not silently retry",
  );
  assert.equal(f.$("#axis-chat-input").value, "Install P on this machine");
  assert.equal(f.$("#axis-chat-attached").hidden, false);
  assert.match(f.$(".axis-message-error").textContent, /expired/);
  f.$("#axis-chat-form").dispatchEvent(
    new f.w.Event("submit", { bubbles: true, cancelable: true }),
  );
  await f.idle();
  assert.equal(f.requests("/api/axis/chat")[2].payload.session_id, undefined);
  assert.equal(
    f.requests("/api/axis/chat")[2].payload.context.hostname,
    "PC-404",
  );
});

test("reset blocks concurrent sends and can clear an expired conversation", async (t) => {
  let finishReset;
  const f = fixture(t, {
    route(call) {
      if (call.url === "/api/axis/reset")
        return new Promise((resolve) => {
          finishReset = () => resolve(json({ detail: "Unknown session" }, 404));
        });
    },
  });
  f.submit("Old conversation");
  await f.idle();
  f.$("#axis-chat-reset").click();
  await until(() => finishReset, "reset request");
  f.submit("A new action");
  await tick();
  assert.equal(
    f.requests("/api/axis/chat").length,
    1,
    "reset and chat must not overlap",
  );
  assert.equal(f.$("#axis-chat-send").disabled, true);
  assert.deepEqual(f.requests("/api/axis/reset")[0].payload, {
    session_id: "session-one",
  });
  finishReset();
  await f.idle();
  assert.equal(f.$(".axis-message-user"), null);
  assert.match(f.$("#axis-chat-messages").textContent, /New conversation/);
  f.submit("A new action");
  await f.idle();
  assert.equal(f.requests("/api/axis/chat")[1].payload.session_id, undefined);
});
