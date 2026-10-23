const esc = (value) => AtlasUI.esc(value);
async function api(url, signal) {
  const response = await fetch(url, { cache: "no-store", signal });
  const data = await response.json();
  if (!response.ok)
    throw Error(data.detail || "Lookup unavailable. Refresh and try again.");
  return data;
}
const personCard = (user) =>
  user
    ? AtlasUI.person(user)
    : '<p class="ops-muted">No confirmed directory account for this desk. Use User lookup to search the full directory.</p>';
const relationship = (row) =>
  row.assigned_relationship && row.logon_relationship
    ? "Assigned + last logged on (inventory)"
    : row.assigned_relationship
      ? "Assigned to user"
      : row.logon_relationship
        ? "Last logged on (inventory)"
        : row.match_type || "Directory inventory";
function machinesCard(machines, inspect = true) {
  return (
    `<div${inspect ? " data-machine-list" : ""}><h3>Stored machine details</h3><p class="ops-muted">Directory inventory; no live or elevated checks are run.</p>` +
    (machines
      .map((m) => {
        const name = m.name || m.machine_name;
        return `<article class="viewer-machine" ${AtlasContext.attributes("device", m)} data-machine-kind="${AtlasUI.machineKind(m)}"><b>${esc(name)}</b>${AtlasUI.machineBadges(m)}<p class="ops-muted">${esc(relationship(m))}</p><p>${esc(m.model_id || "Model not supplied")}${m.operational_status ? " · " + esc(m.operational_status) + " (inventory)" : ""}</p>${AtlasUI.machineDetails(m, { open: !inspect })}${inspect ? `<button type="button" data-machine="${esc(name)}">Inspect machine</button>` : ""}</article>`;
      })
      .join("") || "<p>No linked machines recorded.</p>") +
    "</div>"
  );
}
function deskButtons(desks) {
  return desks.length
    ? '<div class="viewer-desk-links">' +
        desks
          .map(
            (d) =>
              `<button type="button" data-desk="${esc(d.id)}">Show desk ${esc(d.id)} · L${d.floor}${d.match === "confirmed account link" ? "" : d.match === "recorded at this desk" ? " · equipment record" : " · name match, unconfirmed"}</button>`,
          )
          .join("") +
        "</div>"
    : '<p class="ops-muted">No mapped desk recorded.</p>';
}
function userButtons(users) {
  return users
    .map(
      (u) =>
        `<button type="button" class="ops-user-result" ${AtlasContext.attributes("user", u)} data-person="${esc(AtlasUI.personKey(u))}"><b>${esc(u.full_name || u.name)}</b><span>${esc(u.user_name)} · ${esc(u.email)}</span>${u.assigned_relationship || u.logon_relationship ? `<small>${esc(relationship(u))}</small>` : ""}</button>`,
    )
    .join("");
}

export function createViewerOperations({ onSelect, toast }) {
  let generation = 0,
    deskRequest,
    lookup = null,
    lookupVersion = 0,
    lookupRequest;
  const button = document.createElement("button");
  button.textContent = "People";
  button.id = "viewer-lookup";
  button.title = "Search directory users";
  button.setAttribute("aria-label", "Search directory users");
  document.querySelector(".header-right").prepend(button);
  document.querySelector(".empty-detail").innerHTML =
    '<span class="eyebrow">SHARED ATLAS</span><h2>Find a desk or colleague.</h2><p>Search people, machines and locations with Ctrl+K, or explore all ten floors.</p><small>Shared directory and inventory. Changes and elevated operations require the local admin version.</small>';
  AtlasContext.configure({openPerson, search});
  function bindLinks(host, machines = []) {
    host.querySelectorAll(".viewer-machine").forEach((card, i) => {
      if (machines[i]) AtlasContext.bindDevice(card, machines[i]);
    });
    host
      .querySelectorAll("[data-machine-list]")
      .forEach(AtlasUI.machineFilters);
    host
      .querySelectorAll("[data-person]")
      .forEach((b) => (b.onclick = () => openPerson(b.dataset.person)));
    host
      .querySelectorAll("[data-machine]")
      .forEach((b) => (b.onclick = () => openMachine(b.dataset.machine)));
    host.querySelectorAll("[data-desk]").forEach(
      (b) =>
        (b.onclick = () => {
          lookup?.element.close();
          onSelect(b.dataset.desk);
        }),
    );
  }
  function ensureLookup() {
    if (lookup?.element.isConnected) return lookup;
    const { element, body } = AtlasUI.dialog("User & machine lookup");
    element.classList.add("viewer-lookup-dialog");
    body.innerHTML =
      '<form class="viewer-search"><label>Full directory<input type="search" required placeholder="Name, account, email, BRID or machine" aria-label="Directory search"></label><button class="primary">Search</button></form><div class="viewer-results" aria-live="polite"></div>';
    const input = body.querySelector("input"),
      results = body.querySelector(".viewer-results");
    const current = { element, body, input, results };
    lookup = current;
    element.addEventListener(
      "close",
      () => {
        if (lookup === current) {
          lookupVersion++;
          lookupRequest?.abort();
          lookup = null;
        }
      },
      { once: true },
    );
    body.querySelector("form").onsubmit = (event) => {
      event.preventDefault();
      search(input.value.trim());
    };
    input.focus();
    return current;
  }
  async function show(url, render, query) {
    const current = ensureLookup();
    const version = ++lookupVersion;
    lookupRequest?.abort();
    lookupRequest = new AbortController();
    if (query !== undefined) current.input.value = query;
    current.results.textContent = "Loading directory…";
    try {
      const data = await api(url, lookupRequest.signal);
      if (version !== lookupVersion || !current.element.isConnected) return;
      current.results.innerHTML = render(data);
      if (url.startsWith("/api/user/")) AtlasUI.motion.slideUp(current.results);
      bindLinks(current.results, data.machines || (data.machine ? [data.machine] : []));
      const copy = current.results.querySelector("[data-copy-report]");
      if (copy)
        copy.onclick = async () => {
          try {
            await navigator.clipboard.writeText(copy.dataset.copyReport);
            toast("Stored inventory report copied");
          } catch {
            toast("Copy unavailable. Select the report text to copy it.");
          }
        };
    } catch (error) {
      if (
        error.name !== "AbortError" &&
        version === lookupVersion &&
        current.element.isConnected
      )
        current.results.textContent = error.message;
    }
  }
  function search(term) {
    return show(
      "/api/search?" + new URLSearchParams({ term }),
      (data) =>
        userButtons(data.users) +
          (data.machines.length ? machinesCard(data.machines) : "") ||
        "<p>No matches. Try a surname or account.</p>",
      term,
    );
  }
  function openPerson(uid) {
    return show(
      "/api/user/" + encodeURIComponent(uid),
      (person) =>
        personCard(person.user) +
        deskButtons(
          person.desk_matches ||
            person.desks.map((id) => ({ id, match: "matching name" })),
        ) +
        machinesCard(person.machines),
    );
  }
  function openMachine(name) {
    return show(
      "/api/machine/" + encodeURIComponent(name),
      (data) =>
        machinesCard([data.machine], false) +
        `<button type="button" data-copy-report="${esc(AtlasUI.machineReport(data.machine) + "\n\nLinked people\n" + data.users.map((u) => `${u.full_name || u.name} · ${u.user_name || u.user_id} · ${relationship(u)}`).join("\n") + "\n\nRecorded desks\n" + data.desks.map((d) => `${d.id} · L${d.floor}`).join("\n"))}">Copy stored report</button><h3>Linked people</h3><p class="ops-muted">Recorded assignment and logon relationships; not a live sign-in check.</p>` +
        (userButtons(data.users) || "<p>No linked people recorded.</p>") +
        deskButtons(data.desks),
      "machine:" + name,
    );
  }
  const openLookup = () => {
    const current = ensureLookup();
    current.input.focus();
  };
  button.onclick = openLookup;
  return {
    openLookup,
    openPerson,
    openMachine,
    clear() {
      generation++;
      deskRequest?.abort();
    },
    async select(record) {
      const n = ++generation,
        host = document.querySelector("#ops-context");
      deskRequest?.abort();
      deskRequest = new AbortController();
      host.textContent = "Loading directory…";
      try {
        const data = await api(
          "/api/desks/" + encodeURIComponent(record.id) + "/context",
          deskRequest.signal,
        );
        if (n !== generation || !host.isConnected) return;
        const label =
          data.match_method === "confirmed"
            ? "Confirmed account link"
            : data.user
              ? "Name match · account unconfirmed"
              : data.candidates?.length > 1
                ? "Multiple possible people · choose a directory record"
                : "No confirmed account link";
        host.innerHTML =
          `<span class="ops-chip ${data.match_method === "confirmed" ? "good" : ""}">${esc(label)}</span>` +
          personCard(data.user) +
          (data.user
            ? `<button type="button" data-person="${esc(AtlasUI.personKey(data.user))}">Open person details</button>`
            : userButtons(data.candidates || [])) +
          machinesCard(data.machines);
        bindLinks(host, data.machines);
      } catch (error) {
        if (error.name !== "AbortError" && n === generation && host.isConnected)
          host.textContent = error.message;
      }
    },
  };
}
