/* Personas: the software a role needs, saved in Atlas and installed on a machine in one click.
   Installing starts one deployment queue on the server: Atlas checks the machine and every
   package first and starts nothing if any is refused, then runs them one after another with
   the usual checks and history. Personas are also offered in Workspace and the queue drawer. */
(() => {
  const get = (id) => document.getElementById("persona" + id);
  if (!get("List")) return;
  const readonly = () => !!window.AtlasReadOnly;
  const blocked = () => window.AtlasReadOnly?.reason || "Personas install from Atlas Admin";
  const HOST = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$/;
  const ACTIONS = ["Install", "Repair", "Uninstall"];
  // Kits from earlier versions were kept in this browser only; they can be imported once.
  const KITS = "atlasDeploymentKits", PICK = "atlasPersonaPick";
  let personas = [], repository = true, loaded = false, maxItems = 40;
  // drafting: a new or duplicated persona the operator opened; a reload does not replace it.
  let current = null, pristine = "", drafting = false, saving = false, installing = false, searchTimer;
  const searchRequest = AtlasClient.latest();

  const send = (url, method, body) =>
    AtlasClient.request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const packageName = (folder) => String(folder || "").split(/[\\/]/).filter(Boolean).pop() || "";
  const label = (folder) => packageLabels.get(folder) || folder;
  const problems = (persona) => (persona?.items || []).filter((item) => item.problem);
  const verb = (persona) => ((persona?.items || []).every((item) => (item.action || "Install") === "Install") ? "Install" : "Run");
  const target = () => S.target || "";
  const message = (text, tone = "") => {
    get("Message").textContent = text;
    get("Message").dataset.tone = tone;
  };
  const stored = (key, value) => {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {}
    return null;
  };

  async function load(select) {
    try {
      const data = await AtlasClient.request("/api/personas", { atlasSilent: true });
      personas = data.personas || [];
      repository = data.repository !== false;
      maxItems = data.max_items || maxItems;
    } catch (error) {
      message("Personas unavailable: " + error.message, "bad");
    }
    loaded = true;
    const chosen = personas.find((p) => p.id === (select || current?.id));
    if (chosen && (select || !dirty())) choose(chosen, true);
    else if (!dirty() && !drafting) choose(personas[0] || null, true);
    render();
    return personas;
  }
  function render() {
    renderList();
    renderPick();
    renderDrawer();
    renderImport();
    controls();
  }

  /* Persona page: the list on the left, the selected persona on the right. */
  function renderList() {
    const word = get("Search").value.trim().toLowerCase(), list = get("List");
    const shown = personas.filter((p) =>
      !word || [p.name, p.description, ...p.items.map((i) => label(i.folder))].join(" ").toLowerCase().includes(word));
    list.replaceChildren(...shown.map((persona) => {
      const button = document.createElement("button"), name = document.createElement("strong");
      const count = document.createElement("span"), about = document.createElement("small"), issues = problems(persona).length;
      button.type = "button";
      button.className = "personas-item";
      button.dataset.personaId = persona.id;
      if (current?.id === persona.id) button.setAttribute("aria-current", "true");
      name.textContent = persona.name;
      count.className = issues ? "status-bad" : "status-neutral";
      count.textContent = issues ? `${issues} to fix` : plural(persona.items.length, "package");
      about.textContent = persona.description || persona.items.map((i) => label(i.folder)).join(", ");
      button.append(name, count, about);
      button.onclick = () => choose(persona);
      return button;
    }));
    if (!shown.length) {
      const empty = document.createElement("p");
      empty.className = "personas-empty";
      empty.textContent = !loaded ? "Loading personas…" : personas.length ? "No persona matches."
        : readonly() ? "Personas are saved and installed in Atlas Admin." : "No personas yet. Add the packages a role needs, then Save.";
      list.append(empty);
    }
  }

  const blank = () => ({ id: null, revision: 0, name: "", description: "", fresh: false, threads: 8, items: [] });
  const copyOf = (p) => ({
    id: p.id, revision: p.revision, name: p.name, description: p.description || "", fresh: !!p.fresh, threads: p.threads || 8,
    items: p.items.map((i) => ({ folder: i.folder, action: i.action || "Install", script: i.script, scripts: null, problem: i.problem || null })),
  });
  function read() {
    current.name = get("Name").value;
    current.description = get("Description").value;
    current.fresh = get("Fresh").checked;
    current.threads = Math.min(32, Math.max(1, Math.round(Number(get("Threads").value)) || 8));
  }
  function snapshot() {
    if (!current) return "";
    read();
    return JSON.stringify([current.name.trim(), current.description.trim(), current.fresh, current.threads,
      current.items.map((i) => [i.folder, i.action, i.script])]);
  }
  const dirty = () => !!current && snapshot() !== pristine;

  function choose(persona, force = false) {
    if (!force && dirty() && !confirm(`Discard your unsaved changes to ${current.name.trim() || "this persona"}?`)) return false;
    current = persona ? copyOf(persona) : blank();
    drafting = false;
    fill();
    pristine = snapshot();
    message(persona || readonly() ? "" : "New persona: name it, add the packages it needs, then Save.");
    renderList();
    controls();
    return true;
  }
  function fill() {
    get("Name").value = current.name;
    get("Description").value = current.description;
    get("Fresh").checked = current.fresh;
    get("Threads").value = current.threads;
    get("PackageSearch").value = "";
    get("Results").replaceChildren();
    renderItems();
  }

  function renderItems() {
    const host = get("Items"), locked = readonly();
    get("Count").textContent = plural(current.items.length, "package");
    host.replaceChildren(...current.items.map((item, index) => {
      const row = document.createElement("li"), name = document.createElement("span"), title = document.createElement("b");
      const action = document.createElement("select"), script = document.createElement("select"), problem = document.createElement("small");
      const tools = document.createElement("span"), shown = label(item.folder);
      row.className = "personas-row";
      name.className = "personas-row-name";
      title.textContent = shown;
      name.append(title);
      if (shown !== item.folder) {
        const folder = document.createElement("small");
        folder.textContent = item.folder;
        name.append(folder);
      }
      action.setAttribute("aria-label", "Action for " + shown);
      for (const value of ACTIONS) action.add(new Option(value, value));
      action.value = item.action;
      action.onchange = () => {
        // A script belongs to one action: choose again from the scripts for the new one.
        Object.assign(item, { action: action.value, script: "", scripts: null, problem: null });
        loadScripts(item);
      };
      script.setAttribute("aria-label", "Script for " + shown);
      script.onfocus = () => {
        if (!item.scripts && !item.loading) loadScripts(item);
      };
      script.onchange = () => {
        Object.assign(item, { script: script.value, problem: null });
        paint(item);
        controls();
      };
      problem.className = "personas-row-problem status-bad";
      tools.className = "personas-row-tools";
      for (const [text, aria, move] of [["↑", "Move up", -1], ["↓", "Move down", 1], ["✕", "Remove", 0]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.setAttribute("aria-label", `${aria}: ${shown}`);
        button.disabled = locked || (move === -1 && index === 0) || (move === 1 && index === current.items.length - 1);
        button.onclick = () => {
          const [moved] = current.items.splice(index, 1);
          if (move) current.items.splice(index + move, 0, moved);
          renderItems();
          controls();
        };
        tools.append(button);
      }
      action.disabled = locked;
      row.append(name, action, script, tools, problem);
      item.view = { row, script, problem };
      paint(item);
      return row;
    }));
    if (!current.items.length) {
      const empty = document.createElement("li");
      empty.className = "personas-empty";
      empty.textContent = readonly() ? "No packages." : "No packages yet. Search below to add the first one.";
      host.append(empty);
    }
  }
  // Update one row in place, so a list that is open or focused is not rebuilt under the pointer.
  function paint(item) {
    const view = item.view;
    if (!view) return;
    const options = item.scripts || (item.script ? [item.script] : []);
    view.script.replaceChildren(...(options.length ? options.map((name) => new Option(name, name))
      : [new Option(item.loading ? "Loading scripts…" : "No script", "")]));
    view.script.value = item.script;
    view.script.disabled = readonly() || !options.length;
    view.problem.textContent = item.problem || "";
    view.problem.hidden = !item.problem;
    view.row.classList.toggle("has-problem", !!item.problem);
  }
  async function loadScripts(item) {
    const ticket = (item.ticket = (item.ticket || 0) + 1), action = item.action;
    item.loading = true;
    paint(item);
    controls();
    try {
      const data = await AtlasClient.request(
        `/api/scripts?package=${encodeURIComponent(item.folder)}&action=${encodeURIComponent(action)}`, { atlasSilent: true });
      if (ticket !== item.ticket) return;
      item.scripts = data.scripts || [];
      if (!item.scripts.includes(item.script)) item.script = item.scripts[0] || "";
      item.problem = item.scripts.length ? null : `No ${action.toLowerCase()} script in this package`;
    } catch (error) {
      if (ticket === item.ticket) item.problem = item.problem || error.message;
    } finally {
      if (ticket === item.ticket) {
        item.loading = false;
        paint(item);
        controls();
      }
    }
  }
  function add(folder, action = "Install", script = "") {
    if (!current || readonly()) return false;
    if (current.items.some((i) => i.folder.toLowerCase() === folder.toLowerCase() && i.action === action)) {
      message(`${label(folder)} is already in this persona.`);
      return false;
    }
    if (current.items.length >= maxItems) {
      message(`A persona holds up to ${maxItems} packages.`, "bad");
      return false;
    }
    const item = { folder, action, script, scripts: null, problem: null };
    current.items.push(item);
    renderItems();
    if (!script) loadScripts(item);
    controls();
    return true;
  }

  async function search() {
    const term = get("PackageSearch").value.trim(), results = get("Results"), request = searchRequest();
    if (!term) return results.replaceChildren();
    try {
      const data = await AtlasClient.request("/api/catalog?term=" + encodeURIComponent(term), { signal: request.signal, atlasSilent: true });
      if (!request.current()) return;
      const items = (data.items || []).slice(0, 8);
      results.replaceChildren(...items.map((pkg) => {
        const button = document.createElement("button"), name = document.createElement("b"), folder = document.createElement("small");
        const text = pkg.display_name + (pkg.version ? " · " + pkg.version : "");
        packageLabels.set(pkg.folder, text + (pkg.state ? " · " + pkg.state : ""));
        button.type = "button";
        button.className = "personas-result";
        name.textContent = text;
        folder.textContent = pkg.folder + (pkg.state ? " · " + pkg.state : "");
        button.append(name, folder);
        button.onclick = () => {
          if (!add(pkg.folder)) return;
          get("PackageSearch").value = "";
          results.replaceChildren();
          get("PackageSearch").focus();
        };
        return button;
      }));
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "personas-empty";
        empty.textContent = data.available === false ? data.error || "Package repository unavailable." : "No matching package.";
        results.append(empty);
      }
    } catch (error) {
      if (error.name !== "AbortError" && request.current()) results.textContent = error.message;
    }
  }

  function controls() {
    if (!current) return;
    const locked = readonly(), saved = current.id ? personas.find((p) => p.id === current.id) : null;
    const changed = dirty(), loading = current.items.some((i) => i.loading), machine = get("Machine").value.trim();
    get("Save").disabled = locked || saving || !changed || loading;
    get("Delete").hidden = !saved;
    get("Delete").disabled = locked || !saved || saving;
    get("Duplicate").disabled = locked || !current.items.length;
    for (const id of ["New", "FromQueue", "PackageSearch", "Name", "Description", "Fresh", "Threads", "Machine", "UseSelected"])
      get(id).disabled = locked;
    const issue = locked ? blocked()
      : !saved ? "Save the persona first"
      : changed ? "Save your changes before installing"
      : problems(saved).length ? `Fix ${plural(problems(saved).length, "package")} first: ${problems(saved).map((i) => label(i.folder)).join(", ")}`
      : !repository ? "The package repository is unavailable. Check Settings and OneDrive sync."
      : !machine ? "Enter or select the machine to install on"
      : !HOST.test(machine) ? `${machine} is not a valid machine name`
      : installing ? "Starting…" : "";
    const install = get("Install");
    install.disabled = !!issue;
    install.title = issue || `${verb(saved)} ${plural(saved.items.length, "package")} on ${machine}, one after another`;
    install.textContent = machine && HOST.test(machine) ? `${verb(saved || current)} on ${machine}` : verb(saved || current);
  }

  async function save() {
    if (readonly() || !current || saving) return;
    read();
    if (!current.name.trim()) {
      get("Name").focus();
      return message("Name the persona, for example New starter.", "bad");
    }
    if (!current.items.length) return message("Add at least one package.", "bad");
    const missing = current.items.find((i) => !i.script);
    if (missing) return message(`${label(missing.folder)}: choose a script.`, "bad");
    const body = {
      name: current.name.trim().replace(/\s+/g, " "), description: current.description.trim(), fresh: current.fresh, threads: current.threads,
      revision: current.revision, items: current.items.map(({ folder, script, action }) => ({ folder, script, action })),
    };
    saving = true;
    controls();
    try {
      const result = current.id ? await send("/api/personas/" + current.id, "PUT", body) : await send("/api/personas", "POST", body);
      await load(result.id);
      message(`Saved ${result.name}.`, "good");
    } catch (error) {
      message(error.message, "bad");
    } finally {
      saving = false;
      controls();
    }
  }

  async function remove() {
    const saved = personas.find((p) => p.id === current?.id);
    if (readonly() || !saved || !confirm(`Delete the persona ${saved.name}? Deployments already started are not affected.`)) return;
    try {
      await AtlasClient.request(`/api/personas/${saved.id}?revision=${saved.revision}`, { method: "DELETE" });
      current = null;
      await load();
      message(`Deleted ${saved.name}.`);
    } catch (error) {
      message(error.message, "bad");
    }
  }

  // Save as: the copy keeps any unsaved edits; the original stays as it was saved.
  function duplicate() {
    if (!current || readonly()) return;
    read();
    current = { ...current, id: null, revision: 0, name: (current.name.trim() || "Persona") + " (copy)",
      items: current.items.map(({ folder, action, script, scripts, problem }) => ({ folder, action, script, scripts, problem })) };
    drafting = true;
    pristine = "";
    fill();
    for (const item of current.items) if (!item.script) loadScripts(item);
    get("Name").focus();
    get("Name").select();
    message("Copy ready. Rename it, then Save.");
    renderList();
    controls();
  }

  function fromQueue() {
    if (!current || readonly()) return;
    if (!deploymentQueue.length) return message("The deployment queue is empty. Queue packages in Workspace, or search for them here.");
    let added = 0;
    for (const item of deploymentQueue) {
      const folder = packageName(item.folder);
      if (folder && !current.items.some((i) => i.folder.toLowerCase() === folder.toLowerCase() && i.action === (item.action || "Install"))
        && current.items.length < maxItems) {
        current.items.push({ folder, action: item.action || "Install", script: item.script || "", scripts: null, problem: null });
        added++;
      }
    }
    renderItems();
    for (const item of current.items) if (!item.script) loadScripts(item);
    controls();
    message(added ? `Added ${plural(added, "queued package")}. Save to keep them.` : "Every queued package is already in this persona.");
  }

  async function install(persona, computer) {
    if (readonly()) throw Error(blocked());
    if (!computer) throw Error("Select the machine to install on first.");
    const result = await send(`/api/personas/${persona.id}/install`, "POST", { computer, revision: persona.revision });
    toast(`Installing ${result.persona} on ${result.computer} · ${plural(result.count, "package")}${result.count > 1 ? ", one after another" : ""}`);
    return result;
  }
  async function installCurrent() {
    const saved = personas.find((p) => p.id === current?.id);
    if (!saved || installing || dirty()) return;
    installing = true;
    controls();
    try {
      const result = await install(saved, get("Machine").value.trim());
      message(`Started ${result.persona} on ${result.computer}. Follow it under Ongoing actions in the queue.`, "good");
    } catch (error) {
      message(error.message, "bad");
    } finally {
      installing = false;
      controls();
    }
  }

  // The machine follows the Workspace selection until someone types a different one.
  function syncMachine() {
    const field = get("Machine");
    if (field.dataset.typed !== "true" && field.value !== target()) field.value = target();
  }

  /* Workspace: install a persona on the selected machine. */
  function renderPick() {
    const select = get("Pick");
    if (!select) return;
    const wanted = select.value || stored(PICK) || "";
    select.replaceChildren(new Option(personas.length ? "Install a persona…" : "No personas yet", ""),
      ...personas.map((p) => new Option(`${p.name} · ${plural(p.items.length, "package")}`, p.id)));
    select.value = personas.some((p) => p.id === wanted) ? wanted : "";
    pickControls();
  }
  function pickControls() {
    const select = get("Pick"), button = get("PickInstall"), note = get("PickNote");
    if (!select) return;
    const persona = personas.find((p) => p.id === select.value), machine = target();
    const issue = readonly() ? blocked()
      : !persona ? (personas.length ? "Choose a persona" : "Create personas on the Personas page")
      : !machine ? "Select a machine first"
      : problems(persona).length ? `Fix ${persona.name} on the Personas page first: ${problems(persona).map((i) => `${label(i.folder)} (${i.problem})`).join(", ")}`
      : !repository ? "The package repository is unavailable. Check Settings and OneDrive sync."
      : installing ? "Starting…" : "";
    select.disabled = readonly() || !personas.length;
    button.disabled = !!issue;
    button.title = issue || `${verb(persona)} ${plural(persona.items.length, "package")} on ${machine}, one after another`;
    button.textContent = persona ? `${verb(persona)} ${plural(persona.items.length, "package")}` : "Install";
    note.textContent = persona ? persona.items.map((i) => label(i.folder)).join(" · ") : personas.length ? "" : "Save software bundles on the Personas page.";
  }
  async function installPick() {
    const persona = personas.find((p) => p.id === get("Pick").value);
    if (!persona || installing) return;
    installing = true;
    pickControls();
    try {
      await install(persona, target());
    } catch (error) {
      toast(error.message);
    } finally {
      installing = false;
      pickControls();
      controls();
    }
  }

  /* Queue drawer: save the queue as a persona, or queue a persona's packages for the selected machine. */
  function renderDrawer() {
    const host = get("QueueList");
    if (!host) return;
    const locked = readonly(), machine = target();
    host.replaceChildren(...personas.map((persona) => {
      const row = document.createElement("div"), text = document.createElement("div"), name = document.createElement("b");
      const about = document.createElement("span"), button = document.createElement("button");
      const names = persona.items.map((i) => `${label(i.folder)} (${i.action || "Install"})`);
      row.className = "kit-row";
      name.textContent = persona.name;
      about.title = names.join("\n");
      about.textContent = `${plural(persona.items.length, "package")} · ${names.slice(0, 3).join(", ")}${names.length > 3 ? "…" : ""}`;
      text.append(name, about);
      button.type = "button";
      button.dataset.personaQueue = persona.id;
      button.disabled = locked || !machine;
      button.title = locked ? blocked() : machine ? `Queue every package for ${machine}; nothing starts until you start the queue` : "Select a target machine first";
      button.textContent = machine ? `Add for ${machine}` : "Add to queue";
      button.onclick = () => addToQueue(persona.id);
      row.append(text, button);
      return row;
    }));
    if (!personas.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No personas yet. Queue the packages you deploy together, name them, then save.";
      host.append(empty);
    }
    get("SaveQueue").disabled = locked;
    get("SaveQueue").title = locked ? blocked() : "Save the packages in the queue as a persona";
  }
  function addToQueue(id) {
    const persona = personas.find((p) => p.id === id || p.name === id);
    if (!persona) return toast("That persona no longer exists. Reload the page.");
    if (readonly()) return toast(blocked());
    if (activeQueueId) return toast("Finish or clear the saved queue first");
    if (!target()) return toast("Select a target machine first");
    for (const item of persona.items)
      deploymentQueue.push({ computer: target(), folder: item.folder, script: item.script, action: item.action || "Install",
        fresh: !!persona.fresh, threads: persona.threads || 8, mode: "full", state: "waiting" });
    renderQueue();
    toast(`Added ${plural(persona.items.length, "package")} from ${persona.name} for ${target()}`);
  }
  async function saveQueue() {
    const input = get("QueueName"), name = input.value.trim().replace(/\s+/g, " ").slice(0, 60);
    if (readonly()) return toast(blocked());
    if (!deploymentQueue.length) return toast("Add packages to the queue first, then save them as a persona.");
    if (!name) {
      input.focus();
      return toast("Name the persona, for example New starter.");
    }
    const items = [], seen = new Set();
    for (const item of deploymentQueue) {
      const folder = packageName(item.folder), key = folder.toLowerCase() + "|" + (item.action || "Install");
      if (!folder || seen.has(key)) continue;
      seen.add(key);
      items.push({ folder, script: item.script, action: item.action || "Install" });
    }
    const existing = personas.find((p) => p.name.toLowerCase() === name.toLowerCase());
    if (existing && !confirm(`Replace the packages in ${existing.name} with the ${plural(items.length, "queued package")}?`)) return;
    const first = deploymentQueue[0];
    const body = { name: existing?.name || name, description: existing?.description || "", items, fresh: !!first.fresh,
      threads: Math.min(32, Math.max(1, Number(first.threads) || 8)), revision: existing?.revision || 0 };
    try {
      const result = existing ? await send("/api/personas/" + existing.id, "PUT", body) : await send("/api/personas", "POST", body);
      input.value = "";
      await load();
      toast(`${existing ? "Updated" : "Saved"} persona ${result.name} · ${plural(result.items.length, "package")}`);
    } catch (error) {
      toast(error.message);
    }
  }

  /* Kits saved in this browser by earlier versions become personas when imported. */
  function browserKits() {
    try {
      const kits = JSON.parse(stored(KITS) || "[]");
      return Array.isArray(kits) ? kits.filter((k) => k && k.name && Array.isArray(k.items) && k.items.length) : [];
    } catch {
      return [];
    }
  }
  function renderImport() {
    const button = get("ImportKits"), kits = browserKits();
    button.hidden = readonly() || !kits.length;
    button.textContent = `Import ${plural(kits.length, "browser kit")}`;
    button.title = "Deployment kits saved in this browser by an earlier version; import them as personas";
  }
  async function importKits() {
    const kits = browserKits();
    if (readonly() || !kits.length) return;
    const failed = [];
    let imported = 0;
    for (const kit of kits) {
      const items = kit.items.map((i) => ({ folder: packageName(i.folder), script: i.script, action: i.action || "Install" }))
        .filter((i) => i.folder && i.script);
      const name = String(kit.name).trim().replace(/\s+/g, " ").slice(0, 60);
      try {
        if (personas.some((p) => p.name.toLowerCase() === name.toLowerCase())) throw Error("a persona with this name exists");
        await send("/api/personas", "POST", { name, items, fresh: kit.items.some((i) => i.fresh), threads: Math.min(32, Math.max(1, Number(kit.items[0].threads) || 8)) });
        imported++;
      } catch (error) {
        failed.push({ ...kit, error: error.message });
      }
    }
    stored(KITS, failed.length ? JSON.stringify(failed.map(({ error, ...kit }) => kit)) : null);
    await load();
    message(failed.length ? `Imported ${imported}. Not imported: ${failed.map((k) => `${k.name} (${k.error})`).join("; ")}`
      : `Imported ${plural(imported, "kit")} as personas.`, failed.length ? "bad" : "good");
  }

  get("Search").oninput = renderList;
  get("New").onclick = () => {
    if (!choose(null)) return;
    drafting = true;
    get("Name").focus();
  };
  get("Save").onclick = save;
  get("Delete").onclick = remove;
  get("Duplicate").onclick = duplicate;
  get("FromQueue").onclick = fromQueue;
  get("Install").onclick = installCurrent;
  get("ImportKits").onclick = importKits;
  get("UseSelected").onclick = () => {
    if (!target()) return message("Select a machine in Workspace first, or type its name.");
    get("Machine").value = target();
    get("Machine").dataset.typed = "false";
    controls();
  };
  get("Machine").oninput = () => {
    get("Machine").dataset.typed = String(get("Machine").value.trim() !== target());
    controls();
  };
  for (const id of ["Name", "Description", "Threads"]) get(id).addEventListener("input", controls);
  get("Fresh").addEventListener("change", controls);
  get("PackageSearch").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(search, 250);
  };
  get("PackageSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      get("Results").querySelector("button")?.click();
    }
  });
  get("Pick").onchange = () => {
    stored(PICK, get("Pick").value || null);
    pickControls();
  };
  get("PickInstall").onclick = installPick;
  get("SaveQueue").onclick = saveQueue;
  get("QueueName").addEventListener("keydown", (event) => {
    if (event.key === "Enter") saveQueue();
  });
  // The machine is chosen elsewhere in the console; follow it wherever personas are offered.
  new MutationObserver(() => {
    syncMachine();
    pickControls();
    renderDrawer();
    controls();
  }).observe(document.querySelector("#deployTarget"), { childList: true, characterData: true, subtree: true });

  window.AtlasPersonas = {
    load,
    list: () => personas,
    addToQueue,
    open() {
      syncMachine();
      load();
    },
  };
  choose(null, true);
  render();
  load();
})();
