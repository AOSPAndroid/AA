import { COMMANDS } from "./command-registry.js";
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const normalize = (s) =>
  String(s ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
export function installCommandPalette({
  getRecords,
  onSelect,
  toast,
  runCommand,
  openPerson,
  openMachine,
  prepare,
  triggerParent,
  replaceTrigger,
  readOnly = false,
  preferPersonDetails = false,
}) {
  const mount = document.createElement("span");
  mount.className = "atlas-palette-mount";
  if (replaceTrigger) replaceTrigger.replaceWith(mount);
  else triggerParent.prepend(mount);
  const root = mount.attachShadow({ mode: "open" });
  const sheet = document.createElement("link");
  sheet.rel = "stylesheet";
  sheet.href = "/command-palette.css?v=79";
  root.append(sheet);
  const trigger = document.createElement("button");
  trigger.id = "atlas-commands";
  trigger.innerHTML = "Search Atlas <kbd>Ctrl K</kbd>";
  trigger.setAttribute("aria-label", "Search Atlas commands (Ctrl+K)");
  root.append(trigger);
  const dialog = document.createElement("dialog");
  dialog.className = "atlas-palette";
  dialog.setAttribute("aria-label", "Search Atlas");
  dialog.innerHTML =
    '<div class="palette-input-row"><span aria-hidden="true">⌕</span><input id="atlas-command-input" placeholder="Search people, machines, desks or actions…" aria-label="Search people, machines, desks or actions" role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls="atlas-command-results" autocomplete="off"><button class="palette-close" aria-label="Close search">Esc</button></div><div id="atlas-command-status" role="status" aria-live="polite"></div><div id="atlas-command-results" role="listbox" aria-label="Atlas search results"></div><footer><span>↑ ↓ Navigate · Enter Open · Esc Close</span><span>Try person:, machine:, serial:, asset:, team:, location: or &gt; for actions</span></footer>';
  root.append(dialog);
  const input = dialog.querySelector("input"),
    list = dialog.querySelector("[role=listbox]"),
    status = dialog.querySelector("[role=status]");
  let rows = [],
    active = 0,
    generation = 0,
    timer,
    controller,
    previousFocus;
  const focusedElement = () => {
    let element = document.activeElement;
    while (element?.shadowRoot?.activeElement)
      element = element.shadowRoot.activeElement;
    return element;
  };
  function within(container, element) {
    for (
      let node = element;
      node;
      node = node.parentElement || node.getRootNode()?.host
    )
      if (node === container || container.contains(node)) return true;
    return false;
  }
  function visibleFocusTarget(element) {
    if (
      !element?.isConnected ||
      typeof element.focus !== "function" ||
      element.matches(":disabled")
    )
      return false;
    for (
      let node = element;
      node;
      node = node.parentElement || node.getRootNode()?.host
    ) {
      if (node.hidden || node.inert || node.matches("dialog:not([open])"))
        return false;
      const style = getComputedStyle(node);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        style.visibility === "collapse"
      )
        return false;
    }
    return true;
  }
  const openConsole = (key, value) =>
    key === "person" ? openPerson(value) : openMachine(value);
  const actions = COMMANDS.map((a) => ({
    ...a,
    disabled: readOnly && !a.viewer,
    detail:
      readOnly && !a.viewer
        ? a.detail + " · Requires elevated Atlas Admin"
        : a.detail,
    run: () => runCommand(a.id),
  }));
  function invalidate() {
    generation++;
    clearTimeout(timer);
    controller?.abort();
  }
  function close() {
    invalidate();
    dialog.close();
  }
  function setActive(index) {
    active = rows.length ? (index + rows.length) % rows.length : 0;
    [...list.children].forEach((node, i) => {
      node.setAttribute("aria-selected", String(i === active));
      node.classList.toggle("selected", i === active);
    });
    if (rows.length) {
      input.setAttribute("aria-activedescendant", "atlas-command-" + active);
      list.children[active]?.scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  }
  list.addEventListener("contextmenu",e=>{if(e.target.closest("[data-ad-identity]"))dialog.close();});
  function render(items, message) {
    rows = items;
    active = 0;
    list.innerHTML = rows
      .map(
        (r, i) =>
          `<div id="atlas-command-${i}" class="palette-result" role="option" aria-disabled="${!!r.disabled}" aria-selected="false" data-index="${i}" ${r.adIdentity ? `data-ad-kind="${esc(r.adKind)}" data-ad-identity="${esc(r.adIdentity)}"` : ""}><span class="palette-kind">${esc(r.kind)}</span><span><strong>${esc(r.title)}</strong><small>${esc(r.detail)}</small></span><span aria-hidden="true">${esc(r.disabled ? "Unavailable" : r.shortcut || "↵")}</span></div>`,
      )
      .join("");
    status.textContent =
      message ||
      (!rows.length
        ? "No matches. Try a name, account, hostname or desk number."
        : `${rows.length} ${rows.length === 1 ? "result" : "results"}`);
    setActive(0);
  }
  async function choose(index) {
    const row = rows[index];
    if (!row) return;
    if (row.disabled) {
      status.textContent =
        "Requires Atlas Admin running from an elevated Windows account. Disabled in Demo and Preview.";
      return;
    }
    if (row.person) {
      if (preferPersonDetails) {
        close();
        try {
          await openPerson(row.person);
        } catch (e) {
          toast(e.message);
        }
        return;
      }
      invalidate();
      const request = generation;
      status.textContent = "Finding mapped desks…";
      controller = new AbortController();
      try {
        const response = await fetch(
          "/api/palette/person/" + encodeURIComponent(row.person),
          { signal: controller.signal },
        );
        if (!response.ok)
          throw Error("Could not resolve this person. Try again.");
        const data = await response.json();
        if (request !== generation || !dialog.open) return;
        const desks = data.desks.filter((d) =>
          getRecords().some((r) => r.id === d.id),
        );
        if (desks.length === 1) {
          close();
          onSelect(desks[0].id);
          if (desks[0].match !== "confirmed account link")
            toast("Desk matched by name; account link is not confirmed.");
          return;
        }
        if (!desks.length) {
          close();
          await openConsole("person", row.person);
          return;
        }
        render(
          desks
            .map((d) => ({
              kind: "Desk",
              title: d.id,
              detail: `${row.title} · Floor ${d.floor} · ${d.match}`,
              run: () => onSelect(d.id),
            }))
            .concat({
              kind: "Person",
            adKind:row.adKind,adIdentity:row.adIdentity,
              title: "Open person details",
              detail: row.title,
              run: () => openConsole("person", row.person),
            }),
          "Multiple desk matches — choose a location.",
        );
      } catch (e) {
        if (e.name !== "AbortError" && request === generation)
          status.textContent = e.message;
      }
    } else {
      close();
      try {
        await row.run();
      } catch (e) {
        toast(e.message);
      }
    }
  }
  function search() {
    invalidate();
    const request = generation,
      raw = input.value.trim();
    const prefix = raw.match(/^(person|user|machine|desk|action):\s*/i);
    const kind = raw.startsWith(">") ? "action" : prefix?.[1]?.toLowerCase();
    const term = raw.startsWith(">")
      ? raw.slice(1).trim()
      : prefix
        ? raw.slice(prefix[0].length).trim()
        : raw;
    const q = normalize(term),
      words = q.split(/\s+/).filter(Boolean);
    const matches = (text) => words.every((w) => normalize(text).includes(w));
    const local = [];
    if (!kind || kind === "action")
      local.push(...actions.filter((a) => matches(a.title + " " + a.keywords)));
    if (q && (!kind || kind === "desk"))
      local.push(
        ...getRecords()
          .filter((r) => matches([r.id, r.name, r.team, r.hostname].join(" ")))
          .sort(
            (a, b) =>
              (normalize(b.id) === q) - (normalize(a.id) === q) ||
              a.name.localeCompare(b.name),
          )
          .slice(0, 12)
          .map((r) => ({
            kind: "Desk",
            deskId: r.id,
            title: r.name === "Unconfirmed desk" ? r.id : r.name,
            detail: `${r.id} · Floor ${r.floor} · ${r.team}`,
            run: () => onSelect(r.id),
          })),
      );
    const remote = q.length >= 2 && kind !== "desk" && kind !== "action";
    render(
      // Keep Enter from opening a desk while a console name lookup is pending.
      remote && preferPersonDetails
        ? local.filter((row) => row.kind !== "Desk")
        : local,
      remote
        ? "Searching directory…"
        : q.length === 1 &&
            (!kind || ["user", "person", "machine"].includes(kind))
          ? "Type at least two characters for directory search."
          : "",
    );
    if (!remote) return;
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const query =
          (kind === "person" || kind === "user"
            ? "user:"
            : kind === "machine"
              ? "machine:"
              : "") + term;
        const response = await fetch(
          "/api/search?" +
            new URLSearchParams({ term: query, palette: "true" }),
          { signal: controller.signal },
        );
        if (!response.ok)
          throw Error(
            "Directory unavailable. Map and action results are still available.",
          );
        const data = await response.json();
        if (request !== generation || !dialog.open) return;
        const people = data.users.slice(0, 10).map((u) => {
          const mappedDesks = Array.isArray(u.palette_desks)
            ? u.palette_desks.filter(
                (desk) => desk && typeof desk.id === "string",
              )
            : [];
          const locations = mappedDesks
            .slice(0, 3)
            .map((desk) => `${desk.id} · Floor ${desk.floor ?? "?"}`)
            .join("; ");
          const action = preferPersonDetails
            ? "Open person details"
            : mappedDesks.length
              ? "Locate on map"
              : Array.isArray(u.palette_desks)
                ? "Open person details"
                : "Find mapped location or open details";
          return {
            kind: "Person",
            adKind:"user",adIdentity:u.user_name||u.email||"",
            title: u.full_name || u.name,
            detail: [
              action,
              locations,
              mappedDesks.length > 3
                ? `+${mappedDesks.length - 3} more mapped desks`
                : "",
              u.user_name,
              u.email,
              u.location,
              [
                ...new Set(
                  mappedDesks.map((desk) => desk.match).filter(Boolean),
                ),
              ].join("; "),
            ]
              .filter(Boolean)
              .join(" · "),
            person: String(u.canonical_key || "").trim() || "id:" + u.id,
            mappedDesks,
          };
        });
        // Only server-confirmed identity/provenance can combine a desk with a
        // person. Equal display names never merge directory accounts here.
        const peopleByDesk = new Map();
        for (const person of people)
          for (const desk of person.mappedDesks) {
            const owners = peopleByDesk.get(desk.id) || [];
            owners.push(person);
            peopleByDesk.set(desk.id, owners);
          }
        const placedPeople = new Set();
        const combinedLocal = local.flatMap((row) => {
          const owners = peopleByDesk.get(row.deskId);
          if (!owners) return [row];
          if (preferPersonDetails) return [];
          return owners.filter((person) => {
            if (placedPeople.has(person.person)) return false;
            placedPeople.add(person.person);
            return true;
          });
        });
        const machines = data.machines.slice(0, 10).map((m) => ({
          kind: "Machine",
          adKind:"computer",adIdentity:m.name,
          title: m.name,
          detail: [m.model_id, m.operational_status]
            .filter(Boolean)
            .join(" · "),
          run: () => openConsole("machine", m.name),
        }));
        render(
          preferPersonDetails
            ? [...people, ...machines, ...combinedLocal]
            : [
                ...combinedLocal,
                ...people.filter((person) => !placedPeople.has(person.person)),
                ...machines,
              ],
          data.users.length > 10 || data.machines.length > 10
            ? "Showing the first directory matches. Refine your search for more."
            : "",
        );
      } catch (e) {
        if (e.name !== "AbortError" && request === generation && dialog.open)
          render(local, e.message);
      }
    }, 180);
  }
  async function open(query = "", sourceDialog = null) {
    if (dialog.open) {
      if (typeof query === "string" && query) {
        input.value = query;
        search();
      }
      input.focus();
      return;
    }
    // Do not interrupt an existing edit/confirmation dialog.
    if (
      [...document.querySelectorAll("dialog[open]")].some(
        (existing) => existing !== sourceDialog,
      )
    )
      return;
    previousFocus = focusedElement();
    dialog.showModal();
    input.value = typeof query === "string" ? query : "";
    search();
    input.focus();
    if (prepare) {
      try {
        await prepare();
        if (dialog.open) search();
      } catch {
        if (dialog.open)
          status.textContent =
            "Map records unavailable. Directory and commands are still available.";
      }
    }
  }
  trigger.onclick = open;
  input.oninput = search;
  dialog.querySelector(".palette-close").onclick = close;
  dialog.addEventListener("close", () => {
    // Native close events are queued: a command may already have focused its
    // textarea, editor or dialog, or reopened this palette before this runs.
    if (dialog.open) return;
    invalidate();
    const current = focusedElement();
    if (
      current &&
      current !== document.body &&
      current !== document.documentElement &&
      current !== previousFocus &&
      !within(root, current) &&
      visibleFocusTarget(current)
    )
      return;
    if (
      [...document.querySelectorAll("dialog[open]")].some(
        (existing) => !within(existing, previousFocus),
      )
    )
      return;
    const target = visibleFocusTarget(previousFocus) ? previousFocus : trigger;
    if (visibleFocusTarget(target)) target.focus();
  });
  dialog.addEventListener("cancel", invalidate);
  dialog.addEventListener("click", (e) => {
    const option = e.target.closest("[data-index]");
    if (option) choose(+option.dataset.index);
    else if (e.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (
        e.clientX < box.left ||
        e.clientX > box.right ||
        e.clientY < box.top ||
        e.clientY > box.bottom
      )
        close();
    }
  });
  dialog.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive(active + (e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Enter" && e.target === input) {
      e.preventDefault();
      choose(active);
    }
  });
  root.addEventListener("keydown", (e) => {
    if (dialog.open) e.stopPropagation();
  });
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      open();
    }
  });
  window.addEventListener("atlas-directory-search", (event) => {
    const person = event.target.closest?.(".atlas-person"),
      query = event.detail?.query;
    if (!person || typeof query !== "string" || !query.trim()) return;
    open(query, person.closest(".viewer-lookup-dialog"));
  });
  return { open, close, dialog, root };
}
