export function openCatalogue({
  folder = "",
  api = AtlasClient.request,
  toast = () => {},
  onSave = () => {},
} = {}) {
  const existing = document.querySelector(".atlas-catalogue");
  if (existing) {
    existing.querySelector("input")?.focus();
    return existing;
  }
  const { element: d, body } = AtlasUI.dialog("Package catalogue");
  d.classList.add("atlas-catalogue");
  const esc = AtlasUI.esc;
  body.innerHTML =
    '<p class="catalog-muted">Browse applications, inspect package scripts and update catalogue names and versions.</p><label class="catalog-label">Search applications<input id="catalog-search" placeholder="Name, version or folder"></label><p id="catalog-status" role="status"></p><div class="catalog-layout"><div id="catalog-list"></div><div id="catalog-detail"><p>Select a package to inspect scripts and local file availability.</p></div></div>';
  let request = 0,
    inspection = 0,
    timer;
  const list = async () => {
    const v = ++request;
    try {
      const data = await api(
        "/api/catalog?term=" +
          encodeURIComponent(d.querySelector("#catalog-search").value),
      );
      if (!d.isConnected || v !== request) return;
      d.querySelector("#catalog-status").textContent =
        data.error ||
        `${data.total} packages${data.truncated ? " · first 500 shown, refine search" : ""}`;
      d.querySelector("#catalog-list").innerHTML = data.items
        .map(
          (p) =>
            `<button data-catalog-folder="${esc(p.folder)}"><b>${esc(p.display_name)}</b><small>${esc(p.version || "Version not recorded")} · ${esc(p.folder)}${p.state ? " · " + esc(p.state) : ""}</small></button>`,
        )
        .join("");
      d.querySelectorAll("[data-catalog-folder]").forEach(
        (b) => (b.onclick = () => inspect(b.dataset.catalogFolder)),
      );
    } catch (e) {
      if (d.isConnected && v === request)
        d.querySelector("#catalog-status").textContent = e.message;
    }
  };
  const inspect = async (folder) => {
    const v = ++inspection,
      host = d.querySelector("#catalog-detail");
    host.textContent = "Inspecting package file metadata…";
    try {
      const x = await api(
        "/api/catalog/details?folder=" + encodeURIComponent(folder),
      );
      if (!d.isConnected || v !== inspection) return;
      host.innerHTML = `<h3>${esc(x.display_name || folder)}</h3><p class="catalog-muted">${esc(folder)}</p><p><b>${esc(x.availability)}</b> · ${x.files_checked} files checked</p><small>${esc(x.availability_note)}</small>${!x.complete ? '<p class="catalog-error">Scan incomplete. Script lists may be partial.</p>' : ""}<p class="catalog-muted">Checked ${esc(x.checked_at)}</p>${x.package_data ? `<details open><summary>Package data · ${esc(x.package_data.state || "State not supplied")}</summary><p>${esc(x.package_data.package_id)} · Packager: ${esc(x.package_data.packager || "Not supplied")} · Requester: ${esc(x.package_data.requester || "Not supplied")}</p><p>${esc(x.package_data.domain)} · ${esc(x.package_data.build)}</p><small>Imported ${esc(x.package_data.imported_at)}</small></details>` : "<p>No matching package data. State unknown.</p>"}${Object.entries(
        x.scripts,
      )
        .map(
          ([action, scripts]) =>
            `<details open><summary>${action} (${scripts.length})</summary>${scripts.length ? `<ul>${scripts.map((s) => `<li><code>${esc(s)}</code></li>`).join("")}</ul>` : '<p class="catalog-muted">No matching script found.</p>'}</details>`,
        )
        .join(
          "",
        )}<form id="catalog-edit"><label class="catalog-label">Application name<input name="display_name" maxlength="160" required value="${esc(x.display_name || folder)}"></label><label class="catalog-label">Version<input name="version" maxlength="80" value="${esc(x.version || "")}" placeholder="Leave blank if unknown"></label><button class="primary">Save catalogue details</button><p id="catalog-message"></p></form>`;
      host.querySelector("form").onsubmit = async (e) => {
        e.preventDefault();
        const form = e.target,
          save = form.querySelector("button"),
          metadata = {
            folder,
            display_name: form.elements.display_name.value,
            version: form.elements.version.value,
            revision: x.revision,
          };
        if (save.disabled) return;
        save.disabled = true;
        try {
          await api("/api/catalog/metadata", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(metadata),
          });
          await onSave(metadata);
          if (d.isConnected) {
            await list();
            if (v === inspection) await inspect(folder);
          }
          toast("Catalogue details saved");
        } catch (e) {
          if (d.isConnected && v === inspection)
            form.querySelector("#catalog-message").textContent = e.message;
        } finally {
          save.disabled = false;
        }
      };
    } catch (e) {
      if (d.isConnected && v === inspection) host.textContent = e.message;
    }
  };
  d.querySelector("#catalog-search").oninput = () => {
    request++;
    clearTimeout(timer);
    timer = setTimeout(list, 200);
  };
  d.addEventListener(
    "close",
    () => {
      request++;
      inspection++;
      clearTimeout(timer);
    },
    { once: true },
  );
  list();
  if (folder) inspect(folder);
  d.querySelector("#catalog-search").focus();
  return d;
}
