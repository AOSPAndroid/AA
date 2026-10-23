(() => {
  const root = document.getElementById("psexec");
  if (!root) return;
  const get = (id) => document.getElementById("px" + id),
    { commands, build } = window.AtlasPsExecCommands;
  const key = "atlas.psexec.preferences.v1";
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(key) || "{}") || {};
  } catch {}
  let favourites = new Set(
    Array.isArray(saved.favourites) ? saved.favourites : [],
  );
  let selected = commands[0],
    category = "All",
    follow = true,
    values = {},
    current = null;
  const categories = [
    "All",
    "Favourites",
    ...new Set(commands.map((c) => c.category)),
  ];
  if (typeof saved.path === "string") get("Path").value = saved.path;
  if (["powershell", "cmd"].includes(saved.shell))
    get("Shell").value = saved.shell;
  function save() {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          path: get("Path").value,
          shell: get("Shell").value,
          favourites: [...favourites],
        }),
      );
    } catch {}
  }
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function filter() {
    const words = get("Search")
      .value.toLowerCase()
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    const visible = commands.filter(
      (c) =>
        (!get("Tool")?.value || (c.tool || "PsExec") === get("Tool").value) &&
        (category === "All" ||
          (category === "Favourites"
            ? favourites.has(c.id)
            : c.category === category)) &&
        words.every((word) =>
          (
            (c.tool || "PsExec") +
            " " +
            c.title +
            " " +
            c.description +
            " " +
            c.category +
            " " +
            c.insight
          )
            .toLowerCase()
            .includes(word),
        ),
    );
    get("Count").textContent =
      `${visible.length} command${visible.length === 1 ? "" : "s"} · ${commands.length} in your toolkit`;
    get("Categories").replaceChildren(
      ...categories.map((name) => {
        const b = el("button", name);
        b.type = "button";
        b.setAttribute("aria-pressed", String(category === name));
        b.onclick = () => {
          category = name;
          filter();
        };
        return b;
      }),
    );
    get("Cards").replaceChildren(
      ...visible.map((c) => {
        const b = el("button", null, "px-card");
        b.type = "button";
        b.dataset.template = c.id;
        b.setAttribute("aria-pressed", String(selected.id === c.id));
        b.append(
          el("small", c.category + (c.change ? " · Changes target" : "")),
          el("strong", (favourites.has(c.id) ? "★ " : "") + c.title),
          el("span", c.description),
          el("span", "Review command", "px-card-action"),
        );
        b.onclick = () => {
          select(c);
          if (matchMedia("(max-width: 1050px)").matches)
            get("Title").scrollIntoView({ block: "nearest" });
        };
        return b;
      }),
    );
    if (!visible.length)
      get("Cards").append(
        el(
          "p",
          category === "Favourites"
            ? "No matching favourites. Star a command in its review panel."
            : "No matches. Try Excel, DNS or service.",
          "px-empty",
        ),
      );
  }
  function select(item) {
    selected = item;
    values = {};
    get("Fields").replaceChildren();
    // Each template starts without escalation or a prior action's parameters.
    get("Elevated").checked = false;
    get("Elevated").disabled = !!item.direct;
    get("Elevated").closest("label").hidden = !!item.direct;
    get("Title").textContent = item.title;
    get("Category").textContent = item.category;
    get("Description").textContent = item.description;
    get("Impact").textContent =
      (item.change ? "Changes target · " : "") + item.insight;
    get("Impact").classList.toggle("px-change", !!item.change);
    for (const field of item.fields || []) {
      const label = el("label", field.label),
        input = el("input");
      input.id = "pxArg-" + field.key;
      input.placeholder = field.placeholder;
      input.autocomplete = "off";
      input.spellcheck = false;
      input.oninput = () => {
        values[field.key] = input.value;
        preview();
      };
      label.append(input);
      get("Fields").append(label);
    }
    favouriteState();
    filter();
    preview();
  }
  function favouriteState() {
    const yes = favourites.has(selected.id);
    get("Favourite").textContent = yes ? "★ Favourite" : "☆ Favourite";
    get("Favourite").setAttribute("aria-pressed", String(yes));
  }
  function preview() {
    get("Follow").setAttribute("aria-pressed", String(follow));
    get("TargetNote").textContent = follow
      ? "Target follows your selection in Workspace. Browsing templates makes no remote requests."
      : "Using the hostname entered here. Your Workspace/deployment target is unchanged.";
    get("Copy").textContent =
      "Copy " +
      (get("Shell").value === "cmd" ? "Command Prompt" : "PowerShell") +
      " command";
    try {
      current = build(selected.id, {
        target: get("Target").value,
        path: get("Path").value,
        shell: get("Shell").value,
        elevated: get("Elevated").checked,
        values,
      });
      get("Command").textContent = current.command;
      get("Readable").textContent = current.readable;
      get("Error").textContent = "";
      get("Copy").disabled = false;
      get("Encoding").textContent = current.encoded
        ? "The copied command includes the displayed script encoded for PowerShell, so quotes and pipes survive the remote hop."
        : "Paste in the selected terminal on your admin computer. Review the target before pressing Enter.";
    } catch (error) {
      current = null;
      get("Command").textContent =
        "Complete the fields to generate the command.";
      get("Readable").textContent =
        typeof selected.script === "string"
          ? selected.script
          : Array.isArray(selected.args)
            ? selected.args.join(" ")
            : "Complete the parameters above to preview the target command.";
      get("Error").textContent = error.message;
      get("Copy").disabled = true;
      get("Encoding").textContent = "";
    }
    window.AtlasPsExecTerminal?.review(
      current
        ? {
            template: selected.id,
            target: current.target,
            path: get("Path").value.trim(),
            elevated: get("Elevated").checked,
            values: { ...values },
          }
        : null,
      selected,
    );
  }
  function syncTarget(target) {
    if (follow) {
      get("Target").value = target || "";
      preview();
    }
  }
  if (get("Tool")) {
    get("Tool").replaceChildren(
      new Option("All PsTools", ""),
      ...[...new Set(commands.map((c) => c.tool || "PsExec"))].map(
        (t) => new Option(t, t),
      ),
    );
    get("Tool").onchange = () => {
      category = "All";
      filter();
    };
  }
  get("Search").oninput = filter;
  get("Target").oninput = () => {
    follow = false;
    preview();
  };
  get("Follow").onclick = () => {
    follow = true;
    syncTarget(S.target);
  };
  get("Path").oninput = () => {
    save();
    preview();
  };
  get("Shell").onchange = () => {
    save();
    preview();
  };
  get("Elevated").onchange = preview;
  get("Favourite").onclick = () => {
    favourites.has(selected.id)
      ? favourites.delete(selected.id)
      : favourites.add(selected.id);
    save();
    favouriteState();
    filter();
  };
  get("Copy").onclick = async () => {
    preview();
    if (!current) return;
    const snapshot = current;
    try {
      await navigator.clipboard.writeText(snapshot.command);
      toast(`Command copied for ${snapshot.target} · paste to run`);
    } catch {
      get("Error").textContent =
        "Clipboard unavailable. Expand Full PsExec command and select the text to copy manually.";
      get("Command").closest("details").open = true;
    }
  };
  window.AtlasPsExec = Object.freeze({
    syncTarget,
    open() {
      syncTarget(S.target);
      preview();
      window.AtlasPsExecTerminal?.open();
    },
  });
  select(selected);
})();
