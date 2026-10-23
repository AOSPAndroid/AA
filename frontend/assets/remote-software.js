/* Extend the existing software drawer; registered metadata is rendered as text. */
(() => {
  const el = (id) => document.getElementById(id);
  let selected = null,
    action = "",
    preview = null,
    working = false,
    activeJob = null,
    sequence = 0;
  async function request(url, body) {
    return AtlasClient.request(url, {
      ...(body === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    });
  }

  const controls = () => {
    el("softwareExecute").disabled =
      working || !preview || el("softwareConfirm").value !== preview.computer;
    [
      "softwareUninstall",
      "softwareRepair",
      "softwareCleanCache",
      "softwarePreview",
      "softwareArguments",
    ].forEach((id) => (el(id).disabled = working));
  };
  const clear = () => {
    preview = null;
    el("softwareCommandReview").hidden = true;
    el("softwareConfirm").value = "";
    controls();
  };
  function render() {
    const rows = softwareRows();
    el("softwareBody").innerHTML = rows
      .map(
        (x) =>
          `<tr data-software-row="${Number(x.row)}" tabindex="0"><td>${esc(x.Name)}${x.CacheFile ? '<small style="display:block">' + esc(x.CacheFile) + "</small>" : ""}</td><td>${esc(x.Version)}</td><td>${esc(x.Publisher)}</td><td>${esc(x.Scope || "")} ${esc(x.Kind || "")}<small style="display:block">${esc(x.UserSid || x.Architecture || "")}</small></td><td><button data-software-action="${Number(x.row)}">Actions</button></td></tr>`,
      )
      .join("");
    const data = softwareState.software.get(softwareState.softwareTarget) || {};
    el("softwareSummary").textContent =
      `${rows.length} applications shown · ${data.collected_at || ""}${(data.warnings || []).length ? " · " + data.warnings.join(" | ") : ""}`;
    updatePackagePresence();
    let cache = el("softwareCacheResults");
    if (!cache) {
      cache = document.createElement("details");
      cache.id = "softwareCacheResults";
      el("softwareDrawer").append(cache);
    }
    cache.replaceChildren();
    cache.hidden = !(data.cache || []).length;
    if (!cache.hidden) {
      const title = document.createElement("summary");
      title.textContent = `Cached MSI metadata (${data.cache.length} files) — cache presence does not prove installation`;
      cache.append(title);
      const pre = document.createElement("pre");
      pre.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere";
      pre.textContent = data.cache
        .map(
          (x) =>
            `${x.CacheFile} | ${x.Name || x.Subject || "No product name"} | ${x.Version || ""}\nSubject: ${x.Subject || "—"} | Registered product matches: ${x.RegisteredMatches}\n${x.ProductCode || ""}`,
        )
        .join("\n\n");
      cache.append(pre);
    }
  }
  async function load(pc, force = false) {
    if (!pc) return toast("Select a target");
    pc = pc.trim().toUpperCase();
    const turn = ++sequence;
    softwareState.softwareTarget = pc;
    softwareState.currentSoftware = [];
    el("softwareDrawer").classList.add("open");
    el("softwareTarget").textContent = pc;
    el("softwareBody").replaceChildren();
    el("softwareCacheResults")?.replaceChildren();
    el("softwareSummary").textContent =
      "Collecting software on " + pc + " via WMI…";
    if (!force && softwareState.software.has(pc)) {
      softwareState.currentSoftware =
        softwareState.software.get(pc).software || [];
      renderSoftware();
      return;
    }
    try {
      const data = await request("/api/software-tools/inventory", {
        computer: pc,
        cache: el("softwareCache").checked,
        appx: el("softwareAppx").checked,
      });
      if (turn !== sequence) return;
      softwareState.software.set(pc, data);
      softwareState.currentSoftware = data.software || [];
      renderSoftware();
    } catch (e) {
      if (turn === sequence) el("softwareSummary").textContent = e.message;
    }
  }
  async function choose(which) {
    if (working) return;
    clear();
    action = which;
    const x = selected.item;
    const availability =
      which === "Repair" ? x.repair_availability : x.availability;
    el("softwareActionReason").textContent =
      (which === "Repair" ? x.repair_reason : x.reason) ||
      "Rescan software to enable actions.";
    el("softwareArgumentsLabel").hidden = true;
    el("softwarePreview").hidden = true;
    if (availability === "blocked" || !availability) return;
    if (availability === "configure") {
      el("softwareArgumentsLabel").hidden = false;
      el("softwareArguments").value = "";
      el("softwarePreview").hidden = false;
      el("softwareActionLog").textContent =
        "Registered command:\n" +
        (which === "Repair" ? x.ModifyPath : x.UninstallString) +
        "\nEnter the COMPLETE silent argument string, including required original arguments. No switches are guessed.";
      return;
    }
    await showPreview();
  }
  async function showPreview() {
    if (working || !selected) return;
    working = true;
    controls();
    try {
      const data = await request("/api/software-tools/preview", {
        scan: selected.scan,
        row: selected.item.row,
        action,
        arguments: el("softwareArguments").value,
      });
      preview = data;
      el("softwareCommand").textContent =
        `${data.action}: ${data.name} ${data.version}\nTarget: ${data.computer}\nScope: ${data.scope}${data.sid ? " / " + data.sid : ""}\n\n${data.command}`;
      el("softwareCommandReview").hidden = false;
      el("softwareActionLog").textContent = "No action has run yet.";
    } catch (e) {
      el("softwareActionLog").textContent = e.message;
    } finally {
      working = false;
      controls();
    }
  }
  function open(row) {
    if (working && !activeJob) return;
    if (activeJob) {
      el("softwareActionDialog").showModal();
      return;
    }
    const data = softwareState.software.get(softwareState.softwareTarget);
    const item = (data?.software || []).find((x) => x.row === row);
    if (!item) return;
    selected = { item, scan: data.scan, pc: softwareState.softwareTarget };
    clear();
    el("softwareActionTitle").textContent = item.Name;
    el("softwareActionIdentity").textContent =
      `${selected.pc} · ${item.Version || "Version unknown"} · ${item.Kind} · ${item.Scope}${item.UserSid ? " / " + item.UserSid : ""}`;
    el("softwareActionReason").textContent =
      "Choose an action. A preview is required before execution.";
    el("softwareActionLog").textContent = "";
    el("softwareArgumentsLabel").hidden = true;
    el("softwarePreview").hidden = true;
    el("softwareActionDialog").showModal();
  }
  function poll(job) {
    const pc = selected.pc;
    let failures = 0;
    const finish = () => {
      softwareState.software.delete(pc);
      activeJob = null;
      working = false;
      selected = null;
      controls();
    };
    return AtlasClient.watch("console-software-action", "/api/software-tools/jobs/" + job,
      data => {
        failures = 0;
        el("softwareActionLog").textContent =
          data.events.map(e => `[${e.time || ""}] ${e.message}`).join("\n") || "Queued…";
        if (AtlasClient.terminal.has(data.state)) {
          finish();
          el("softwareActionLog").textContent += `\nState: ${data.state}. Refresh the software list before another action.`;
        }
      }, {
        onError: error => {
          failures++;
          el("softwareActionLog").textContent =
            `Monitoring unavailable: ${error.message}. Check deployment history; the remote action may still be running.`;
          if (failures >= 8) {
            finish();
            el("softwareActionLog").textContent += "\nMonitoring stopped after eight failed attempts. Refresh inventory only after checking the operation state.";
          }
        },
      });
  }
  document.addEventListener("DOMContentLoaded", () => {
    el("adminSoftware").onclick = () =>
      loadSoftware(el("adminPc").value || S.target);
    el("softwareBody").addEventListener("contextmenu", (e) => {
      const row = e.target.closest("[data-software-row]");
      if (row) {
        e.preventDefault();
        open(Number(row.dataset.softwareRow));
      }
    });
    el("softwareBody").addEventListener("click", (e) => {
      const button = e.target.closest("[data-software-action]");
      if (button) open(Number(button.dataset.softwareAction));
    });
    el("softwareBody").addEventListener("keydown", (e) => {
      if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
        const row = e.target.closest("[data-software-row]");
        if (row) {
          e.preventDefault();
          open(Number(row.dataset.softwareRow));
        }
      }
    });
    el("softwareActionClose").onclick = () =>
      el("softwareActionDialog").close();
    el("softwareUninstall").onclick = () => selected && choose("Uninstall");
    el("softwareRepair").onclick = () => selected && choose("Repair");
    el("softwareCleanCache").onclick = () => {
      clear();
      el("softwareArgumentsLabel").hidden = true;
      el("softwarePreview").hidden = true;
      el("softwareActionReason").textContent =
        "No application cache location is configured for this app. Cleanup is unavailable until its disposable cache folders are identified.";
      el("softwareActionLog").textContent =
        "The MSI files under Windows\\Installer support repair and uninstall and will not be deleted.\nCached MSI: " +
        (selected?.item.LocalPackage || "No mapped MSI cache file") +
        "\nApplication caches vary by product and user profile; installation folders are not cache folders.";
    };
    el("softwarePreview").onclick = showPreview;
    el("softwareArguments").oninput = clear;
    el("softwareConfirm").oninput = controls;
    el("softwareExecute").onclick = async () => {
      if (!preview || working) return;
      working = true;
      controls();
      try {
        const d = await request("/api/software-tools/uninstall", {
          plan: preview.plan,
          confirmation: el("softwareConfirm").value,
        });
        activeJob = d.job;
        clear();
        el("softwareActionLog").textContent = "Queued on " + d.computer;
        poll(d.job);
      } catch (e) {
        el("softwareActionLog").textContent = e.message;
        working = false;
        controls();
      }
    };
    for (const id of ["softwareAppx", "softwareCache"])
      el(id).onchange = () => {
        softwareState.software.delete(softwareState.softwareTarget);
        loadSoftware(softwareState.softwareTarget || S.target, true);
      };
  });
  window.AtlasSoftware = { render, load };
})();
