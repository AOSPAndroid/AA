/* New joiners: the two steps for each person joining a desk. Step 1 lists the access requests of
   their persona's desk to raise in the request portal, with an earlier joiner's ticket to copy;
   step 2 installs the persona's software on their machine in one click. Atlas keeps both until the
   joiner is marked complete; it never raises requests itself. */
(() => {
  const get = (id) => document.getElementById("joiner" + id);
  if (!get("List")) return;
  const readonly = () => !!window.AtlasReadOnly;
  const blocked = () => window.AtlasReadOnly?.reason || "New joiners are tracked in Atlas Admin";
  const HOST = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$/;
  const ACTIVE = new Set(["queued", "running", "paused"]);
  const SITE = "atlasJoinerSite";
  // mode: what the right-hand side shows (a joiner's checklist, the new joiner form, or nothing yet).
  let joiners = [], people = [], site = "", currentId = null, mode = "empty", loaded = false;
  let picked = null, installing = false, saving = false, timer, matchTimer;
  const matchRequest = AtlasClient.latest();

  const send = (url, method, body) =>
    AtlasClient.request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const day = (value) => {
    const date = value && new Date(value.slice(0, 10) + "T12:00:00");
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "";
  };
  const current = () => joiners.find((j) => j.id === currentId);
  const personaOf = (joiner) => window.AtlasPersonas?.all().find((p) => p.id === joiner?.persona_id);
  const message = (text, tone = "") => {
    get("Message").textContent = text;
    get("Message").dataset.tone = tone;
  };
  // The site chosen for Starting soon ("" is All sites); null until someone chooses one.
  let siteChoice = (() => {
    try {
      return localStorage.getItem(SITE);
    } catch {
      return null;
    }
  })();
  const raisedCount = (joiner) => joiner.requests.filter((r) => r.raised).length;

  async function load(select) {
    try {
      joiners = (await AtlasClient.request("/api/joiners", { atlasSilent: true })).joiners || [];
    } catch (error) {
      if (!readonly()) message("New joiners unavailable: " + error.message, "bad");
    }
    loaded = true;
    if (select) {
      currentId = select;
      mode = "detail";
    }
    if (mode === "detail" && !current()) mode = "empty";
    render();
    schedule();
  }
  async function loadSoon() {
    try {
      const data = await AtlasClient.request("/api/joiners/starting", { atlasSilent: true });
      people = data.people || [];
      site = data.site || "";
    } catch {
      people = [];
    }
    renderSoon();
  }
  function render() {
    renderList();
    get("Form").hidden = mode !== "form";
    get("Detail").hidden = mode !== "detail";
    get("Empty").hidden = mode !== "empty";
    get("Empty").textContent = readonly() ? "New joiners are tracked in Atlas Admin."
      : joiners.length ? "Choose a new joiner, or start one with New joiner." : "No new joiners yet. Click New joiner, or pick someone starting soon.";
    if (mode === "detail") renderDetail();
    get("New").disabled = readonly();
  }

  function renderList() {
    const word = get("Search").value.trim().toLowerCase(), list = get("List");
    const shown = joiners.filter((j) => !word || [j.name, j.email, j.persona, j.computer].join(" ").toLowerCase().includes(word))
      .sort((a, b) => Number(a.done) - Number(b.done));
    list.replaceChildren(...shown.map((joiner) => {
      const button = document.createElement("button"), name = document.createElement("strong");
      const badge = document.createElement("span"), about = document.createElement("small");
      const raised = raisedCount(joiner), total = joiner.requests.length;
      button.type = "button";
      button.className = "personas-item";
      button.dataset.joinerId = joiner.id;
      if (mode === "detail" && joiner.id === currentId) button.setAttribute("aria-current", "true");
      name.textContent = joiner.name;
      badge.className = joiner.done ? "status-ok" : raised === total && joiner.install ? "status-ok" : "status-neutral";
      badge.textContent = joiner.done ? "Done" : `${raised}/${total}${joiner.install ? " · software" : ""}`;
      about.textContent = [joiner.persona, joiner.computer, joiner.start && "starts " + day(joiner.start)].filter(Boolean).join(" · ");
      button.append(name, badge, about);
      button.onclick = () => {
        currentId = joiner.id;
        mode = "detail";
        message("");
        render();
      };
      return button;
    }));
    if (!shown.length) {
      const empty = document.createElement("p");
      empty.className = "personas-empty";
      empty.textContent = !loaded ? "Loading new joiners…" : joiners.length ? "No new joiner matches." : readonly() ? "New joiners are tracked in Atlas Admin." : "No new joiners yet.";
      list.append(empty);
    }
  }

  /* The checklist: rows are built once per joiner and then updated in place, so typing a ticket
     number and moving to the next row never loses the field being edited. */
  function renderDetail() {
    const joiner = current(), host = get("Requests"), locked = readonly();
    host.replaceChildren(...joiner.requests.map((row, index) => {
      const item = document.createElement("li"), box = document.createElement("input"), name = document.createElement("span");
      const title = document.createElement("b"), notes = document.createElement("small"), earlier = document.createElement("span");
      const ticket = document.createElement("input");
      item.className = "joiners-request";
      box.type = "checkbox";
      box.checked = row.raised;
      box.disabled = locked;
      box.setAttribute("aria-label", "Raised: " + row.catalog);
      box.onchange = () => change({ request: { index, raised: box.checked } });
      title.textContent = row.catalog;
      notes.textContent = row.notes;
      notes.hidden = !row.notes;
      name.className = "joiners-request-name";
      name.append(title, notes);
      earlier.className = "joiners-reference";
      if (row.reference) {
        const code = document.createElement("code"), copyButton = document.createElement("button");
        code.textContent = row.reference;
        copyButton.type = "button";
        copyButton.textContent = "Copy";
        copyButton.title = "Copy the earlier joiner's ticket to use as a template";
        copyButton.setAttribute("aria-label", "Copy earlier ticket " + row.reference);
        copyButton.onclick = () => copy(row.reference, "Ticket").catch(() => toast("Select the ticket and copy it manually."));
        earlier.append(code, copyButton);
      }
      ticket.value = row.ticket;
      ticket.placeholder = "New ticket";
      ticket.maxLength = 40;
      ticket.spellcheck = false;
      ticket.disabled = locked;
      ticket.setAttribute("aria-label", "New ticket for " + row.catalog);
      ticket.onchange = () => change({ request: { index, ticket: ticket.value } });
      item.append(box, name, earlier, ticket);
      item.dataset.index = index;
      return item;
    }));
    if (!joiner.requests.length) {
      const empty = document.createElement("li");
      empty.className = "personas-empty";
      empty.textContent = joiner.desk === "" ? `${joiner.persona} names no desk from the requests workbook, so there is nothing to raise here.` : "No requests for this desk.";
      host.append(empty);
    }
    get("Computer").value = joiner.computer || "";
    paintDetail();
  }
  function paintDetail() {
    const joiner = current();
    if (!joiner || mode !== "detail") return;
    const locked = readonly(), raised = raisedCount(joiner), total = joiner.requests.length, persona = personaOf(joiner);
    get("Title").textContent = joiner.name;
    get("Facts").textContent = [joiner.email, joiner.persona + (joiner.area ? " · " + joiner.area : ""), joiner.start && "starts " + day(joiner.start)]
      .filter(Boolean).join(" · ");
    get("RequestCount").textContent = `· ${raised} of ${total} raised`;
    for (const item of get("Requests").querySelectorAll(".joiners-request")) {
      const row = joiner.requests[Number(item.dataset.index)];
      item.dataset.raised = String(!!row.raised);
      item.hidden = get("HideRaised").checked && row.raised;
      const box = item.querySelector('input[type="checkbox"]'), ticket = item.querySelector('input:not([type])');
      if (box.checked !== row.raised) box.checked = row.raised;
      if (document.activeElement !== ticket && ticket.value !== row.ticket) ticket.value = row.ticket;
    }
    const install = joiner.install, items = persona?.items || [];
    get("SoftwareCount").textContent = persona ? `· ${persona.name} · ${plural(items.length, "package")}` : "· persona deleted";
    get("Software").textContent = items.length ? items.map((i) => (packageLabels.get(i.folder) || i.folder) + (i.action !== "Install" ? ` (${i.action})` : "")).join(" · ")
      : persona ? `${persona.name} has no software yet. Add its packages on the Personas page.` : "Its persona was deleted; recreate it to install software.";
    const machine = get("Computer").value.trim(), running = install && ACTIVE.has(install.state);
    const issue = locked ? blocked() : !items.length ? "This persona has no software yet" : !machine ? "Enter the new joiner's machine"
      : !HOST.test(machine) ? `${machine} is not a valid machine name` : running ? "The software is installing now" : installing ? "Starting…" : "";
    get("Install").disabled = !!issue;
    get("Install").title = issue || `Install ${plural(items.length, "package")} on ${machine}, one after another`;
    get("Install").textContent = items.length && machine && HOST.test(machine) ? `Install ${plural(items.length, "package")} on ${machine}` : "Install";
    const status = get("InstallStatus");
    status.textContent = !install ? "Not installed yet."
      : `${install.state === "unknown" ? "Started" : install.state === "complete" ? "Finished" : install.state === "cancelled" ? "Stopped" : "Installing"} on ${install.computer}, ${day(install.at)}: ${install.finished} of ${install.total} done`
        + (install.failed ? ` · ${install.failed} failed` : "") + (install.cancelled ? ` · ${install.cancelled} cancelled` : "")
        + (install.state === "unknown" ? ". See History for the outcome." : ". Exit codes are in History.");
    status.dataset.tone = install?.failed ? "bad" : install?.state === "complete" ? "good" : "";
    const softwareDone = install && install.state === "complete" && !install.failed;
    get("Progress").textContent = joiner.done ? "Complete" : `${raised}/${total} requests · ${softwareDone ? "software installed" : install ? "software started" : "software to install"}`;
    get("Progress").className = "pill " + (joiner.done ? "status-ok" : "");
    get("Done").textContent = joiner.done ? "Reopen" : "Mark complete";
    for (const id of ["Done", "Delete", "Computer", "CopyRemaining", "HideRaised"]) get(id).disabled = locked && id !== "HideRaised";
  }

  async function change(body) {
    const joiner = current();
    if (!joiner || readonly()) return;
    try {
      const updated = await send("/api/joiners/" + joiner.id, "PUT", body);
      joiners = joiners.map((j) => (j.id === updated.id ? updated : j));
      message("");
    } catch (error) {
      message(error.message, "bad");
    }
    renderList();
    paintDetail();
  }

  async function install() {
    const joiner = current();
    if (!joiner || installing || readonly()) return;
    installing = true;
    paintDetail();
    try {
      const machine = get("Computer").value.trim();
      if (machine !== (joiner.computer || "")) await change({ computer: machine });
      const result = await AtlasClient.request(`/api/joiners/${joiner.id}/install`, { method: "POST" });
      toast(`Installing ${result.persona} on ${result.computer} · ${plural(result.count, "package")}`);
      await load(joiner.id);
    } catch (error) {
      message(error.message, "bad");
    } finally {
      installing = false;
      paintDetail();
    }
  }
  // While software installs, refresh its progress (only the progress: rows being edited are kept).
  function schedule() {
    clearTimeout(timer);
    if (!joiners.some((j) => j.install && ACTIVE.has(j.install.state)) || !document.querySelector("#joiners.active")) return;
    timer = setTimeout(async () => {
      try {
        const fresh = (await AtlasClient.request("/api/joiners", { atlasSilent: true })).joiners || [];
        joiners = joiners.map((j) => ({ ...j, install: fresh.find((f) => f.id === j.id)?.install ?? j.install }));
        renderList();
        paintDetail();
      } catch {}
      schedule();
    }, 4000);
  }

  /* New joiner form: the person (from the directory or typed), their persona and their machine. */
  function openForm(person = {}) {
    if (readonly()) return;
    picked = person.user ? person : null;
    mode = "form";
    get("Name").value = person.name || "";
    get("Email").value = person.email || "";
    get("Machine").value = person.computer || "";
    get("Matches").replaceChildren();
    get("FormMessage").textContent = "";
    renderPersonas();
    render();
    get("Name").focus();
  }
  function renderPersonas() {
    const select = get("Persona"), wanted = select.value, all = window.AtlasPersonas?.all() || [];
    select.replaceChildren(new Option(all.length ? "Choose the persona…" : "No personas yet: import the requests workbook or create one", ""),
      ...all.map((p) => {
        const desk = window.AtlasPersonas.desk(p);
        return new Option([p.name, desk ? plural(desk.requests.length, "request") : "", plural(p.items.length, "package")].filter(Boolean).join(" · "), p.id);
      }));
    select.value = all.some((p) => p.id === wanted) ? wanted : "";
    plan();
  }
  function plan() {
    const persona = window.AtlasPersonas?.all().find((p) => p.id === get("Persona").value), desk = persona && window.AtlasPersonas.desk(persona);
    get("Plan").textContent = !persona ? "" : `${desk ? plural(desk.requests.length, "access request") + " from " + desk.name : "No access requests (no desk)"} · `
      + (persona.items.length ? plural(persona.items.length, "package") + " to install" : "no software yet");
    get("Create").disabled = readonly() || saving || !persona || !get("Name").value.trim();
  }
  async function matches() {
    const term = get("Name").value.trim(), host = get("Matches"), request = matchRequest();
    if (term.length < 2 || picked?.name === term) return host.replaceChildren();
    try {
      const data = await AtlasClient.request("/api/search?term=" + encodeURIComponent(term), { signal: request.signal, atlasSilent: true });
      if (!request.current()) return;
      host.replaceChildren(...(data.users || []).slice(0, 6).map((user) => {
        const button = document.createElement("button"), name = document.createElement("b"), about = document.createElement("small");
        button.type = "button";
        button.className = "personas-result";
        name.textContent = user.name || user.full_name || user.user_name;
        about.textContent = [user.email, user.department || user.organisational_unit, user.start_date && "starts " + day(user.start_date)].filter(Boolean).join(" · ");
        button.append(name, about);
        button.onclick = () => choosePerson(user);
        return button;
      }));
    } catch (error) {
      if (error.name !== "AbortError" && request.current()) host.replaceChildren();
    }
  }
  async function choosePerson(user) {
    const email = String(user.email || "");
    picked = { user: user.canonical_key || "", name: user.name || user.full_name || "", start: String(user.start_date || "").slice(0, 10) };
    get("Name").value = picked.name;
    get("Email").value = email.includes("@") ? email : "";
    get("Matches").replaceChildren();
    plan();
    if (get("Machine").value.trim() || !user.id) return;
    try {
      const record = await AtlasClient.request("/api/user/id:" + user.id, { atlasSilent: true });
      const machine = (record.machines || []).find((m) => AtlasUI.supportsWindows(m));
      if (machine && !get("Machine").value.trim()) get("Machine").value = machine.name || machine.machine_name || "";
    } catch {}
  }
  async function create(event) {
    event.preventDefault();
    if (readonly() || saving) return;
    const name = get("Name").value.trim(), persona = get("Persona").value, machine = get("Machine").value.trim();
    if (!name) return (get("FormMessage").textContent = "Enter the new joiner's name.");
    if (!persona) return (get("FormMessage").textContent = "Choose the persona for their desk.");
    if (machine && !HOST.test(machine)) return (get("FormMessage").textContent = `${machine} is not a valid machine name.`);
    saving = true;
    plan();
    try {
      const keep = picked && picked.name === name ? picked : {};
      const created = await send("/api/joiners", "POST", { name, email: get("Email").value.trim(), user: keep.user || "",
        start: keep.start || "", computer: machine, persona });
      await load(created.id);
      loadSoon();
      message(`Checklist ready for ${created.name}: ${plural(created.requests.length, "request")} to raise.`, "good");
    } catch (error) {
      get("FormMessage").textContent = error.message;
    } finally {
      saving = false;
      plan();
    }
  }

  /* Starting soon: directory people whose start date is near, at the chosen site. */
  function renderSoon() {
    const select = get("Site"), counts = new Map();
    for (const person of people) counts.set(person.location || "", (counts.get(person.location || "") || 0) + 1);
    const sites = [...counts].filter(([name]) => name).sort((a, b) => b[1] - a[1]);
    const wanted = siteChoice ?? sites.find(([name]) => site && name.toLowerCase().includes(site.toLowerCase()))?.[0] ?? "";
    select.replaceChildren(new Option(`All sites · ${people.length}`, ""), ...sites.map(([name, n]) => new Option(`${name} · ${n}`, name)));
    select.value = sites.some(([name]) => name === wanted) ? wanted : "";
    const shown = people.filter((p) => !select.value || p.location === select.value);
    get("SoonCount").textContent = people.length ? `· ${shown.length}` : "";
    get("SoonList").replaceChildren(...shown.map((person) => {
      const button = document.createElement("button"), name = document.createElement("strong");
      const when = document.createElement("span"), about = document.createElement("small");
      button.type = "button";
      button.className = "personas-item";
      button.dataset.joinerStart = person.user;
      button.disabled = readonly();
      button.title = readonly() ? blocked() : `Start ${person.name}'s checklist`;
      name.textContent = person.name;
      when.className = "status-neutral";
      when.textContent = day(person.start);
      about.textContent = [person.title, person.department, person.computer].filter(Boolean).join(" · ");
      button.append(name, when, about);
      button.onclick = () => openForm(person);
      return button;
    }));
    if (!shown.length) {
      const empty = document.createElement("p");
      empty.className = "personas-empty";
      empty.textContent = readonly() ? "Start dates are read in Atlas Admin." : "Nobody in the directory starts in the next few weeks here.";
      get("SoonList").append(empty);
    }
  }

  get("Search").oninput = renderList;
  get("New").onclick = () => openForm();
  get("Cancel").onclick = () => {
    mode = current() ? "detail" : "empty";
    render();
  };
  get("Form").addEventListener("submit", create);
  get("Persona").onchange = plan;
  get("Name").oninput = () => {
    if (picked && picked.name !== get("Name").value.trim()) picked = null;
    plan();
    clearTimeout(matchTimer);
    matchTimer = setTimeout(matches, 250);
  };
  get("Site").onchange = () => {
    siteChoice = get("Site").value;
    try {
      localStorage.setItem(SITE, siteChoice);
    } catch {}
    renderSoon();
  };
  get("HideRaised").onchange = paintDetail;
  get("Computer").oninput = paintDetail;
  get("Computer").onchange = () => {
    const machine = get("Computer").value.trim();
    if (!machine || HOST.test(machine)) change({ computer: machine });
  };
  get("Install").onclick = install;
  get("Done").onclick = () => change({ done: !current()?.done });
  get("Delete").onclick = async () => {
    const joiner = current();
    if (!joiner || readonly() || !confirm(`Delete ${joiner.name}'s checklist? Requests already raised and software already installed are not affected.`)) return;
    try {
      await AtlasClient.request("/api/joiners/" + joiner.id, { method: "DELETE" });
      currentId = null;
      mode = "empty";
      await load();
      loadSoon();
    } catch (error) {
      message(error.message, "bad");
    }
  };
  get("CopyRemaining").onclick = () => {
    const joiner = current();
    const rows = (joiner?.requests || []).filter((r) => !r.raised);
    if (!rows.length) return toast("Every request is raised.");
    copy(rows.map((r) => [r.catalog, r.reference, r.notes].filter(Boolean).join(" · ")).join("\n"), `${plural(rows.length, "request")}`)
      .catch(() => toast("Copy is unavailable here."));
  };

  window.AtlasJoiners = {
    load,
    open() {
      window.AtlasPersonas?.load().then(() => {
        renderPersonas();
        paintDetail();
      });
      load();
      loadSoon();
    },
  };
  render();
})();
