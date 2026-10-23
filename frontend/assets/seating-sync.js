/* Live floor plan card: choose the plan folder, see what Atlas read, review held changes. */
(() => {
  const $ = (id) => document.getElementById(id);
  if (!$("live-plan")) return;
  const tones = { synced: "status-ok", held: "status-warn", waiting: "status-warn", checking: "status-warn", error: "status-bad", off: "" };
  const labels = { synced: "Synced", held: "Waiting for review", waiting: "Waiting", checking: "Checking", error: "Needs attention", off: "Off" };
  const kinds = { moved: "moved", assigned: "assigned", vacated: "freed", updated: "updated", restored: "restored" };
  let editing = false, timer, review = null;
  const canApply = () => !!review?.id && !review.report?.errors?.length && !!review.report?.changes?.length;
  const api = (url, options = {}) => window.AtlasClient.request(url, { ...options, atlasSilent: true });
  const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const when = (value) => {
    const date = value && new Date(value);
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—";
  };
  const describe = (counts = {}) => Object.entries(counts).map(([kind, n]) => `${n} ${kinds[kind] || kind}`).join(", ") || "no changes";
  const item = (text, tone) => {
    const li = document.createElement("li");
    li.textContent = text;
    if (tone) li.className = tone;
    return li;
  };
  function list(title, entries, tone) {
    if (!entries?.length) return null;
    const box = document.createElement("details");
    box.className = "atlas-live-plan-notes";
    const summary = document.createElement("summary");
    summary.innerHTML = `<span class="${tone}">${entries.length}</span> ${title}`;
    const ul = document.createElement("ul");
    ul.append(...entries.slice(0, 200).map((text) => item(text)));
    box.append(summary, ul);
    return box;
  }

  function render(data) {
    if (!editing) {
      $("live-plan-folder").value = data.folder || "";
      $("live-plan-enabled").checked = !!data.enabled;
      $("live-plan-review").checked = data.review_large !== false;
    }
    const status = data.status || {}, state = status.state || "off";
    $("live-plan-state").className = tones[state] || "";
    $("live-plan-state").textContent = labels[state] || state;
    $("live-plan-message").textContent = status.message || "";
    $("live-plan-message").dataset.tone = state === "error" ? "bad" : "";
    const details = $("live-plan-details"), last = data.last;
    details.replaceChildren();
    if (last) {
      const facts = document.createElement("p");
      facts.textContent = `${last.file} · saved ${when(last.modified)} · ${last.desks} desks read · last checked ${when(data.checked)}`;
      details.append(facts);
      const reader = last.reader || {};
      const tabs = Object.entries(reader.sheets || {});
      if (tabs.length) {
        const read = document.createElement("p");
        read.className = "atlas-live-plan-tabs";
        read.textContent = "Tabs read: " + tabs.map(([name, n]) => `${name} (${n})`).join(" · ") +
          (reader.hidden_sheets?.length ? ` · hidden tabs skipped: ${reader.hidden_sheets.join(", ")}` : "");
        details.append(read);
      }
      const notes = [
        list("notes · the plan was applied as written", last.notes || [], "status-warn"),
        list("desk codes corrected", (reader.fixes || []).map((f) => `${f.written} → ${f.desk} (${f.cell})`), "status-warn"),
        list("names linked to a slightly different directory name (plan wording kept)", (reader.matched_partly || []).map((x) => `${x.name} → ${x.directory} (${x.account}) · ${x.desk} · ${{ fuller: "fuller name", paris: "same name, the one in Paris", spelling: "spelling corrected" }[x.how] || x.how}`), "status-ok"),
        list("names not matched to one person (shown as written)", (reader.not_in_directory || []).map((x) => `${x.name} · ${x.desk}${x.ambiguous ? " · several people share this name" : ""}`), "status-warn"),
        list("desk codes not on the map (skipped)", (reader.unknown_desks || []).map((x) => `${x.desk} ${x.label ? "· " + x.label : ""} (${x.cell})`), "status-bad"),
        list("desk codes with nothing written beside them (desk left as it is)", (reader.blank || []).map((x) => `${x.desk} (${x.cell})`), "status-warn"),
        list("desk codes on another floor's tab (check the code)", (reader.other_floor || []).map((x) => `${x.desk}${x.label ? " · " + x.label : ""} (${x.cell})`), "status-warn"),
        list("desks with two different names in the plan", (reader.conflicts || []).map((x) => `${x.desk}: ${x.labels.join(" / ")} (${x.cells.join(", ")})`), "status-bad"),
      ].filter(Boolean);
      details.append(...notes);
    }
    const twice = list("people on more than one desk now", (data.duplicates || []).map((p) => `${p.name} · ${p.desks.join(", ")}`), "status-bad");
    if (twice) { twice.classList.add("atlas-live-plan-duplicates"); details.prepend(twice); }
    else if (data.duplicates) { const none = document.createElement("p"); none.className = "atlas-live-plan-no-duplicates"; none.innerHTML = '<span class="status-ok">No duplicates</span> nobody is on more than one desk.'; details.prepend(none); }
    const held = review = data.held || null;
    $("live-plan-apply").disabled = !canApply();
    $("live-plan-held").hidden = !held;
    if (held) {
      $("live-plan-held-reason").textContent = `${held.file}: ${held.reason}`;
      const changes = held.report?.changes || [];
      $("live-plan-changes").replaceChildren(
        ...(held.report?.errors || []).map((text) => item(text, "status-bad")),
        ...changes.slice(0, 300).map((c) => item(`${c.desk} · ${kinds[c.kind] || c.kind}${c.from_desk ? " from " + c.from_desk : ""}: ${c.before.name} → ${c.after.name}`)),
        ...(changes.length > 300 ? [item(`… and ${changes.length - 300} more`)] : []),
      );
    }
    $("live-plan-history").replaceChildren(...(data.history || []).map((h, index) => {
      const li = item(`${when(h.at)} · ${h.file} · ${describe(h.counts)}${h.undone ? " · undone" : ""}`);
      if (h.backup && !h.undone && index < 10) {
        const undo = document.createElement("button");
        undo.type = "button";
        undo.className = "atlas-live-plan-undo";
        undo.textContent = "Undo";
        undo.title = "Put these desks back as they were before this update";
        undo.onclick = () => {
          const n = h.desks?.length;
          if (!confirm(`Put ${n ? n + " desks" : "the desks from this update"} back as they were before ${when(h.at)}? Atlas backs up first.`)) return;
          act(undo, () => post("/api/seating-sync/undo", { backup: h.backup }));
        };
        li.append(" ", undo);
      }
      return li;
    }));
    if (!(data.history || []).length) $("live-plan-history").append(item("No live updates yet."));
  }

  async function refresh() {
    clearTimeout(timer);
    try { render(await api("/api/seating-sync")); }
    catch (error) { $("live-plan-message").textContent = "Live floor plan unavailable: " + error.message; }
    if (!document.hidden) timer = setTimeout(refresh, 15000);
  }
  async function act(button, task) {
    button.disabled = true;
    try { render(await task()); }
    catch (error) { $("live-plan-message").textContent = error.message; $("live-plan-message").dataset.tone = "bad"; }
    finally { button.disabled = button.id === "live-plan-apply" ? !canApply() : false; }
  }
  $("live-plan-folder").addEventListener("input", () => (editing = true));
  $("live-plan-enabled").addEventListener("change", () => (editing = true));
  $("live-plan-review").addEventListener("change", () => (editing = true));
  $("live-plan-save").onclick = () => act($("live-plan-save"), async () => {
    const result = await post("/api/seating-sync/settings", { folder: $("live-plan-folder").value, enabled: $("live-plan-enabled").checked, review_large: $("live-plan-review").checked });
    editing = false;
    return result;
  });
  $("live-plan-check").onclick = () => act($("live-plan-check"), () => post("/api/seating-sync/check"));
  $("live-plan-apply").onclick = () => {
    if (!canApply()) return;
    const id = review.id, count = review.report.changes.length;
    if (!confirm(`Apply ${count} seating change${count === 1 ? "" : "s"} from the plan? Atlas backs up first.`)) return;
    act($("live-plan-apply"), async () => {
      try { return await post("/api/seating-sync/apply", { id }); }
      catch (error) { await refresh(); throw error; }
    });
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  if (window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content === "viewer") {
    $("live-plan").hidden = true;
    return;
  }
  refresh();
  window.AtlasLivePlanSettings = { refresh };
})();
