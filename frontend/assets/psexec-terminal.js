/* A single polling owner follows the explicitly started local PsExec process. */
(() => {
  const get = (id) => document.getElementById("px" + id);
  let review = null,
    item = null,
    current = null,
    submitting = false,
    sending = false,
    unwatch = null,
    opened = false,
    transcriptRequest = 0,
    listRequest = 0;
  const finished = (s) =>
    ["complete", "failed", "stopped", "timed_out"].includes(s);
  const request = (url, body) =>
    AtlasClient.request(
      url,
      body === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
    );
  function controls() {
    const active = current && !finished(current.state);
    get("Run").disabled =
      !!window.AtlasReadOnly || !review || submitting || !!active;
    get("Run").textContent = submitting
      ? "Starting…"
      : active
        ? "Session running"
        : item?.id === "pst-password-help"
          ? "Show local PsPasswd help"
          : "Run on " + (review?.target || "target");
    get("Stop").disabled = !active || submitting;
    get("InputForm").hidden = !(
      current?.interactive && current.state === "running"
    );
    get("Send").disabled = !!window.AtlasReadOnly || sending;
  }
  function show(data) {
    current = data;
    get("RunStatus").textContent =
      `${data.target} · ${data.title} · ${data.state}${data.exit_code == null ? "" : ` · exit ${data.exit_code}`}`;
    get("RunStatus").dataset.tone = data.exit_code != null ? (Number(data.exit_code) === 0 ? "good" : "bad")
      : /fail|error|timed out|timeout/i.test(data.state || "") ? "bad" : "";
    get("Host").textContent =
      `Atlas account: ${data.account} · ${data.host_elevated ? "Elevated" : "Not elevated"}`;
    get("Output").textContent =
      (data.truncated ? "[Earlier output trimmed]\n" : "") + data.output;
    if (get("AutoScroll").checked)
      get("Output").scrollTop = get("Output").scrollHeight;
    controls();
  }
  function follow(data) {
    transcriptRequest++;
    unwatch?.();
    show(data);
    if (finished(data.state)) return;
    const id = data.id;
    unwatch = AtlasClient.watch(
      "psexec-terminal",
      `/api/psexec/runs/${id}`,
      (result) => {
        if (current?.id !== id) return;
        show(result);
        if (finished(result.state)) refreshSessions(false).catch(() => {});
      },
      {
        interval: 1000,
        done: (result) => finished(result.state),
        onError: (error) => {
          get("TerminalMessage").textContent =
            "Connection lost: " +
            error.message +
            " Use Refresh sessions to reconnect; do not rerun blindly.";
        },
      },
    );
  }
  async function refreshSessions(restore = true) {
    const turn = restore ? ++transcriptRequest : transcriptRequest,
      listing = ++listRequest;
    let rows;
    try {
      rows = await request("/api/psexec/runs");
    } catch (error) {
      if (turn === transcriptRequest && listing === listRequest) throw error;
      return;
    }
    if (turn !== transcriptRequest || listing !== listRequest) return;
    const select = get("Sessions"),
      previous = current?.id || "";
    select.replaceChildren(
      new Option("Choose a session…", ""),
      ...rows.map(
        (r) => new Option(`${r.target} · ${r.title} · ${r.state}`, r.id),
      ),
    );
    select.value = previous;
    if (restore) {
      const active = rows.find((r) => !finished(r.state));
      const id =
        active?.id ||
        (rows.some((r) => r.id === previous) ? previous : rows[0]?.id);
      if (id) {
        select.value = id;
        try {
          const data = await request("/api/psexec/runs/" + id);
          if (turn === transcriptRequest && select.value === id) follow(data);
        } catch (error) {
          if (turn === transcriptRequest && select.value === id) throw error;
        }
      } else {
        unwatch?.();
        current = null;
        controls();
      }
    }
  }
  get("Run").onclick = async () => {
    if (!review || submitting || (current && !finished(current.state))) return;
    const payload = {
      ...review,
      values: { ...review.values },
      id: crypto.randomUUID(),
    };
    if (item.change) {
      const answer = prompt(
        `${item.title} on ${payload.target}\n${item.insight}\n\nType ${payload.target} to confirm:`,
      );
      if (answer?.trim().toUpperCase() !== payload.target) return;
      payload.confirmation = answer.trim();
    }
    submitting = true;
    transcriptRequest++;
    controls();
    get("TerminalMessage").textContent = "";
    get("RunStatus").textContent =
      `Starting ${item.title} on ${payload.target}…`;
    try {
      follow(await request("/api/psexec/run", payload));
      await refreshSessions(false);
    } catch (error) {
      get("TerminalMessage").textContent = error.message;
      get("RunStatus").textContent = "Start not confirmed. No automatic retry.";
      // Reconcile the exact run ID after an uncertain response, never rerun it.
      try {
        follow(await request("/api/psexec/runs/" + payload.id));
      } catch {}
    } finally {
      submitting = false;
      controls();
    }
  };
  get("Stop").onclick = async () => {
    if (!current || finished(current.state)) return;
    const id = current.id;
    get("Stop").disabled = true;
    try {
      await request(`/api/psexec/runs/${id}/stop`, {});
      get("TerminalMessage").textContent =
        "Stopping local session. Remote completion is not guaranteed.";
    } catch (error) {
      get("TerminalMessage").textContent = error.message;
      controls();
    }
  };
  get("InputForm").onsubmit = async (event) => {
    event.preventDefault();
    if (sending || !current?.interactive || current.state !== "running") return;
    const id = current.id,
      line = get("Input").value;
    if (!line.trim()) return;
    sending = true;
    controls();
    try {
      await request(`/api/psexec/runs/${id}/input`, { line });
      if (current?.id === id) get("Input").value = "";
    } catch (error) {
      get("TerminalMessage").textContent =
        error.message +
        " Input was not retried; check the terminal before sending again.";
    } finally {
      sending = false;
      controls();
      get("Input").focus();
    }
  };
  get("CopyOutput").onclick = async () => {
    try {
      await navigator.clipboard.writeText(
        get("RunStatus").textContent + "\n" + get("Output").textContent,
      );
      toast("Terminal output copied");
    } catch {
      get("TerminalMessage").textContent =
        "Clipboard unavailable. Select terminal output to copy it.";
    }
  };
  get("Reconnect").onclick = () =>
    refreshSessions().catch(
      (e) => (get("TerminalMessage").textContent = e.message),
    );
  get("Sessions").onchange = async () => {
    if (current && !finished(current.state)) {
      get("Sessions").value = current.id;
      get("TerminalMessage").textContent =
        "Finish the active session before switching transcripts.";
      return;
    }
    const id = get("Sessions").value, turn = ++transcriptRequest;
    if (!id) return;
    try {
      const data = await request("/api/psexec/runs/" + id);
      if (turn === transcriptRequest && get("Sessions").value === id) follow(data);
    } catch (e) {
      if (turn === transcriptRequest && get("Sessions").value === id)
        get("TerminalMessage").textContent = e.message;
    }
  };
  window.addEventListener("pagehide", () => { transcriptRequest++; listRequest++; });
  window.AtlasPsExecTerminal = {
    review(payload, command) {
      review = payload;
      item = command;
      controls();
    },
    open() {
      if (!opened) {
        opened = true;
        refreshSessions().catch((e) => {
          opened = false;
          get("TerminalMessage").textContent = e.message;
        });
      }
    },
  };
})();
