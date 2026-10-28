/* Shared display primitives and on-demand, read-only export inspection. */
(() => {
  const motionMedia = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motionKey = "atlas-motion";
  const displayKey = "atlas-display-mode";
  let displayChoice = "standard";
  try {
    displayChoice =
      localStorage.getItem(displayKey) === "citrix" ? "citrix" : "standard";
  } catch {}
  const isCitrix = () => displayChoice === "citrix";
  function applyDisplay() {
    document.documentElement.dataset.atlasDisplay = displayChoice;
    document
      .querySelectorAll(".atlas-display-mode select")
      .forEach((select) => {
        select.value = displayChoice;
      });
    window.dispatchEvent(new Event("atlas-display-change"));
    window.dispatchEvent(new Event("atlas-motion-change"));
  }
  function setDisplay(value) {
    displayChoice = value === "citrix" ? "citrix" : "standard";
    try {
      localStorage.setItem(displayKey, displayChoice);
    } catch {}
    applyDisplay();
  }
  document.documentElement.dataset.atlasDisplay = displayChoice;
  // Light or dark theme: follows Windows until the header button picks one.
  // Applied here, before the page draws, so dark mode never flashes white.
  const themeKey = "atlas-theme";
  const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
  let themeChoice = null;
  const readTheme = () => {
    try {
      const saved = localStorage.getItem(themeKey);
      themeChoice = saved === "dark" || saved === "light" ? saved : null;
    } catch {}
  };
  const currentTheme = () => themeChoice || (themeMedia.matches ? "dark" : "light");
  function applyTheme() {
    const theme = currentTheme();
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelectorAll(".atlas-theme-toggle").forEach((button) => {
      const next = theme === "dark" ? "light" : "dark";
      button.setAttribute("aria-pressed", String(theme === "dark"));
      button.setAttribute("aria-label", `Switch to ${next} mode`);
      button.title = `Switch to ${next} mode`;
    });
    window.dispatchEvent(new Event("atlas-theme-change"));
  }
  function setTheme(value) {
    themeChoice = value === "dark" ? "dark" : "light";
    try { localStorage.setItem(themeKey, themeChoice); } catch {}
    applyTheme();
  }
  readTheme();
  applyTheme();
  themeMedia.addEventListener?.("change", applyTheme);
  window.addEventListener("storage", (event) => {
    if (event.key === themeKey || event.key === null) { readTheme(); applyTheme(); }
  });
  let motionChoice = "system";
  try {
    motionChoice = localStorage.getItem(motionKey) || "system";
  } catch {}
  const isReduced = () =>
    motionChoice === "reduce" ||
    (motionChoice !== "full" && motionMedia.matches);
  function applyMotion() {
    document.documentElement.dataset.atlasMotion = isReduced()
      ? "reduce"
      : "full";
    document.querySelectorAll(".atlas-motion-toggle").forEach((el) => {
      el.querySelector("input").checked = !isReduced();
      el.querySelector(".atlas-motion-state").textContent = isReduced()
        ? "Off"
        : "On";
    });
    window.dispatchEvent(new Event("atlas-motion-change"));
  }
  motionMedia.addEventListener?.("change", applyMotion);
  window.addEventListener("storage", (event) => {
    if (event.key === displayKey || event.key === null) {
      try {
        displayChoice =
          localStorage.getItem(displayKey) === "citrix" ? "citrix" : "standard";
      } catch {}
      applyDisplay();
    }
    if (event.key === motionKey || event.key === null) {
      try {
        motionChoice = localStorage.getItem(motionKey) || "system";
      } catch {}
      applyMotion();
    }
  });
  applyMotion();
  function setMotion(enabled) {
    motionChoice = enabled ? "full" : "reduce";
    try {
      localStorage.setItem(motionKey, motionChoice);
    } catch {}
    applyMotion();
  }
  const isWorkspace = () =>
    document.documentElement.dataset.atlasSurface === "workspace" ||
    !!document.getElementById("deploymentPanel");
  const applySurfaceProfile = () => {
    document.documentElement.dataset.atlasSurface = isWorkspace()
      ? "workspace"
      : "map";
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", applySurfaceProfile, {
      once: true,
    });
  else applySurfaceProfile();
  const activeReveals = new Map();
  function reveal(
    element,
    { distance = 18, duration = 320, delay = 0, settle = false } = {},
  ) {
    activeReveals.get(element)?.cancel();
    if (
      isReduced() ||
      isCitrix() ||
      !element?.animate ||
      element.hidden ||
      document.hidden
    )
      return;
    const workspace = isWorkspace();
    if (workspace) {
      distance = Math.min(distance, settle ? 32 : 8);
      duration = Math.min(duration, settle ? 280 : 180);
      delay = 0;
    }
    // A panel entrance already moves its cards; don't stack scroll effects inside it.
    for (
      let parent = element.parentElement;
      parent;
      parent = parent.parentElement
    )
      if (activeReveals.has(parent)) return;
    // If a panel opens after its cards appeared, replace their entrances with one motion.
    for (const [child, animation] of activeReveals)
      if (element.contains(child)) animation.cancel();
    const frames = settle
      ? [
          {
            opacity: workspace ? 0.55 : 0.2,
            transform: `translateY(${distance}px) scale(${workspace ? 0.995 : 0.985})`,
            offset: 0,
            easing: "cubic-bezier(0.16, 1, 0.3, 1)",
          },
          {
            opacity: 1,
            transform: `translateY(${workspace ? -1 : -2}px) scale(1)`,
            offset: 0.78,
            easing: "ease-in-out",
          },
          { opacity: 1, transform: "translateY(0) scale(1)", offset: 1 },
        ]
      : [
          {
            opacity: workspace ? 0.65 : 0.3,
            transform: `translateY(${distance}px)`,
          },
          { opacity: 1, transform: "translateY(0)" },
        ];
    const animation = element.animate(frames, {
      duration,
      delay,
      fill: workspace ? "none" : "backwards",
      easing: settle ? "linear" : "cubic-bezier(0.22, 1, 0.36, 1)",
    });
    activeReveals.set(element, animation);
    const clear = () => {
      if (activeReveals.get(element) === animation)
        activeReveals.delete(element);
    };
    animation.onfinish = clear;
    animation.oncancel = clear;
  }
  const slideUp = (element) =>
    reveal(element, { distance: 58, duration: 440, settle: true });
  const clearReveals = () => {
    for (const animation of activeReveals.values()) animation.cancel();
    activeReveals.clear();
  };
  window.addEventListener("atlas-motion-change", () => {
    if (isReduced() || isCitrix()) clearReveals();
  });
  window.addEventListener("pagehide", clearReveals);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearReveals();
  });
  function installScrollReveals() {
    if (typeof IntersectionObserver === "undefined") return;
    const selector =
      ".machine, .ops-machine, .viewer-machine, .atlas-person, .atlas-health-item, .deployment-monitor-card";
    const seen = new WeakSet(),
      observed = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        let animated = 0;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          observer.unobserve(entry.target);
          observed.delete(entry.target);
          seen.add(entry.target);
          // Limit simultaneous effects when a long result list first appears.
          if (animated < 6) reveal(entry.target, { delay: animated++ * 32 });
        }
      },
      { threshold: 0.08 },
    );
    const scan = (node, removed = false) => {
      if (node.nodeType !== 1) return;
      const elements = [
        ...(node.matches(selector) ? [node] : []),
        ...node.querySelectorAll(selector),
      ];
      for (const element of elements) {
        if (removed) {
          observer.unobserve(element);
          observed.delete(element);
          activeReveals.get(element)?.cancel();
        } else if (!seen.has(element) && !observed.has(element)) {
          observed.add(element);
          observer.observe(element);
        }
      }
    };
    const changes = new MutationObserver((records) => {
      for (const record of records) {
        record.removedNodes.forEach((node) => scan(node, true));
        record.addedNodes.forEach((node) => scan(node));
      }
    });
    const stop = () => {
      observer.disconnect();
      changes.disconnect();
      observed.clear();
    };
    const sync = () => {
      stop();
      if (isReduced() || isCitrix()) return;
      scan(document.body);
      changes.observe(document.body, { childList: true, subtree: true });
    };
    window.addEventListener("atlas-motion-change", sync);
    window.addEventListener("pagehide", stop);
    window.addEventListener("pageshow", sync);
    sync();
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", installScrollReveals, {
      once: true,
    });
  else installScrollReveals();
  const iconPaths = {
    map: '<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5Zm6-2v16m6-14v16"/>',
    workspace: '<path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    inbox: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
    knowledge: '<path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3V4Zm9 2v15M6 8h3m-3 4h3m6-4h3m-3 4h3"/>',
    packages: '<path d="m12 3 9 5v8l-9 5-9-5V8l9-5Zm-9 5 9 5 9-5m-9 5v8M7.5 5.5l9 5"/>',
    deployment: '<path d="M12 3v10m-4-4 4 4 4-4M5 13H3v7h18v-7h-2M7 17h10"/>',
    queue: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3" cy="6" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="18" r="1"/>',
    'active-directory': '<rect x="8" y="2" width="8" height="5" rx="1"/><path d="M12 7v5M4 16v-4h16v4"/><rect x="1" y="16" width="6" height="5" rx="1"/><rect x="9" y="16" width="6" height="5" rx="1"/><rect x="17" y="16" width="6" height="5" rx="1"/>',
    psexec: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/>',
    scripts: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M10 12l-2 2 2 2m4-4 2 2-2 2"/>',
    admin: '<path d="M4 5h16v11H4zM8 20h8M12 16v4"/>',
    laptop: '<rect x="5" y="4" width="14" height="11" rx="1"/><path d="m5 15-3 5h20l-3-5M9 17h6"/>',
    phone: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 5h4m-3 14h2"/>',
    tablet: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M11 18h2"/>',
    bulk: '<path d="M5 4h14v4H5zM5 10h14v4H5zM5 16h14v4H5z"/>',
    joiners: '<circle cx="10" cy="7.5" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0M19 8v6m-3-3h6"/>',
    personas: '<circle cx="9" cy="7.5" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 10-5.5M18 12l3.5 2v4L18 20l-3.5-2v-4L18 12Zm-3.5 2 3.5 2 3.5-2M18 16v4"/>',
    history: '<path d="M4 12a8 8 0 1 0 2.3-5.7L4 8.6M4 4v4.6h4.6M12 7v5l3 2"/>',
    clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M8.5 10h7M8.5 14h7M8.5 18h4"/>',
    copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    external: '<path d="M14 3h7v7m0-7L10 14M11 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
  };
  function icon(name) {
    const paths = iconPaths[name === "terminal" ? "psexec" : name];
    return paths ? `<svg class="atlas-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>` : "";
  }
  function installIcons(root = document) {
    root.querySelectorAll('[data-atlas-icon]').forEach(element => {
      if (!element.querySelector('.atlas-icon')) element.insertAdjacentHTML('afterbegin', icon(element.dataset.atlasIcon));
    });
  }
  function installShell() {
    installIcons();
    const header = document.querySelector("body > .atlas-app-header");
    if (!header) return;
    const actions = header.querySelector(".atlas-header-actions");
    // One stable toolbar on Map, Workspace and Knowledge Base.
    if (actions && header.querySelector('.atlas-primary-nav')) {
      header.classList.add('atlas-unified-header');
      let more = actions.querySelector('.atlas-header-more');
      if (!more) {
        more = document.createElement('details');
        more.className = 'atlas-header-more';
        more.innerHTML = '<summary aria-label="More actions">More</summary><div class="atlas-header-menu"></div>';
        actions.append(more);
      }
      const menu = more.querySelector('.atlas-header-menu');
      const organize = () => {
        for (const item of [...actions.children]) {
          if (item === more || item.matches('.atlas-palette-mount,#openCommands,.atlas-theme-toggle')) continue;
          menu.append(item);
        }
      };
      organize();
      new MutationObserver(organize).observe(actions, {childList:true});
    }

    if (actions && !actions.querySelector(".atlas-theme-toggle")) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "atlas-theme-toggle";
      toggle.innerHTML = '<svg class="atlas-icon atlas-theme-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg><svg class="atlas-icon atlas-theme-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
      toggle.onclick = () => setTheme(currentTheme() === "dark" ? "light" : "dark");
      actions.insertBefore(toggle, actions.querySelector(".atlas-header-more"));
      applyTheme();
    }
    if (actions && !actions.querySelector(".atlas-display-mode")) {
      const label = document.createElement("label");
      label.className = "atlas-display-mode";
      label.textContent = "Display ";
      const select = document.createElement("select");
      select.setAttribute("aria-label", "Display mode");
      select.title =
        "Citrix / remote: lighter 3D movement and fewer interface effects. Does not change permissions or start scans.";
      for (const [value, text] of [
        ["standard", "Standard"],
        ["citrix", "Citrix / remote"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        select.append(option);
      }
      select.value = displayChoice;
      select.onchange = () => setDisplay(select.value);
      label.append(select);
      actions.append(label);
    }
    const more = header.querySelector(".atlas-header-more");
    if (more) {
      document.addEventListener("click", (event) => {
        if (!more.contains(event.target) || event.target.closest("button"))
          more.open = false;
      });
      more.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          more.open = false;
          more.querySelector("summary").focus();
        }
      });
    }
    const measure = () => {
      const height = header.getBoundingClientRect().height;
      if (height)
        document.documentElement.style.setProperty(
          "--atlas-header-height",
          height + "px",
        );
      window.dispatchEvent(new Event("atlas-shell-resize"));
    };
    if (typeof ResizeObserver !== "undefined")
      new ResizeObserver(measure).observe(header);
    else window.addEventListener("resize", measure, { passive: true });
    measure();
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", installShell, { once: true });
  else installShell();
  function motionControl(parent) {
    if (!parent || parent.querySelector(".atlas-motion-toggle")) return;
    const label = document.createElement("label");
    label.className = "atlas-motion-toggle";
    label.title = "Enable or disable map and interface animations.";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.setAttribute("role", "switch");
    input.setAttribute("aria-label", "Animations");
    input.checked = !isReduced();
    const track = document.createElement("span");
    track.className = "atlas-motion-track";
    track.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.textContent = "Animations";
    const state = document.createElement("span");
    state.className = "atlas-motion-state";
    state.setAttribute("aria-hidden", "true");
    state.textContent = isReduced() ? "Off" : "On";
    input.onchange = () => setMotion(input.checked);
    label.append(input, track, text, state);
    parent.append(label);
  }
  const esc = (value) =>
    String(value ?? "").replace(
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
  function csvCell(value) {
    let text = String(value ?? "");
    // CSV quoting preserves delimiters; an apostrophe also keeps spreadsheet
    // formula prefixes and leading control whitespace literal when imported.
    if (/^\s*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }
  function domainAccount(user) {
    const login = String(
      user?.login_id || user?.user_name || user?.user_id || "",
    ).trim();
    return !login ? "" : /[\\@]/.test(login) ? login : `INTRANET\\${login}`;
  }
  function person(user) {
    const name =
      user.full_name || user.name || user.user_name || "Unknown person";
    const facts = [
      ["Account", user.user_name || user.user_id],
      ["Domain account", domainAccount(user)],
      ["Email", user.email],
    ];
    const supplied = (value) =>
      value !== null && value !== undefined && String(value).trim() !== "";
    const account = user.user_name || user.user_id || "",
      employee = user.employee_number || user.employee_id,
      loginTime = exportDate(user.last_login_time),
      loginDate = exportDate(user.last_login),
      lastLogin = loginTime || loginDate;
    const sections = [
      [
        "Profile",
        [
          ["Department", user.department],
          ["Office", user.location],
          ["Job title", user.job_role || user.job_title],
          ["Manager", user.manager],
        ],
      ],
      [
        "Organisation",
        [
          ["Business unit", user.business_unit],
          ["Organisation unit", user.organisational_unit || user.organisation],
          ["Worker type", user.job_type || user.worker_type],
          [
            "Start date",
            String(exportDate(user.start_date) || "").replace(/ 00:00:00$/, ""),
          ],
        ],
      ],
      [
        "Account activity",
        [
          [
            "Employee ID",
            String(employee || "").toLowerCase() !==
            String(account).toLowerCase()
              ? employee
              : "",
          ],
          ["Last recorded login", lastLogin || "Not supplied"],
          [
            "Login date in export",
            loginTime &&
            loginDate &&
            !String(loginTime).startsWith(String(loginDate).slice(0, 10))
              ? loginDate
              : "",
          ],
        ],
      ],
    ]
      .map(([title, rows]) => [
        title,
        rows.filter(([, value]) => supplied(value)),
      ])
      .filter(([, rows]) => rows.length);
    const copyButton = (label, value, text = "") =>
      `<button type="button" class="atlas-person-copy" data-person-copy="${esc(value)}" data-copy-label="${esc(label)}" aria-label="Copy ${esc(label.toLowerCase())}" title="Copy ${esc(label.toLowerCase())}">${icon("copy")}${icon("check")}${text ? `<span>${esc(text)}</span>` : ""}</button>`;
    const fields = (rows) =>
      rows
        .filter(([, value]) => supplied(value))
        .map(
          ([key, value]) =>
            `<div class="atlas-person-field${key === "Domain account" ? " domain-account-fact" : ""}"><span class="atlas-person-field-label">${esc(key)}</span><b>${esc(value)}</b>${copyButton(key, value)}</div>`,
        )
        .join("");
    const grouped = sections
      .map(
        ([title, rows]) =>
          `<section><h3>${esc(title)}</h3><dl>${rows.map(([label, value]) => `<div class="atlas-person-detail-row"><dt>${esc(label)}</dt><dd>${esc(value)}</dd>${value === "Not supplied" ? "" : copyButton(label, value)}</div>`).join("")}</dl>${title === "Account activity" ? '<p class="atlas-person-source">From the directory export, not a live sign-in check.</p>' : ""}</section>`,
      )
      .join("");
    const related = [
      ["Find manager", "user", user.manager],
      ["Same department", "department", user.department],
      ["Same office", "location", user.location],
    ]
      .filter(([, , value]) => supplied(value))
      .map(
        ([label, prefix, value]) =>
          `<button type="button" data-person-search="${esc(prefix + ":" + value)}" title="${esc(value)}">${esc(label)}</button>`,
      )
      .join("");
    const summary = [["Name", name], ...facts, ...sections.flatMap(([, rows]) => rows)]
      .filter(([, value]) => supplied(value) && value !== "Not supplied")
      .map(([label, value]) => `${label}: ${value}`).join("\n");
    const context = [user.department, user.location].filter(supplied).join(" · ");
    return `<div class="card usercard atlas-person atlas-person-profile" ${AtlasContext.attributes("user", user)} tabindex="0"><div class="avatar" aria-hidden="true">${esc(
      name
        .split(/\s+/)
        .slice(0, 2)
        .map((s) => s[0])
        .join(""),
    )}</div><div class="atlas-person-content"><div class="atlas-person-heading"><div class="atlas-person-identity"><h2>${esc(name)}</h2>${context ? `<p class="atlas-person-context">${esc(context)}</p>` : ""}</div><div class="atlas-person-quick-copy" role="group" aria-label="Quick copy">${copyButton("Name", name, "Name")}${copyButton("Summary", summary, "Summary")}</div></div><div class="facts atlas-person-accounts">${fields(facts)}</div><details class="details atlas-person-details"><summary>User details</summary><div class="atlas-person-detail-sections">${grouped}</div>${related ? `<div class="atlas-person-related" role="group" aria-label="Related people">${related}</div>` : ""}${exportButton("user", user.canonical_key)}</details><span class="atlas-person-feedback" role="status" aria-live="polite"></span></div></div>`;
  }
  function exportDate(value) {
    if (value === null || value === undefined || String(value).trim() === "")
      return value;
    if (!/^\d+(\.\d+)?$/.test(String(value))) return value;
    const serial = Number(value);
    if (serial > 2958465) return value;
    const date = new Date(
      Date.UTC(1899, 11, 30) + Math.round(serial * 86400) * 1000,
    );
    return serial < 1
      ? date.toISOString().slice(11, 19)
      : date.toISOString().slice(0, 19).replace("T", " ");
  }
  function exportButton(kind, key) {
    return key
      ? `<button type="button" class="atlas-export-button" data-export-kind="${esc(kind)}" data-export-key="${esc(key)}">All export fields</button>`
      : "";
  }
  function personKey(user) {
    return String(user?.canonical_key || "").trim() ||
      (/^\d+$/.test(String(user?.id ?? "")) ? "id:" + user.id : "");
  }
  function isCitrixVdi(machine) {
    return !!machine.vdi_key ||
      (machineKind(machine) === "vdi" && String(machine.source || "").toLowerCase() === "citrix");
  }
  function vdiAccounts(machine) {
    return Array.isArray(machine.vdi_assigned_users)
      ? machine.vdi_assigned_users.map(value => String(value ?? "")).filter(value => value.trim())
      : [];
  }
  function vdiAssignmentCount(machine) {
    const supplied = machine.vdi_assignment_count ?? machine.vdi_assigned_user_count;
    return supplied !== undefined && supplied !== null && Number.isInteger(Number(supplied)) && Number(supplied) >= 0
      ? Number(supplied) : vdiAccounts(machine).length;
  }
  function machineSnapshotNote(machine) {
    return isCitrixVdi(machine)
      ? "Imported Citrix snapshot. Registration, power and assignments describe the extract; " +
        (supportsWindows(machine) ? "run a manual health check for current connectivity." : "Windows checks are unavailable for this inventory identity.")
      : machineNote;
  }
  // Only fields actually supplied by the directory export. No live-state aliases.
  function machineSections(machine) {
    const supplied = (value) =>
      value !== null && value !== undefined && String(value).trim() !== "";
    const sections = [
      [
        "Identity",
        [
          ["Infrastructure", machine.infrastructure_itsi],
          ["Manufacturer", machine.manufacturer],
          ["Model", machine.model_id],
          ["Device category", machine.model_category],
          ["Asset tag", machine.asset_tag],
          ["Export CI", String(machine.source_ci || "").toUpperCase() !== String(machine.name || machine.machine_name || "").toUpperCase() ? machine.source_ci : ""],
          ["Asset display name", machine.display_name],
          ["Device location", machine.device_location],
          ["Serial number", machine.serial_number],
          ["Correlation ID", machine.correlation_id],
          ["Record class", machine.sys_class_name],
          ["Description", machine.short_description],
        ],
      ],
      [
        "Ownership",
        [
          ["Assigned to", machine.assigned_to || "Not supplied"],
          ["Assignment date", exportDate(machine.assigned_at)],
          ["Last logged-on user", machine.last_logon_user || "Not supplied"],
        ],
      ],
      [
        "Discovery",
        [
          ["Inventory status", machine.operational_status],
          ["Asset state", machine.install_status],
          ["Last used", exportDate(machine.last_used)],
          ["Discovery source", machine.discovery_source],
          ["Last discovered", machine.last_discovered],
          ["Record updated", machine.updated_on],
        ],
      ],
    ];
    if (isCitrixVdi(machine)) sections.push([
      "Citrix snapshot",
      [
        ["Citrix machine name", machine.vdi_original_name || machine.vdi_fqdn || machine.name || machine.machine_name],
        ["Remote target", machine.vdi_original_name && String(machine.vdi_original_name).toUpperCase() !== String(machine.name || machine.machine_name || "").toUpperCase() && supportsWindows(machine) ? machine.name || machine.machine_name : ""],
        ["Domain", machine.vdi_domain],
        ["Catalog", machine.vdi_catalog],
        ["Delivery group", machine.vdi_delivery_group],
        ["Registration state (snapshot)", machine.vdi_registration_state || machine.vdi_state],
        ["Power state (snapshot)", machine.vdi_power_state],
        ["Maintenance mode", machine.vdi_maintenance_mode ?? (machine.vdi_maintenance_enabled === true ? "On" : machine.vdi_maintenance_enabled === false ? "Off" : "")],
        ["User change persistence", machine.vdi_user_change_persistence],
        ["Assigned account count", vdiAssignmentCount(machine)],
        ["Assigned accounts (all)", vdiAccounts(machine).join("\n") || "No assigned accounts supplied"],
        ["Assigned user display names", machine.vdi_user_display_names],
        ["Source", "Citrix"],
        ["Source file", machine.vdi_source],
        ["Imported at", machine.vdi_imported_at || "Import time unavailable"],
      ],
    ]);
    return sections
      .map(([title, fields]) => [
        title,
        fields.filter(([, value]) => supplied(value)),
      ])
      .filter(([, fields]) => fields.length);
  }
  const machineNote =
    "Stored inventory. Status and last logged-on user do not confirm current connectivity or sign-in.";
  function machineDetails(machine, { open = false } = {}) {
    const sections = machineSections(machine)
      .map(
        ([title, fields]) =>
          `<section><h4>${esc(title)}</h4><dl>${fields
            .map(
              ([label, value]) =>
                `<div${["Infrastructure", "Serial number", "Description", "Assigned accounts (all)", "Citrix machine name", "Remote target", "Catalog", "Delivery group"].includes(label) ? ' class="atlas-machine-wide"' : ""}><dt>${esc(label)}</dt><dd>${label === "Assigned accounts (all)" && vdiAccounts(machine).length ? '<ul class="atlas-vdi-assigned-accounts">' + vdiAccounts(machine).map(account => `<li>${esc(account)}</li>`).join("") + "</ul>" : esc(value)}</dd></div>`,
            )
            .join("")}</dl></section>`,
      )
      .join("");
    const citrix = isCitrixVdi(machine);
    return `<details class="atlas-machine-details${citrix ? " atlas-vdi-details" : ""}"${open ? " open" : ""}><summary>${citrix ? "Citrix details" : "Device details"}</summary><div class="atlas-machine-inventory"><p>${machineSnapshotNote(machine)}</p>${sections}${citrix ? exportButton("vdi", machine.vdi_key) : exportButton("machine", machine.machine_name_norm || String(machine.name || machine.machine_name || "").toLowerCase())}</div></details>`;
  }
  function machineReport(machine) {
    return [
      "Stored machine details",
      "Machine: " + (machine.name || machine.machine_name || "Not supplied"),
      machineSnapshotNote(machine),
      ...machineSections(machine).flatMap(([title, fields]) => [
        "",
        title,
        ...fields.map(([label, value]) => `${label}: ${value}`),
      ]),
    ].join("\n");
  }
  function dialog(title) {
    const previous =
        document.activeElement?.shadowRoot?.activeElement ||
        document.activeElement,
      element = document.createElement("dialog");
    element.className = "atlas-dialog";
    element.setAttribute("aria-label", title);
    const heading = document.createElement("h2");
    heading.textContent = title;
    const close = document.createElement("button");
    close.textContent = "Close";
    close.setAttribute("aria-label", "Close " + title.toLowerCase());
    close.onclick = () => element.close();
    const header = document.createElement("header");
    header.append(heading, close);
    const body = document.createElement("div");
    body.className = "atlas-dialog-body";
    element.append(header, body);
    element.addEventListener(
      "close",
      () => {
        element.remove();
        previous?.focus();
      },
      { once: true },
    );
    document.body.append(element);
    element.showModal();
    return { element, body };
  }
  document.addEventListener(
    "click",
    async (event) => {
      const quickCopy = event.target.closest?.("[data-person-copy]");
      if (quickCopy) {
        event.stopPropagation();
        if (quickCopy.dataset.copyPending) return;
        quickCopy.dataset.copyPending = "true";
        clearTimeout(quickCopy.atlasCopyTimer);
        delete quickCopy.dataset.copyState;
        const label = quickCopy.dataset.copyLabel,
          feedback = quickCopy.closest(".atlas-person")?.querySelector(".atlas-person-feedback");
        try {
          const value = quickCopy.atlasCopyValue?.() ?? quickCopy.dataset.personCopy;
          const copied = await AtlasContext.copy(value, label);
          if (feedback) feedback.textContent = copied ? label + " copied" : "Select the text to copy " + label.toLowerCase();
          if (copied) {
            clearTimeout(quickCopy.atlasCopyTimer);
            quickCopy.dataset.copyState = "copied";
            quickCopy.atlasCopyTimer = setTimeout(() => delete quickCopy.dataset.copyState, 1800);
          }
        } finally {
          delete quickCopy.dataset.copyPending;
        }
        return;
      }
      const related = event.target.closest?.("[data-person-search]");
      if (related) {
        event.stopPropagation();
        related.dispatchEvent(
          new CustomEvent("atlas-directory-search", {
            bubbles: true,
            detail: { query: related.dataset.personSearch },
          }),
        );
        return;
      }
      const button = event.target.closest?.("[data-export-kind]");
      if (!button) return;
      event.stopPropagation();
      const { element, body } = dialog("All export fields"),
        controller = new AbortController();
      element.classList.add("atlas-export-dialog");
      element.addEventListener("close", () => controller.abort(), {
        once: true,
      });
      body.textContent = "Loading stored fields…";
      try {
        const query = new URLSearchParams({
          kind: button.dataset.exportKind,
          key: button.dataset.exportKey,
        });
        const citrix = button.dataset.exportKind === "vdi";
        const response = await fetch(citrix
          ? "/api/vdi-data/record/" + encodeURIComponent(button.dataset.exportKey)
          : "/api/directory/record?" + query, {
          signal: controller.signal,
          cache: "no-store",
        });
        const data = await response.json();
        if (!response.ok)
          throw Error(data.detail || "Export fields unavailable");
        if (!element.open) return;
        body.innerHTML = `<h3>${esc(data.name)}</h3>${citrix ? '<p>Imported Citrix snapshot · stored source fields.</p>' : ""}<p>${esc(data.original_cells ? `${data.source} · ${data.sheet} · row ${data.row}${data.source_rows > 1 ? ` · selected from ${data.source_rows} retained source rows` : ""}` : "Stored directory fields. Refresh the directory export to retain original cells and any additional columns.")}</p>${data.restricted_columns ? "<p>Additional export columns are available in the admin version.</p>" : ""}<label>Find a field<input type="search" aria-label="Find an export field" placeholder="Name or value…"></label><p class="atlas-export-count" role="status"></p><div class="atlas-export-fields"></div><button type="button" class="atlas-export-copy">Copy all fields</button>`;
        const valueOf = (field) => {
          const value = field.stored_value ?? field.value;
          return [
            "start_date",
            "last_login",
            "last_login_time",
            "updated_on",
            "last_discovered",
            "last_used",
            "assigned_at",
          ].includes(field.field)
            ? exportDate(value)
            : value;
        };
        const render = () => {
          const q = body.querySelector("input").value.trim().toLowerCase();
          const fields = data.fields.filter((f) =>
            [f.header, f.label, f.value, valueOf(f)].some((v) =>
              String(v ?? "")
                .toLowerCase()
                .includes(q),
            ),
          );
          body.querySelector(".atlas-export-count").textContent =
            `${fields.length} of ${data.fields.length} fields`;
          body.querySelector(".atlas-export-fields").innerHTML = fields
            .map((f) => {
              const value = valueOf(f),
                blank = value === null || value === undefined || value === "";
              return `<article><b>${esc(f.label)}</b><small>${esc(f.header)}</small><div>${blank ? "Not supplied" : esc(value)}</div>${data.original_cells && String(value ?? "") !== String(f.value ?? "") ? `<small>Export value: ${esc(f.value)}</small>` : ""}</article>`;
            })
            .join("");
        };
        body.querySelector("input").oninput = render;
        body.querySelector(".atlas-export-copy").onclick = async () => {
          try {
            const lines = [
              data.name,
              data.source,
              ...data.fields.map(
                (f) =>
                  `${f.header}: ${valueOf(f) ?? ""}${data.original_cells && String(valueOf(f) ?? "") !== String(f.value ?? "") ? ` (export: ${f.value})` : ""}`,
              ),
            ];
            await navigator.clipboard.writeText(lines.join("\n"));
            body.querySelector(".atlas-export-count").textContent =
              "All fields copied";
          } catch {
            body.querySelector(".atlas-export-count").textContent =
              "Clipboard unavailable. Select and copy the fields.";
          }
        };
        render();
      } catch (error) {
        if (element.open && error.name !== "AbortError")
          body.textContent = error.message;
      }
    },
    true,
  );
  function machineKind(machine) {
    if (machine.device_kind) return String(machine.device_kind).toLowerCase();
    const name = String(machine.name || machine.machine_name || "")
      .trim()
      .toUpperCase()
      .split(".")[0];
    const text = [machine.model_category, machine.model_id, machine.sys_class_name].filter(Boolean).join(" ").toLowerCase();
    if (/\b(vdi|citrix)\b/.test(text)) return "vdi";
    if (text.includes("iphone") || name === "IPHONE" || name.startsWith("IPHONE-")) return "iphone";
    if (/\b(ipad|tablet)\b/.test(text) || ["IPAD", "TABLET"].includes(name) || /^(IPAD|TABLET)-/.test(name)) return "tablet";
    if (/mobile device|handheld|android|\b(phone|smartphone)\b/.test(text) || name === "PHONE" || name.startsWith("PHONE-")) return "phone";
    if (/\b(macbook|imac|mac mini|mac pro)\b/.test(text)) return "mac";
    if (/\b(laptop|notebook|latitude|thinkpad|elitebook|zbook|probook)\b/.test(text)) return "laptop";
    // The K belongs to PWMK, not the country prefix (e.g. NYK).
    if (/^[A-Z]{3}PWMK/.test(name)) return "kiosk";
    if (name.includes("VDI")) return "vdi";
    if (/^[A-Z]{3}PWMF/.test(name)) return "desktop";
    if (/\b(computer|desktop|workstation)\b/.test(text)) return "desktop";
    return "other";
  }
  function supportsWindows(machine) {
    if (machine.windows_remote_supported !== undefined && machine.windows_remote_supported !== null)
      return [true, 1, "1"].includes(machine.windows_remote_supported);
    return !["iphone", "phone", "tablet", "mac"].includes(machineKind(machine));
  }
  function machineBadges(machine) {
    const kind = machineKind(machine);
    const labels = {desktop:"Desktop", laptop:"Laptop", iphone:"iPhone", phone:"Phone", tablet:"Tablet", mac:"Mac", kiosk:"Kiosk", vdi:"VDI", other:"Device"};
    const date = value => String(exportDate(value) || "").split(/[ T]/)[0];
    const assigned = String(machine.assigned_to || "").trim();
    const owned = !!assigned || !!Number(machine.assigned_relationship);
    const ownership = owned
      ? (assigned ? "Assigned to " + assigned : "Assigned relationship in inventory") + (machine.assigned_at ? " · " + exportDate(machine.assigned_at) : "")
      : "No assignee supplied in the export";
    const status = [
      [labels[kind] || "Device", "kind", labels[kind] || "Device"],
      [owned ? "Assigned" : "Unassigned", owned ? "assigned" : "unassigned", ownership],
    ];
    const citrix = isCitrixVdi(machine), shared = vdiAssignmentCount(machine);
    if (citrix && shared > 1)
      status[1] = [`Shared (${shared})`, "assigned shared", `Citrix snapshot: assigned to ${shared} accounts; assignments do not establish concurrent sessions`];
    if (citrix && (machine.vdi_registration_state || machine.vdi_state))
      status.push(["Citrix: " + (machine.vdi_registration_state || machine.vdi_state), "vdi-state", "Registration state in the imported Citrix snapshot"]);
    if (citrix && machine.vdi_power_state)
      status.push(["Power: " + machine.vdi_power_state, "vdi-power", "Power state in the imported Citrix snapshot"]);
    if (machine.install_status)
      status.push([machine.install_status, "asset-state", "Asset state from the export: " + machine.install_status]);
    const history = citrix
      ? [["Citrix snapshot · " + (date(machine.vdi_imported_at) || "Import time unavailable"), "vdi-snapshot", machineSnapshotNote(machine) + " Imported at: " + (machine.vdi_imported_at || "Unavailable")]]
      : [["Last used: " + (date(machine.last_used) || "—"), "last-used", "Last used in the export: " + (exportDate(machine.last_used) || "Not supplied")]];
    if (citrix && machine.last_used)
      history.push(["Last used: " + date(machine.last_used), "last-used", "Last used in the inventory export: " + exportDate(machine.last_used)]);
    const logon = machine.logon_relationship !== undefined ? !!Number(machine.logon_relationship) : !!machine.last_logon_user;
    if (logon)
      history.push(["Last logged-on", "logon", "Inventory relationship" + (machine.last_logon_user ? ": " + machine.last_logon_user : "") + "; not a live sign-in check"]);
    const render = entries => entries.map(([label, style, title]) =>
      `<span class="atlas-device-badge ${style}" title="${esc(title)}">${esc(label)}</span>`
    ).join("");
    return '<div class="atlas-device-badges" aria-label="Stored device information"><div class="atlas-device-status">' + render(status) + '</div><div class="atlas-device-history">' + render(history) + '</div></div>';
  }
  function machineFilters(host, {linked = true} = {}) {
    if (!host || host.querySelector(":scope > .atlas-machine-filters")) return;
    const rows = [...host.querySelectorAll("[data-machine-kind]")];
    if (!rows.length) return;
    const types = [
      ["all", "All"],
      ["desktop", "Desktops"],
      ["laptop", "Laptops"],
      ["mobile", "Mobile"],
      ["mac", "Macs"],
      ["vdi", "VDI"],
      ["kiosk", "Kiosks"],
      ["other", "Other"],
    ];
    const mobile = new Set(["iphone", "phone", "tablet"]);
    const filterKind = row => mobile.has(row.dataset.machineKind)
      ? "mobile" : row.dataset.machineKind;
    const counts = new Map();
    for (const row of rows) {
      const kind = filterKind(row);
      counts.set(kind, (counts.get(kind) || 0) + 1);
    }
    const bar = document.createElement("div");
    bar.className = "atlas-machine-filters";
    bar.innerHTML =
      '<div class="atlas-machine-filter-heading"><strong>' + (linked ? 'Linked devices' : 'Matching devices') + '</strong><small aria-live="polite"></small></div><div role="group" aria-label="Filter machine types"></div>';
    const group = bar.querySelector('[role="group"]'),
      status = bar.querySelector("small");
    const selected = new Set();
    const empty = document.createElement("p");
    empty.className = "atlas-machine-filter-empty";
    empty.textContent = "No devices match these filters.";
    empty.hidden = true;
    host.prepend(bar);
    host.append(empty);
    const update = () => {
      for (const row of rows)
        row.hidden =
          selected.size > 0 && !selected.has(filterKind(row));
      for (const button of group.children)
        button.setAttribute(
          "aria-pressed",
          button.dataset.kind === "all"
            ? !selected.size
            : selected.has(button.dataset.kind),
        );
      const count = rows.filter((row) => !row.hidden).length;
      status.textContent = count === rows.length
        ? `${rows.length} ${linked ? "linked " : ""}${rows.length === 1 ? "device" : "devices"}`
        : `${count} of ${rows.length} shown`;
      empty.hidden = count > 0;
      for (const section of host.querySelectorAll(".ops-machine-group")) {
        const visible = [
          ...section.querySelectorAll("[data-machine-kind]"),
        ].filter((row) => !row.hidden).length;
        section.hidden = !visible;
        const countLabel = section.querySelector("h4 span");
        if (countLabel) countLabel.textContent = visible;
      }
    };
    for (const [kind, label] of types) {
      const count =
        kind === "all"
          ? rows.length
          : counts.get(kind) || 0;
      if (!count && !["all", "desktop", "laptop", "mobile"].includes(kind)) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.kind = kind;
      const name = document.createElement("span"), total = document.createElement("span");
      name.className = "atlas-filter-label";name.textContent = label;
      total.className = "atlas-filter-count";total.textContent = count;
      button.append(name, total);
      button.setAttribute("aria-label", `${label}, ${count} ${count === 1 ? "device" : "devices"}`);
      button.disabled = !count;
      button.title =
        kind === "other"
          ? "Hostnames outside the confirmed PWMF, PWMK and VDI patterns"
          : "Filter this machine list; the selected target stays unchanged";
      button.onclick = () => {
        if (kind === "all") selected.clear();
        else if (selected.has(kind)) selected.delete(kind);
        else selected.add(kind);
        update();
      };
      group.append(button);
    }
    update();
  }
  window.AtlasUI = {
    setTheme,
    theme: currentTheme,
    icon,
    installIcons,
    machineKind,
    isCitrixVdi,
    machineSnapshotNote,
    supportsWindows,
    machineBadges,
    machineFilters,
    esc,
    csvCell,
    person,
    domainAccount,
    machineDetails,
    machineReport,
    personKey,
    dialog,
    performance: { isCitrix, setDisplay },
    motion: {
      isReduced,
      reveal,
      slideUp,
      install: motionControl,
      toggle: () => setMotion(isReduced()),
    },
  };
})();

// Context actions share exact record identities across console, map and viewers.
window.AtlasGroups = {
  open(kind, identity, action = "groups") {
    if (window.AtlasAD) return AtlasAD.show(kind, identity, true, action);
    const url = "/installer?" + new URLSearchParams({command: "ad-open", adkind: kind, adidentity: identity || "", adaction: action});
    if (!window.AtlasNavigate?.(url)) location.assign(url);
  }
};
window.AtlasContext = (() => {
  let menu, origin;
  const bindings = new WeakMap();
  let handlers = {};
  const attribute = (key, value) => value == null || value === "" ? "" : ` data-context-${key}="${AtlasUI.esc(value)}"`;
  function attributes(kind, record) {
    const identity = kind === "user" ? record.user_name || record.user_id || record.email || "" : record.name || record.machine_name || "";
    const ad = kind === "user" || AtlasUI.supportsWindows(record);
    return `data-atlas-context="${kind}"${ad ? ` data-ad-kind="${kind === "user" ? "user" : "computer"}" data-ad-identity="${AtlasUI.esc(identity)}"` : ""}` + attribute("identity", identity) + (kind === "user" ?
      attribute("person", AtlasUI.personKey(record)) +
      attribute("name", record.full_name || record.name) + attribute("domain", AtlasUI.domainAccount(record)) + attribute("email", record.email) +
      attribute("department", record.department) + attribute("location", record.location) + attribute("manager", record.manager) : "");
  }
  function navigate(params) {
    const url = "/installer?" + new URLSearchParams(params);
    if (!window.AtlasNavigate?.(url)) location.assign(url);
  }
  function search(term) {
    return handlers.search ? handlers.search(term) : navigate({lookup: term});
  }
  async function copy(value, label) {
    if (value === null || value === undefined || String(value) === "") return false;
    try {
      await navigator.clipboard.writeText(String(value));
      if (typeof window.toast === "function") window.toast(label + " copied");
      return true;
    } catch {
      const {body} = AtlasUI.dialog("Copy " + label.toLowerCase());
      const instruction = document.createElement("p");
      instruction.textContent = "Select the text below and use Copy (Ctrl+C or ⌘C).";
      const field = document.createElement("textarea");
      field.readOnly = true;field.value = String(value);field.setAttribute("aria-label", label);
      body.append(instruction, field);field.focus();field.select();
      return false;
    }
  }
  function groupActions(kind, identity, available = true) {
    return [
      ["ad-groups", "See groups", "groups"],
      ["ad-compare", "Compare groups…", "compare"],
      ["ad-properties", "Account health & properties", "properties"],
      ["ad-export", "Export groups to CSV", "export"],
      ["ad-summary", "Copy AD support summary", "summary"],
    ].map(([id, label, action]) => ({id, label, section: "Active Directory", navigate: true,
      disabled: !available || !identity || ((!!window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content === "viewer") && action !== "groups"),
      reason: !available ? "Windows computer accounts only" : !identity ? "No AD account supplied" : "Live Active Directory requires local Admin",
      run: () => AtlasGroups.open(kind, identity, action)}));
  }
  function userActions(item) {
    const d = item.dataset, identity = d.adIdentity || d.contextIdentity || "", key = d.contextPerson || d.person;
    const summary = ["Atlas · stored user record", d.contextName || identity,
      ...[["Account", identity], ["Domain account", d.contextDomain], ["Email", d.contextEmail], ["Department", d.contextDepartment], ["Office", d.contextLocation], ["Manager", d.contextManager]]
        .filter(([, value]) => value).map(([label, value]) => label + ": " + value), "From imported directory data; not a live sign-in check."].join("\n");
    return [
      ...groupActions("user", identity),
      {id: "user-devices", label: "Assigned devices & desks", section: "Inventory", disabled: !key, reason: "Open the full user record first", navigate: true,
        run: () => handlers.openPerson ? handlers.openPerson(key) : navigate({person: key})},
      ...[["manager", "Find manager", "user"], ["department", "Find teammates", "department"], ["location", "People in the same office", "location"]]
        .map(([field, label, prefix]) => ({id: "user-" + field, label, section: "Inventory", disabled: !d["context" + field[0].toUpperCase() + field.slice(1)], navigate: true,
          reason: "Not supplied in this record", run: () => search(prefix + ":" + d["context" + field[0].toUpperCase() + field.slice(1)])})),
      ...[["copy-account", "Copy account", identity], ["copy-domain", "Copy domain account", d.contextDomain || (identity ? AtlasUI.domainAccount({user_name: identity}) : "")], ["copy-email", "Copy email", d.contextEmail], ["copy-user-report", "Copy stored support summary", summary]]
        .map(([id, label, value]) => ({id, label, section: "Copy", disabled: !value, reason: "Not supplied in this record", run: () => copy(value, label.replace(/^Copy /, ""))})),
    ];
  }
  function inventory(machine) {
    const {body} = AtlasUI.dialog("Inventory · " + machine.name);
    body.innerHTML = AtlasUI.machineBadges(machine) + AtlasUI.machineDetails(machine, {open: true});
  }
  function deviceActions(machine) {
    const name = machine.name || machine.machine_name || "";
    return [
      ...groupActions("computer", name, AtlasUI.supportsWindows(machine)),
      {id: "inventory", label: "View inventory details", section: "Inventory", run: () => inventory(machine)},
      ...[["copy", "Copy device identity", name], ["copy-asset", "Copy asset tag", machine.asset_tag], ["copy-serial", "Copy serial number", machine.serial_number || machine.serial], ["report", "Copy stored inventory report", AtlasUI.machineReport(machine)]]
        .map(([id, label, value]) => ({id, label, section: "Copy", disabled: !value, reason: "Not supplied in this record", run: () => copy(value, label.replace(/^Copy /, ""))})),
    ];
  }
  function close(restore = false) {
    menu?.remove();menu = null;
    if (restore && origin?.isConnected) origin.focus({preventScroll: true});
    origin = null;
  }
  function open(event, actions, anchor, title) {
    event.preventDefault();event.stopPropagation();close();
    origin = anchor;
    menu = document.createElement("div");menu.className = "atlas-ad-context";
    menu.setAttribute("role", "menu");menu.setAttribute("aria-label", title || "Record actions");
    const heading = document.createElement("div");heading.className = "atlas-context-title";heading.textContent = title || "Record actions";menu.append(heading);
    let section;
    for (const action of actions) {
      if (action.section !== section) {
        section = action.section;
        const label = document.createElement("div");label.className = "atlas-context-section";label.setAttribute("role", "presentation");label.textContent = section || "Actions";menu.append(label);
      }
      const button = document.createElement("button");button.type = "button";button.tabIndex = -1;button.dataset.cmd = action.id;
      button.setAttribute("role", "menuitem");button.textContent = action.label;button.disabled = !!action.disabled;
      if (action.disabled) button.title = action.reason || "Unavailable";
      button.onclick = async () => {
        close();
        if (action.navigate) anchor?.closest("dialog[open]")?.close();
        try {await action.run();} catch (error) {
          if (typeof window.toast === "function") window.toast(error.message);
          else AtlasUI.dialog("Action unavailable").body.textContent = error.message;
        }
      };
      menu.append(button);
    }
    // Menus opened inside a modal must be in that modal's top layer.
    (anchor?.closest("dialog[open]") || document.body).append(menu);
    const bounds = menu.getBoundingClientRect(), anchorBounds = anchor?.getBoundingClientRect();
    const keyboard = event.type === "keydown" || (!event.clientX && !event.clientY);
    const x = keyboard ? anchorBounds?.left || 8 : event.clientX;
    const y = keyboard ? anchorBounds?.bottom || 8 : event.clientY;
    menu.style.left = Math.max(8, Math.min(x, innerWidth - bounds.width - 8)) + "px";
    menu.style.top = Math.max(8, Math.min(y, innerHeight - bounds.height - 8)) + "px";
    const enabled = () => [...menu.querySelectorAll("button:not(:disabled)")];
    menu.onkeydown = e => {
      const buttons = enabled(), current = buttons.indexOf(document.activeElement);
      let next;
      if (e.key === "ArrowDown") next = (current + 1) % buttons.length;
      if (e.key === "ArrowUp") next = (current - 1 + buttons.length) % buttons.length;
      if (e.key === "Home") next = 0;
      if (e.key === "End") next = buttons.length - 1;
      if (next !== undefined && buttons.length) {
        e.preventDefault();e.stopPropagation();buttons[next].focus({preventScroll: true});buttons[next].scrollIntoView({block: "nearest"});
      }
    };
    const first = enabled()[0];
    first?.focus({preventScroll: true});
    first?.scrollIntoView({block: "nearest"});
    window.AtlasInteractions?.animateMenu(menu);
    return menu;
  }
  function fromEvent(event) {
    const item = event.composedPath().find(node => node?.matches?.("[data-ad-identity], [data-atlas-context]"));
    if (!item) return;
    const record = bindings.get(item);
    const device = item.dataset.adKind === "computer" || item.dataset.atlasContext === "device";
    const actions = record?.actions || (device ? deviceActions({name: item.dataset.adIdentity || item.dataset.contextIdentity, model_category: item.dataset.adIdentity ? "Computer" : "Mobile Device - Handheld"}) : userActions(item));
    open(event, actions, item, "Actions for " + (record?.name || item.dataset.contextName || item.dataset.adIdentity || item.dataset.contextIdentity));
  }
  document.addEventListener("contextmenu", fromEvent);
  document.addEventListener("pointerdown", e => {if (menu && !menu.contains(e.target)) close();});
  document.addEventListener("keydown", e => {
    if (menu && (e.key === "Escape" || e.key === "Tab")) {if (e.key === "Escape") e.preventDefault();close(e.key === "Escape");return;}
    if (!menu && (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))) fromEvent(e);
  });
  document.addEventListener("scroll", e => {if (menu && !menu.contains(e.target)) close();}, true);
  window.addEventListener("resize", () => close());
  window.addEventListener("blur", () => close());
  return {attributes, groupActions, userActions, deviceActions, inventory, copy, navigate, open, close,
    configure: value => {handlers = value;},
    bindDevice: (node, machine, extra = []) => {
      node.dataset.atlasContext = "device";
      if (!node.hasAttribute("tabindex")) node.tabIndex = 0;
      bindings.set(node, {name: machine.name, actions: [...deviceActions(machine), ...extra]});
    }};
})();

/* An on-demand index of original controls: no background scans or cloned handlers. */
(() => {
  function install() {
    if (window.AtlasInteractions?.ready || document.querySelector('.atlas-reachable-toggle') || !document.querySelector('main')) return;
    const toggle = document.createElement('button');
    toggle.className = 'atlas-reachable-toggle'; toggle.type = 'button';
    toggle.textContent = 'Actions'; toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', 'atlasReachableActions');
    const panel = document.createElement('section');
    panel.id = 'atlasReachableActions'; panel.className = 'atlas-reachable-panel'; panel.hidden = true;
    panel.setAttribute('aria-label', 'Actions on this page');
    panel.innerHTML = '<div class="atlas-reachable-heading"><strong>Actions on this page</strong><button type="button" aria-label="Close actions">×</button></div><input type="search" aria-label="Find a button or field" placeholder="Find a button or field…"><p role="status"></p><div class="atlas-reachable-list"></div>';
    const search = panel.querySelector('input'), list = panel.querySelector('.atlas-reachable-list'), status = panel.querySelector('[role="status"]');
    const visible = node => {
      const inert = node.closest('[inert]');
      return node.isConnected && !node.closest('[hidden], .page:not(.active)') && node.getClientRects().length > 0 && (!inert || inert.classList.contains('atlas-edge-panel'));
    };
    let entries = [];
    function close(restore = true) {
      panel.hidden = true; toggle.setAttribute('aria-expanded', 'false');
      if (restore) toggle.focus();
    }
    function collect() {
      entries = [...document.querySelectorAll('main button, main input:not([type="hidden"]), main select, main textarea, main summary')]
        .filter(node => visible(node) && !node.closest('dialog, .atlas-reachable-panel, .atlas-action-fallback'))
        .map(node => {
          const field = /^(INPUT|SELECT|TEXTAREA)$/.test(node.tagName);
          const labelCopy = field ? node.labels?.[0]?.cloneNode(true) : null;
          labelCopy?.querySelectorAll('input,select,textarea,button').forEach(n => n.remove());
          const label = node.getAttribute('aria-label') || (field ? labelCopy?.textContent.trim() || node.placeholder : node.textContent.trim()) || node.title;
          const contextNode = node.closest('tr, article, .machine-card, .panel, section');
          const context = (contextNode?.querySelector('h2,h3,h4,th,td')?.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100);
          return {node, field, label: label?.replace(/\s+/g, ' ').slice(0, 140), context};
        }).filter(entry => entry.label);
    }
    function render() {
      const query = search.value.trim().toLowerCase();
      const matches = entries.filter(e => `${e.label} ${e.context}`.toLowerCase().includes(query));
      list.replaceChildren();
      status.textContent = `${matches.length} ${matches.length === 1 ? 'control' : 'controls'} · Select to open or run`;
      let lastContext;
      for (const entry of matches) {
        if(entry.context && entry.context !== lastContext){const heading=document.createElement('div');heading.className='atlas-action-group';heading.textContent=entry.context;list.append(heading);lastContext=entry.context;}
        const button = document.createElement('button'); button.type = 'button';
        button.disabled = entry.node.matches(':disabled') || entry.node.getAttribute('aria-disabled') === 'true';
        const label = document.createElement('span'); label.textContent = entry.label;
        const context = document.createElement('small'); context.textContent = entry.field ? 'Edit field' : entry.node.tagName === 'SUMMARY' ? 'Expand / collapse' : 'Action';
        button.title=entry.context ? entry.label+' · '+entry.context : entry.label;
        button.append(label, context);
        button.onclick = () => {
          // Recheck state at activation: navigation or live updates may have replaced the original.
          if (!visible(entry.node) || entry.node.matches(':disabled') || entry.node.getAttribute('aria-disabled') === 'true') { collect(); render(); return; }
          close(false);
          entry.node.scrollIntoView({block:'center', behavior:'instant'});
          entry.node.focus({preventScroll:true});
          if (!entry.field) entry.node.click();
        };
        list.append(button);
      }
    }
    toggle.onclick = () => {
      if (!panel.hidden) return close();
      collect(); search.value = ''; render(); panel.hidden = false;
      toggle.setAttribute('aria-expanded', 'true'); search.focus();
    };
    search.oninput = render;
    panel.querySelector('button').onclick = () => close();
    const onKey = event => { if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); close(); } };
    const onOutside = event => { if (!panel.hidden && !panel.contains(event.target) && event.target !== toggle) close(false); };
    const onRoute = () => close(false);
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onOutside);
    window.addEventListener('hashchange', onRoute);
    const fallback = document.createElement('div');fallback.className='atlas-action-fallback';
    fallback.append(toggle, panel);
    const main = document.querySelector('main');
    const heading = main.querySelector(':scope > .console-page-heading, :scope > .map-heading, :scope > header');
    if (heading) heading.after(fallback);else main.prepend(fallback);
    window.AtlasReachableFallback = {destroy() {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onOutside);
      window.removeEventListener('hashchange', onRoute);
      fallback.remove();window.AtlasReachableFallback=null;
    }};
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, {once:true}); else install();
})();
