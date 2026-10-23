import { openRemoteRegistry } from "./service-actions.js";
import { openCatalogue } from "./catalogue.js";
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export function createOperations({
  onSelect,
  token,
  getSelection,
  onChange,
  toast,
}) {
  let generation = 0,
    current = null,
    target = "",
    job = null,
    timer = null,
    catalogVersion = 0,
    scriptVersion = 0,
    previewVersion = 0,
    submitting = false,
    packageDetails = null,
    userSearchVersion = 0;
  const host = () => document.querySelector("#ops-panel");
  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        "X-Atlas-Token": token() || "",
        ...(options.body && typeof options.body === "string"
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
      },
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(
        typeof result.detail === "string"
          ? result.detail
          : result.error || "Request failed",
      );
    return result;
  }
  function clear() {
    generation++;
    current = null;
    target = "";
    clearTimeout(timer);
    timer = null;
    job = null;
    submitting = false;
    packageDetails = null;
  }
  function valid(g) {
    return (
      g === generation && host() && current?.desk.id === getSelection()?.id
    );
  }
  function summary(u) {
    return AtlasUI.person(u);
  }
  async function select(record) {
    clear();
    const g = generation;
    if (!host()) return;
    host().innerHTML =
      '<p class="ops-muted">Loading directory and machines…</p>';
    try {
      const data = await api(
        "/api/desks/" + encodeURIComponent(record.id) + "/context",
      );
      if (g !== generation || !host()) return;
      current = data;
      if (record.kind !== "desk" && !data.candidates.length) {
        host().innerHTML =
          '<p class="ops-muted">Room / area. Select a desk to view its user and machines.</p>';
        return;
      }
      render(g);
    } catch (e) {
      if (g === generation && host())
        host().innerHTML = `<p class="ops-error">${esc(e.message)}</p>`;
    }
  }
  function render(g) {
    const { desk, user, match_method, deployments } = current;
    const explanation = {
      "name-match": "Matched by plan name · verify the person",
      "unconfirmed-name-match": "Directory match · seating is unconfirmed",
      confirmed: "Directory link confirmed",
      ambiguous: "More than one user matches this name",
      unmatched: "Link this desk to a directory user",
      unassigned: "This desk has no assigned directory user",
      "missing-linked-user":
        "Previously linked user is absent from the directory",
    }[match_method];
    host().innerHTML = `<section class="ops-section"><div class="ops-section-title"><span class="eyebrow">USER & MACHINES</span><span class="ops-chip ${match_method === "confirmed" ? "good" : ""}">${esc(explanation)}</span></div>
   ${desk.kind !== "desk" ? '<p class="ops-error">This person was imported as an area. Confirm the directory link below to register this location as a desk before deploying.</p>' : ""}${user ? summary(user) : '<p class="ops-muted">Choose the correct colleague below. Search by name or login to choose the directory account.</p>'}
   <button id="ops-match-directory" class="ops-link-button">Match to directory</button><details class="ops-link" ${!user || desk.kind !== "desk" ? "open" : ""}><summary>Choose the correct database account</summary><p class="ops-muted">Selecting an account replaces the floor label with its exact directory name and saves a permanent account link. The directory itself is not renamed.</p><div class="ops-search-row"><input id="ops-user-search" aria-label="Directory user search" placeholder="Name, login, email or employee ID"><button id="ops-find-user">Search</button></div><div id="ops-user-results"></div></details></section>
   <section class="ops-section"><div class="ops-section-title"><span class="eyebrow">SELECT A TARGET MACHINE</span><span>${current.machines.length} linked</span></div><p class="ops-muted">Inventory links are historical evidence, not a live sign-in check. Choose a target explicitly.</p><div class="ops-machines">${machineRows()}</div><div id="ops-target-health" class="ops-muted"></div></section>
   <section class="ops-section ops-deployment"><span class="eyebrow">APPLICATION DEPLOYMENT</span><h3 id="ops-target-label">Choose a machine above</h3><label class="ops-label">Find a package<input id="ops-package-filter" placeholder="Filter application packages"></label><label class="ops-label">Application<select id="ops-package"><option value="">Loading packages…</option></select></label><div class="ops-two"><label class="ops-label">Action<select id="ops-action"><option>Install</option><option>Uninstall</option><option>Repair</option></select></label><label class="ops-label">Run mode<select id="ops-mode"><option value="full">Copy + execute</option><option value="copy">Copy only</option><option value="execute">Execute existing</option></select></label></div><label class="ops-label">Installation script<select id="ops-script"><option value="">Select a package</option></select></label><button id="ops-preview" class="ops-text-button">View script</button><pre id="ops-script-content" hidden></pre><p id="ops-package-status" class="ops-muted"></p><div id="ops-package-details"></div><dl id="ops-deploy-summary" class="ops-facts"></dl><button id="ops-deploy" class="primary" disabled>Deploy to selected machine</button><div id="ops-job" role="status" aria-live="polite"></div></section>
   <section class="ops-section"><span class="eyebrow">DEPLOYMENTS AT THIS DESK</span><div id="ops-desk-history">${historyRows(deployments)}</div><a class="ops-link-button" href="/installer" target="_blank" rel="noopener">Open full IT console ↗</a></section>`;
    const q = (s) => host()?.querySelector(s);
    q("#ops-user-search").value =
      desk.occupancy !== "vacant" && desk.name !== "Unconfirmed desk"
        ? desk.name
        : "";
    q("#ops-match-directory").onclick = () => {
      q(".ops-link").open = true;
      q("#ops-user-search").focus();
      q("#ops-user-search").select();
    };
    q("#ops-find-user").onclick = () => findUser(g);
    q("#ops-user-search").onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        findUser(g);
      }
    };
    AtlasUI.machineFilters(q(".ops-machines"));
    showCandidates(current.candidates, g);
    host()
      .querySelectorAll('[name="ops-machine"]')
      .forEach(
        (input) =>
          (input.onchange = () => {
            const machine = current.machines[+input.value];
            if (!AtlasUI.supportsWindows(machine)) return;
            target = machine.name;
            q("#ops-target-label").textContent = target;
            host()
              .querySelectorAll(".ops-machine")
              .forEach((n) => n.classList.toggle("chosen", n.contains(input)));
            updateDeploy();
            AtlasUI.motion.slideUp(q(".ops-deployment"));
            if (AtlasUI.isCitrixVdi(machine)) {
              const healthHost = q("#ops-target-health");
              window.AtlasHealth.mount(
                healthHost,
                target,
                () => valid(g) && target === machine.name,
              );
              const note = healthHost.querySelector(":scope > p");
              if (note)
                note.textContent = AtlasUI.machineSnapshotNote(machine);
            } else health(g, target);
          }),
      );
    host().querySelectorAll(".ops-machine").forEach(card => {
      const m = current.machines[Number(card.querySelector("input").value)], windows = AtlasUI.supportsWindows(m);
      AtlasContext.bindDevice(card, m, [
        {id: "specs", label: "View specifications", section: "Remote support", disabled: !windows, reason: "Windows tools require a PC", run: () => window.AtlasHealth.specs(m.name)},
        {id: "remote-registry", label: "Enable Remote Registry…", section: "Remote support", disabled: !windows, reason: "Windows tools require a PC", run: () => openRemoteRegistry(m.name)},
        {id: "admin", label: "Open Remote Admin", section: "Remote support", disabled: !windows, reason: "Windows tools require a PC", navigate: true, run: () => AtlasContext.navigate({machine: m.name, command: "admin"})},
        {id: "deploy", label: "Deploy software…", section: "Deployment", disabled: !windows, reason: "Windows tools require a PC", navigate: true, run: () => AtlasContext.navigate({machine: m.name, command: "deploy"})},
      ]);
    });
    let filterTimer;
    q("#ops-package-filter").oninput = () => {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(() => loadPackages(g), 200);
    };
    q("#ops-package").onchange = () => loadScripts(g);
    q("#ops-action").onchange = () => loadScripts(g);
    q("#ops-mode").onchange = updateDeploy;
    q("#ops-script").onchange = () => {
      previewVersion++;
      q("#ops-script-content").hidden = true;
      updateDeploy();
    };
    q("#ops-preview").onclick = () => preview(g);
    q("#ops-deploy").onclick = () => deploy(g);
    loadPackages(g);
  }
  function historyRows(rows) {
    return rows.length
      ? rows
          .map(
            (r) =>
              `<div class="ops-history-row"><b>${esc(r.package)}</b><span>${esc(r.target)} · ${esc(r.action)}</span><small>${esc(r.started)} · <strong class="${r.state === "failed" ? "ops-error" : ""}">${esc(r.state)}</strong>${r.exit_code ? " · exit " + esc(r.exit_code) : ""}</small></div>`,
          )
          .join("")
      : '<p class="ops-muted">No deployments recorded for this desk.</p>';
  }
  function showCandidates(users, g) {
    if (!valid(g)) return;
    const list = host().querySelector("#ops-user-results");
    list.innerHTML = users.length
      ? users
          .slice(0, 30)
          .map(
            (u, i) =>
              `<button class="ops-user-result" ${AtlasContext.attributes("user", u)} data-link-user="${i}"><b>${esc(u.full_name || u.name)}</b><span>${esc(u.user_name || u.user_id)} · ${esc(u.email)}</span><span>${esc(u.department || u.business_unit || "Team not recorded")} · ${esc(u.location || "Office not recorded")}</span><small>${current.desk.kind === "desk" ? "Use this name and account" : "Confirm as desk & use this account"}</small></button>`,
          )
          .join("")
      : '<p class="ops-muted">No exact match. Search the directory above.</p>';
    list.querySelectorAll("[data-link-user]").forEach(
      (b) =>
        (b.onclick = async () => {
          const u = users[+b.dataset.linkUser];
          if (
            !confirm(
              `Update ${current.desk.id}?\n\nCurrent label: ${current.desk.name}\nDirectory name: ${u.full_name || u.name}\nAccount: ${u.user_name || u.user_id}\nTeam: ${u.department || u.business_unit || "Not recorded"}\nOffice: ${u.location || "Not recorded"}\n${current.desk.kind !== "desk" ? " This converts the area record to a desk." : ""} This updates its recorded occupant; on-site verification stays off.`,
            )
          )
            return;
          b.disabled = true;
          try {
            await api(
              "/api/desks/" + encodeURIComponent(current.desk.id) + "/link",
              {
                method: "POST",
                body: JSON.stringify({
                  user_key: u.canonical_key,
                  revision: current.desk.revision,
                }),
              },
            );
            if (valid(g)) {
              await onChange();
              toast("Directory user linked to desk");
            }
          } catch (e) {
            if (valid(g)) {
              b.disabled = false;
              toast(e.message);
            }
          }
        }),
    );
  }
  async function findUser(g) {
    const term = host().querySelector("#ops-user-search").value.trim(),
      v = ++userSearchVersion;
    if (!term) {
      showCandidates([], g);
      return;
    }
    host().querySelector("#ops-user-results").textContent =
      "Searching directory…";
    try {
      const data = await api(
        "/api/search?term=" + encodeURIComponent("user:" + term),
      );
      if (valid(g) && v === userSearchVersion) showCandidates(data.users, g);
    } catch (e) {
      if (valid(g) && v === userSearchVersion) {
        host().querySelector("#ops-user-results").textContent =
          "Search unavailable. Try again.";
        toast(e.message);
      }
    }
  }
  async function health(g, pc) {
    return window.AtlasHealth.quick(
      host().querySelector("#ops-target-health"),
      pc,
      () => valid(g) && target === pc,
    );
  }
  async function loadPackages(g) {
    const v = ++catalogVersion;
    if (!valid(g)) return;
    const term = host().querySelector("#ops-package-filter").value;
    try {
      const d = await api("/api/catalog?term=" + encodeURIComponent(term));
      if (!valid(g) || v !== catalogVersion) return;
      host().querySelector("#ops-package").innerHTML =
        d.items
          .map(
            (p) =>
              `<option value="${esc(p.folder)}" data-display-name="${esc(p.display_name)}" data-version="${esc(p.version)}">${esc(p.display_name)}${p.version ? " · " + esc(p.version) : ""}</option>`,
          )
          .join("") || '<option value="">No packages found</option>';
      host().querySelector("#ops-package-status").textContent = d.error
        ? d.error + " " + d.repository
        : (d.truncated
            ? "Showing first 500 matches. Refine the filter. "
            : "") +
          (d.repository || "Check the package repository in Settings.");
      await loadScripts(g);
    } catch (e) {
      if (valid(g) && v === catalogVersion) toast(e.message);
    }
  }
  let detailsVersion = 0;
  async function refreshPackageDetails(g, pkg) {
    const v = ++detailsVersion;
    packageDetails = null;
    const q = (x) => host()?.querySelector(x);
    if (q("#ops-package-details"))
      q("#ops-package-details").textContent = pkg
        ? "Inspecting package metadata…"
        : "";
    if (!pkg) return;
    try {
      const d = await api(
        "/api/catalog/details?folder=" + encodeURIComponent(pkg),
      );
      if (!valid(g) || v !== detailsVersion || q("#ops-package").value !== pkg)
        return;
      packageDetails = d;
      q("#ops-package-details").innerHTML =
        `<p><b>${esc(d.display_name || pkg)}</b> · ${esc(d.version || "Version not recorded")}</p><small>${esc(d.availability)} · ${d.files_checked} files checked${d.complete ? "" : " · scan incomplete"}</small><p class="ops-muted">${esc(d.availability_note)}</p><small>Install: ${d.scripts.Install.length} · Uninstall: ${d.scripts.Uninstall.length} · Repair: ${d.scripts.Repair.length}</small>`;
      updateDeploy();
    } catch (e) {
      if (valid(g) && v === detailsVersion)
        q("#ops-package-details").textContent =
          "Metadata inspection unavailable: " + e.message;
    }
  }
  async function loadScripts(g) {
    if (!valid(g)) return;
    const q = (s) => host().querySelector(s),
      pkg = q("#ops-package").value,
      action = q("#ops-action").value,
      v = ++scriptVersion;
    previewVersion++;
    refreshPackageDetails(g, pkg);
    q("#ops-script").innerHTML = '<option value="">Loading…</option>';
    q("#ops-script-content").hidden = true;
    updateDeploy();
    if (!pkg) {
      q("#ops-script").innerHTML = '<option value="">Select a package</option>';
      return;
    }
    try {
      const d = await api(
        "/api/scripts?package=" +
          encodeURIComponent(pkg) +
          "&action=" +
          encodeURIComponent(action),
      );
      if (!valid(g) || v !== scriptVersion) return;
      q("#ops-script").innerHTML =
        d.scripts
          .map((s) => `<option value="${esc(s)}">${esc(s)}</option>`)
          .join("") || '<option value="">No matching script</option>';
      updateDeploy();
    } catch (e) {
      if (valid(g) && v === scriptVersion) toast(e.message);
    }
  }
  function updateDeploy() {
    if (!host()) return;
    const q = (s) => host().querySelector(s);
    if (q("#ops-deploy"))
      q("#ops-deploy").disabled =
        submitting ||
        current?.desk.kind !== "desk" ||
        !target ||
        !q("#ops-package").value ||
        !q("#ops-script").value;
    const fields = [
      ["Person", current?.user?.full_name || "No directory user"],
      ["Machine", target || "Choose a machine"],
      [
        "Application",
        packageDetails?.display_name ||
          q("#ops-package")?.selectedOptions[0]?.dataset.displayName ||
          q("#ops-package")?.value ||
          "Choose a package",
      ],
      [
        "Version",
        packageDetails?.version ||
          q("#ops-package")?.selectedOptions[0]?.dataset.version ||
          "Not recorded",
      ],
      ["Action", q("#ops-action")?.value],
      ["Script", q("#ops-script")?.value || "Choose a script"],
      ["Mode", q("#ops-mode")?.selectedOptions[0]?.textContent],
    ];
    if (q("#ops-deploy-summary"))
      q("#ops-deploy-summary").innerHTML = fields
        .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
        .join("");
  }
  async function preview(g) {
    const q = (s) => host().querySelector(s),
      pkg = q("#ops-package").value,
      script = q("#ops-script").value,
      action = q("#ops-action").value,
      v = ++previewVersion;
    if (!pkg || !script) return;
    try {
      const d = await api(
        "/api/package-script?package=" +
          encodeURIComponent(pkg) +
          "&script=" +
          encodeURIComponent(script) +
          "&action=" +
          action,
      );
      if (
        !valid(g) ||
        v !== previewVersion ||
        q("#ops-package").value !== pkg ||
        q("#ops-action").value !== action ||
        q("#ops-script").value !== script
      )
        return;
      q("#ops-script-content").textContent = d.content;
      q("#ops-script-content").hidden = false;
    } catch (e) {
      if (valid(g) && v === previewVersion) toast(e.message);
    }
  }
  async function deploy(g) {
    if (submitting || !valid(g) || !target) return;
    const q = (s) => host().querySelector(s),
      pc = target,
      body = {
        computer: pc,
        folder: q("#ops-package").value,
        script: q("#ops-script").value,
        action: q("#ops-action").value,
        mode: q("#ops-mode").value,
        revision: current.desk.revision,
        user_key: current.user?.canonical_key || null,
      };
    if (
      !confirm(
        `${body.action} ${body.folder}\n\nDesk: ${current.desk.id}\nUser: ${current.user?.full_name || "No directory user"}\nMachine: ${pc}\nScript: ${body.script}\nMode: ${body.mode}\n\nStart this operation?`,
      )
    )
      return;
    submitting = true;
    updateDeploy();
    try {
      const d = await api(
        "/api/desks/" + encodeURIComponent(current.desk.id) + "/deploy",
        { method: "POST", body: JSON.stringify(body) },
      );
      if (valid(g)) {
        job = d.job;
        poll(g, d.job);
      }
    } catch (e) {
      if (valid(g)) q("#ops-job").textContent = e.message;
      submitting = false;
      updateDeploy();
    }
  }
  async function poll(g, id) {
    try {
      const d = await api("/api/job/" + id);
      if (!valid(g) || job !== id) return;
      const box = host().querySelector("#ops-job");
      box.innerHTML = `<b class="${d.state === "failed" ? "ops-error" : ""}">${esc(d.events.some((x) => x.pid) ? "Launched" : d.state)}</b><pre>${esc(d.events.map((x) => `[${x.time || ""}] ${x.message}${x.log ? "\n" + x.log.join("\n") : ""}`).join("\n"))}</pre>`;
      if (!["complete", "launched", "failed"].includes(d.state))
        timer = setTimeout(() => poll(g, id), 1500);
      else {
        submitting = false;
        updateDeploy();
        const ctx = await api(
          "/api/desks/" + encodeURIComponent(current.desk.id) + "/context",
        );
        if (valid(g))
          host().querySelector("#ops-desk-history").innerHTML = historyRows(
            ctx.deployments,
          );
      }
    } catch (e) {
      if (valid(g)) {
        host().querySelector("#ops-job").textContent =
          "Monitoring interrupted. Check Deployments before retrying. " +
          e.message;
        submitting = false;
        updateDeploy();
      }
    }
  }
  function machineRows() {
    const groups = [
      "Assigned to user",
      "Desk equipment",
      "Last logged on (inventory)",
    ];
    return (
      groups
        .map((group) => {
          const rows = current.machines
            .map((m, i) => ({ m, i }))
            .filter(
              ({ m }) =>
                (m.relationship_group || "Last logged on (inventory)") ===
                group,
            );
          return rows.length
            ? `<div class="ops-machine-group"><h4>${esc(group)} <span>${rows.length}</span></h4>${rows.map(({ m, i }) => `<div class="ops-machine-entry" data-machine-kind="${AtlasUI.machineKind(m)}"><label class="ops-machine"><input type="radio" name="ops-machine" value="${i}" ${AtlasUI.supportsWindows(m) ? "" : 'disabled aria-label="Inventory only: Windows tools require a PC"'}><div><b>${esc(m.name)}</b>${window.AtlasHealth.badges(m)}<span>${esc(m.model_id || "Model unavailable")}${m.operational_status ? " · " + esc(m.operational_status) + " (inventory)" : ""}</span>${AtlasUI.supportsWindows(m) ? "" : '<small class="atlas-device-note">Inventory only · Windows tools require a PC.</small>'}<small>${esc(m.match_type || m.link_source || "Recorded at this desk")}${m.desk_equipment && m.assigned_relationship ? " · Also recorded at this desk" : ""}</small><small>Inventory discovered: ${esc(m.inventory_discovered_at || m.last_discovered || "Not supplied")}</small><small>Record updated: ${esc(m.inventory_updated_at || m.updated_on || "Not supplied")}</small></div></label>${AtlasUI.machineDetails(m)}</div>`).join("")}</div>`
            : "";
        })
        .join("") ||
      '<p class="ops-muted">No linked machines. Link a directory user or record a verified hostname under Desk record.</p>'
    );
  }
  function dialogShell(title) {
    const d = document.createElement("dialog");
    d.className = "ops-dialog ops-wide";
    d.innerHTML = `<div class="ops-dialog-heading"><h2>${esc(title)}</h2><button aria-label="Close">×</button></div><div class="ops-dialog-body"></div>`;
    d.querySelector("button").onclick = () => d.close();
    d.onclose = () => d.remove();
    document.body.append(d);
    d.showModal();
    return d;
  }
  const issueNames = {
    "person-as-area": "Person recorded as area",
    unmatched: "Name not matched",
    ambiguous: "Ambiguous name",
    "missing-linked-user": "Linked account missing",
    "unconfirmed-link": "Directory link unconfirmed",
    "duplicate-person": "Possible duplicate seating",
    "duplicate-hostname": "Hostname at multiple desks",
  };
  async function audit() {
    const d = dialogShell("Review Paris mappings"),
      body = d.querySelector(".ops-dialog-body");
    body.textContent = "Checking mapped locations…";
    try {
      const data = await api("/api/ops/audit");
      if (!d.isConnected) return;
      body.innerHTML = `<p>${data.rows.length} Paris locations need review out of ${data.locations_checked}. Users elsewhere in Europe do not need a Paris desk. Suggestions do not change records.</p><p class="ops-muted">${esc(data.note)}</p><div class="ops-two"><label class="ops-label">Issue<select id="audit-type"><option value="">All issues</option>${Object.entries(
        data.counts,
      )
        .map(
          ([k, v]) =>
            `<option value="${k}">${esc(issueNames[k])} (${v})</option>`,
        )
        .join(
          "",
        )}</select></label><label class="ops-label">Find a location<input id="audit-search" placeholder="Name, desk or floor"></label></div><div id="audit-results"></div>`;
      const render = () => {
        const issue = d.querySelector("#audit-type").value,
          q = d.querySelector("#audit-search").value.toLowerCase();
        const rows = data.rows.filter(
          (e) =>
            (!issue || e.issues.includes(issue)) &&
            `${e.desk.name} ${e.desk.id} ${e.desk.floor}`
              .toLowerCase()
              .includes(q),
        );
        d.querySelector("#audit-results").innerHTML =
          rows
            .map(
              (e) =>
                `<article class="audit-row"><div><b>${esc(e.desk.name)}</b><p>${esc(e.desk.id)} · Level ${e.desk.floor}</p><p>${e.issues.map((i) => `<span class="ops-chip">${esc(issueNames[i])}</span>`).join(" ")}</p>${
                  e.candidates.length
                    ? `<small>${e.candidates.length === 1 ? "Suggested account:" : "Candidate accounts:"} ${e.candidates
                        .slice(0, 4)
                        .map((u) => esc(u.user_name))
                        .join(", ")}</small>`
                    : ""
                }${e.related_desks.length ? `<p>Also review: ${e.related_desks.map((id) => `<button data-audit-desk="${esc(id)}">${esc(id)}</button>`).join(" ")}</p>` : ""}</div><button data-audit-desk="${esc(e.desk.id)}">Review location</button></article>`,
            )
            .join("") || "<p>No matching review items.</p>";
        d.querySelectorAll("[data-audit-desk]").forEach(
          (b) =>
            (b.onclick = () => {
              d.close();
              onSelect?.(b.dataset.auditDesk);
            }),
        );
      };
      d.querySelector("#audit-type").onchange = render;
      d.querySelector("#audit-search").oninput = render;
      render();
    } catch (e) {
      body.textContent = e.message;
    }
  }
  const catalogue = () =>
    openCatalogue({
      api,
      toast,
      onSave: () => (current ? loadPackages(generation) : undefined),
    });
  async function settings() {
    try {
      const d = await api("/api/ops/settings");
      const dialog = document.createElement("dialog");
      dialog.className = "ops-dialog";
      dialog.innerHTML = `<form><span class="eyebrow">LOCAL APPLICATION SETTINGS</span><h2>Package repository</h2><p>Choose the folder containing your application package subfolders.</p><label class="ops-label">Repository path<input id="ops-repo-input" value="${esc(d.repository)}" required></label><p class="ops-muted">Shared database: ${esc(d.database)} · Python: ${esc(d.python)}</p><p id="ops-settings-error" class="ops-error"></p><div class="ops-actions"><button type="button" id="ops-settings-close">Cancel</button><button class="primary">Save settings</button></div></form>`;
      document.body.append(dialog);
      dialog.querySelector("#ops-settings-close").onclick = () =>
        dialog.close();
      dialog.onclose = () => dialog.remove();
      dialog.querySelector("form").onsubmit = async (e) => {
        e.preventDefault();
        try {
          await api("/api/ops/settings", {
            method: "POST",
            body: JSON.stringify({
              repository: dialog.querySelector("input").value,
            }),
          });
          dialog.close();
          toast("Repository saved");
          if (current) loadPackages(generation);
        } catch (e) {
          dialog.querySelector("#ops-settings-error").textContent = e.message;
        }
      };
      dialog.showModal();
    } catch (e) {
      toast(e.message);
    }
  }
  async function history() {
    try {
      const rows = await api("/api/history?limit=100");
      const dialog = document.createElement("dialog");
      dialog.className = "ops-dialog ops-wide";
      dialog.innerHTML = `<div class="ops-dialog-heading"><div><span class="eyebrow">SHARED DEPLOYMENT HISTORY</span><h2>Recent operations</h2></div><button aria-label="Close">×</button></div><p class="ops-muted">Active jobs continue when you close the desk inspector. Open the IT console for live monitoring.</p><div class="ops-history-grid">${historyRows(rows)}</div><a class="ops-link-button" href="/installer" target="_blank" rel="noopener">Full IT console and live jobs ↗</a>`;
      dialog.querySelector("button").onclick = () => dialog.close();
      dialog.onclose = () => dialog.remove();
      document.body.append(dialog);
      dialog.showModal();
    } catch (e) {
      toast(e.message);
    }
  }
  document.querySelector("#ops-audit").onclick = audit;
  document.querySelector("#ops-catalog").onclick = catalogue;
  if (new URLSearchParams(location.search).get("catalog") === "1") catalogue();
  document.querySelector("#ops-settings").onclick = settings;
  document.querySelector("#ops-history").onclick = history;
  document.querySelector("#ops-import-atlas").onclick = () =>
    document.querySelector("#ops-db-file").click();
  document.querySelector("#ops-db-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      if (
        !confirm(
          "Import this Atlas database backup? Matching desk records will be replaced by the backup. Directory and deployment history are preserved. Back up the shared database first.",
        )
      )
        return;
      const d = await api("/api/atlas/import-db", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: f,
      });
      await onChange();
      toast(
        d.already_imported
          ? "This backup was already imported"
          : `${d.imported} desk records imported`,
      );
    } catch (e) {
      toast(e.message);
    } finally {
      e.target.value = "";
    }
  };
  return { select, clear, getTarget: () => target };
}
