/* Deployment kits: named package sets saved in this browser and added to the
   deployment queue for the selected machine in one click. Nothing deploys until
   the queue is started, exactly as with items added one at a time. */
(() => {
  const KEY = "atlasDeploymentKits";
  const readonly = () =>
    !!window.AtlasReadOnly ||
    document.querySelector('meta[name="atlas-mode"]')?.content === "viewer";
  const fields = ["folder", "script", "action", "fresh", "threads", "mode"];

  function load() {
    try {
      const kits = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(kits) ? kits.filter((k) => k && k.name && Array.isArray(k.items)) : [];
    } catch {
      return [];
    }
  }
  function store(kits) {
    try {
      localStorage.setItem(KEY, JSON.stringify(kits));
      return true;
    } catch {
      toast("This browser could not save the kit.");
      return false;
    }
  }
  const packageName = (folder) =>
    String(folder || "").split(/[\\/]/).filter(Boolean).pop() || "";

  function save() {
    const input = document.querySelector("#kitName");
    const name = input.value.trim().replace(/\s+/g, " ").slice(0, 60);
    if (!deploymentQueue.length) return toast("Add packages to the queue first, then save them as a kit.");
    if (!name) {
      input.focus();
      return toast("Name the kit, for example New starter.");
    }
    const items = deploymentQueue.map((item) =>
      Object.fromEntries(fields.map((key) => [key, item[key]])),
    );
    const kits = load();
    const existing = kits.findIndex((k) => k.name.toLowerCase() === name.toLowerCase());
    const kit = { name, items, saved: new Date().toISOString() };
    if (existing >= 0) kits[existing] = kit;
    else kits.push(kit);
    kits.sort((a, b) => a.name.localeCompare(b.name));
    if (!store(kits)) return;
    input.value = "";
    render();
    toast(`${existing >= 0 ? "Updated" : "Saved"} kit ${name} · ${items.length} package${items.length === 1 ? "" : "s"}`);
  }

  function addToQueue(name) {
    const kit = load().find((k) => k.name === name);
    if (!kit) return render();
    if (activeQueueId) return toast("Finish or clear the saved queue first");
    if (!S.target) return toast("Select a target machine first");
    for (const item of kit.items)
      deploymentQueue.push({ ...item, computer: S.target, state: "waiting" });
    renderQueue();
    render();
    toast(`Added ${kit.items.length} package${kit.items.length === 1 ? "" : "s"} from ${kit.name} for ${S.target}`);
  }

  function remove(name) {
    if (!confirm(`Delete the kit ${name}? Queued items are not affected.`)) return;
    store(load().filter((k) => k.name !== name));
    render();
  }

  function render() {
    const host = document.querySelector("#kitList");
    if (!host) return;
    const kits = load(), locked = readonly();
    const target = typeof S !== "undefined" ? S.target : "";
    host.innerHTML = kits.length
      ? kits
          .map((kit) => {
            const names = kit.items.map((i) => `${packageName(i.folder)} (${i.action || "Install"})`);
            return `<div class="kit-row"><div><b>${esc(kit.name)}</b><span title="${esc(names.join("\n"))}">${kit.items.length} package${kit.items.length === 1 ? "" : "s"} · ${esc(names.slice(0, 3).join(", "))}${names.length > 3 ? "…" : ""}</span></div><button data-kit-add="${esc(kit.name)}" ${locked || !target ? "disabled" : ""} title="${locked ? "Deployment is available in Atlas Admin" : target ? `Queue every package for ${esc(target)}` : "Select a target machine first"}">${target ? `Add for ${esc(target)}` : "Add to queue"}</button><button data-kit-delete="${esc(kit.name)}" aria-label="Delete kit ${esc(kit.name)}">Delete</button></div>`;
          })
          .join("")
      : '<p class="empty">No kits yet. Queue the packages you deploy together, name them, then save.</p>';
    host.querySelectorAll("[data-kit-add]").forEach((b) => (b.onclick = () => addToQueue(b.dataset.kitAdd)));
    host.querySelectorAll("[data-kit-delete]").forEach((b) => (b.onclick = () => remove(b.dataset.kitDelete)));
    const saveButton = document.querySelector("#saveKit");
    if (saveButton) {
      saveButton.disabled = locked;
      saveButton.title = locked ? "Deployment is available in Atlas Admin" : "Save the packages in the queue as a reusable kit";
    }
  }

  function install() {
    const button = document.querySelector("#saveKit");
    if (!button || button.dataset.installed) return;
    button.dataset.installed = "1";
    button.onclick = save;
    document.querySelector("#kitName").addEventListener("keydown", (event) => {
      if (event.key === "Enter") save();
    });
    // The target is chosen elsewhere in the console; refresh labels whenever the drawer opens.
    const drawer = document.querySelector("#queueDrawer");
    if (drawer)
      new MutationObserver(() => drawer.classList.contains("open") && render()).observe(drawer, {
        attributes: true,
        attributeFilter: ["class"],
      });
    render();
  }
  window.AtlasKits = { load, render, save, addToQueue };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();
