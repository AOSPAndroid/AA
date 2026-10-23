(() => {
  const $ = (id) => document.getElementById("seating-" + id);
  let stage = null,
    working = false;
  async function api(path, options = {}) {
    const state = await fetch("/api/session");
    if (!state.ok) throw Error("Cannot connect to Atlas.");
    const token = (await state.json()).token;
    const r = await fetch(path, {
      ...options,
      headers: { "X-Atlas-Token": token, ...options.headers },
    });
    const d = await r.json();
    if (!r.ok) throw Error(d.detail || "Request failed");
    return d;
  }
  function controls() {
    ["preview", "file", "layout", "complete"].forEach(
      (id) => ($(id).disabled = working),
    );
    $("apply").disabled = working || !stage || $("confirm").value !== "APPLY";
  }
  function reset() {
    stage = null;
    $("result").hidden = true;
    $("confirm").value = "";
    $("export").href = "/api/seating-excel/export?layout=" + $("layout").value;
    controls();
  }
  async function task(fn) {
    if (working) return;
    working = true;
    controls();
    try {
      await fn();
    } catch (e) {
      $("message").textContent = e.message;
    } finally {
      working = false;
      controls();
    }
  }
  function list(id, items) {
    $(id).replaceChildren(
      ...items.map((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
      }),
    );
  }
  async function history() {
    const rows = await api("/api/seating-excel/history");
    list(
      "history",
      rows.length
        ? rows.map((r) => `${r.at} · ${r.source} · ${r.changes} desk changes`)
        : ["No seating Excel imports yet."],
    );
  }
  ["file", "layout", "complete"].forEach((id) => ($(id).onchange = reset));
  $("confirm").oninput = controls;
  $("preview").onclick = () =>
    task(async () => {
      reset();
      const file = $("file").files[0];
      if (!file || !file.name.toLowerCase().endsWith(".xlsx"))
        throw Error("Choose an .xlsx seating workbook.");
      $("message").textContent = "Comparing the sheet with the saved seating…";
      const d = await api(
        "/api/seating-excel/preview?layout=" +
          $("layout").value +
          "&complete=" +
          $("complete").checked,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-File-Name": encodeURIComponent(file.name),
          },
          body: file,
        },
      );
      const r = d.report;
      stage = d.id;
      $("result").hidden = false;
      $("counts").textContent =
        `${r.changes.length} desk changes · ${r.unchanged} unchanged · ${r.omitted} desks omitted from the sheet. ${r.complete ? "Omitted desks are set to vacant." : "Omitted desks stay unchanged, except the source of a recognised move."}`;
      $("errors").replaceChildren();
      if (r.errors.length) {
        const title = document.createElement("b");
        title.textContent = "Resolve these conflicts and upload again:";
        $("errors").append(title);
        for (const e of r.errors) {
          const p = document.createElement("p");
          p.textContent = e;
          $("errors").append(p);
        }
      }
      list(
        "warnings",
        r.warnings.length ? r.warnings : ["No account or data warnings."],
      );
      $("changes").replaceChildren();
      const describe = (x) =>
        `${x.name} · ${x.team} · ${x.status}${x.account ? " · " + x.account : ""}`;
      for (const ch of r.changes) {
        const tr = document.createElement("tr");
        for (const value of [
          ch.desk,
          ch.kind +
            (ch.from_desk ? " from " + ch.from_desk : "") +
            " (" +
            ch.fields.join(", ") +
            ")",
          describe(ch.before),
          describe(ch.after),
        ]) {
          const td = document.createElement("td");
          td.textContent = value;
          td.style.cssText =
            "padding:10px 8px;border-bottom:1px solid #cbd5e1;vertical-align:top";
          tr.append(td);
        }
        $("changes").append(tr);
      }
      $("message").textContent = r.errors.length
        ? "Import blocked. No data has changed."
        : stage
          ? "Changes detected. Review before applying. Preview expires after one hour."
          : "No changes detected. The sheet already matches the saved seating.";
    });
  $("apply").onclick = () =>
    task(async () => {
      $("message").textContent = "Backing up and applying seating changes…";
      const d = await api("/api/seating-excel/apply/" + stage, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: $("confirm").value }),
      });
      reset();
      $("message").textContent =
        `${d.changes} desk changes saved. Backup: ${d.backup}. Reload the Atlas to see them.`;
      await history();
    });
  task(history);
})();
