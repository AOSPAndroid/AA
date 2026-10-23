(() => {
  const $ = (id) => document.getElementById(id);
  let staged = null,
    working = false,
    operation = "",
    interacted = false;
  const esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const api = (url, opts = {}) =>
    window.AtlasClient.request(url, { ...opts, atlasSilent: true });
  function message(text, scope = "directory") {
    $(scope === "review" ? "review-message" : "directory-message").textContent =
      text;
    $("message").textContent = text;
  }
  function resetPreview() {
    staged = null;
    $("preview").hidden = true;
    $("full").checked = false;
    $("confirm").value = "";
  }
  function controls() {
    $("apply").disabled =
      working ||
      !staged ||
      !$("full").checked ||
      $("confirm").value !== "APPLY";
    $("validate").disabled = working;
    $("file").disabled = working;
    $("cancel").disabled = working;
    $("full").disabled = working;
    $("confirm").disabled = working;
    $("validate").textContent =
      operation === "validate" ? "Validating…" : "Validate and preview";
    $("apply").textContent =
      operation === "apply" ? "Applying…" : "Back up and apply";
    $("directory-progress").hidden =
      !working || operation === "apply" || operation === "cancel";
    $("review-progress").hidden =
      !working || (operation !== "apply" && operation !== "cancel");
    document
      .querySelector('[data-database-controls="directory"]')
      .setAttribute("aria-busy", String(!$("directory-progress").hidden));
    document
      .querySelector('[data-database-controls="directory-review"]')
      .setAttribute("aria-busy", String(!$("review-progress").hidden));
    document
      .querySelectorAll("[data-restore]")
      .forEach((b) => (b.disabled = working));
  }
  async function task(action, fn) {
    if (working) return;
    interacted = true;
    working = true;
    operation = action;
    controls();
    try {
      await fn();
    } catch (e) {
      message(
        e.message + " You can try again.",
        action === "apply" || action === "cancel" ? "review" : "directory",
      );
    } finally {
      working = false;
      operation = "";
      controls();
    }
  }
  async function status(summary = !interacted) {
    const d = await api("/api/database/status");
    if ($("coverage") && d.coverage)
      $("coverage").innerHTML = coverage(d.coverage);
    if (summary && !interacted)
      $("message").textContent =
        `${d.counts.users.toLocaleString()} users · ${d.counts.machines.toLocaleString()} machines · ${d.counts.assignments.toLocaleString()} relationships${d.busy ? " — jobs active; imports are blocked." : ""}`;
    $("history").innerHTML = d.history.length
      ? d.history
          .map(
            (r) =>
              `<article><b>${esc(r.source)}</b><p>${esc(r.at)}</p><button data-restore="${esc(r.id)}">Restore directory before this import</button></article>`,
          )
          .join("")
      : "<p>No GUI imports yet. Existing directory and command-line refreshes are not listed here.</p>";
    document.querySelectorAll("[data-restore]").forEach(
      (b) =>
        (b.onclick = () =>
          task("restore", async () => {
            resetPreview();
            message("Preparing backup comparison…");
            show(
              await api("/api/database/restore-preview/" + b.dataset.restore, {
                method: "POST",
              }),
            );
          })),
    );
    controls();
  }
  function show(d) {
    staged = d.id;
    $("source").textContent = d.source;
    $("full").checked = false;
    $("confirm").value = "";
    $("changes").innerHTML = ["users", "machines", "relationships"]
      .map((k) => {
        const x = d.report[k];
        return `<article><b>${esc(k)}</b><p>${x.before.toLocaleString()} → ${x.after.toLocaleString()}</p><p>+${x.added} added · −${x.removed} removed${x.changed !== undefined ? " · " + x.changed + " changed" : ""}</p></article>`;
      })
      .join("");
    const resolution=d.report.import_resolution || {};
    const duplicates=(resolution.user?.duplicate_rows || 0)+(resolution.machine?.duplicate_rows || 0);
    if (duplicates || resolution.mobile_identity_rows)
      $("changes").insertAdjacentHTML("beforeend",`<article><h3>Extract handled automatically</h3><p>${duplicates.toLocaleString()} duplicate rows consolidated · ${(resolution.mobile_identity_rows || 0).toLocaleString()} mobile rows identified by hardware ID or source row.</p><p>Every original row and column is retained. Separate phones stay separate.</p></article>`);
    if (d.report.coverage)
      $("changes").insertAdjacentHTML(
        "beforeend",
        `<article><h3>Incoming export columns</h3>${coverage(d.report.coverage)}</article>`,
      );
    $("warnings").textContent = [
      ...d.report.warnings,
      `${d.report.unlinked_machine_references} machines have user references but no resolved relationship.`,
      `${d.report.missing_desk_accounts.length} confirmed desk links point to accounts absent from this extract.`,
    ].join(" ");
    $("examples").textContent = JSON.stringify(
      {
        added_users: d.report.users.added_examples,
        removed_users: d.report.users.removed_examples,
        added_machines: d.report.machines.added_examples,
        removed_machines: d.report.machines.removed_examples,
        missing_desk_accounts: d.report.missing_desk_accounts,
        duplicate_records: resolution,
      },
      null,
      2,
    );
    $("preview").hidden = false;
    message(
      "Preview ready. No directory data has changed. Review the changes below; the preview expires after one hour.",
    );
    $("review-message").textContent =
      "Review the removals, confirm the complete snapshot, then type APPLY to enable saving.";
    $("preview").scrollIntoView({ block: "start", behavior: "instant" });
  }
  const megabytes = (files) => (files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024).toFixed(1);
  $("file").onchange = () => {
    interacted = true;
    resetPreview();
    const files = [...($("file").files || [])];
    message(
      files.length
        ? `${files.map((file) => file.name).join(" + ")} selected · ${megabytes(files)} MB. Click Validate and preview. Large extracts can take a few minutes.`
        : "Choose your users and devices exports (or one workbook), then validate.",
    );
    controls();
  };
  // Drop the two exports (or a workbook) straight onto the Users & devices card.
  const dropZone = $("directory-import");
  dropZone.addEventListener("dragover", (event) => {
    if (working || !event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    dropZone.dataset.drop = "true";
  });
  dropZone.addEventListener("dragleave", () => delete dropZone.dataset.drop);
  dropZone.addEventListener("drop", (event) => {
    delete dropZone.dataset.drop;
    if (working || !event.dataTransfer?.files?.length) return;
    event.preventDefault();
    $("file").files = event.dataTransfer.files;
    $("file").onchange();
  });
  $("validate").onclick = () =>
    task("validate", async () => {
      resetPreview();
      const files = [...($("file").files || [])];
      if (!files.length) throw Error("Choose an Excel workbook, or your users and devices exports.");
      if (files.length > 2) throw Error("Choose one workbook, or exactly two exports: users and devices.");
      if (files.length === 2) {
        if (files.some((file) => !/\.(xlsx|csv)$/i.test(file.name)))
          throw Error("Use the .xlsx or .csv exports from ServiceNow.");
        if (files.some((file) => file.size > 50 * 1024 * 1024))
          throw Error("Each export must be under the 50 MB upload limit.");
        message(`Combining ${files[0].name} and ${files[1].name}, then comparing… Large extracts can take a few minutes. Keep this page open.`);
        const result = await api("/api/database/preview-pair", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-First-Size": String(files[0].size),
            "X-First-Name": encodeURIComponent(files[0].name),
            "X-Second-Name": encodeURIComponent(files[1].name),
          },
          body: new Blob(files),
        });
        show(result);
        const { users_file, devices_file, rows } = result.pair || {};
        if (users_file)
          $("source").textContent = `Users: ${users_file} (${(rows?.users ?? 0).toLocaleString()} rows) · Devices: ${devices_file} (${(rows?.devices ?? 0).toLocaleString()} rows)`;
        return;
      }
      const [file] = files;
      if (!file.name.toLowerCase().endsWith(".xlsx"))
        throw Error("Use an .xlsx workbook with users and devices tabs, or select both exports together.");
      if (file.size > 50 * 1024 * 1024)
        throw Error("Excel file exceeds the 50 MB upload limit.");
      message(
        `Validating ${file.name} and comparing your extract… Large extracts can take a few minutes. Keep this page open.`,
      );
      show(
        await api("/api/database/preview", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-File-Name": encodeURIComponent(file.name),
          },
          body: file,
        }),
      );
    });
  $("apply").onclick = () =>
    task("apply", async () => {
      message("Backing up and applying directory changes…", "review");
      const d = await api("/api/database/apply/" + staged, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation: $("confirm").value,
          full_snapshot: $("full").checked,
        }),
      });
      resetPreview();
      const completed =
        "Import completed. Backup: " +
        d.backup +
        "\nReload any open Atlas or console tabs to refresh displayed records.";
      message(completed);
      try {
        await status(false);
      } catch {
        message(
          completed +
            "\nCounts and history could not refresh. Reload this page to see them.",
        );
      }
    });
  $("cancel").onclick = () =>
    task("cancel", async () => {
      message("Discarding preview…", "review");
      if (staged)
        await api("/api/database/preview/" + staged, { method: "DELETE" });
      resetPreview();
      message("Preview discarded. Directory unchanged.");
    });
  $("full").onchange = controls;
  $("confirm").oninput = controls;
  function coverage(data) {
    return (
      `<p>${data.original_cells ? "Original export cells retained, including additional columns and sheets." : "This database predates original-cell retention. The stored directory columns are listed below; the next directory refresh will also retain original cells."}</p>` +
      data.sheets
        .map(
          (sheet) =>
            `<details><summary>${esc(sheet.sheet)} · ${sheet.columns.length} columns · ${sheet.rows.toLocaleString()} rows</summary><p>${esc(sheet.source)} · ${sheet.linked.toLocaleString()} rows linked to directory records</p><div style="overflow-x:auto"><table><thead><tr><th>Export column</th><th>Populated</th><th>Used in Atlas</th></tr></thead><tbody>${sheet.columns.map((col) => `<tr><td>${esc(col.header)}</td><td>${col.populated.toLocaleString()} / ${sheet.rows.toLocaleString()}</td><td>${esc(col.label)} · ${esc(col.use)}</td></tr>`).join("")}</tbody></table></div></details>`,
        )
        .join("")
    );
  }
  // Direct updater commands focus the matching workflow without opening a file dialog.
  function focusUploadSection() {
    const section = document.getElementById(location.hash.slice(1));
    if (!section?.classList.contains("atlas-upload-section")) return;
    section.tabIndex = -1;
    section.focus({ preventScroll: true });
    section.scrollIntoView({ block: "start", behavior: "instant" });
  }
  window.addEventListener("hashchange", focusUploadSection);
  focusUploadSection();
  // Loading counts and history must not disable uploads. Mutation requests
  // acquire a session lazily and recover on the next click after expiry.
  controls();
  status().catch((e) => {
    if (!interacted)
      $("message").textContent =
        "Database status unavailable: " +
        e.message +
        " You can still validate a workbook.";
  });
})();
