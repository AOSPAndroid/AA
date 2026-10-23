/* Scripts: built-in and saved PowerShell scripts, run on the Atlas host against a list of
   machines. Atlas checks the machine names and adds them (with the values typed here) as
   PowerShell variables on the server; scripts that change machines ask before running. */
(() => {
  const get = (id) => document.getElementById("script" + id);
  if (!get("List")) return;
  const done = new Set(["complete", "failed", "stopped", "timed_out"]);
  const HOST = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$/;
  let library = { builtin: [], saved: [] }, current = null, runId = null, active = false, timer, loaded = false;

  const request = async (url, options = {}) =>
    AtlasClient.request(url, { ...options, headers: { "X-Atlas-Token": await AtlasClient.sessionToken(), ...(options.headers || {}) } });
  const send = (url, method, body) =>
    request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const message = (text, tone = "") => { get("Message").textContent = text; get("Message").dataset.tone = tone; };

  function targets() {
    const names = [], bad = [], seen = new Set();
    for (const raw of get("Targets").value.split(/[\s,;]+/)) {
      const name = raw.trim().replace(/^\\+/, "");
      if (!name) continue;
      if (!HOST.test(name)) bad.push(name);
      else if (!seen.has(name.toUpperCase())) { seen.add(name.toUpperCase()); names.push(name); }
    }
    return { names, bad };
  }
  function countTargets() {
    const { names, bad } = targets();
    get("TargetCount").textContent = `${names.length} machine${names.length === 1 ? "" : "s"}` + (bad.length ? ` · ${bad.length} not valid: ${bad.slice(0, 3).join(", ")}` : "");
    get("TargetCount").dataset.tone = bad.length ? "bad" : "";
  }

  // Lines from built-ins start with [OK]/[FAIL]/[WARN]/[INFO]; other scripts are read by their words.
  function tone(line) {
    const marked = line.match(/^\s*\[(OK|FAIL|WARN|INFO)\]/);
    if (marked) return { OK: "good", FAIL: "bad", WARN: "warn", INFO: "info" }[marked[1]];
    if (/^Atlas > /.test(line)) return "atlas";
    if (/\b(fail(ed|ure)?|error|denied|cannot|unable|refused|unavailable|exception)\b/i.test(line)) return "bad";
    if (/not found|warning|skipped/i.test(line)) return "warn";
    if (/\b(disabled|stopped|started|running|success(ful)?|requested|completed?|online|ok)\b/i.test(line)) return "good";
    return "";
  }
  function render(text) {
    const output = get("Output"), atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
    const counts = { good: 0, bad: 0, warn: 0 };
    output.replaceChildren(...text.split("\n").map((line) => {
      const span = document.createElement("span"), kind = tone(line);
      span.textContent = line + "\n";
      if (kind) span.dataset.tone = kind;
      if (kind in counts && /^\s*\[(OK|FAIL|WARN)\]/.test(line)) counts[kind]++;
      return span;
    }));
    if (atBottom) output.scrollTop = output.scrollHeight;
    const parts = [];
    if (counts.good) parts.push(`<span class="status-ok">${counts.good} OK</span>`);
    if (counts.bad) parts.push(`<span class="status-bad">${counts.bad} failed</span>`);
    if (counts.warn) parts.push(`<span class="status-warn">${counts.warn} warning${counts.warn === 1 ? "" : "s"}</span>`);
    get("Summary").innerHTML = parts.join(" ");
  }

  function controls() {
    const readonly = !!window.AtlasReadOnly, saved = current?.kind === "saved", builtin = current?.kind === "builtin";
    get("Run").disabled = readonly || active || !current;
    get("Stop").disabled = !active || !runId;
    get("Save").disabled = readonly || !current || builtin;
    get("Delete").disabled = readonly || !saved;
    get("Delete").hidden = !saved;
    get("Duplicate").disabled = !current;
    get("Download").disabled = !current;
    get("Code").readOnly = builtin;
    get("Name").readOnly = builtin || !current;
    get("Changes").disabled = builtin;
    get("Output").setAttribute("aria-busy", String(active));
  }

  function items() {
    const word = get("Search").value.trim().toLowerCase();
    const all = [...library.saved.map((item) => ({ ...item, category: "My scripts", kind: "saved" })),
      ...library.builtin.map((item) => ({ ...item, kind: "builtin" }))];
    return all.filter((item) => !word || [item.name, item.description, item.category].join(" ").toLowerCase().includes(word));
  }
  function renderList() {
    const list = get("List"), groups = new Map();
    for (const item of items()) {
      if (!groups.has(item.category)) groups.set(item.category, []);
      groups.get(item.category).push(item);
    }
    list.replaceChildren();
    if (!groups.size) {
      const empty = document.createElement("p");
      empty.className = "scripts-empty";
      empty.textContent = loaded ? "No script matches." : "Loading scripts…";
      list.append(empty);
    }
    for (const [category, rows] of groups) {
      const heading = document.createElement("h3");
      heading.textContent = category;
      list.append(heading);
      for (const item of rows) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "scripts-item";
        button.dataset.script = item.id;
        if (current && current.item.id === item.id && current.kind === item.kind) button.setAttribute("aria-current", "true");
        const name = document.createElement("strong"), badge = document.createElement("span"), about = document.createElement("small");
        name.textContent = item.name;
        badge.className = item.changes ? "status-warn" : "status-ok";
        badge.textContent = item.changes ? "Changes machines" : "Read-only";
        about.textContent = item.description || "";
        button.append(name, badge, about);
        button.onclick = () => choose(item.kind, item);
        list.append(button);
      }
    }
  }

  function paramField(param) {
    const label = document.createElement("label");
    label.textContent = param.label;
    let field;
    if (param.kind === "choice") {
      field = document.createElement("select");
      for (const option of param.options) field.add(new Option(option, option));
      field.value = param.default;
    } else {
      field = document.createElement("textarea");
      field.rows = Math.min(5, Math.max(2, String(param.default || "").split("\n").length));
      field.spellcheck = false;
      field.value = param.default || "";
    }
    field.dataset.param = param.name;
    label.append(field);
    return label;
  }
  function values() {
    return Object.fromEntries([...get("Params").querySelectorAll("[data-param]")].map((field) => [field.dataset.param, field.value]));
  }
  const psQuote = (text) => "'" + String(text).replace(/'/g, "''") + "'";
  const listValues = (text) => text.split(/[\r\n,;]+/).map((x) => x.trim()).filter(Boolean);
  // A duplicate keeps the selected values; Atlas supplies its helpers when it runs.
  function selfContained() {
    const lines = (current.item.params || []).map((param) => {
      const value = values()[param.name] ?? param.default ?? "";
      return param.kind === "choice" ? `$${param.name} = ${psQuote(value)}`
        : `$${param.name} = @(${listValues(value).map(psQuote).join(", ")})`;
    });
    return (lines.length ? lines.join("\n") + "\n" : "") + get("Code").value.trim() + "\n";
  }

  function downloadCode() {
    if (!library.export_helpers) throw Error("Reload Scripts before downloading so its helper functions are included.");
    const helpers = library.export_helpers.trim() + "\n";
    const code = get("Code").value.trim() + "\n";
    if (current.kind !== "builtin") {
      // Keep a custom param() block first in its scope and forward command-line arguments.
      // Native Read-Host continues to prompt in a standalone PowerShell session.
      return "# Set these names if your script uses $Computers without declaring its own parameter.\n$Computers = @()\n"
        + helpers + "\n& {\n" + code + "} @args\n";
    }
    const parameters = [
      `[Parameter(Mandatory=$true)][ValidateCount(1, 500)][ValidatePattern(${psQuote(HOST.source)})][string[]]$Computers`,
      ...(current.item.params || []).map((param) => {
        const value = values()[param.name] ?? param.default ?? "";
        if (param.kind === "choice") {
          return `[ValidateSet(${param.options.map(psQuote).join(", ")})][string]$${param.name} = ${psQuote(value)}`;
        }
        const items = listValues(value);
        return (items.length ? "" : "[Parameter(Mandatory=$true)]") + `[ValidateNotNullOrEmpty()][string[]]$${param.name}`
          + (items.length ? ` = @(${items.map(psQuote).join(", ")})` : "");
      }),
    ];
    return "param(\n    " + parameters.join(",\n    ") + "\n)\n$ErrorActionPreference = \"Continue\"\n" + helpers + "\n" + code;
  }

  function choose(kind, item) {
    current = { kind, item };
    get("Name").value = item.name;
    get("Description").textContent = item.description || (kind === "draft" ? "New script: write PowerShell that uses $Computers." : "");
    get("Kind").className = item.changes ? "status-warn" : "status-ok";
    get("Kind").textContent = kind === "builtin" ? (item.changes ? "Built-in · changes machines" : "Built-in · read-only") : item.changes ? "Changes machines" : "Read-only";
    get("Params").replaceChildren(...(item.params || []).map(paramField));
    get("Code").value = (item.code || "").trim() + "\n";
    get("Changes").checked = item.changes !== false;
    get("CodeNote").textContent = kind === "builtin"
      ? "· read-only; Duplicate to edit"
      : "· $Computers holds the target machines; Read-Host answers with them too";
    get("CodeBox").open = kind !== "builtin";
    message("");
    controls();
    renderList();
  }

  function slug(name) {
    const base = name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "script";
    const taken = new Set([...library.saved, ...library.builtin].map((item) => item.id));
    let id = base, n = 2;
    while (taken.has(id)) id = `${base}-${n++}`;
    return id;
  }

  async function load(select) {
    try {
      library = await AtlasClient.request("/api/script-library", { atlasSilent: true });
      loaded = true;
    } catch (error) {
      loaded = true;
      message(window.AtlasReadOnly ? "Scripts run in Atlas Admin on the support PC." : "Scripts unavailable: " + error.message, "bad");
    }
    if (select) {
      const item = library.saved.find((x) => x.id === select) || library.builtin.find((x) => x.id === select);
      if (item) choose(library.saved.includes(item) ? "saved" : "builtin", item);
    } else if (!current) {
      const initial = library.builtin.find((item) => item.id === "online" && !item.changes)
        || library.builtin.find((item) => !item.changes);
      if (initial) choose("builtin", initial);
    }
    renderList();
  }

  async function poll() {
    try {
      const result = await request("/api/script-library/runs/" + runId, { atlasSilent: true });
      render((result.truncated ? "[Earlier output trimmed]\n" : "") + result.output);
      const status = get("Status");
      status.textContent = `${result.title} · ${result.target} · ${result.state}${result.exit_code == null ? "" : " · exit " + result.exit_code}`;
      status.dataset.tone = result.state === "complete" ? "good" : done.has(result.state) ? "bad" : "";
      active = !done.has(result.state);
      controls();
      if (active) timer = setTimeout(poll, 1000);
    } catch (error) {
      message("Connection lost: " + error.message + " Checking the same run again; nothing is rerun.", "bad");
      timer = setTimeout(poll, 5000);
    }
  }

  async function run() {
    if (!current || active || window.AtlasReadOnly) return;
    const { names, bad } = targets();
    if (bad.length) return message(`Fix these machine names first: ${bad.slice(0, 5).join(", ")}`, "bad");
    if (!names.length) return message("Add at least one target machine.", "bad");
    if (current.kind === "builtin") {
      for (const param of current.item.params || []) {
        if (param.kind === "list" && !listValues(values()[param.name] || "").length)
          return message(`${param.label}: enter at least one value.`, "bad");
      }
    }
    const changes = current.kind === "builtin" ? current.item.changes : get("Changes").checked;
    if (changes) {
      const shown = names.slice(0, 15).join("\n") + (names.length > 15 ? `\n… and ${names.length - 15} more` : "");
      if (!confirm(`"${get("Name").value}" will change ${names.length} machine${names.length === 1 ? "" : "s"}:\n\n${shown}\n\nRun it now?`)) return;
    }
    // Your own scripts are confirmed above when ticked "Changes machines"; built-ins always declare it.
    const id = crypto.randomUUID(), body = { id, script: current.item.id, targets: names.join("\n"), values: values(), confirmed: changes || current.kind !== "builtin" };
    if (current.kind !== "builtin") body.code = get("Code").value;
    if (current.kind === "draft") body.script = "draft";
    active = true; runId = null; controls(); message("");
    get("Status").textContent = "Starting…"; get("Status").dataset.tone = "";
    get("Summary").replaceChildren(); get("Output").replaceChildren();
    try {
      await send("/api/script-library/run", "POST", body);
      runId = id; poll();
    } catch (error) {
      // Reconcile only this ID after an uncertain start; never launch it twice.
      try { await request("/api/script-library/runs/" + id, { atlasSilent: true }); runId = id; poll(); }
      catch { active = false; get("Status").textContent = "Not started"; get("Status").dataset.tone = "bad"; message(error.message, "bad"); controls(); }
    }
  }

  async function save() {
    if (!current || current.kind === "builtin") return;
    const name = get("Name").value.trim();
    if (!name) return message("Give the script a name first.", "bad");
    const id = current.kind === "saved" ? current.item.id : slug(name);
    try {
      const item = await send("/api/script-library/saved/" + id, "PUT", {
        name, description: current.item.description || "", changes: get("Changes").checked,
        code: get("Code").value, revision: current.kind === "saved" ? current.item.revision : 0,
      });
      await load(item.id);
      message(`Saved "${item.name}".`, "good");
    } catch (error) { message(error.message, "bad"); }
  }

  function duplicate() {
    if (!current) return;
    const code = current.kind === "builtin" ? selfContained() : get("Code").value;
    choose("draft", { id: "draft", name: get("Name").value + " (copy)", description: current.item.description || "",
      changes: current.kind === "builtin" ? current.item.changes : get("Changes").checked, code, params: [] });
    get("Name").focus(); get("Name").select();
    message("Copy ready. Edit it, then Save.");
  }

  get("Search").oninput = renderList;
  get("Targets").oninput = countTargets;
  get("Run").onclick = run;
  get("Save").onclick = save;
  get("Duplicate").onclick = duplicate;
  get("New").onclick = () => {
    choose("draft", { id: "draft", name: "New script", description: "", changes: true, params: [],
      code: "foreach ($Computer in $Computers) {\n    # Your PowerShell here. Write-Ok / Write-Fail / Write-Warn colour the output.\n    Write-Ok \"$Computer\"\n}\n" });
    get("Name").focus(); get("Name").select();
  };
  get("Import").onclick = () => get("File").click();
  get("File").onchange = async () => {
    const file = get("File").files[0];
    get("File").value = "";
    if (!file) return;
    if (file.size > 65536) return message("Choose a script under 64 KB.", "bad");
    choose("draft", { id: "draft", name: file.name.replace(/\.[^.]+$/, ""), description: "", changes: true, params: [], code: await file.text() });
    message("Imported. Check it, then Save.");
  };
  get("Delete").onclick = async () => {
    if (current?.kind !== "saved" || !confirm(`Delete the saved script "${current.item.name}"?`)) return;
    try {
      await request(`/api/script-library/saved/${current.item.id}?revision=${current.item.revision}`, { method: "DELETE" });
      current = null; await load(); message("Script deleted.");
    } catch (error) { message(error.message, "bad"); }
  };
  get("Download").onclick = () => {
    if (!current) return;
    let code;
    try { code = downloadCode(); }
    catch (error) { return message(error.message, "bad"); }
    const url = URL.createObjectURL(new Blob([code], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = (current.kind === "saved" ? current.item.id : slug(get("Name").value)) + ".ps1"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  get("Stop").onclick = async () => {
    try { await send(`/api/script-library/runs/${runId}/stop`, "POST", {}); message("Stopping. A remote action that already started may still finish on its machine."); }
    catch (error) { message(error.message, "bad"); }
  };
  get("Copy").onclick = async () => {
    try { await navigator.clipboard.writeText(get("Output").textContent); message("Output copied.", "good"); }
    catch { message("Select the output and copy it manually."); }
  };
  get("UseSelected").onclick = () => {
    const machine = typeof S === "undefined" ? "" : S.target; // app.js keeps the selection in a script-level S
    if (!machine) return message("Select a machine in Workspace first.");
    const area = get("Targets");
    if (!targets().names.some((name) => name.toUpperCase() === machine.toUpperCase()))
      area.value = (area.value.trim() ? area.value.trim() + "\n" : "") + machine;
    countTargets();
  };
  get("ClearTargets").onclick = () => { get("Targets").value = ""; countTargets(); };
  document.querySelector("#scripts .scripts-pstools").onclick = () => page("psexec");

  async function reconnect() {
    if (window.AtlasReadOnly || active) return;
    try {
      const rows = await request("/api/script-library/runs", { atlasSilent: true });
      const running = rows.find((row) => !done.has(row.state));
      if (running) { runId = running.id; active = true; controls(); poll(); }
    } catch {}
  }
  window.AtlasScripts = {
    open() { if (!loaded) load(); reconnect(); },
    choose: (id) => load(id),
  };
  if (window.AtlasReadOnly) message("Browse and copy scripts here. Running them needs Atlas Admin.");
  countTargets();
  controls();
})();
