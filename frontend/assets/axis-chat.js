/* AA's local Axis panel. No browser storage of messages, records or approvals:
   the local Admin backend keeps recent chats and returns the latest on load. */
(() => {
  "use strict";
  if (document.querySelector('meta[name="atlas-mode"]')?.content === "viewer")
    return;
  const header = document.querySelector(".atlas-app-header");
  const actions = header?.querySelector(".atlas-header-actions");
  if (!actions || !window.AtlasClient) return;

  const button = document.createElement("button");
  button.id = "axis-chat-toggle";
  button.type = "button";
  button.textContent = "Axis chat";
  button.setAttribute("aria-controls", "axis-chat");
  // The shared shell moves secondary actions into More, so chat lives in the
  // primary navigation and remains reachable after its panel is closed.
  (header.querySelector(".atlas-primary-nav") || header).append(button);
  header.classList.add("axis-chat-header");
  const panel = document.createElement("aside");
  panel.id = "axis-chat";
  panel.className = "axis-chat";
  panel.setAttribute("aria-labelledby", "axis-chat-title");
  panel.innerHTML = `
    <div class="axis-chat-heading">
      <div><strong id="axis-chat-title">AXIS</strong><span class="axis-chat-subtitle">Chat</span></div>
      <div class="axis-chat-heading-actions">
        <button type="button" id="axis-chat-memory-toggle" aria-controls="axis-chat-memory" aria-expanded="false" title="Facts Axis remembers between chats">Memory</button>
        <button type="button" id="axis-chat-reset" title="Start a new conversation">New chat</button>
        <button type="button" id="axis-chat-close" aria-label="Close Axis chat and return to Atlas" title="Close Axis and show the desk inspector">Inspector <span aria-hidden="true">×</span></button>
      </div>
    </div>
    <div class="axis-chat-connection"><span id="axis-chat-model">Checking model…</span><button id="axis-chat-refresh" type="button" title="Refresh model connection" aria-label="Refresh model connection">↻</button></div>
    <section id="axis-chat-memory" class="axis-chat-memory" aria-label="Axis memory" hidden><div class="axis-chat-memory-heading"><strong>Remembered between chats</strong><small id="axis-chat-memory-status"></small></div><ul id="axis-chat-memory-list"></ul></section>
    <div class="axis-chat-context-row"><button id="axis-chat-use-desk" type="button" disabled>Use selected desk</button><span id="axis-chat-selection">Select a desk on the map</span></div>
    <div id="axis-chat-messages" class="axis-chat-messages" role="log" aria-label="Conversation with Axis" aria-live="off" tabindex="0">
      <div id="axis-chat-empty" class="axis-chat-empty"><strong>What do you need?</strong><p>Find a person or PC, check a machine, or start an IT task.</p><small>Thinking and tool activity appear here. Changes ask for approval.</small></div>
    </div>
    <div id="axis-chat-activity" class="axis-chat-activity" role="status" aria-live="polite" hidden><span id="axis-chat-spinner" aria-hidden="true">/</span><span id="axis-chat-activity-text">Thinking</span></div>
    <form id="axis-chat-form" class="axis-chat-form">
      <div id="axis-chat-attached" class="axis-chat-attached" hidden><span></span><button type="button" title="Remove attached desk" aria-label="Remove attached desk">×</button></div>
      <label class="axis-chat-input-label" for="axis-chat-input">Message Axis</label>
      <textarea id="axis-chat-input" rows="3" maxlength="20000" placeholder="Ask Axis…" aria-describedby="axis-chat-input-help"></textarea>
      <div class="axis-chat-compose-actions"><span id="axis-chat-input-help">Enter to send · Shift+Enter for a new line</span><button id="axis-chat-stop" type="button" hidden>Stop</button><button id="axis-chat-send" type="submit">Send <span aria-hidden="true">↑</span></button></div>
    </form>`;
  document.body.append(panel);
  const $ = (selector) => panel.querySelector(selector);
  const messages = $("#axis-chat-messages"),
    input = $("#axis-chat-input");
  let sessionId = null,
    busy = false,
    attached = null,
    stream = null,
    spinner = null;
  let activeText = null,
    activeKind = null,
    followTail = true,
    scrollFrame = null;
  const pendingTools = [],
    approvals = new Map();
  const openKey = "aa-axis-chat-open";

  function headerSize() {
    panel.style.setProperty(
      "--aa-header-bottom",
      Math.max(0, header.getBoundingClientRect().bottom) + "px",
    );
  }
  new ResizeObserver(headerSize).observe(header);
  window.addEventListener("resize", headerSize);
  headerSize();
  function setOpen(open, focus = false) {
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("axis-chat-open", open);
    const inspector = document.querySelector("#detail");
    if (inspector) inspector.inert = open;
    try {
      localStorage.setItem(openKey, open ? "yes" : "no");
    } catch {}
    if (open) {
      updateSelection();
      headerSize();
      if (focus) input.focus();
    }
  }
  let initiallyOpen = window.innerWidth > 760;
  try {
    const savedOpen = localStorage.getItem(openKey);
    if (savedOpen !== null) initiallyOpen = savedOpen === "yes";
  } catch {}
  setOpen(initiallyOpen);
  button.addEventListener("click", () => setOpen(panel.hidden, panel.hidden));
  $("#axis-chat-close").addEventListener("click", () => {
    setOpen(false);
    button.focus();
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.stopPropagation();
      setOpen(false);
      button.focus();
    }
  });

  messages.addEventListener("scroll", () => {
    followTail =
      messages.scrollHeight - messages.scrollTop - messages.clientHeight < 70;
  });
  function scrollToTail(force = false) {
    if (force) followTail = true;
    if (!followTail || scrollFrame !== null) return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = null;
      if (followTail) messages.scrollTop = messages.scrollHeight;
    });
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function entry(kind, title, text) {
    $("#axis-chat-empty")?.remove();
    const article = element("article", "axis-message axis-message-" + kind);
    article.append(element("div", "axis-message-label", title));
    const content = element("div", "axis-message-content", text || "");
    article.append(content);
    messages.append(article);
    activeText = null;
    activeKind = null;
    scrollToTail();
    return { article, content };
  }
  function chunk(kind, text) {
    if (!text) return;
    if (!activeText || activeKind !== kind) {
      activeText = entry(
        kind,
        kind === "thinking" ? "Thinking" : "Axis",
      ).content;
      activeKind = kind;
    }
    if (activeText.lastChild?.nodeType === Node.TEXT_NODE) {
      activeText.lastChild.appendData(String(text));
    } else activeText.append(document.createTextNode(String(text)));
    scrollToTail();
  }
  function print(value) {
    if (typeof value !== "string") return JSON.stringify(value, null, 2);
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  // Desks found by Axis open on this map; selecting one gives no permission.
  function deskLinks(container, result) {
    let items = [];
    try {
      items = JSON.parse(result).items || [];
    } catch {}
    const ids = [
      ...new Set(
        items
          .map((item) => item && item.desk_id)
          .filter((id) => typeof id === "string" && id),
      ),
    ].slice(0, 10);
    if (!ids.length || typeof window.AtlasSelectDesk !== "function") return;
    const row = element("div", "axis-desk-links");
    for (const id of ids) {
      const link = element("button", "", "Show " + id + " on map");
      link.type = "button";
      link.addEventListener("click", () => {
        if (!window.AtlasSelectDesk(id))
          link.textContent = id + " is not on the current map";
      });
      row.append(link);
    }
    container.append(row);
  }
  function updateSelection() {
    const selected = window.AtlasAxisSelection?.();
    $("#axis-chat-use-desk").disabled = busy || !selected;
    $("#axis-chat-selection").textContent = selected
      ? [selected.desk_id, selected.name].filter(Boolean).join(" · ")
      : "Select a desk on the map";
  }
  window.addEventListener("atlas:selection", updateSelection);
  function setAttached(value) {
    attached = value;
    const chip = $("#axis-chat-attached");
    chip.hidden = !value;
    chip.querySelector("span").textContent = value
      ? "Desk " + value.desk_id + (value.hostname ? " · " + value.hostname : "")
      : "";
  }
  $("#axis-chat-use-desk").addEventListener("click", () => {
    const value = window.AtlasAxisSelection?.();
    if (!value) {
      updateSelection();
      return;
    }
    setAttached(
      Object.fromEntries(
        ["desk_id", "name", "hostname", "floor"].map((key) => [
          key,
          String(value[key] ?? ""),
        ]),
      ),
    );
    input.focus();
  });
  $("#axis-chat-attached button").addEventListener("click", () =>
    setAttached(null),
  );

  async function request(path, body, options = {}) {
    const token = await AtlasClient.sessionToken();
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Atlas-Token": token },
      body: JSON.stringify(body),
      ...options,
    });
  }
  async function checked(response) {
    if (response.ok) return response;
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {}
    const error = Error(
      typeof detail === "string"
        ? detail
        : "Axis request failed (" + response.status + ").",
    );
    error.status = response.status;
    throw error;
  }
  async function refreshStatus() {
    const label = $("#axis-chat-model");
    try {
      const response = await checked(
        await fetch("/api/axis/status", {
          cache: "no-store",
          credentials: "same-origin",
        }),
      );
      const status = await response.json();
      label.textContent = status.ready
        ? status.model || "Model ready"
        : "Model offline · /jobs is still available";
      label.dataset.ready = String(Boolean(status.ready));
      label.title = status.ready
        ? "Running locally"
        : "Start AA to load the model, then refresh.";
    } catch (error) {
      label.textContent = "Axis unavailable";
      label.dataset.ready = "false";
      label.title = error.message;
    }
  }
  $("#axis-chat-refresh").addEventListener("click", refreshStatus);
  refreshStatus();

  function setBusy(value) {
    busy = value;
    $("#axis-chat-send").disabled = value;
    $("#axis-chat-reset").disabled = value;
    $("#axis-chat-stop").hidden = !value;
    $("#axis-chat-stop").disabled = false;
    $("#axis-chat-activity").hidden = !value;
    input.setAttribute("aria-busy", String(value));
    clearInterval(spinner);
    spinner = null;
    if (
      value &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      let index = 0;
      spinner = setInterval(() => {
        $("#axis-chat-spinner").textContent = ["|", "/", "-", "\\"][
          index++ % 4
        ];
      }, 160);
    }
    if (!value) {
      for (const approval of approvals.values()) {
        for (const control of approval.controls) control.disabled = true;
        if (!approval.resolved)
          approval.note.textContent = "No approval submitted.";
      }
      approvals.clear();
      activeText = null;
      activeKind = null;
    }
    updateSelection();
  }
  function activity(text) {
    const label = $("#axis-chat-activity-text");
    if (label.textContent !== (text || "Working"))
      label.textContent = text || "Working";
  }

  function approval(event) {
    const item = entry("approval", "Approval required", event.action);
    const controls = element("div", "axis-approval-actions");
    const deny = element("button", "", "Deny"),
      allow = element("button", "axis-approve", "Approve");
    allow.type = deny.type = "button";
    const note = element(
      "span",
      "axis-approval-note",
      "Waiting for your decision.",
    );
    controls.append(deny, allow);
    item.article.append(controls, note);
    const state = { controls: [deny, allow], note, resolved: false };
    approvals.set(event.id, state);
    activity("Waiting for approval");
    const approvalSession = sessionId;
    for (const [control, approved] of [
      [deny, false],
      [allow, true],
    ])
      control.addEventListener("click", async () => {
        if (state.resolved || !busy || sessionId !== approvalSession) return;
        state.controls.forEach((node) => {
          node.disabled = true;
        });
        try {
          await checked(
            await request("/api/axis/approve", {
              session_id: approvalSession,
              approval_id: event.id,
              approved,
            }),
          );
          state.resolved = true;
          note.textContent = approved ? "Approved." : "Declined.";
          activity("Working");
        } catch (error) {
          note.textContent = error.message;
          if (busy && sessionId === approvalSession)
            state.controls.forEach((node) => {
              node.disabled = false;
            });
        }
      });
    scrollToTail();
  }
  function receive(event) {
    switch (event.type) {
      case "session":
        sessionId = event.session_id;
        break;
      case "thinking":
        activity("Thinking");
        chunk("thinking", event.text);
        break;
      case "answer":
        activity("Answering");
        chunk("assistant", event.text);
        break;
      case "assistant":
        entry("assistant", "Axis", event.text);
        break;
      case "activity":
        activity(event.text);
        break;
      case "tool_start": {
        const tool = entry(
          "tool",
          String(event.name || "Tool").replaceAll("_", " "),
        );
        tool.content.append(
          element("pre", "axis-tool-arguments", print(event.args || {})),
        );
        pendingTools.push({ ...tool, name: event.name });
        activity(
          "Running " + String(event.name || "tool").replaceAll("_", " "),
        );
        break;
      }
      case "tool_result": {
        const index = pendingTools.findIndex(
          (tool) => tool.name === event.name,
        );
        const tool =
          index >= 0
            ? pendingTools.splice(index, 1)[0]
            : entry("tool", event.name || "Tool result");
        tool.content.append(
          element("pre", "axis-tool-result", print(event.result)),
        );
        if (event.name === "find_desk") deskLinks(tool.content, event.result);
        if (event.output_id)
          tool.content.append(
            element("small", "axis-tool-saved", "/output " + event.output_id),
          );
        activeText = null;
        activeKind = null;
        scrollToTail();
        break;
      }
      case "approval":
        approval(event);
        break;
      case "notice":
        entry(event.tone === "error" ? "error" : "notice", "Axis", event.text);
        break;
      case "error":
        entry("error", "Axis", event.text);
        break;
      case "done":
        return true;
    }
    return false;
  }
  async function readStream(response) {
    if (!response.body)
      throw Error("This browser could not open Axis's response stream.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "",
      complete = false;
    function frames(final = false) {
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) complete = receive(JSON.parse(data)) || complete;
      }
      if (final && buffer.trim())
        throw Error("Axis's response ended before the last event completed.");
    }
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        frames(done);
        if (done) break;
      }
      if (!complete)
        throw Error(
          "The connection ended before Axis finished. Check job status before retrying a change.",
        );
    } finally {
      reader.releaseLock();
    }
  }
  async function send(event) {
    event?.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    const context = attached ? { ...attached } : null;
    const user = entry("user", "You", text);
    if (context)
      user.article.append(
        element(
          "small",
          "axis-attached-record",
          "Attached desk: " +
            context.desk_id +
            (context.hostname ? " · " + context.hostname : ""),
        ),
      );
    input.value = "";
    setAttached(null);
    scrollToTail(true);
    setBusy(true);
    activity("Thinking");
    pendingTools.length = 0;
    stream = new AbortController();
    try {
      const response = await checked(
        await request(
          "/api/axis/chat",
          {
            message: text,
            ...(sessionId ? { session_id: sessionId } : {}),
            ...(context ? { context } : {}),
          },
          { signal: stream.signal },
        ),
      );
      await readStream(response);
    } catch (error) {
      stream?.abort();
      if (error.status === 404) {
        sessionId = null;
        input.value = text;
        setAttached(context);
      }
      entry(
        "error",
        "Axis",
        error.name === "AbortError"
          ? "Request stopped. Accepted background jobs continue."
          : error.message,
      );
    } finally {
      stream = null;
      setBusy(false);
      input.focus();
    }
  }
  $("#axis-chat-form").addEventListener("submit", send);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  $("#axis-chat-stop").addEventListener("click", async () => {
    if (!busy) return;
    $("#axis-chat-stop").disabled = true;
    activity("Stopping");
    if (!sessionId) {
      stream?.abort();
      return;
    }
    try {
      await checked(
        await request("/api/axis/cancel", { session_id: sessionId }),
      );
    } catch (error) {
      entry("error", "Axis", error.message);
      $("#axis-chat-stop").disabled = false;
    }
  });
  $("#axis-chat-reset").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    activity("Starting a new conversation");
    $("#axis-chat-stop").hidden = true;
    try {
      if (sessionId) {
        const response = await request("/api/axis/reset", {
          session_id: sessionId,
        });
        if (response.status !== 404) await checked(response);
      }
      messages.replaceChildren();
      sessionId = null;
      attached = null;
      setAttached(null);
      activeText = null;
      activeKind = null;
      entry("notice", "Axis", "New conversation.");
      input.focus();
    } catch (error) {
      entry("error", "Axis", error.message);
    } finally {
      setBusy(false);
    }
  });
  // Show the latest chat again after a reload or restart; nothing is kept in the browser.
  function replay(transcript) {
    for (const event of transcript) {
      if (event.type === "user") {
        const user = entry("user", "You", event.text);
        if (event.context?.desk_id)
          user.article.append(
            element(
              "small",
              "axis-attached-record",
              "Attached desk: " +
                event.context.desk_id +
                (event.context.hostname ? " · " + event.context.hostname : ""),
            ),
          );
      } else if (event.type === "approval") {
        // A saved approval is history: it shows the decision and has no controls.
        entry("approval", "Approval required", event.action).article.append(
          element(
            "span",
            "axis-approval-note",
            { approved: "Approved.", declined: "Declined." }[event.decision] ||
              "No approval submitted.",
          ),
        );
      } else receive(event);
    }
    pendingTools.length = 0;
    activeText = null;
    activeKind = null;
    scrollToTail(true);
  }
  async function resume() {
    try {
      const saved = await (
        await checked(await request("/api/axis/resume", {}))
      ).json();
      if (busy || sessionId || typeof saved.session_id !== "string") return;
      sessionId = saved.session_id;
      if (Array.isArray(saved.transcript) && saved.transcript.length) {
        messages.replaceChildren();
        replay(saved.transcript);
      }
      if (saved.busy)
        entry(
          "notice",
          "Axis",
          "This chat is still working in another window. Reopen the panel later to see its result.",
        );
    } catch {}
  }
  resume();

  const memoryPanel = $("#axis-chat-memory"),
    memoryStatus = $("#axis-chat-memory-status");
  function showMemory(data) {
    const list = $("#axis-chat-memory-list");
    list.replaceChildren();
    for (const fact of data.entries || []) {
      const item = element("li", "", "");
      const forget = element("button", "", "Forget");
      forget.type = "button";
      forget.title = "Remove this fact from Axis's memory";
      forget.addEventListener("click", async () => {
        if (
          !window.confirm(
            'Forget "' + fact + '"? New chats will no longer see it.',
          )
        )
          return;
        forget.disabled = true;
        try {
          showMemory(
            await (
              await checked(
                await request("/api/axis/memory/forget", { entry: fact }),
              )
            ).json(),
          );
        } catch (error) {
          memoryStatus.textContent = error.message;
          forget.disabled = false;
        }
      });
      item.append(element("span", "", fact), forget);
      list.append(item);
    }
    memoryStatus.textContent = (data.entries || []).length
      ? data.path || ""
      : "Nothing remembered yet. Ask Axis to remember a fact.";
  }
  $("#axis-chat-memory-toggle").addEventListener("click", async () => {
    memoryPanel.hidden = !memoryPanel.hidden;
    $("#axis-chat-memory-toggle").setAttribute(
      "aria-expanded",
      String(!memoryPanel.hidden),
    );
    if (memoryPanel.hidden) return;
    memoryStatus.textContent = "Loading…";
    try {
      showMemory(
        await (await checked(await request("/api/axis/memory", {}))).json(),
      );
    } catch (error) {
      memoryStatus.textContent = error.message;
    }
  });

  window.addEventListener("pagehide", () => {
    clearInterval(spinner);
    stream?.abort();
  });
})();
