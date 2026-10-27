/* Import folder card: the exports Atlas found, what each import did, and a held users & devices review. */
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("import-folder")) return;
  const tones = { synced: "status-ok", held: "status-warn", waiting: "status-warn", checking: "status-warn", empty: "", error: "status-bad", off: "" };
  const labels = { synced: "Up to date", held: "Waiting for review", waiting: "Waiting", checking: "Checking", empty: "No exports yet", error: "Needs attention", off: "Off" };
  const kinds = { users: "Users", devices: "Devices", vdi: "Citrix VDI", packages: "Packages" };
  const groupOf = { users: "directory", devices: "directory", vdi: "vdi", packages: "packages" };
  const results = { applied: "imported", error: "not imported", skipped: "skipped", held: "waiting for review", waiting: "waiting" };
  let editing = false, timer, review = null, latest;
  const api = (url, options = {}) => window.AtlasClient.request(url, { ...options, atlasSilent: true });
  const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const when = (value) => {
    const date = value && new Date(value);
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—";
  };
  const item = (text, tone) => {
    const li = document.createElement("li");
    li.textContent = text;
    if (tone) li.className = tone;
    return li;
  };

  function render(data) {
    if (!editing) {
      $("import-folder-path").value = data.folder || "";
      $("import-folder-enabled").checked = !!data.enabled;
      $("import-folder-review").checked = data.review_large !== false;
    }
    const status = data.status || {}, state = data.enabled ? status.state || "checking" : "off";
    $("import-folder-state").className = tones[state] || "";
    $("import-folder-state").textContent = labels[state] || state;
    $("import-folder-message").textContent = status.message || "";
    $("import-folder-message").dataset.tone = state === "error" ? "bad" : "";
    const groups = data.groups || {};
    $("import-folder-files").replaceChildren(...(data.files || []).map((file) => {
      const group = groups[groupOf[file.kind]];
      const outcome = !file.kind ? "not an export Atlas reads"
        : !file.used ? "older copy, not used"
        : group ? `${results[group.result] || group.result}${group.message && group.result !== "held" ? " · " + group.message : ""}` : "";
      const tone = !file.kind || !file.used ? "" : group?.result === "error" ? "status-bad" : group?.result === "applied" ? "status-ok" : "status-warn";
      const li = item(`${file.name} · ${kinds[file.kind] || "Other"} · saved ${when(file.modified)}${outcome ? " · " + outcome : ""}`, tone);
      if (!file.kind || !file.used) li.dataset.muted = "true";
      return li;
    }));
    const held = review = data.held || null;
    $("import-folder-held").hidden = !held;
    $("import-folder-apply").disabled = !held;
    $("import-folder-skip").disabled = !held;
    if (held) {
      $("import-folder-held-reason").textContent = `${held.files.join(" + ")}: ${held.reason}`;
      const report = held.report || {};
      $("import-folder-held-counts").replaceChildren(
        ...[["users", "Users"], ["machines", "Devices"]].map(([key, label]) => {
          const r = report[key] || {};
          return item(`${label}: ${(r.before ?? 0).toLocaleString()} → ${(r.after ?? 0).toLocaleString()} (+${(r.added ?? 0).toLocaleString()} / −${(r.removed ?? 0).toLocaleString()})`,
            r.removed > (r.before || 0) * 0.1 ? "status-bad" : "");
        }),
        ...(report.missing_desk_accounts?.length ? [item(`${report.missing_desk_accounts.length} desk links point at accounts this snapshot removes`, "status-warn")] : []),
        ...(report.warnings || []).map((text) => item(text, "status-warn")),
      );
    }
    $("import-folder-history").replaceChildren(...(data.history || []).map((h) =>
      item(`${when(h.at)} · ${h.kind} · ${h.files.join(" + ")} · ${results[h.result] || h.result}${h.message ? ": " + h.message : ""}`,
        h.result === "error" ? "status-bad" : "")));
    if (!(data.history || []).length) $("import-folder-history").append(item("No folder imports yet."));
    // A new folder import, including one made in the background: the sections below refresh their counts.
    const newest = data.history?.[0]?.at || "";
    if (latest !== undefined && newest !== latest) window.dispatchEvent(new Event("atlas:database-imported"));
    latest = newest;
  }

  async function refresh() {
    clearTimeout(timer);
    try { render(await api("/api/import-folder")); }
    catch (error) { $("import-folder-message").textContent = "Import folder unavailable: " + error.message; }
    if (!document.hidden) timer = setTimeout(refresh, 15000);
  }
  async function act(button, task) {
    button.disabled = true;
    try { render(await task()); }
    catch (error) { $("import-folder-message").textContent = error.message; $("import-folder-message").dataset.tone = "bad"; }
    finally { button.disabled = ["import-folder-apply", "import-folder-skip"].includes(button.id) ? !review : false; }
  }
  for (const id of ["import-folder-path", "import-folder-enabled", "import-folder-review"])
    $(id).addEventListener(id === "import-folder-path" ? "input" : "change", () => (editing = true));
  $("import-folder-save").onclick = () => act($("import-folder-save"), async () => {
    const result = await post("/api/import-folder/settings", { folder: $("import-folder-path").value, enabled: $("import-folder-enabled").checked, review_large: $("import-folder-review").checked });
    editing = false;
    return result;
  });
  $("import-folder-check").onclick = () => act($("import-folder-check"), () => post("/api/import-folder/check"));
  $("import-folder-apply").onclick = () => {
    if (!review) return;
    const id = review.id;
    if (!confirm(`Apply ${review.files.join(" + ")} as the complete directory? Users and devices missing from these exports disappear from directory search. Atlas backs up first.`)) return;
    act($("import-folder-apply"), async () => {
      try { return await post("/api/import-folder/apply", { id }); }
      catch (error) { await refresh(); throw error; }
    });
  };
  $("import-folder-skip").onclick = () => {
    if (!review) return;
    act($("import-folder-skip"), () => post("/api/import-folder/skip", { id: review.id }));
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  refresh();
})();
