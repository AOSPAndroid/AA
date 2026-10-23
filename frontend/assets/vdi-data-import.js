/* Citrix inventory is supplemental; this workflow never replaces ServiceNow data. */
(() => {
  const $ = (id) => document.getElementById("vdi-data-" + id);
  if (!$("file")) return;
  const api = (url, options = {}) =>
    AtlasClient.request(url, { ...options, atlasSilent: true });
  const readonly = () =>
    !!window.AtlasReadOnly ||
    document.querySelector('meta[name="atlas-mode"]')?.content === "viewer";
  const count = (value) =>
    Number.isFinite(value) ? value.toLocaleString() : "0";
  const text = (value) => (value == null ? "" : String(value));
  const message = (value) => {
    $("message").textContent = value;
  };
  let staged = null,
    working = false,
    interacted = false,
    operation = "",
    revision = 0,
    statusRevision = 0;
  function clear() {
    staged = null;
    $("review").hidden = true;
  }
  function controls() {
    const blocked = working || readonly();
    $("file").disabled = blocked;
    $("full").disabled = blocked;
    $("validate").disabled = blocked;
    $("apply").disabled = blocked || !staged;
    $("cancel").disabled = blocked;
    $("progress").hidden = !working;
    $("controls").setAttribute("aria-busy", String(working));
    $("validate").textContent =
      operation === "validate" ? "Validating…" : "Validate and preview";
    $("apply").textContent =
      operation === "apply" ? "Saving…" : "Back up and save VDI data";
  }
  function mode() {
    $("mode").textContent = $("full").checked
      ? "Complete VDI snapshot: omitted VDI machines will be removed. ServiceNow inventory is unchanged."
      : "Merge update: VDI machines omitted from this export are retained.";
  }
  async function status() {
    const version = ++statusRevision;
    const data = await api("/api/vdi-data/import/status");
    if (version !== statusRevision) return;
    $("status").textContent =
      `${count(data.count)} VDI machines${data.last_import ? ` · Last import: ${text(data.last_import.source)} · ${text(data.last_import.at)}` : " · No imports yet"}`;
  }
  async function task(kind, action) {
    if (working) return;
    if (readonly()) {
      message("VDI uploads are available in Admin.");
      controls();
      return;
    }
    interacted = true;
    working = true;
    operation = kind;
    const version = revision;
    controls();
    try {
      await action();
    } catch (error) {
      if (kind !== "validate" || version === revision)
        message(error.message + " You can try again.");
    } finally {
      working = false;
      operation = "";
      controls();
    }
  }
  const account = (row) =>
    typeof row === "string"
      ? row
      : text(row.account ?? row.user ?? row.username ?? row.raw);
  const reason = (value) =>
    ({
      unknown_account: "No matching username",
      invalid_account: "Not a valid account name",
      invalid_machine_name: "Machine name cannot be used for user links",
      domain_mismatch: "Domain differs from the directory account",
    })[value] || text(value).replaceAll("_", " ");
  function show(data, fullSnapshot) {
    if (!data.id || data.full_snapshot !== fullSnapshot)
      throw Error(
        "The preview mode does not match this upload. Validate again.",
      );
    const r = data.report;
    $("source").textContent =
      `${text(data.source)} · ${fullSnapshot ? "Complete VDI snapshot" : "Merge update"}`;
    $("summary").textContent =
      `${count(r.rows)} source rows · ${count(r.unique)} VDI machines · ${count(r.added)} new · ${count(r.changed)} updated · ${count(r.removed)} removed · ${count(r.retained)} existing VDI records retained · ${count(r.after)} machines after saving`;
    $("user-summary").textContent =
      `${r.associations != null ? `${count(r.associations)} linked user associations · ` : ""}${count(r.matched_users)} matched · ${count(r.unmatched_users)} unmatched · ${count(r.ambiguous_users)} ambiguous account references. Every account in a multi-user cell is kept.`;
    $("warnings").textContent = [
      ...(r.warnings || []),
      r.duplicates
        ? `${count(r.duplicates)} repeated machine rows reconciled.`
        : "",
      r.invalid_machines
        ? `${count(r.invalid_machines)} source rows have no usable machine name; review the preserved source records.`
        : "",
    ]
      .filter(Boolean)
      .join(" ");
    const userExamples = [
      ...(r.unmatched_examples || []).map(
        (row) =>
          `${account(row)}${row.machine_name ? " · " + row.machine_name : ""} · Unmatched${row.reason ? " · " + reason(row.reason) : ""}`,
      ),
      ...(r.ambiguous_examples || []).map(
        (row) =>
          `${account(row)}${row.machine_name ? " · " + row.machine_name : ""} · Ambiguous${row.matches ? " · " + count(Array.isArray(row.matches) ? row.matches.length : row.matches) + " possible users" : ""}`,
      ),
    ];
    $("user-warnings").hidden = !userExamples.length;
    $("user-examples").textContent = userExamples.join("\n");
    const recordExamples = (r.collision_examples || []).map((row) =>
      typeof row === "string"
        ? row
        : `${text(row.short_name ?? row.machine_name ?? row.name)}${row.machines ? " · " + row.machines.join(", ") : ""}${row.reason ? " · " + row.reason : ""}`,
    );
    $("record-warnings").hidden = !recordExamples.length;
    $("record-examples").textContent = recordExamples.join("\n");
    $("removals").hidden = !fullSnapshot || !r.removed;
    $("removed-examples").textContent =
      (r.removed_examples || [])
        .map((row) =>
          typeof row === "string" ? row : text(row.machine_name ?? row.name),
        )
        .join("\n") ||
      "Review the removal count above. Only omitted VDI records are removed.";
    const columns = r.columns || r.source_columns || [];
    $("columns").textContent = columns.length
      ? "Original columns retained: " + columns.join(", ")
      : "All original rows and export columns are retained.";
    $("examples").textContent =
      (r.machine_examples || r.examples || [])
        .map(
          (row) =>
            `${text(row.machine_name ?? row.name)} · ${text(row.catalog ?? row.machine_catalog) || "No catalogue"} · ${text(row.delivery_group) || "No delivery group"} · ${(row.users || []).map(account).join(", ") || "No assigned users"}`,
        )
        .join("\n") ||
      "All machine records and user associations are retained in the import.";
    staged = Object.freeze({ id: data.id, full_snapshot: fullSnapshot });
    $("review").hidden = false;
    message(
      `Preview ready. Review the VDI changes, then save. Preview expires in ${count(data.expires_minutes || 60)} minutes.`,
    );
  }
  function changed() {
    interacted = true;
    revision++;
    clear();
    mode();
    const file = $("file").files[0];
    message(
      file
        ? `${file.name} selected. Validate again to review ${$("full").checked ? "the complete VDI snapshot" : "this merge update"}.`
        : "Choose your Citrix CSV or Excel export.",
    );
    controls();
  }
  $("file").onchange = changed;
  $("full").onchange = changed;
  $("validate").onclick = () =>
    task("validate", async () => {
      clear();
      const file = $("file").files[0],
        version = revision,
        fullSnapshot = $("full").checked;
      if (!file || !/\.(csv|xlsx)$/i.test(file.name))
        throw Error("Choose a Citrix .csv or .xlsx export.");
      if (file.size > 50 * 1024 * 1024)
        throw Error("VDI export exceeds 50 MB.");
      message(
        "Reading the raw Citrix export and comparing VDI records and user associations…",
      );
      const data = await api(
        "/api/vdi-data/import/preview?full_snapshot=" + fullSnapshot,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-File-Name": encodeURIComponent(file.name),
          },
          body: file,
        },
      );
      if (version === revision) show(data, fullSnapshot);
    });
  $("apply").onclick = () =>
    task("apply", async () => {
      if (!staged) throw Error("Validate a VDI export before saving.");
      const preview = staged;
      message("Backing up and saving VDI records…");
      const result = await api(
        "/api/vdi-data/import/apply/" + encodeURIComponent(preview.id),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ full_snapshot: preview.full_snapshot }),
        },
      );
      clear();
      const completed = `VDI data saved: ${count(result.count)} machines. Backup: ${text(result.backup)}. Refresh the user or machine profile in other open Atlas windows.`;
      message(completed);
      try {
        await status();
      } catch {
        message(
          completed + " Import status could not refresh; reload this page.",
        );
      }
    });
  $("cancel").onclick = () =>
    task("cancel", async () => {
      if (staged)
        await api(
          "/api/vdi-data/import/preview/" + encodeURIComponent(staged.id),
          { method: "DELETE" },
        );
      clear();
      message("VDI preview discarded. Inventory unchanged.");
    });
  mode();
  controls();
  if (readonly()) {
    $("status").textContent = "VDI uploads are available in Admin.";
    message("Open Admin to update Citrix VDI inventory.");
  } else
    status().catch((error) => {
      if (!interacted)
        $("status").textContent =
          "VDI status unavailable: " +
          error.message +
          ". You can still validate an export.";
    });
})();
