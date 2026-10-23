/* On-demand service inventory and exact, verified service control. */
(() => {
  const el = (id) => document.getElementById(id);
  const target = () => el("adminPc").value.trim().toUpperCase();
  const actions = {
    start: {
      label: "Start",
      button: "Start",
      progress: "Starting",
      state: "Running",
      outcomes: ["started", "already_running"],
    },
    stop: {
      label: "Stop",
      button: "Stop…",
      progress: "Stopping",
      state: "Stopped",
      outcomes: ["stopped", "already_stopped"],
    },
    restart: {
      label: "Restart",
      button: "Restart…",
      progress: "Restarting",
      state: "Running",
      outcomes: ["restarted"],
    },
  };
  const observedStates = new Set([
    "Running",
    "Stopped",
    "Paused",
    "Start Pending",
    "Stop Pending",
    "Continue Pending",
    "Pause Pending",
    "Unknown",
  ]);
  let rows = [],
    computer = "",
    sequence = 0,
    listing = false,
    mutation = null,
    confirmation = null;
  const readonly = () => !!window.AtlasReadOnly;
  const identity = (value) =>
    typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const sameName = (left, right) =>
    typeof left === "string" &&
    typeof right === "string" &&
    left.toLowerCase() === right.toLowerCase();
  const request = (url, body) =>
    AtlasClient.request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  function available(item, action) {
    return (
      actions[action] &&
      item?.["can_" + action] === true &&
      identity(item.identity) &&
      !item.requires_refresh
    );
  }
  function controls() {
    const busy = listing || !!mutation || !!confirmation;
    el("adminServices").disabled = readonly() || !target() || busy;
    el("refreshServices").disabled = readonly() || !target() || busy;
    el("servicesDialog").setAttribute("aria-busy", String(busy));
    for (const button of el("servicesBody").querySelectorAll(
      "[data-service-action]",
    )) {
      const item = rows[Number(button.dataset.serviceIndex)];
      button.disabled =
        readonly() ||
        busy ||
        computer !== target() ||
        !available(item, button.dataset.serviceAction);
    }
    el("confirmServiceControl").disabled =
      readonly() ||
      listing ||
      !!mutation ||
      !confirmation ||
      confirmation.computer !== target() ||
      confirmation.sequence !== sequence;
  }
  function render() {
    const word = el("servicesFilter").value.trim().toLocaleLowerCase();
    const shown = rows
      .map((item, index) => ({ item, index }))
      .filter(({ item }) =>
        [item.name, item.display_name, item.state, item.start_mode].some(
          (value) =>
            String(value || "")
              .toLocaleLowerCase()
              .includes(word),
        ),
      );
    el("servicesCount").textContent =
      `${shown.length} of ${rows.length} services`;
    const body = el("servicesBody");
    body.replaceChildren();
    for (const { item, index } of shown) {
      const row = document.createElement("tr"),
        name = row.insertCell();
      name.textContent = item.display_name || item.name;
      const detail = document.createElement("small");
      detail.textContent = item.name;
      name.append(detail);
      const state = document.createElement("span");
      state.textContent = item.state;
      state.className = item.state === "Running" ? "status-ok" : item.state === "Stopped" ? "status-bad" : item.state ? "status-warn" : "";
      row.insertCell().append(state);
      for (const value of [item.start_mode, item.pid ?? "—"])
        row.insertCell().textContent = value;
      const buttons = document.createElement("div");
      buttons.className = "services-row-actions";
      for (const [action, info] of Object.entries(actions)) {
        const button = document.createElement("button");
        if (action !== "start") button.className = "danger";
        button.textContent = info.button;
        button.dataset["service" + info.label] = index;
        button.dataset.serviceAction = action;
        button.dataset.serviceIndex = index;
        button.setAttribute(
          "aria-label",
          `${info.label} ${item.display_name || item.name}`,
        );
        button.title =
          item[action + "_reason"] ||
          `${info.label} ${item.name} on ${computer}`;
        buttons.append(button);
      }
      row.insertCell().append(buttons);
      body.append(row);
    }
    if (!shown.length) {
      const cell = body.insertRow().insertCell();
      cell.colSpan = 5;
      cell.textContent = rows.length
        ? "No services match this search."
        : "No services loaded.";
    }
    controls();
  }
  function closeConfirmation() {
    if (el("serviceControlDialog").open) el("serviceControlDialog").close();
  }
  function changedTarget() {
    sequence++;
    listing = false;
    computer = "";
    rows = [];
    closeConfirmation();
    el("servicesTarget").textContent = target() || "No target";
    el("servicesStatus").textContent = target()
      ? "Choose Refresh to list services on this target."
      : "Choose a target and list its services.";
    render();
  }
  async function load() {
    if (readonly() || !target() || listing || mutation || confirmation) return;
    const pc = target(),
      turn = ++sequence;
    computer = pc;
    rows = [];
    listing = true;
    el("servicesTarget").textContent = pc;
    if (!el("servicesDialog").open) el("servicesDialog").showModal();
    el("servicesStatus").textContent = `Listing services on ${pc}…`;
    render();
    try {
      const result = await request("/api/services", { computer: pc });
      if (turn !== sequence || pc !== target()) return;
      if (result.computer?.toUpperCase() !== pc || !Array.isArray(result.items))
        throw Error("Service list did not match the target. Refresh services.");
      rows = result.items;
      el("servicesStatus").textContent =
        `${pc}: ${rows.length} services loaded. Controls are available where Windows allows them.`;
    } catch (error) {
      if (turn === sequence && pc === target())
        el("servicesStatus").textContent = error.message;
    } finally {
      if (turn === sequence) {
        listing = false;
        render();
      }
    }
  }
  function confirmed(selection) {
    const dialog = el("serviceControlDialog"),
      info = actions[selection.action];
    confirmation = selection;
    el("serviceControlTitle").textContent = `${info.label} service?`;
    el("serviceControlQuestion").textContent =
      `${info.label} ${selection.item.display_name || selection.item.name} (${selection.item.name}) on ${selection.computer}?`;
    el("serviceControlWarning").textContent =
      selection.action === "restart"
        ? "Applications using this service will be interrupted while it stops and starts."
        : "Applications using this service may stop working.";
    const button = el("confirmServiceControl");
    button.textContent = `${info.label} service`;
    button.classList.toggle("danger", selection.action !== "start");
    dialog.returnValue = "";
    const answer = new Promise((resolve) => {
      dialog.addEventListener(
        "close",
        () => resolve(dialog.returnValue === selection.action),
        { once: true },
      );
    });
    controls();
    dialog.showModal();
    el("cancelServiceControl").focus();
    return answer;
  }
  function refreshedItem(result, selection) {
    const item = result.item;
    if (
      !item ||
      Array.isArray(item) ||
      !sameName(item.name, selection.item.name) ||
      !identity(item.identity) ||
      item.identity !== selection.item.identity ||
      !observedStates.has(item.state) ||
      item.state !== result.state ||
      !Number.isInteger(item.pid) ||
      item.pid < 0 ||
      (result.pid !== undefined && result.pid !== item.pid) ||
      Object.keys(actions).some(
        (action) => typeof item["can_" + action] !== "boolean",
      )
    )
      return null;
    return { ...item };
  }
  function lock(item) {
    item.requires_refresh = true;
    for (const action of Object.keys(actions)) {
      item["can_" + action] = false;
      item[action + "_reason"] = "Refresh services to verify the current state";
    }
  }
  function ownsRowFocus(node, selection) {
    const button = node?.closest?.("[data-service-action]");
    return !!button && Number(button.dataset.serviceIndex) === selection.index;
  }
  function restoreActionFocus(selection, wanted) {
    if (
      !wanted ||
      selection.sequence !== sequence ||
      selection.computer !== target() ||
      !el("servicesDialog").open ||
      !sameName(rows[selection.index]?.name, selection.item.name)
    )
      return;
    const active = document.activeElement;
    if (
      active !== document.body &&
      active !== document.documentElement &&
      active !== el("servicesDialog") &&
      !ownsRowFocus(active, selection) &&
      !el("serviceControlDialog").contains(active)
    )
      return;
    const rowButtons = [
      ...el("servicesBody").querySelectorAll(
        `[data-service-index="${selection.index}"]`,
      ),
    ];
    const candidate =
      rowButtons.find(
        (button) =>
          !button.disabled && button.dataset.serviceAction === selection.action,
      ) ||
      rowButtons.find((button) => !button.disabled) ||
      (!el("refreshServices").disabled ? el("refreshServices") : null);
    candidate?.focus({ preventScroll: true });
  }
  async function control(action, index) {
    const item = rows[index];
    if (
      !actions[action] ||
      readonly() ||
      listing ||
      mutation ||
      confirmation ||
      computer !== target() ||
      !available(item, action)
    )
      return;
    const selection = Object.freeze({
      item: Object.freeze({ ...item }),
      action,
      index,
      computer,
      sequence,
    });
    let focusOwned = ownsRowFocus(document.activeElement, selection),
      focusMoved = false;
    const trackFocus = (event) => {
      if (
        el("serviceControlDialog").contains(event.target) &&
        confirmation === selection
      )
        focusOwned = true;
      else if (
        event.target !== document.body &&
        event.target !== document.documentElement &&
        event.target !== el("servicesDialog") &&
        !ownsRowFocus(event.target, selection)
      )
        focusMoved = true;
    };
    document.addEventListener("focusin", trackFocus);
    if (action !== "start") {
      const accepted = await confirmed(selection);
      if (confirmation === selection) confirmation = null;
      if (
        !accepted ||
        readonly() ||
        selection.computer !== target() ||
        selection.sequence !== sequence ||
        mutation
      ) {
        document.removeEventListener("focusin", trackFocus);
        controls();
        restoreActionFocus(selection, focusOwned && !focusMoved);
        return;
      }
    }
    mutation = selection;
    controls();
    const pc = selection.computer,
      info = actions[action];
    el("servicesStatus").textContent =
      `${info.progress} ${selection.item.name} on ${pc}…`;
    try {
      const result = await request(`/api/services/${action}`, {
        computer: pc,
        name: selection.item.name,
        expected_identity: selection.item.identity,
      });
      if (pc !== target() || selection.sequence !== sequence) return;
      if (
        result.computer?.toUpperCase() !== pc ||
        !sameName(result.name, selection.item.name)
      )
        throw Error(
          `${info.label} outcome did not match the selected service.`,
        );
      const refreshed = refreshedItem(result, selection),
        verified =
          !!refreshed &&
          info.outcomes.includes(result.outcome) &&
          refreshed.state === info.state;
      const current = rows[selection.index];
      if (
        !sameName(current?.name, selection.item.name) ||
        current.identity !== selection.item.identity
      )
        throw Error(
          "The displayed service changed. Refresh services before retrying.",
        );
      // A failed restart can truthfully leave the service Stopped or pending.
      // Keep the observed state/PID, but never make an unverified outcome retryable.
      if (refreshed) rows[selection.index] = refreshed;
      if (!verified) lock(rows[selection.index]);
      const message = verified
        ? result.message ||
          `Service ${action === "restart" ? "restarted" : action === "start" ? "started" : "stopped"}.`
        : `${info.label} was not verified.${result.message ? " " + result.message : ""} Refresh services to verify the current state before retrying.`;
      el("servicesStatus").textContent =
        `${pc} · ${selection.item.name}: ${message}`;
    } catch (error) {
      if (pc === target() && selection.sequence === sequence) {
        const current = rows[selection.index];
        if (sameName(current?.name, selection.item.name)) lock(current);
        el("servicesStatus").textContent =
          `${pc} · ${selection.item.name}: ${error.message} Refresh services to verify the current state before retrying.`;
      }
    } finally {
      document.removeEventListener("focusin", trackFocus);
      if (mutation === selection) mutation = null;
      render();
      restoreActionFocus(selection, focusOwned && !focusMoved);
    }
  }
  function bind() {
    if (!el("adminServices")) return;
    el("adminServices").addEventListener("click", load);
    el("refreshServices").addEventListener("click", load);
    el("servicesFilter").addEventListener("input", render);
    el("servicesBody").addEventListener("click", (event) => {
      const button = event.target.closest("[data-service-action]");
      if (button && !button.disabled)
        control(
          button.dataset.serviceAction,
          Number(button.dataset.serviceIndex),
        );
    });
    el("cancelServiceControl").onclick = () =>
      el("serviceControlDialog").close();
    el("confirmServiceControl").onclick = () => {
      if (
        !confirmation ||
        !el("serviceControlDialog").open ||
        readonly() ||
        confirmation.computer !== target() ||
        confirmation.sequence !== sequence
      )
        return;
      el("serviceControlDialog").returnValue = confirmation.action;
      el("serviceControlDialog").close();
    };
    el("closeServices").onclick = () => el("servicesDialog").close();
    el("servicesDialog").addEventListener("close", () => {
      sequence++;
      listing = false;
      computer = "";
      rows = [];
      closeConfirmation();
      render();
    });
    el("adminPc").addEventListener("input", changedTarget);
    window.addEventListener("atlas:admin-target-change", changedTarget);
    changedTarget();
  }
  // Live Inbox's request tools list services for the selected machine without opening Remote Admin.
  window.AtlasServices = { load };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", bind, { once: true });
  else bind();
})();
