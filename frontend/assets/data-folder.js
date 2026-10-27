/* Data folder card: choose the exports folder, see each export's state, review a held users-and-devices snapshot. */
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("data-folder")) return;
  const tones = { synced: "status-ok", held: "status-warn", waiting: "status-warn", checking: "status-warn", error: "status-bad", off: "" };
  const labels = { synced: "Up to date", held: "Waiting for review", waiting: "Waiting", checking: "Checking", error: "Needs attention", off: "Off" };
  const results = { applied: ["Imported", "status-ok"], unchanged: ["Up to date", "status-ok"], held: ["Waiting for review", "status-warn"],
    waiting: ["Waiting", "status-warn"], error: ["Not imported", "status-bad"], missing: ["No file", ""] };
  let editing = false, timer, review = null;
  const api = (url, options = {}) => window.AtlasClient.request(url, { ...options, atlasSilent: true });
  const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const when = (value) => {
    const date = value && new Date(value);
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—";
  };
  const number = (n) => Number(n || 0).toLocaleString();
  const item = (text, tone) => {
    const li = document.createElement("li");
    li.textContent = text;
    if (tone) li.className = tone;
    return li;
  };

  function kindRow(entry) {
    const li = document.createElement("li");
    const name = document.createElement("b");
    name.textContent = entry.label;
    const [label, tone] = results[entry.result] || ["Not checked yet", ""];
    const state = document.createElement("span");
    const badge = document.createElement("span");
    badge.textContent = label;
    if (tone) badge.className = tone;
    const files = (entry.files || []).join(" + ");
    state.append(badge, ` · ${[files, entry.message, entry.at && when(entry.at)].filter(Boolean).join(" · ")}`);
    li.append(name, state);
    return li;
  }

  function changeLines(report = {}) {
    const lines = [];
    for (const [key, label] of [["users", "Users"], ["machines", "Devices"]]) {
      const r = report[key];
      if (!r) continue;
      lines.push(item(`${label}: ${number(r.before)} → ${number(r.after)} (${number(r.added)} added, ${number(r.removed)} removed, ${number(r.changed)} updated)`,
        r.removed > r.before * 0.1 ? "status-bad" : ""));
      if (r.removed_examples?.length) lines.push(item(`${label} removed, for example: ${r.removed_examples.slice(0, 10).join(", ")}`));
    }
    // The review reasons are already the heading; list only the other notes.
    const repeated = (text) => /more than 10% of existing records disappear|^Columns absent/.test(text);
    for (const text of (report.warnings || []).filter((text) => !repeated(text))) lines.push(item(text, "status-warn"));
    return lines;
  }

  function render(data) {
    if (!editing) {
      $("data-folder-path").value = data.folder || "";
      $("data-folder-enabled").checked = !!data.enabled;
      $("data-folder-review").checked = data.review_large !== false;
    }
    const status = data.status || {}, state = data.enabled ? status.state || "checking" : "off";
    $("data-folder-state").className = tones[state] || "";
    $("data-folder-state").textContent = labels[state] || state;
    $("data-folder-message").textContent = data.enabled ? `${status.message || ""}${data.checked ? ` Last checked ${when(data.checked)}.` : ""}` : status.message || "";
    $("data-folder-message").dataset.tone = state === "error" ? "bad" : "";
    $("data-folder-kinds").replaceChildren(...(data.enabled ? (data.kinds || []).map(kindRow) : []));
    const ignored = data.enabled ? data.ignored || [] : [];
    $("data-folder-ignored").hidden = !ignored.length;
    $("data-folder-ignored").textContent = ignored.length ? `Not recognised as an export, so left alone: ${ignored.join(", ")}` : "";
    review = data.held || null;
    $("data-folder-held").hidden = !review;
    $("data-folder-apply").disabled = !review?.id;
    if (review) {
      $("data-folder-held-reason").textContent = `${(review.files || []).join(" + ")}: ${review.reason}`;
      $("data-folder-changes").replaceChildren(...changeLines(review.report));
    }
    $("data-folder-history").replaceChildren(...(data.history || []).map((h) => item(`${when(h.at)} · ${h.label} · ${(h.files || []).join(" + ")} · ${h.summary}`)));
    if (!(data.history || []).length) $("data-folder-history").append(item("No imports from the folder yet."));
  }

  async function refresh() {
    clearTimeout(timer);
    try { render(await api("/api/data-folder")); }
    catch (error) { $("data-folder-message").textContent = "Data folder unavailable: " + error.message; }
    if (!document.hidden) timer = setTimeout(refresh, 15000);
  }
  async function act(button, task) {
    button.disabled = true;
    try { render(await task()); }
    catch (error) { $("data-folder-message").textContent = error.message; $("data-folder-message").dataset.tone = "bad"; }
    finally { button.disabled = button.id === "data-folder-apply" ? !review?.id : false; }
  }
  for (const id of ["data-folder-path", "data-folder-enabled", "data-folder-review"]) {
    $(id).addEventListener(id === "data-folder-path" ? "input" : "change", () => (editing = true));
  }
  $("data-folder-save").onclick = () => act($("data-folder-save"), async () => {
    const result = await post("/api/data-folder/settings", { folder: $("data-folder-path").value || $("data-folder-path").placeholder,
      enabled: $("data-folder-enabled").checked, review_large: $("data-folder-review").checked });
    editing = false;
    return result;
  });
  $("data-folder-check").onclick = () => act($("data-folder-check"), () => post("/api/data-folder/check"));
  $("data-folder-apply").onclick = () => {
    if (!review?.id) return;
    const id = review.id;
    if (!confirm(`Replace users and devices with ${(review.files || []).join(" + ")}? ${review.reason.replace(/\.?$/, ".")} Atlas backs up the database first.`)) return;
    act($("data-folder-apply"), async () => {
      try { return await post("/api/data-folder/apply", { id }); }
      catch (error) { await refresh(); throw error; }
    });
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  if (window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content === "viewer") {
    $("data-folder").hidden = true;
    return;
  }
  refresh();
})();
