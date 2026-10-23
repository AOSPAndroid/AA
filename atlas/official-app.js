// window.AtlasNavigate lets tests observe navigation (jsdom cannot replace location.assign).
function atlasMapNavigate(url) {
  if (!window.AtlasNavigate?.(url)) location.assign(url);
}
import { applyFurnitureCorrections } from "./map-furniture.js?v=7";
import { applyMapAmenities } from "./map-amenities.js?v=13";
import { createCameraMotion } from "./camera-motion.js";
import { installMapCursor } from "./map-cursor.js?v=5";
import { openSiteInfo } from "./site-info.js?v=1";
const readOnly =
  document.querySelector('meta[name="atlas-mode"]')?.content === "viewer";
const { createOperations } = readOnly
  ? { createOperations: (await import("./viewer.js")).createViewerOperations }
  : await import("./operations.js?v=3");
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)],
  esc = (s) =>
    String(s ?? "").replace(
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
const toast = (s) => {
  $("#toast").textContent = s;
  $("#toast").classList.add("show");
  clearTimeout(window.tt);
  window.tt = setTimeout(() => $("#toast").classList.remove("show"), 3500);
};
let data;
// Desk records download alongside the floor geometry instead of after it.
const initialState = fetch("/api/official/state").catch(() => null);
try {
  const response = await fetch("official-data.json", { cache: "no-cache" });
  if (!response.ok) throw Error();
  data = await response.json();
  applyMapAmenities(data);
  applyFurnitureCorrections(data);
} catch {
  $("#results").textContent =
    "The directory could not load. Refresh to try again.";
  throw Error("Directory unavailable");
}
const layerPreference = (name) => {
  try {
    return localStorage.getItem(`atlas.map.${name}`) !== "off";
  } catch {
    return true;
  }
};
const mapLayers = {
  walls: layerPreference("walls"),
  facilities: layerPreference("amenities"),
  doors: layerPreference("doors"),
};
const mapColors = {
  lift: [0.7, 0.85, 1, 1],
  wc: [0.76, 0.91, 0.86, 1],
  print: [0.83, 0.88, 1, 1],
  kitchen: [1, 0.9, 0.73, 1],
  room: [0.88, 0.83, 0.98, 1],
  stairs: [0.87, 0.9, 0.93, 1],
};
const facilityVisible = (r) =>
  Object.hasOwn(mapColors, r.kind) && mapLayers.facilities;
const mapPanel = document.createElement("details");
mapPanel.className = "map-settings";
mapPanel.innerHTML =
  '<summary>⚙ <span>Map settings</span></summary><div class="map-settings-body"><div class="map-settings-view"></div><div class="map-settings-layers" role="group" aria-label="Map layers"></div></div>';
document.querySelector("#map-labels").parentElement.append(mapPanel);
const settingsBody = mapPanel.querySelector(".map-settings-body");
const settingsView = mapPanel.querySelector(".map-settings-view");
settingsView.append($(".view-switch"), $("#name-tags").closest("label"));
// Display stays in the shared More menu.
settingsBody.append($(".map-tools"));
for (const [layer, title] of [
  ["walls", "Walls"],
  ["doors", "Doors"],
  ["facilities", "Amenities"],
]) {
  const label = document.createElement("label");
  label.className = "name-toggle layer-toggle";
  label.innerHTML = `<input type="checkbox" role="switch" data-layer="${layer}"><span class="switch-track" aria-hidden="true"></span><span>${title}</span>`;
  label.querySelector("input").checked = mapLayers[layer];
  mapPanel.querySelector(".map-settings-layers").append(label);
}
document.addEventListener("pointerdown", (event) => {
  if (mapPanel.open && !mapPanel.contains(event.target)) mapPanel.open = false;
});
mapPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.stopPropagation();
    mapPanel.open = false;
    mapPanel.querySelector("summary").focus();
  }
});
const amenityOverlay = document.createElement("div");
amenityOverlay.className = "amenity-labels";
document.querySelector("#map-labels").parentElement.append(amenityOverlay);
const amenityNodes = new Map();
mapPanel.onchange = (e) => {
  if (e.target.dataset.layer) {
    mapLayers[e.target.dataset.layer] = e.target.checked;
    const name =
      e.target.dataset.layer === "facilities"
        ? "amenities"
        : e.target.dataset.layer;
    try {
      localStorage.setItem(
        `atlas.map.${name}`,
        e.target.checked ? "on" : "off",
      );
    } catch {}
    draw();
  }
};
function doorPoints(curve) {
  const p = curve.map((a) => modelPoint(...a));
  return Array.from({ length: 17 }, (_, i) => {
    const t = i / 16,
      u = 1 - t;
    return [0, 1, 2].map(
      (k) =>
        u * u * u * p[0][k] +
        3 * u * u * t * p[1][k] +
        3 * u * t * t * p[2][k] +
        t * t * t * p[3][k],
    );
  });
}
function paintArchitecture(c) {
  const g = data.floors.find((f) => f.level === floor).geometry;
  for (const points of [...(g.curvedTables || []), ...(g.counters || [])]) {
    c.beginPath();
    points.forEach((point, i) => {
      const p = modelPoint(...point);
      i ? c.lineTo(p[0], p[2]) : c.moveTo(p[0], p[2]);
    });
    c.closePath();
    c.fillStyle = "#c5deea";
    c.fill();
    c.strokeStyle = "#7396aa";
    c.lineWidth = 0.08;
    c.stroke();
  }
  for (const [items, fill, stroke] of [
    [
      [...(g.kitchenCounters || []), ...(g.kitchenTables || [])],
      "#b8d7e5",
      "#527f96",
    ],
    [g.kitchenSeats || [], "#d9e8ef", "#7396aa"],
    [g.kitchenSinks || [], "#f8fcfe", "#007eae"],
    [g.cupboards || [], "#d9e5eb", "#7396aa"],
    [g.printers || [], "#f1f5f7", "#527080"],
  ])
    for (const points of items) {
      c.beginPath();
      points.forEach((point, i) => {
        const p = modelPoint(...point);
        i ? c.lineTo(p[0], p[2]) : c.moveTo(p[0], p[2]);
      });
      c.closePath();
      c.fillStyle = fill;
      c.fill();
      c.strokeStyle = stroke;
      c.lineWidth = 0.08;
      c.stroke();
    }
  if (mapLayers.doors) {
    c.beginPath();
    for (const curve of g.doorSwings || []) {
      const [a, b, d, e] = curve.map((p) => modelPoint(...p));
      c.moveTo(a[0], a[2]);
      c.bezierCurveTo(b[0], b[2], d[0], d[2], e[0], e[2]);
    }
    c.strokeStyle = "#b45309";
    c.lineWidth = 0.12;
    c.stroke();
  }
  for (const r of g.wayfinding || []) {
    if (!facilityVisible(r)) continue;
    c.beginPath();
    r.points.forEach((p, i) => {
      const q = modelPoint(...p);
      i ? c.lineTo(q[0], q[2]) : c.moveTo(q[0], q[2]);
    });
    c.closePath();
    const color = mapColors[r.kind];
    c.fillStyle =
      "rgba(" +
      color
        .slice(0, 3)
        .map((x) => Math.round(x * 255))
        .join(",") +
      (r.kind === "stairs" ? ",0.12)" : ",0.55)");
    c.fill();
    if (r.kind === "lift" || r.kind === "stairs") {
      c.strokeStyle = "#0084b4";
      c.lineWidth = 0.12;
      c.stroke();
    }
  }
  if (mapLayers.walls) {
    c.beginPath();
    for (const [a, b] of g.walls || []) {
      const p = modelPoint(...a),
        q = modelPoint(...b);
      c.moveTo(p[0], p[2]);
      c.lineTo(q[0], q[2]);
    }
    c.strokeStyle = "#405765";
    c.lineWidth = 0.045;
    c.stroke();
    const perimeter = g.buildingPerimeter || [];
    c.beginPath();
    perimeter.forEach((a, i) => {
      const p = modelPoint(...a);
      i ? c.lineTo(p[0], p[2]) : c.moveTo(p[0], p[2]);
    });
    c.closePath();
    c.lineJoin = "round";
    c.strokeStyle = "#ffffff";
    c.lineWidth = 0.4;
    c.stroke();
    c.strokeStyle = "#075985";
    c.lineWidth = 0.22;
    c.stroke();
  }
}
function updateMapLayers() {
  settingsBody.style.maxHeight = `${Math.max(80, canvas.clientHeight - 108)}px`;
  for (const input of mapPanel.querySelectorAll("[data-layer]"))
    input.disabled = view === "source";
}

let records = data.records,
  floor = 2,
  selected = null,
  view = "plan",
  placing = false,
  floorFitted = true,
  lastMatches = [],
  cam = { yaw: -0.14, tilt: 1.0, scale: 1, cx: 0, cz: 0 };
// Chat receives a small, explicit selection only when the operator attaches it.
window.AtlasAxisSelection = () =>
  !readOnly && selected
    ? {
        desk_id: selected.id,
        name: selected.name,
        hostname: selected.hostname || "",
        floor: selected.floor,
      }
    : null;
const motionPreference = {
  get matches() {
    return AtlasUI.motion.isReduced();
  },
};
AtlasUI.motion.install($(".view-switch"));
const cameraMotion = createCameraMotion({
  read: () => cam,
  write: (value) => {
    cam = value;
  },
  requestFrame: () => draw(),
  reduced: () => motionPreference.matches,
  light: () => AtlasUI.performance.isCitrix(),
});
const mapEffects = new Map();
function revealMap(element = canvas) {
  mapEffects.get(element)?.cancel();
  if (
    motionPreference.matches ||
    AtlasUI.performance.isCitrix() ||
    !element.animate
  )
    return;
  const animation = element.animate([{ opacity: 0.45 }, { opacity: 1 }], {
    duration: 260,
    easing: "ease-out",
  });
  mapEffects.set(element, animation);
  animation.onfinish = () => mapEffects.delete(element);
}
const locator = document.createElement("div");
locator.className = "map-locator";
locator.hidden = true;
locator.setAttribute("aria-hidden", "true");
locator.innerHTML =
  '<span class="locator-ring"></span><span class="locator-core"></span>';
$("#viewport").append(locator);
let locatorAnimation;
function clearLocator() {
  locatorAnimation?.cancel();
  locatorAnimation = null;
  locator.hidden = true;
}
function locateBeacon() {
  clearLocator();
  if (
    motionPreference.matches ||
    AtlasUI.performance.isCitrix() ||
    !locator.animate
  )
    return;
  locator.hidden = false;
  positionLocator();
  const ring = locator.querySelector(".locator-ring");
  locatorAnimation = ring.animate(
    [
      { transform: "scale(.45)", opacity: 0 },
      { transform: "scale(.7)", opacity: 0.9, offset: 0.25 },
      { transform: "scale(1)", opacity: 0.65, offset: 0.6 },
      { transform: "scale(1.45)", opacity: 0 },
    ],
    { duration: 1500, easing: "ease-out" },
  );
  locatorAnimation.onfinish = clearLocator;
}
function positionLocator() {
  if (locator.hidden) return;
  if (!selected || selected.floor !== floor) {
    clearLocator();
    return;
  }
  const p = world(selected);
  const [x, y] = projected([p[0], view === "3d" ? 1.95 : 0, p[2]]);
  locator.style.transform = `translate3d(${x}px, ${y}px, 0)`;
}
window.addEventListener("atlas-motion-change", () => {
  if (!motionPreference.matches && !AtlasUI.performance.isCitrix()) return;
  cameraMotion.finish();
  clearLocator();
  for (const animation of mapEffects.values()) animation.cancel();
  mapEffects.clear();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    cancelMapGesture();
    cameraMotion.finish();
    clearLocator();
    clearTimeout(motionTimer);
    moving = false;
    if (pendingDraw) cancelAnimationFrame(pendingDraw);
    pendingDraw = 0;
  } else draw();
});
window.addEventListener("pagehide", () => {
  cameraMotion.cancel();
  clearLocator();
  for (const animation of mapEffects.values()) animation.cancel();
  mapEffects.clear();
  clearTimeout(motionTimer);
  clearTimeout(searchTimer);
  if (pendingDraw) cancelAnimationFrame(pendingDraw);
  pendingDraw = 0;
});
let showNameTags = true;
try {
  showNameTags = localStorage.getItem("atlas-show-name-tags") !== "false";
} catch {}
$("#name-tags").checked = showNameTags;
$("#name-tags").onchange = (e) => {
  showNameTags = e.target.checked;
  try {
    localStorage.setItem("atlas-show-name-tags", String(showNameTags));
  } catch {}
  applyNameVisibility();
  draw();
};
function applyNameVisibility() {
  updateMapLayers();
  const hide = !showNameTags || view === "source";
  $("#map-labels").hidden = hide;
  $("#label-lines").style.display = hide ? "none" : "";
  if (hide) $("#location-banner").hidden = true;
  $("#name-tags").disabled = view === "source";
}

let token = null,
  databaseReady = false,
  previousRecords = [],
  previousMappings = {};
try {
  const response = await initialState;
  if (response?.ok) {
    const state = await response.json();
    records = state.records;
    previousRecords = state.legacy || [];
    previousMappings = state.mappings || {};
    token = state.token;
    databaseReady = true;
  }
} catch {}
const operations = createOperations({
  onSelect: (id) => selectRecord(id),
  token: () => token,
  getSelection: () => selected,
  toast,
  onChange: () => reloadRecords(),
});
function hasPendingMapEdits() {
  if (readOnly) return false;
  if (placing || document.querySelector(".move-dialog[open]")) return true;
  const form = document.getElementById("record-form");
  return (
    !!form &&
    [...form.elements].some((field) => {
      if (!field.name) return false;
      if (field.type === "checkbox" || field.type === "radio")
        return field.checked !== field.defaultChecked;
      if (field.tagName === "SELECT") {
        const original =
          [...field.options].find((option) => option.defaultSelected) ||
          field.options[0];
        return field.value !== (original?.value || "");
      }
      return field.value !== field.defaultValue;
    })
  );
}
async function reloadRecords({ background = false } = {}) {
  const response = await fetch("/api/official/state");
  if (!response.ok) throw Error("Refresh failed");
  const result = await response.json();
  // A draft may have started while the request was in flight. Leave the marker
  // unchanged so the next poll retries after the edit is saved or discarded.
  if (background && hasPendingMapEdits()) return false;
  const id = selected?.id;
  records = result.records;
  previousRecords = result.legacy || [];
  previousMappings = result.mappings || {};
  token = result.token;
  selected = records.find((r) => r.id === id) || null;
  setupFilters();
  search();
  if (selected) renderDetail();
  return true;
}
// Live floor plan: seating changed by the assistants' plan (or another window) reloads in place,
// in Admin and Demo alike. One small request a minute while the map is visible.
let seatingVersion = null;
function showLivePlan(plan) {
  const footer = document.getElementById("mapSource");
  if (!footer) return;
  const when = plan && new Date(plan.at);
  footer.textContent =
    plan && !Number.isNaN(when.getTime())
      ? `Live plan: ${plan.source} · updated ${when.toLocaleString([], { dateStyle: "short", timeStyle: "short" })}`
      : "Paris map · Europe-wide directory";
}
async function checkSeating() {
  if (document.hidden || hasPendingMapEdits()) return;
  try {
    const response = await fetch("/api/official/version", {
      cache: "no-store",
    });
    if (!response.ok) return;
    const current = await response.json();
    if (seatingVersion !== null && current.version !== seatingVersion) {
      if (!(await reloadRecords({ background: true }))) return;
      toast(
        current.live_plan
          ? `Seating updated from ${current.live_plan.source}`
          : "Seating updated",
      );
    }
    seatingVersion = current.version;
    showLivePlan(current.live_plan);
  } catch {}
}
async function watchSeating() {
  await checkSeating();
  setTimeout(watchSeating, 60000);
}
window.AtlasLivePlan = { check: checkSeating };
setTimeout(watchSeating, 1500);
function validRecord(r) {
  return (
    r &&
    typeof r.id === "string" &&
    /^(L[2-7]-[0-9]+|custom-[a-zA-Z0-9-]+|[0-9]{2}[A-Z][0-9]{6})$/.test(r.id) &&
    typeof r.name === "string" &&
    typeof r.team === "string" &&
    Number.isInteger(r.floor) &&
    r.floor >= -1 &&
    r.floor <= 8 &&
    Number.isFinite(r.x) &&
    Number.isFinite(r.y) &&
    r.x >= 0 &&
    r.x <= 1 &&
    r.y >= 0 &&
    r.y <= 1
  );
}
async function mutate(path, body) {
  if (readOnly) {
    toast("This shared Atlas is read only.");
    return false;
  }
  if (!databaseReady) {
    toast("Editing requires the Python app. This preview is read-only.");
    return false;
  }
  try {
    const response = await fetch("/api/" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Atlas-Token": token },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(result.error || result.detail || "Save failed");
    const id = selected?.id;
    records = (await (await fetch("/api/official/state")).json()).records;
    selected = records.find((r) => r.id === id) || null;
    setupFilters();
    search();
    if (selected) renderDetail();
    toast("Saved to shared database");
    return true;
  } catch (error) {
    toast(error.message);
    return false;
  }
}
async function saveRecord(r) {
  return mutate("save", { records: [r] });
}
const normalize = (s) =>
  String(s ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
function setupFilters() {
  const old = $("#team").value;
  $("#team").innerHTML =
    '<option value="all">All teams</option>' +
    [...new Set(records.map((r) => r.team))]
      .sort()
      .map((t) => `<option value="${esc(t)}">${esc(t)}</option>`)
      .join("");
  if ([...$("#team").options].some((o) => o.value === old))
    $("#team").value = old;
}
$("#scope").innerHTML += data.floors
  .map((f) => `<option value="${f.level}">Level ${f.level}</option>`)
  .join("");
setupFilters();
$(".floor-rail").innerHTML = [...data.floors]
  .reverse()
  .map(
    (f) =>
      `<button data-floor="${f.level}" title="Level ${f.level}: ${esc(f.title)}" aria-label="Level ${f.level}: ${esc(f.title)}">${f.label}</button>`,
  )
  .join("");
let indexedRecords = null,
  searchText = new Map();
function indexRecords() {
  if (indexedRecords === records) return;
  indexedRecords = records;
  searchText = new Map(
    records.map((r) => [
      r.id,
      normalize(
        [
          r.name,
          r.team,
          r.id,
          r.asset,
          r.hostname,
          r.outlet,
          r.notes,
          r.status,
        ].join(" "),
      ),
    ]),
  );
}
function search() {
  indexRecords();
  const words = normalize($("#search").value)
      .trim()
      .split(/\s+/)
      .filter(Boolean),
    scope = $("#scope").value,
    team = $("#team").value;
  lastMatches = records.filter(
    (r) =>
      (scope === "all" || r.floor === +scope) &&
      (team === "all" || r.team === team) &&
      words.every((w) => searchText.get(r.id).includes(w)),
  );
  const sorted = [...lastMatches].sort(
    (a, b) =>
      (a.floor !== floor) - (b.floor !== floor) || a.name.localeCompare(b.name),
  );
  $("#resultcount").textContent = `${sorted.length} locations`;
  $("#results").innerHTML = sorted.length
    ? sorted
        .map(
          (r) =>
            `<button class="result ${r.id === selected?.id ? "active" : ""}" data-record="${esc(r.id)}" title="${esc([r.name === "Unconfirmed desk" ? r.id : r.name, r.team].filter(Boolean).join(" · "))}" role="listitem"><span class="avatar">${
              r.kind === "area"
                ? "⌖"
                : esc(
                    r.name
                      .split(" ")
                      .filter(Boolean)
                      .slice(0, 2)
                      .map((s) => s[0])
                      .join(""),
                  )
            }</span><div><strong>${esc(r.name === "Unconfirmed desk" ? r.id : r.name)}</strong><small>${esc(r.team)}</small></div><span class="level">L${r.floor}</span></button>`,
        )
        .join("")
    : '<div class="no-results">No matching locations.<br>Try a surname, team or room number.</div>';
  draw();
}
function setFloor(n, reset = true) {
  const changed = floor !== n;
  stopFocus();
  cancelMapGesture();
  clearLocator();
  floor = n;
  const f = data.floors.find((x) => x.level === n);
  $("#floor-title").innerHTML = `Floor ${f.label}<span>${esc(f.title)}</span>`;
  $("#source-image").src = `official-floor-${n}.jpg`;
  $$("[data-floor]").forEach((b) => {
    b.classList.toggle("active", +b.dataset.floor === n);
    b.setAttribute("aria-current", +b.dataset.floor === n ? "true" : "false");
  });
  $("#floor-stats").textContent =
    `L${n}  /  ${records.filter((r) => r.floor === n).length} mapped locations`;
  if (reset) resetCam(false);
  search();
  if (changed) {
    revealMap();
    revealMap($("#floor-title"));
  }
}
function stopFocus() {
  cameraMotion.cancel();
}
// Canvas dimensions already exclude the desktop sidebars. Also leave room for
// the floor rail, map controls and any inspector overlapping a narrow map.
function mapArea() {
  const w = Math.max(1, canvas.clientWidth),
    h = Math.max(1, canvas.clientHeight);
  const rect = canvas.getBoundingClientRect();
  const detail = $("#detail.open")?.getBoundingClientRect();
  let right = w - Math.min(60, w * 0.12);
  if (
    detail?.width &&
    detail.left > rect.left + 180 &&
    detail.left < rect.right
  )
    right = Math.min(right, detail.left - rect.left - 18);
  return {
    left: Math.min(65, w * 0.15),
    right,
    top: Math.min(65, h * 0.15),
    bottom: h - Math.min(65, h * 0.15),
  };
}
function fitTarget() {
  const saved = cam,
    area = mapArea();
  const goal = {
    yaw: view === "plan" ? 0 : -0.14,
    tilt: view === "plan" ? Math.PI / 2 : 1,
    scale: 1,
    cx: 0,
    cz: 0,
  };
  cam = goal;
  const geometry = data.floors.find((f) => f.level === floor).geometry;
  const points = geometry.outline.flatMap((p) =>
    (view === "3d" ? [0, 4] : [0]).map((height) =>
      projected(modelPoint(...p, floor, height)),
    ),
  );
  const xs = points.map((p) => p[0]),
    ys = points.map((p) => p[1]);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const center = inversePoint((minX + maxX) / 2, (minY + maxY) / 2);
  goal.cx = center[0];
  goal.cz = center[1];
  goal.scale = Math.max(
    0.05,
    Math.min(
      16,
      (area.right - area.left) / Math.max(1, maxX - minX),
      (area.bottom - area.top) / Math.max(1, maxY - minY),
    ),
  );
  const desired = inversePoint(
    (area.left + area.right) / 2,
    (area.top + area.bottom) / 2,
  );
  goal.cx += goal.cx - desired[0];
  goal.cz += goal.cz - desired[1];
  cam = saved;
  return goal;
}
function focusTarget(r) {
  const saved = cam,
    area = mapArea(),
    fit = fitTarget();
  // Bring the selected desk closer while retaining enough surrounding desks for context.
  const goal = {
    ...fit,
    scale: Math.min(3.025, fit.scale * 2.2385),
    cx: world(r)[0],
    cz: world(r)[2],
  };
  cam = goal;
  const desired = inversePoint(
    (area.left + area.right) / 2,
    (area.top + area.bottom) / 2,
  );
  goal.cx += goal.cx - desired[0];
  goal.cz += goal.cz - desired[1];
  cam = saved;
  return goal;
}
function focusPerson(r) {
  stopFocus();
  floorFitted = false;
  cameraMotion.to(focusTarget(r), { duration: 420 });
  locateBeacon();
  draw();
}

function selectRecord(id) {
  const r = records.find((x) => x.id === id);
  if (!r) return;
  clearTimeout(searchTimer);
  stopFocus();
  selected = r;
  if (r.floor !== floor) setFloor(r.floor);
  if (view === "source" && ready) setView("plan");
  placing = false;
  $("#add").textContent = "＋ Add location";
  renderDetail();
  $("#detail").scrollTop = 0;
  AtlasUI.motion.slideUp($("#detail"));
  search();
  focusPerson(r);
}

function renderDetail() {
  window.dispatchEvent(new Event("atlas:selection"));
  if (!selected) return;
  const r = selected;
  $("#detail").classList.add("open");
  if (readOnly) {
    $("#detail").innerHTML =
      `<div class="record-head"><button id="close-detail" aria-label="Close inspector" style="float:right">×</button><span class="eyebrow">READ ONLY · L${r.floor}</span><h2>${esc(r.name === "Unconfirmed desk" ? r.id : r.name)}</h2><p>${esc(r.id)} · ${esc(r.team)}</p></div><dl class="viewer-fields">${[
        ["Occupancy", r.occupancy],
        ["Asset", r.asset],
        ["Hostname", r.hostname],
        ["Outlet", r.outlet],
        ["Notes", r.notes],
      ]
        .filter(([, v]) => v)
        .map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`)
        .join("")}</dl><div id="ops-context"></div>`;
    $("#close-detail").onclick = () => {
      $("#detail").classList.remove("open");
      selected = null;
      window.dispatchEvent(new Event("atlas:selection"));
      operations.clear();
      $("#detail").innerHTML =
        '<div class="empty-detail">Select a desk to inspect its record.</div>';
      search();
    };
    operations.select(r);
    return;
  }

  $("#detail").innerHTML =
    `<div class="record-head"><button id="close-detail" style="float:right" aria-label="Close inspector">×</button><span class="eyebrow">DESK REGISTER · L${r.floor}</span><h2>${esc(r.name === "Unconfirmed desk" ? r.id : r.name)}</h2><p>${esc(r.id)} · ${esc(r.team)}</p><span class="badge">${r.verified ? "User verified" : "Needs on-site verification"}</span></div>
 <details class="ops-desk-editor"><summary>Carry over previous seating</summary><p>Select a person from the previous register after checking this official desk number. Existing desk equipment stays in the previous record for review.</p><select id="previous-person"><option value="">Choose previous occupant…</option>${previousRecords
   .filter(
     (p) =>
       p.floor === r.floor &&
       p.occupancy !== "vacant" &&
       p.name !== "Unconfirmed desk" &&
       !previousMappings[p.id],
   )
   .map(
     (p) =>
       `<option value="${esc(p.id)}">${esc(p.name)} · ${esc(p.id)}</option>`,
   )
   .join(
     "",
   )}</select><button id="map-previous">Use this occupant at ${esc(r.id)}</button></details><div id="ops-panel"></div><details class="ops-desk-editor"><summary>Desk record & seating changes</summary><form id="record-form" class="record-body"><fieldset ${databaseReady ? "" : "disabled"} style="border:0;padding:0;margin:0;min-width:0">
 <label>Name / location<input name="name" maxlength="160" value="${esc(r.name)}"></label><label>Team<input name="team" maxlength="120" value="${esc(r.team)}"></label>
 <label>Occupancy<select name="occupancy">${["assigned", "vacant", "unconfirmed"].map((v) => `<option value="${v}" ${v === (r.occupancy || "unconfirmed") ? "selected" : ""}>${v}</option>`).join("")}</select></label>
 <label>Desk rotation (degrees)<input type="number" name="angle" step="1" min="0" max="359" value="${Math.round(r.angle || 0)}"></label>
 <label>Move status<select name="status">${["Not checked", "In progress", "Ready", "Issue"].map((v) => `<option ${v === (r.status || "Not checked") ? "selected" : ""}>${v}</option>`).join("")}</select></label>
 <div class="section-label">EQUIPMENT AT THIS DESK</div>
 ${[
   ["asset", "Asset tag"],
   ["hostname", "Hostname"],
   ["outlet", "Network outlet / port"],
 ]
   .map(
     ([k, label]) =>
       `<label>${label}<input name="${k}" maxlength="120" value="${esc(r[k])}"></label>`,
   )
   .join("")}
 <label>Desk / equipment notes<textarea name="notes" maxlength="4000">${esc(r.notes)}</textarea></label>
 <label class="verify"><input type="checkbox" name="verified" ${r.verified ? "checked" : ""}>I verified this record on site</label>
 <button class="primary" type="submit">Save to database</button><button id="reposition" type="button">Reposition desk</button>
 ${r.kind === "desk" ? '<button id="move-person" type="button">Move occupant…</button><button id="vacate" type="button">Leaver / mark vacant…</button>' : ""}</fieldset>
 <button id="history" type="button">View history</button><div id="history-list"></div>
 <small>${databaseReady ? "SQLite connected · edits survive restarts." : "Read-only preview · launch the Python app to edit."} Official desk codes; both views share the same desk identities and names. Occupants need on-site verification. Occupancy represents the seating register, not live presence.</small></form></details>`;
  $("#close-detail").onclick = () => {
    $("#detail").classList.remove("open");
    selected = null;
    window.dispatchEvent(new Event("atlas:selection"));
    operations.clear();
    $("#detail").innerHTML =
      '<div class="empty-detail">Select a desk to inspect its record.</div>';
    search();
  };
  $("#record-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = new FormData(e.target),
      next = { ...r };
    for (const k of [
      "name",
      "team",
      "asset",
      "hostname",
      "outlet",
      "notes",
      "status",
      "occupancy",
    ])
      next[k] = String(form.get(k) || "").trim();
    next.angle = Number(form.get("angle"));
    next.verified = form.has("verified");
    await saveRecord(next);
  };
  $("#reposition").onclick = () => {
    placing = "move";
    setView("plan");
    toast("Click the new desk position. Escape cancels.");
    $("#detail").style.visibility = "hidden";
  };
  if ($("#move-person")) $("#move-person").onclick = () => moveDialog(r);
  if ($("#vacate")) $("#vacate").onclick = () => vacateDesk(r);
  const historyHost = $("#history-list"),
    historyDeskId = r.id;
  let historyVersion = 0;
  const historyIsCurrent = () =>
    selected?.id === historyDeskId &&
    historyHost.isConnected &&
    $("#history-list") === historyHost;
  $("#history").onclick = async () => {
    if (!databaseReady) return toast("History is available in the Python app");
    const version = ++historyVersion;
    try {
      const response = await fetch(
        "/api/history/" + encodeURIComponent(historyDeskId),
      );
      if (!response.ok) throw Error("History unavailable");
      const result = await response.json();
      if (version !== historyVersion || !historyIsCurrent()) return;
      historyHost.innerHTML = result.history
        .map(
          (h) =>
            `<p><b>${esc(h.action)}</b><br>${esc(new Date(h.at).toLocaleString())}<br>${esc(h.before?.name || "—")} → ${esc(h.after.name)}<details><summary>Record changes</summary><pre style="white-space:pre-wrap">${esc(JSON.stringify({ before: h.before, after: h.after }, null, 2))}</pre></details></p>`,
        )
        .join("");
    } catch (e) {
      if (version === historyVersion && historyIsCurrent()) toast(e.message);
    }
  };
  $("#map-previous").onclick = async () => {
    const old = previousRecords.find(
      (p) => p.id === $("#previous-person").value,
    );
    if (!old) return toast("Select a previous occupant.");
    if (
      !confirm(
        `Record ${old.name} at official desk ${r.id}? This maps previous location ${old.id}; the old record and history are retained.`,
      )
    )
      return;
    try {
      const response = await fetch("/api/official/map-occupant", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Atlas-Token": token },
        body: JSON.stringify({
          source: old.id,
          target: r.id,
          sourceRevision: old.revision,
          targetRevision: r.revision,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.detail);
      const state = await (await fetch("/api/official/state")).json();
      records = state.records;
      previousRecords = state.legacy;
      previousMappings = state.mappings;
      setupFilters();
      selectRecord(r.id);
      toast("Previous occupant mapped to official desk.");
    } catch (e) {
      toast(e.message);
    }
  };
  operations.select(r);
}
function vacateDesk(r) {
  if (
    confirm(
      `Mark ${r.id} vacant and remove ${r.name} from this desk? Equipment and history are retained.`,
    )
  )
    mutate("vacate", { id: r.id, revision: r.revision });
}
function moveDialog(r) {
  if (!databaseReady) return toast("Launch the Python app to edit");
  const options = records.filter(
    (x) => x.kind === "desk" && x.occupancy === "vacant" && x.id !== r.id,
  );
  if (!options.length)
    return toast(
      "No confirmed vacant desks. Verify and mark a destination vacant first.",
    );
  const dialog = document.createElement("dialog");
  dialog.className = "move-dialog";
  dialog.innerHTML = `<form method="dialog"><h2>Move ${esc(r.name)}</h2><p>Equipment stays at each desk. Both seating records and their history update together.</p><label>Destination desk<select name="target">${options.map((x) => `<option value="${esc(x.id)}">Level ${x.floor} · ${esc(x.id)} · ${esc(x.team)}</option>`).join("")}</select></label><button value="cancel">Cancel</button><button class="primary" value="move">Confirm move</button></form>`;
  document.body.append(dialog);
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue === "move") {
      const target = records.find(
        (x) => x.id === dialog.querySelector("select").value,
      );
      if (
        target &&
        (await mutate("move", {
          source: r.id,
          target: target.id,
          sourceRevision: r.revision,
          targetRevision: target.revision,
        }))
      ) {
        selectRecord(target.id);
        $("#detail").classList.add("open");
      }
    }
    dialog.remove();
  });
  dialog.showModal();
}
$("#results").addEventListener("contextmenu", (e) => {
  const b = e.target.closest("[data-record]");
  if (b)
    deskMenu(
      e,
      records.find((r) => r.id === b.dataset.record),
    );
});
$("#results").onclick = (e) => {
  const b = e.target.closest("[data-record]");
  if (b) selectRecord(b.dataset.record);
};
let searchTimer;
$("#search").addEventListener("input", () => {
  search();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(locateMatches, 180);
});
$$("#scope,#team").forEach((e) =>
  e.addEventListener("change", () => {
    search();
    locateMatches();
  }),
);
$("#search").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && lastMatches.length) {
    e.preventDefault();
    selectRecord(lastMatches[0].id);
  }
});
function locateMatches() {
  stopFocus();
  if (!$("#search").value.trim() && $("#team").value === "all") return;
  if (!lastMatches.length) {
    selected = null;
    window.dispatchEvent(new Event("atlas:selection"));
    operations.clear();
    $("#detail").classList.remove("open");
    $("#detail").innerHTML =
      '<div class="empty-detail">No location selected.</div>';
    draw();
    return;
  }
  if (lastMatches.length === 1) {
    selectRecord(lastMatches[0].id);
    return;
  }
  selected = null;
  window.dispatchEvent(new Event("atlas:selection"));
  operations.clear();
  $("#detail").classList.remove("open");
  $("#detail").innerHTML =
    '<div class="empty-detail">Select a matching desk to see its user and machines.</div>';
  const groups = new Map();
  for (const r of lastMatches)
    groups.set(r.floor, (groups.get(r.floor) || 0) + 1);
  const target = [...groups].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
  if (floor !== target) setFloor(target);
  if (view === "source" && ready) setView("plan");
  const points = lastMatches.filter((r) => r.floor === floor).map(world),
    xs = points.map((p) => p[0]),
    zs = points.map((p) => p[2]);
  const goal = { ...cam };
  goal.cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  goal.cz = (Math.min(...zs) + Math.max(...zs)) / 2;
  goal.scale = Math.min(
    4,
    Math.max(
      1,
      65 /
        Math.max(
          16,
          Math.max(...xs) - Math.min(...xs),
          Math.max(...zs) - Math.min(...zs),
        ),
    ),
  );
  cameraMotion.to(goal, { duration: 620, panoramic: true });
}

$(".floor-rail").onclick = (e) => {
  const b = e.target.closest("[data-floor]");
  if (b) setFloor(+b.dataset.floor);
};
$("#clear").onclick = () => {
  $("#search").value = "";
  $("#scope").value = "all";
  $("#team").value = "all";
  search();
};
function setView(v, animate = false) {
  if (v !== "plan" && v !== "3d") v = "plan";
  stopFocus();
  cancelMapGesture();
  if (v === "3d") init3d();
  if (v === "3d" && !glReady) {
    toast(
      `3D could not start: ${glError || "WebGL is unavailable in this browser session"}. Using 2D; switch on 3D to retry.`,
    );
    v = "plan";
  }
  if (v === "plan" && !ctx2d) {
    $("#webgl-error").hidden = false;
    return;
  }
  const changed = view !== v;
  view = v;
  canvas = v === "plan" ? planCanvas : glCanvas;
  mapCursor.reset();
  mapCursor.set(canvas, placing ? "place" : "default");
  applyNameVisibility();
  $("#source").hidden = true;
  glCanvas.hidden = v !== "3d";
  planCanvas.hidden = v !== "plan";
  $("#three-d-toggle").checked = v === "3d";
  const goal = {
    ...cam,
    yaw: v === "plan" ? 0 : -0.14,
    tilt: v === "plan" ? Math.PI / 2 : 1,
  };
  if (floorFitted) Object.assign(goal, fitTarget());
  if (animate && changed) {
    revealMap();
    if (v === "3d") cameraMotion.to(goal, { duration: 480, kind: "view" });
    else cam = goal;
  } else cam = goal;
  draw();
}

$("#three-d-toggle").onchange = (e) =>
  setView(e.target.checked ? "3d" : "plan", true);
function resetCam(animate = true) {
  stopFocus();
  cancelMapGesture();
  clearLocator();
  floorFitted = true;
  const goal = fitTarget();
  if (animate) cameraMotion.to(goal, { duration: 550, kind: "reset" });
  else cam = goal;
  draw();
}
$("#reset").onclick = () => resetCam();
function zoomCamera(factor, anchor) {
  floorFitted = false;
  const goal = cameraMotion.destination("zoom");
  goal.scale = Math.max(0.05, Math.min(16, goal.scale * factor));
  if (anchor) {
    const saved = cam;
    const before = inversePoint(...anchor);
    cam = goal;
    const after = inversePoint(...anchor);
    goal.cx += before[0] - after[0];
    goal.cz += before[1] - after[1];
    cam = saved;
  }
  cameraMotion.to(goal, { duration: 200, kind: "zoom" });
}
$("#zoom-in").onclick = () => zoomCamera(1.25);
$("#zoom-out").onclick = () => zoomCamera(1 / 1.25);
$("#rotate").onclick = () => {
  floorFitted = false;
  const goal = cameraMotion.destination("rotate");
  goal.yaw += Math.PI / 8;
  cameraMotion.to(goal, { duration: 340, kind: "rotate" });
};
$("#add").onclick = () => {
  if (!databaseReady) return toast("Launch the Python app to add desks");
  placing = placing ? false : "new";
  mapCursor.set(canvas, placing ? "place" : "default");
  $("#add").textContent = placing ? "Cancel placement" : "＋ Add location";
  if (placing) {
    setView("plan");
    toast("Click a location on the plan. Press Escape to cancel.");
  }
};
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    placing = false;
    mapCursor.reset();
    $("#detail").style.visibility = "";
    $("#add").textContent = "＋ Add location";
  }
  if (
    e.key === "/" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  ) {
    e.preventDefault();
    $("#search").focus();
  }
});
$("#export").onclick = () => {
  const blob = new Blob(
    [
      JSON.stringify(
        {
          schema: "barclays-office-atlas-v1",
          exportedAt: new Date().toISOString(),
          records,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "office-atlas-records.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast("Records exported");
};
$("#import").onclick = () => {
  if (!databaseReady) return toast("Launch the Python app to import");
  $("#file").click();
};
$("#file").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    if (f.size > 5e6) throw Error("File exceeds 5 MB");
    const d = JSON.parse(await f.text());
    if (
      d.schema !== "barclays-office-atlas-v1" ||
      !Array.isArray(d.records) ||
      !d.records.every(validRecord)
    )
      throw Error("Invalid Office Atlas export");
    if (
      confirm(
        `Import ${d.records.length} records? Matching desk IDs will be updated. Download a database backup first if needed.`,
      )
    ) {
      await mutate("save", {
        records: d.records.map((r) => ({
          ...r,
          revision: records.find((x) => x.id === r.id)?.revision || 0,
        })),
      });
    }
  } catch (err) {
    toast(err.message);
  }
  e.target.value = "";
};
const storageBadge = document.createElement("div");
storageBadge.className = "storage-status";
storageBadge.textContent = readOnly
  ? "● Shared read-only viewer · live database"
  : databaseReady
    ? "● SQLite connected · right-click a desk to manage"
    : "Read-only preview · use Python app for persistent editing";
document.querySelector(".directory-foot").prepend(storageBadge);
const backup = document.createElement("button");
backup.textContent = "Back up .db";
backup.onclick = () => {
  if (databaseReady) window.location.href = "/api/backup";
  else toast("Launch the Python app to back up its database");
};
if (!readOnly) document.querySelector("#atlasMoreActions").append(backup);
const refresh = document.createElement("button");
refresh.textContent = "Refresh";
refresh.title = "Refresh records";
refresh.setAttribute("aria-label", "Refresh records");
refresh.onclick = () => window.location.reload();
document.querySelector(".header-right").append(refresh);
// Self-contained WebGL renderer: orthographic 3D plan, raised desk markers and traced perimeter walls.
const glCanvas = $("#canvas"),
  planCanvas = document.createElement("canvas");
planCanvas.id = "plan-canvas";
planCanvas.setAttribute(
  "aria-label",
  "Interactive office plan. Select a name from the directory for keyboard access.",
);
glCanvas.after(planCanvas);
let canvas = planCanvas;
const mapCursor = installMapCursor({
  viewport: $("#viewport"),
  canvases: [glCanvas, planCanvas],
});
let drag = null,
  pinchDistance = 0,
  draggedContext = false;
const pointers = new Map();
const ctx2d = planCanvas.getContext("2d");
let gl = null,
  program,
  loc = {},
  ready = !!ctx2d,
  glReady = false,
  glError = "",
  screenRecords = [];
const gpuGeometryCache = new Map();
function onMap(type, handler, options) {
  for (const element of [glCanvas, planCanvas])
    element.addEventListener(type, handler, options);
}

const dot = (a, b) => a.reduce((s, n, i) => s + n * b[i], 0),
  sub = (a, b) => a.map((n, i) => n - b[i]);

// World coordinates: x east, y height, z toward the page bottom. Up vector points toward page top.
function getBasis() {
  const cy = Math.cos(cam.yaw),
    sy = Math.sin(cam.yaw),
    st = Math.sin(cam.tilt),
    ct = Math.cos(cam.tilt);
  return {
    right: [cy, 0, -sy],
    up: [-sy * st, ct, -cy * st],
    forward: [sy * ct, st, cy * ct],
  };
}
function projected(p) {
  const b = getBasis(),
    v = sub(p, [cam.cx, 0, cam.cz]),
    unit =
      Math.min(canvas.clientWidth / 112, canvas.clientHeight / 78) * cam.scale;
  return [
    canvas.clientWidth / 2 + dot(v, b.right) * unit,
    canvas.clientHeight / 2 - dot(v, b.up) * unit,
    dot(v, b.forward),
  ];
}
function inversePoint(px, py) {
  const b = getBasis(),
    unit =
      Math.min(canvas.clientWidth / 112, canvas.clientHeight / 78) * cam.scale;
  const u = (px - canvas.clientWidth / 2) / unit,
    v = -(py - canvas.clientHeight / 2) / unit,
    det = b.right[0] * b.up[2] - b.right[2] * b.up[0];
  return [
    cam.cx + (u * b.up[2] - v * b.right[2]) / det,
    cam.cz + (v * b.right[0] - u * b.up[0]) / det,
  ];
}
function modelPoint(x, y, level = floor, height = 0) {
  const f = data.floors.find((f) => f.level === level);
  return [
    x / 18 - 50,
    height,
    (y + f.geometry.shear * (x - 900)) / 18 - f.height / 36,
  ];
}
function sourcePoint(p, level = floor) {
  const f = data.floors.find((f) => f.level === level),
    x = (p[0] + 50) * 18;
  return [
    x / 1800,
    (p[1] * 18 + f.height / 2 - f.geometry.shear * (x - 900)) / 1800,
  ];
}
function world(r) {
  return modelPoint(r.x * 1800, r.y * 1800, r.floor, 1.1);
}
let deskAngleRecords = null,
  inferredDeskAngles = new Map();
function deskLayoutAngle(r) {
  const saved = Number(r.angle) || 0;
  if (saved) return saved;
  if (deskAngleRecords !== records) {
    deskAngleRecords = records;
    inferredDeskAngles = new Map();
    const floors = new Map();
    for (const desk of records)
      if (desk.kind === "desk") {
        if (!floors.has(desk.floor)) floors.set(desk.floor, []);
        floors.get(desk.floor).push({ desk, point: world(desk) });
      }
    for (const desks of floors.values())
      for (const current of desks) {
        let nearest = null;
        for (const candidate of desks) {
          if (candidate === current) continue;
          const dx = candidate.point[0] - current.point[0],
            dz = candidate.point[2] - current.point[2],
            distance = Math.hypot(dx, dz);
          if (
            distance > 0.1 &&
            distance <= 4.5 &&
            (!nearest || distance < nearest.distance)
          )
            nearest = { dx, dz, distance };
        }
        if (nearest)
          inferredDeskAngles.set(
            current.desk.id,
            ((Math.atan2(nearest.dz, nearest.dx) * 180) / Math.PI + 180) % 180,
          );
      }
  }
  return inferredDeskAngles.get(r.id) || 0;
}
function init3d() {
  if (glReady) return;
  glError = "";
  const shaders = [];
  try {
    gl = glCanvas.getContext("webgl", { antialias: false, alpha: true });
    if (!gl) throw Error(glError || "WebGL context creation failed");
    const shader = (type, source) => {
      const s = gl.createShader(type);
      if (!s)
        throw Error("Shader allocation failed; graphics context may be lost");
      shaders.push(s);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw Error(gl.getShaderInfoLog(s));
      return s;
    };
    program = gl.createProgram();
    gl.attachShader(
      program,
      shader(
        gl.VERTEX_SHADER,
        "attribute vec3 position; attribute vec4 color; uniform vec3 right; uniform vec3 up; uniform vec3 forward; uniform vec3 center; uniform vec2 scale; varying vec4 vColor; void main(){vec3 p=position-center;gl_Position=vec4(dot(p,right)*scale.x,dot(p,up)*scale.y,-dot(p,forward)/200.0,1.0);vColor=color;}",
      ),
    );
    gl.attachShader(
      program,
      shader(
        gl.FRAGMENT_SHADER,
        "precision mediump float; varying vec4 vColor; void main(){gl_FragColor=vColor;}",
      ),
    );
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS))
      throw Error(
        gl.getProgramInfoLog(program) || "Shader program could not link",
      );
    gl.useProgram(program);
    for (const n of ["right", "up", "forward", "center", "scale"])
      loc[n] = gl.getUniformLocation(program, n);
    for (const n of ["position", "color"])
      loc[n] = gl.getAttribLocation(program, n);
    loc.buffer = gl.createBuffer();
    if (!loc.buffer) throw Error("3D buffer allocation failed");
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    glReady = true;
  } catch (error) {
    glError = String(error.message || error).slice(0, 240);
    glReady = false;
    if (program && gl) gl.deleteProgram(program);
    if (loc.buffer && gl) gl.deleteBuffer(loc.buffer);
    program = null;
    loc = {};
  } finally {
    for (const shader of shaders) gl.deleteShader(shader);
  }
  ready = glReady || !!ctx2d;
}
glCanvas.addEventListener("webglcontextcreationerror", (event) => {
  glError = (event.statusMessage || "WebGL context creation failed").slice(
    0,
    240,
  );
});
glCanvas.addEventListener("webglcontextlost", (event) => {
  event.preventDefault();
  glReady = false;
  glError = "Graphics context was lost";
  gpuGeometryCache.clear();
  program = null;
  loc = {};
  if (view === "3d") {
    setView("plan");
    toast(
      "3D graphics connection lost. Using 2D; switch on 3D to retry after recovery.",
    );
  }
});
glCanvas.addEventListener("webglcontextrestored", () => {
  glReady = false;
  glError = "";
  gpuGeometryCache.clear();
});
if (!ctx2d) init3d();
if (!ready) {
  $("#webgl-error").hidden = false;
  setView("source");
}
function mesh(vertices, cacheKey = null) {
  let buffer = cacheKey ? gpuGeometryCache.get(cacheKey) : null;
  if (buffer) gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  else {
    buffer = cacheKey ? gl.createBuffer() : loc.buffer;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array(vertices),
      cacheKey ? gl.STATIC_DRAW : gl.DYNAMIC_DRAW,
    );
    if (cacheKey) {
      gpuGeometryCache.set(cacheKey, buffer);
      if (gpuGeometryCache.size > 3) {
        const first = gpuGeometryCache.keys().next().value;
        gl.deleteBuffer(gpuGeometryCache.get(first));
        gpuGeometryCache.delete(first);
      }
    }
  }
  for (const [name, size, offset] of [
    ["position", 3, 0],
    ["color", 4, 20],
  ]) {
    gl.enableVertexAttribArray(loc[name]);
    gl.vertexAttribPointer(loc[name], size, gl.FLOAT, false, 36, offset);
  }
  gl.drawArrays(gl.TRIANGLES, 0, vertices.length / 9);
}
function quad(
  arr,
  p,
  color,
  uvs = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ],
) {
  for (const i of [0, 1, 2, 0, 2, 3]) arr.push(...p[i], ...uvs[i], ...color);
}
function box(arr, x, y, z, w, h, d, c) {
  const X = x + w / 2,
    A = x - w / 2,
    Z = z + d / 2,
    B = z - d / 2,
    Y = y + h;
  quad(
    arr,
    [
      [A, Y, B],
      [X, Y, B],
      [X, Y, Z],
      [A, Y, Z],
    ],
    c,
  );
  quad(
    arr,
    [
      [A, y, B],
      [X, y, B],
      [X, Y, B],
      [A, Y, B],
    ],
    c.map((v, i) => (i < 3 ? v * 0.72 : v)),
  );
  quad(
    arr,
    [
      [X, y, B],
      [X, y, Z],
      [X, Y, Z],
      [X, Y, B],
    ],
    c.map((v, i) => (i < 3 ? v * 0.83 : v)),
  );
  quad(
    arr,
    [
      [X, y, Z],
      [A, y, Z],
      [A, Y, Z],
      [X, Y, Z],
    ],
    c.map((v, i) => (i < 3 ? v * 0.8 : v)),
  );
  quad(
    arr,
    [
      [A, y, Z],
      [A, y, B],
      [A, Y, B],
      [A, Y, Z],
    ],
    c.map((v, i) => (i < 3 ? v * 0.72 : v)),
  );
}
function orientedBox(arr, x, y, z, w, h, d, c, degrees = 0) {
  if (!degrees) return box(arr, x, y, z, w, h, d, c);
  const angle = (degrees * Math.PI) / 180,
    cosine = Math.cos(angle),
    sine = Math.sin(angle),
    point = (dx, height, dz) => [
      x + dx * cosine - dz * sine,
      height,
      z + dx * sine + dz * cosine,
    ],
    bottom = [
      point(-w / 2, y, -d / 2),
      point(w / 2, y, -d / 2),
      point(w / 2, y, d / 2),
      point(-w / 2, y, d / 2),
    ],
    top = bottom.map(([px, , pz]) => [px, y + h, pz]);
  quad(arr, top, c);
  for (let i = 0; i < 4; i++)
    quad(
      arr,
      [bottom[i], bottom[(i + 1) % 4], top[(i + 1) % 4], top[i]],
      c.map((value, channel) =>
        channel < 3 ? value * (i % 2 ? 0.83 : 0.72) : value,
      ),
    );
}
const geometryCache = new Map();
function triangulate(points) {
  const ids = points.map((_, i) => i),
    out = [];
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i],
      b = points[(i + 1) % points.length];
    area += a[0] * b[1] - b[0] * a[1];
  }
  if (area < 0) ids.reverse();
  const cross = (a, b, c) =>
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  while (ids.length > 3) {
    let found = false;
    for (let i = 0; i < ids.length; i++) {
      const a = ids[(i + ids.length - 1) % ids.length],
        b = ids[i],
        c = ids[(i + 1) % ids.length];
      if (cross(points[a], points[b], points[c]) <= 1e-8) continue;
      if (
        ids.some(
          (k) =>
            k !== a &&
            k !== b &&
            k !== c &&
            cross(points[a], points[b], points[k]) >= -1e-8 &&
            cross(points[b], points[c], points[k]) >= -1e-8 &&
            cross(points[c], points[a], points[k]) >= -1e-8,
        )
      )
        continue;
      out.push([a, b, c]);
      ids.splice(i, 1);
      found = true;
      break;
    }
    if (!found) throw Error("Invalid floor polygon");
  }
  if (ids.length === 3) out.push([...ids]);
  return out;
}
function polygonMesh(arr, points, height, color) {
  const p = points.map((p) => modelPoint(p[0], p[1], floor, height));
  for (const tri of triangulate(points))
    for (const i of tri) arr.push(...p[i], 0, 0, ...color);
}
function beam(arr, a, b, width, height, color, bottom = 0) {
  const dx = b[0] - a[0],
    dz = b[2] - a[2],
    len = Math.hypot(dx, dz);
  if (len < 0.001) return;
  const nx = ((-dz / len) * width) / 2,
    nz = ((dx / len) * width) / 2;
  const corners = [
    [a[0] + nx, bottom, a[2] + nz],
    [b[0] + nx, bottom, b[2] + nz],
    [b[0] - nx, bottom, b[2] - nz],
    [a[0] - nx, bottom, a[2] - nz],
  ];
  quad(
    arr,
    corners.map((p) => [p[0], bottom + height, p[2]]),
    color,
  );
  for (let i = 0; i < 4; i++) {
    const p = corners[i],
      q = corners[(i + 1) % 4];
    quad(
      arr,
      [p, q, [q[0], bottom + height, q[2]], [p[0], bottom + height, p[2]]],
      color.map((v, j) => (j < 3 ? v * (i % 2 ? 0.86 : 0.75) : v)),
    );
  }
}

// Recover the hinge from the endpoint normals of each source quarter-circle swing.
function doorGeometry(curve) {
  const [a, b, c, d] = curve.map((p) => modelPoint(...p)),
    n = [-(b[2] - a[2]), b[0] - a[0]],
    m = [-(d[2] - c[2]), d[0] - c[0]],
    det = n[0] * m[1] - n[1] * m[0];
  if (Math.abs(det) < 1e-8) return null;
  const t = ((d[0] - a[0]) * m[1] - (d[2] - a[2]) * m[0]) / det,
    h = [a[0] + t * n[0], 0, a[2] + t * n[1]],
    r = Math.hypot(h[0] - a[0], h[2] - a[2]),
    r2 = Math.hypot(h[0] - d[0], h[2] - d[2]);
  if (!Number.isFinite(r) || r < 0.25 || r > 4 || Math.abs(r - r2) > r * 0.12)
    return null;
  return { hinge: h, leaf: a, jamb: d };
}
function raisedDoor(arr, curve) {
  const door = doorGeometry(curve);
  if (!door) return;
  const { hinge: h, leaf: a, jamb: d } = door;
  // Open leaf and frame; the angle illustrates the source swing, not live door state.
  beam(arr, h, a, 0.11, 2.05, [0.76, 0.43, 0.16, 1], 0.04);
  for (const p of [h, d])
    box(arr, p[0], 0, p[2], 0.15, 2.22, 0.15, [0.35, 0.25, 0.17, 1]);
  beam(arr, h, d, 0.15, 0.13, [0.35, 0.25, 0.17, 1], 2.09);
  const x = h[0] + (a[0] - h[0]) * 0.84,
    z = h[2] + (a[2] - h[2]) * 0.84;
  box(arr, x, 0.98, z, 0.18, 0.07, 0.18, [0.88, 0.91, 0.93, 1]);
}
function architecturalMesh() {
  const key =
    floor +
    ":" +
    view +
    ":" +
    mapLayers.doors +
    ":" +
    mapLayers.facilities +
    ":" +
    mapLayers.walls;
  if (geometryCache.has(key)) return geometryCache.get(key);
  const arr = [],
    g = data.floors.find((f) => f.level === floor).geometry;
  polygonMesh(
    arr,
    g.outline.map((p) => [p[0] + 8, p[1] + 12]),
    -0.65,
    [0.3, 0.4, 0.48, 0.16],
  );
  polygonMesh(arr, g.outline, 0, [0.9, 0.94, 0.96, 1]);
  for (let i = 0; i < g.outline.length; i++)
    beam(
      arr,
      modelPoint(...g.outline[i]),
      modelPoint(...g.outline[(i + 1) % g.outline.length]),
      0.2,
      0.45,
      [0.66, 0.77, 0.83, 1],
      -0.45,
    );
  // Keep the full source vector plan underneath the raised architecture in 3D.
  for (const [a, b] of g.planLinework || []) {
    const p = modelPoint(...a),
      q = modelPoint(...b),
      dx = q[0] - p[0],
      dz = q[2] - p[2],
      len = Math.hypot(dx, dz);
    if (len < 0.001) continue;
    const nx = (-dz / len) * 0.018,
      nz = (dx / len) * 0.018;
    quad(
      arr,
      [
        [p[0] + nx, 0.012, p[2] + nz],
        [q[0] + nx, 0.012, q[2] + nz],
        [q[0] - nx, 0.012, q[2] - nz],
        [p[0] - nx, 0.012, p[2] - nz],
      ],
      [0.44, 0.53, 0.59, 1],
    );
  }
  for (const [a, b] of g.walls || [])
    if (mapLayers.walls)
      beam(
        arr,
        modelPoint(...a),
        modelPoint(...b),
        0.075,
        2.4,
        [0.38, 0.48, 0.55, 1],
      );
  if (mapLayers.walls) {
    const p = g.buildingPerimeter || [];
    for (let i = 0; i < p.length; i++)
      beam(
        arr,
        modelPoint(...p[i]),
        modelPoint(...p[(i + 1) % p.length]),
        0.3,
        2.8,
        [0.03, 0.35, 0.52, 1],
      );
  }
  if (mapLayers.doors)
    for (const curve of g.doorSwings || []) {
      raisedDoor(arr, curve);
      const points = doorPoints(curve);
      for (let i = 1; i < points.length; i++)
        beam(
          arr,
          points[i - 1],
          points[i],
          0.1,
          0.04,
          [0.7, 0.33, 0.04, 1],
          0.03,
        );
    }
  for (const r of g.wayfinding || [])
    if (facilityVisible(r)) {
      // Keep the source stair treads visible beneath the amenity outline.
      if (r.kind !== "stairs")
        polygonMesh(arr, r.points, 0.025, mapColors[r.kind]);
      if (r.kind === "lift" || r.kind === "stairs")
        for (let i = 0; i < r.points.length; i++)
          beam(
            arr,
            modelPoint(...r.points[i]),
            modelPoint(...r.points[(i + 1) % r.points.length]),
            0.12,
            0.035,
            [0, 0.52, 0.71, 1],
            0.03,
          );
    }
  const furniture = [
    ...[...(g.tables || []), ...(g.curvedTables || [])].map((points) => ({
      points,
      height: 0.84,
    })),
    ...(g.chairSeats || []).map((points) => ({ points, height: 0.44 })),
    ...(g.counters || []).map((points) => ({ points, height: 1, solid: true })),
    ...(g.kitchenTables || []).map((points) => ({ points, height: 0.84 })),
    ...(g.kitchenSeats || []).map((points) => ({ points, height: 0.44 })),
    ...(g.kitchenCounters || []).map((points) => ({
      points,
      height: 1,
      solid: true,
    })),
    ...(g.cupboards || []).map((points) => ({
      points,
      height: 1.35,
      solid: true,
      color: [0.79, 0.85, 0.89, 1],
    })),
    ...(g.printers || []).map((points) => ({
      points,
      height: 1.0,
      solid: true,
      color: [0.88, 0.92, 0.94, 1],
    })),
  ];
  for (const {
    points,
    height,
    solid,
    color = [0.67, 0.82, 0.89, 1],
  } of furniture) {
    polygonMesh(arr, points, height, color);
    for (let i = 0; i < points.length; i++)
      beam(
        arr,
        modelPoint(...points[i]),
        modelPoint(...points[(i + 1) % points.length]),
        0.035,
        solid ? height - 0.06 : 0.17,
        [0.43, 0.6, 0.69, 1],
        solid ? 0.06 : height - 0.17,
      );
    if (solid) continue;
    const center = points.reduce(
        (a, p) => [a[0] + p[0] / points.length, a[1] + p[1] / points.length],
        [0, 0],
      ),
      p = modelPoint(...center);
    box(
      arr,
      p[0],
      0.05,
      p[2],
      0.12,
      height - 0.22,
      0.12,
      [0.34, 0.45, 0.52, 1],
    );
  }
  // A dark scanner lid distinguishes the printer from the taller cupboards.
  for (const points of g.printers || []) {
    const center = points.reduce(
      (a, p) => [a[0] + p[0] / points.length, a[1] + p[1] / points.length],
      [0, 0],
    );
    const lid = points.map((p) =>
      p.map((v, i) => center[i] + (v - center[i]) * 0.76),
    );
    polygonMesh(arr, lid, 1.04, [0.28, 0.39, 0.45, 1]);
  }
  for (const points of g.kitchenSinks || [])
    polygonMesh(arr, points, 1.015, [0.93, 0.98, 1, 1]);
  geometryCache.set(key, arr);
  if (geometryCache.size > 3)
    geometryCache.delete(geometryCache.keys().next().value);
  return arr;
}

// Coalesce pointer events; reuse desk markers until scene data changes.
let lastDrawTime = -Infinity;
let pendingDraw = 0,
  deskSceneKey = "",
  deskSceneRecords = null,
  deskVertices = [];
window.addEventListener("atlas-display-change", () => {
  lastDrawTime = -Infinity;
  draw();
});
function draw() {
  if (!ready || pendingDraw || document.hidden) return;
  pendingDraw = requestAnimationFrame((time) => {
    pendingDraw = 0;
    if (document.hidden) return;
    // Coalesce changes into at most 30 rendered frames/s in remote mode.
    if (
      AtlasUI.performance.isCitrix() &&
      time - lastDrawTime < 1000 / 30 - 0.01
    ) {
      draw();
      return;
    }
    lastDrawTime = time;
    cameraMotion.step(time);
    renderFrame();
    positionLocator();
    if (cameraMotion.active) draw();
  });
}
function renderFrame() {
  if (!ready || view === "source") return;
  const started = performance.now();
  metrics.labelsMs = 0;
  trackMotion();
  if (view === "plan") {
    renderPlan();
    finishFrame(started);
    return;
  }
  const dpr = AtlasUI.performance.isCitrix() && moving ? 0.75 : 1,
    w = canvas.clientWidth,
    h = canvas.clientHeight;
  if (!w || !h) return;
  if (
    canvas.width !== Math.round(w * dpr) ||
    canvas.height !== Math.round(h * dpr)
  ) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.useProgram(program);
  const b = getBasis(),
    unit = Math.min(w / 112, h / 78) * cam.scale;
  gl.uniform3fv(loc.right, b.right);
  gl.uniform3fv(loc.up, b.up);
  gl.uniform3fv(loc.forward, b.forward);
  gl.uniform3fv(loc.center, [cam.cx, 0, cam.cz]);
  gl.uniform2f(loc.scale, (2 * unit) / w, (2 * unit) / h);
  mesh(architecturalMesh(), floor + ":" + view + JSON.stringify(mapLayers));
  const matches = new Set(lastMatches.map((r) => r.id)),
    filtering =
      $("#search").value ||
      $("#team").value !== "all" ||
      $("#scope").value !== "all";
  const sceneKey = JSON.stringify([
    floor,
    view,
    selected?.id,
    !!filtering,
    filtering ? [...matches] : [],
  ]);
  const changed = deskSceneRecords !== records || deskSceneKey !== sceneKey;
  const floorRecords = records.filter((r) => r.floor === floor);
  if (changed) {
    const verts = [];
    for (const r of floorRecords) {
      const p = world(r),
        isSelected = selected?.id === r.id;
      if (r.occupancy === "assigned")
        box(
          verts,
          p[0],
          0.88,
          p[2],
          0.22,
          0.08,
          0.22,
          isSelected ? [1, 0.55, 0.15, 1] : [0, 0.48, 0.65, 1],
        );
      if (isSelected) {
        orientedBox(
          verts,
          p[0],
          0.03,
          p[2],
          3.0,
          0.05,
          2.1,
          [1, 0.56, 0.12, 1],
          deskLayoutAngle(r),
        );
        box(verts, p[0], 0.1, p[2], 0.1, 3.3, 0.1, [1, 0.5, 0.08, 1]);
      }
    }
    const previous = gpuGeometryCache.get("desks");
    if (previous) {
      gl.deleteBuffer(previous);
      gpuGeometryCache.delete("desks");
    }
    deskVertices = verts;
    deskSceneRecords = records;
    deskSceneKey = sceneKey;
  }
  // Project pick targets each frame, including desks brought into view by panning.
  screenRecords = [];
  for (const r of floorRecords) {
    if (filtering && !matches.has(r.id)) continue;
    const p = world(r),
      screen = projected([p[0], view === "3d" ? 1.95 : 0.2, p[2]]);
    if (
      r.id === selected?.id ||
      (screen[0] >= -200 &&
        screen[0] <= w + 200 &&
        screen[1] >= -200 &&
        screen[1] <= h + 200)
    )
      screenRecords.push({ r, p: screen });
  }
  mesh(deskVertices, "desks");
  renderNames();
  finishFrame(started);
}

// Reuse label/connector nodes by desk ID; only their text and coordinates change.
const labelNodes = new Map();
let bannerKey = "",
  labelScene = "",
  labelRecords = null;
function labelNode(id, room = false) {
  if (labelNodes.has(id)) return labelNodes.get(id);
  const el = document.createElement(room ? "span" : "button");
  el.className = room ? "room-label" : "map-name";
  let line = null,
    circle = null;
  if (!room) {
    el.dataset.person = id;
    const title = document.createElement("strong"),
      sub = document.createElement("span");
    el.append(title, sub);
    line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    $("#label-lines").append(line, circle);
  }
  $("#map-labels").append(el);
  const item = { el, line, circle };
  labelNodes.set(id, item);
  return item;
}
const orbitHint =
  "Left-drag to move · Right-drag to rotate / tilt · Scroll to zoom";
const labelZoomSteps = [1.35, 1.85, 2.7, 4];
let labelZoomScene = "",
  labelFitScale = 1,
  labelZoomLevel = 0;
function labelPolicy(w, h) {
  const scene = `${floor}:${view}:${w}:${h}`;
  if (scene !== labelZoomScene) {
    labelZoomScene = scene;
    labelFitScale = fitTarget().scale;
    labelZoomLevel = labelZoomSteps.filter(
      (step) => cam.scale / labelFitScale >= step,
    ).length;
  }
  const zoom = cam.scale / labelFitScale;
  // A small dead band prevents tags flickering at a zoom threshold.
  while (labelZoomLevel < 4 && zoom >= labelZoomSteps[labelZoomLevel] + 0.06)
    labelZoomLevel++;
  while (labelZoomLevel > 0 && zoom < labelZoomSteps[labelZoomLevel - 1] - 0.06)
    labelZoomLevel--;
  const area = Math.max(0.4, Math.min(1.5, (w * h) / 650000));
  return {
    level: labelZoomLevel,
    names: Math.max(
      16,
      Math.round([32, 44, 60, 84, 112][labelZoomLevel] * area),
    ),
    amenities: Math.max(
      1,
      Math.round([4, 6, 8, 12, 14][labelZoomLevel] * area),
    ),
  };
}
function labelBounds(w, h) {
  return {
    left: Math.min(65, w * 0.15),
    right: w - 12,
    top: 60,
    bottom: h - 48,
  };
}
function labelsOverlap(a, b, gap = 8) {
  return (
    a.x < b.x + b.w + gap &&
    a.x + a.w + gap > b.x &&
    a.y < b.y + b.h + gap &&
    a.y + a.h + gap > b.y
  );
}
function labelFits(rect, bounds, occupied, gap = 8) {
  return (
    rect.x >= bounds.left &&
    rect.x + rect.w <= bounds.right &&
    rect.y >= bounds.top &&
    rect.y + rect.h <= bounds.bottom &&
    !occupied.some((other) => labelsOverlap(rect, other, gap))
  );
}
function selectedLabelSpot(p, w, h) {
  const bounds = labelBounds(w, h),
    wide = Math.min(210, bounds.right - bounds.left);
  return {
    x: Math.max(bounds.left, Math.min(bounds.right - wide, p[0] - wide / 2)),
    y: Math.max(bounds.top, Math.min(bounds.bottom - 54, p[1] - 68)),
    w: wide,
    h: 54,
  };
}
function nameLabelSize(name, viewportWidth, boundsWidth, active = false) {
  if (active) return { width: Math.min(210, boundsWidth), height: 54 };
  // Leave enough room for real glyph widths. The earlier character-count shortcut
  // could make a two-word name wrap while still assigning it a one-line box.
  const textWidth = name.length * 7.2,
    width = Math.min(
      boundsWidth,
      Math.min(viewportWidth < 640 ? 112 : 128, Math.max(80, textWidth + 20)),
    ),
    wraps = textWidth > width - 16;
  return { width, height: wraps ? 38 : 28 };
}
function amenityPriority(room) {
  if (["elevator-bank", "lift-main", "main-entrance"].includes(room.id))
    return 0;
  if (room.kind === "stairs" && /centre|center/.test(room.id)) return 1;
  return (
    { lift: 2, stairs: 3, wc: 4, kitchen: 5, print: 6, room: 7 }[room.kind] ?? 8
  );
}
function renderAmenities(occupied, policy, bounds) {
  amenityOverlay.hidden = !mapLayers.facilities || view === "source";
  for (const el of amenityNodes.values()) el.hidden = true;
  if (amenityOverlay.hidden) return;
  const geometry = data.floors.find((f) => f.level === floor).geometry;
  const amenities = (geometry.wayfinding || [])
    .filter(facilityVisible)
    .map((room, i) => ({ room, id: `${floor}:${room.id || i}` }))
    .sort((a, b) => amenityPriority(a.room) - amenityPriority(b.room));
  const retained = new Set(amenities.map((item) => item.id));
  let count = 0;
  const kindsShown = new Set();
  for (const { room, id } of amenities) {
    if (!room.points?.length) continue;
    const minimum = /seating/.test(room.id)
      ? 3
      : room.kind === "room" && amenityPriority(room) > 1
        ? 1
        : 0;
    if (policy.level < minimum || count >= policy.amenities) continue;
    if (policy.level === 0 && kindsShown.has(room.kind)) continue;
    const title =
      room.kind === "lift"
        ? `↕ ${room.name || "Elevators"}`
        : room.name || "Room";
    const center =
      room.anchor ||
      room.points.reduce(
        (a, p) => [
          a[0] + p[0] / room.points.length,
          a[1] + p[1] / room.points.length,
        ],
        [0, 0],
      );
    const pt = projected(modelPoint(center[0], center[1], floor, 0));
    if (!pt.every(Number.isFinite)) continue;
    const width = Math.min(190, Math.max(72, title.length * 6.8 + 22)),
      height = 28;
    const rect = {
      x: pt[0] - width / 2,
      y: pt[1] - height / 2,
      w: width,
      h: height,
    };
    if (!labelFits(rect, bounds, occupied)) continue;
    let el = amenityNodes.get(id);
    if (!el) {
      el = document.createElement("span");
      el.className = "amenity-tag";
      amenityOverlay.append(el);
      amenityNodes.set(id, el);
    }
    el.textContent = title;
    el.title = title;
    el.hidden = false;
    el.style.cssText = `left:${rect.x}px;top:${rect.y}px;width:${width}px;height:${height}px`;
    occupied.push(rect);
    kindsShown.add(room.kind);
    count++;
  }
  for (const [id, el] of amenityNodes)
    if (!retained.has(id)) {
      el.remove();
      amenityNodes.delete(id);
    }
}
function renderNames() {
  const start = performance.now();
  applyNameVisibility();
  updateMapLayers();
  const w = canvas.clientWidth,
    h = canvas.clientHeight;
  if (!w || !h) return;
  const policy = labelPolicy(w, h),
    bounds = labelBounds(w, h);
  const key = JSON.stringify([
    floor,
    view,
    cam,
    selected?.id,
    moving,
    AtlasUI.performance.isCitrix(),
    $("#search").value,
    lastMatches.map((r) => r.id),
    canvas.clientWidth,
    canvas.clientHeight,
    showNameTags,
    mapLayers.facilities,
    policy.level,
  ]);
  if (key === labelScene && records === labelRecords) return;
  labelScene = key;
  labelRecords = records;
  const activeScreen =
    showNameTags && screenRecords.find((item) => item.r.id === selected?.id);
  const activeSpot = activeScreen && selectedLabelSpot(activeScreen.p, w, h);
  const occupied = activeSpot ? [activeSpot] : [];
  renderAmenities(occupied, policy, bounds);
  if (!showNameTags) {
    $("#location-banner").hidden = true;
    $("#hint").textContent =
      view === "3d" ? orbitHint : "Name tags off · Click a desk to inspect";
    metrics.labelsMs = performance.now() - start;
    return;
  }
  // Prune labels when the floor or underlying record set changes; the pool stays bounded.
  const floorIds = new Set(
    records.filter((r) => r.floor === floor).map((r) => r.id),
  );
  for (const [id, n] of labelNodes) {
    if (!id.startsWith("room:" + floor + ":") && !floorIds.has(id)) {
      n.el.remove();
      n.line?.remove();
      n.circle?.remove();
      labelNodes.delete(id);
    } else {
      n.el.hidden = true;
      if (n.line) {
        n.line.style.display = "none";
        n.circle.style.display = "none";
      }
    }
  }
  const searching = !!$("#search").value.trim(),
    matches = new Set(lastMatches.map((r) => r.id));
  const nameBudget = Math.max(policy.names, searching ? 3 : 0);
  const candidates = screenRecords
    .filter(
      ({ r }) =>
        (!AtlasUI.performance.isCitrix() || !moving || r.id === selected?.id) &&
        (!searching || matches.has(r.id) || r.id === selected?.id) &&
        (r.id === selected?.id ||
          r.kind === "area" ||
          (r.occupancy !== "vacant" &&
            r.name?.trim() &&
            !/^(unconfirmed desk|vacant desk|unnamed(?: desk)?|unassigned|open|new location)$/i.test(
              r.name.trim(),
            ))),
    )
    .sort(
      (a, b) =>
        (b.r.id === selected?.id) - (a.r.id === selected?.id) ||
        Math.hypot(a.p[0] - w / 2, a.p[1] - h / 2) -
          Math.hypot(b.p[0] - w / 2, b.p[1] - h / 2),
    );
  let hidden = 0,
    shown = 0;
  for (const { r, p } of candidates) {
    const active = r.id === selected?.id;
    if (!active && (p[0] < 0 || p[0] > w || p[1] < 50 || p[1] > h - 45))
      continue;
    if (!active && shown >= nameBudget) {
      hidden++;
      continue;
    }
    const size = nameLabelSize(r.name, w, bounds.right - bounds.left, active),
      wide = size.width,
      height = size.height;
    const columns = Math.max(
      1,
      Math.floor((bounds.right - bounds.left + 4) / (wide + 4)),
    );
    const horizontalOffsets =
      w < 640
        ? Array.from(
            { length: columns },
            (_, i) =>
              bounds.left +
              (columns > 1
                ? (i * (bounds.right - bounds.left - wide)) / (columns - 1)
                : 0) -
              (p[0] - wide / 2),
          ).sort((a, b) => Math.abs(a) - Math.abs(b))
        : [0, -wide * 0.55, wide * 0.55, -wide * 1.05, wide * 1.05];
    let spot = null;
    if (active) spot = activeSpot || selectedLabelSpot(p, w, h);
    else if (moving && labelNodes.get(r.id)?.offset) {
      const offset = labelNodes.get(r.id).offset;
      spot = { x: p[0] + offset.x, y: p[1] + offset.y, w: wide, h: height };
      if (!labelFits(spot, bounds, occupied, 4)) spot = null;
    } else
      // Try nearby free space before omitting a name in a crowded desk bank.
      for (const dy of [
        -height - 8,
        8,
        -height - 40,
        40,
        -height - 72,
        72,
        -height - 104,
        104,
      ]) {
        for (const dx of horizontalOffsets) {
          const rect = {
            x: Math.max(
              bounds.left,
              Math.min(bounds.right - wide, p[0] - wide / 2 + dx),
            ),
            y: Math.max(
              bounds.top,
              Math.min(bounds.bottom - height, p[1] + dy),
            ),
            w: wide,
            h: height,
          };
          if (labelFits(rect, bounds, occupied, 4)) {
            spot = rect;
            break;
          }
        }
        if (spot) break;
      }
    if (!spot) {
      hidden++;
      continue;
    }
    if (!active) {
      occupied.push(spot);
      shown++;
    }
    const n = labelNode(r.id);
    n.offset = { x: spot.x - p[0], y: spot.y - p[1] };
    n.el.hidden = false;
    n.el.classList.toggle("chosen", active);
    n.el.style.cssText = `left:${spot.x}px;top:${spot.y}px;width:${wide}px;height:${height}px`;
    if (n.el.firstChild.textContent !== r.name)
      n.el.firstChild.textContent = r.name;
    const subtitle = active ? r.id : `Level ${r.floor}`;
    if (n.el.lastChild.textContent !== subtitle)
      n.el.lastChild.textContent = subtitle;
    n.el.lastChild.hidden = !active;
    n.el.title = `${r.id} · ${r.name}`;
    // Connectors follow the projected desk throughout camera movement.
    n.line.style.display = "";
    n.circle.style.display = "";
    for (const [k, v] of Object.entries({
      x1: p[0],
      y1: p[1],
      x2: spot.x + wide / 2,
      y2: spot.y + (spot.y > p[1] ? 0 : height),
    }))
      n.line.setAttribute(k, v);
    for (const [k, v] of Object.entries({
      cx: p[0],
      cy: p[1],
      r: active ? 6 : 2.5,
    }))
      n.circle.setAttribute(k, v);
    n.line.classList.toggle("chosen", active);
    n.circle.classList.toggle("chosen", active);
  }
  if (!moving && policy.level >= 2 && !searching) {
    let roomsShown = 0;
    for (const [i, room] of data.floors
      .find((f) => f.level === floor)
      .geometry.rooms.entries()) {
      if (room.kind === "core" || room.name === "Office") continue;
      if (roomsShown >= 2) break;
      const center = room.points.reduce(
          (s, p) => [
            s[0] + p[0] / room.points.length,
            s[1] + p[1] / room.points.length,
          ],
          [0, 0],
        ),
        pt = projected(modelPoint(center[0], center[1], floor, 0)),
        rect = { x: pt[0] - 48, y: pt[1] - 8, w: 96, h: 22 };
      if (!labelFits(rect, bounds, occupied)) continue;
      occupied.push(rect);
      roomsShown++;
      const n = labelNode("room:" + floor + ":" + i, true);
      n.el.hidden = false;
      n.el.textContent = room.name;
      n.el.title = room.name;
      n.el.style.cssText = `left:${rect.x}px;top:${rect.y}px;width:${rect.w}px;height:${rect.h}px`;
    }
  }
  updateMapLayers();
  $("#label-lines").setAttribute("viewBox", `0 0 ${w} ${h}`);
  const banner = $("#location-banner"),
    current = selected?.floor === floor ? selected : null;
  banner.hidden = !current && !$("#search").value.trim();
  const next = JSON.stringify([
    current?.id,
    current?.name,
    current?.team,
    current?.occupancy,
    floor,
    lastMatches.length,
  ]);
  if (next !== bannerKey) {
    bannerKey = next;
    banner.replaceChildren();
    const text = document.createElement("div"),
      title = document.createElement("b"),
      sub = document.createElement("span");
    title.textContent = current
      ? current.name
      : lastMatches.length
        ? `${lastMatches.length} matches`
        : "No matching location";
    sub.textContent = current
      ? `Level ${floor} · ${current.team} · ${current.occupancy === "assigned" ? "Assigned location" : "Seating unconfirmed"}`
      : lastMatches.length
        ? "Select a name to pinpoint its desk."
        : "Try a surname, team or room.";
    text.append(title, sub);
    banner.append(text);
    if (current) {
      const actions = document.createElement("div");
      actions.className = "location-actions";
      for (const [id, label, fn] of [
        ["refocus", "Focus desk", () => selected && focusPerson(selected)],
        [
          "show-record",
          "Desk details",
          () => {
            $("#detail").classList.add("open");
            renderDetail();
            AtlasUI.motion.slideUp($("#detail"));
          },
        ],
      ]) {
        const b = document.createElement("button");
        b.id = id;
        b.textContent = label;
        b.onclick = fn;
        actions.append(b);
      }
      banner.append(actions);
    }
  }
  $("#hint").textContent =
    view === "3d"
      ? orbitHint
      : hidden
        ? "Zoom in to reveal names and more places"
        : "Drag to pan · Scroll to zoom";
  metrics.labelsMs = performance.now() - start;
}

$("#map-labels").onclick = (e) => {
  const b = e.target.closest("[data-person]");
  if (b) selectRecord(b.dataset.person);
};

new ResizeObserver(() => {
  if (floorFitted && ready) resetCam(false);
  else draw();
}).observe($("#viewport"));
function cancelMapGesture() {
  drag = null;
  pinchDistance = 0;
  const captured = [...pointers.keys()];
  pointers.clear();
  for (const element of [glCanvas, planCanvas])
    for (const pointerId of captured)
      if (element.hasPointerCapture?.(pointerId))
        element.releasePointerCapture(pointerId);
  mapCursor.reset();
}
onMap("pointerdown", (e) => {
  if (e.currentTarget !== canvas || e.button > 2 || pointers.size >= 2) return;
  e.preventDefault();
  floorFitted = false;
  stopFocus();
  clearLocator();
  draggedContext = false;
  mapCursor.set(canvas, placing ? "place" : "drag");
  canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pointers.size === 2) {
    const p = [...pointers.values()];
    pinchDistance = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
    drag = null;
    return;
  }
  const rect = canvas.getBoundingClientRect(),
    point = [e.clientX - rect.left, e.clientY - rect.top];
  drag = {
    pointerId: e.pointerId,
    x: e.clientX,
    y: e.clientY,
    point,
    anchor: inversePoint(...point),
    yaw: cam.yaw,
    tilt: cam.tilt,
    moved: false,
    orbit: view === "3d" && (e.button === 2 || (e.shiftKey && e.button === 0)),
    button: e.button,
  };
});
onMap("pointermove", (e) => {
  if (e.currentTarget !== canvas) return;
  if (pointers.has(e.pointerId))
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pointers.size === 2 && pointers.has(e.pointerId)) {
    const p = [...pointers.values()],
      d = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
    if (pinchDistance)
      cam.scale = Math.max(0.05, Math.min(16, (cam.scale * d) / pinchDistance));
    pinchDistance = d;
    draw();
    return;
  }
  if (drag && drag.pointerId === e.pointerId) {
    const dx = e.clientX - drag.x,
      dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 3) drag.moved = true;
    if (!drag.moved) return;
    if (drag.button === 2) draggedContext = true;
    const rect = canvas.getBoundingClientRect();
    if (drag.orbit) {
      cam.yaw = drag.yaw + dx * 0.005;
      cam.tilt = Math.max(0.3, Math.min(1.48, drag.tilt + dy * 0.004));
    }
    // Move the grabbed floor point with the hand; rotation keeps that point
    // at its original screen position instead of orbiting the map centre.
    const point = drag.orbit
      ? drag.point
      : [e.clientX - rect.left, e.clientY - rect.top];
    const current = inversePoint(...point);
    cam.cx += drag.anchor[0] - current[0];
    cam.cz += drag.anchor[1] - current[1];
    $("#hover").hidden = true;
    draw();
  } else if (!pointers.size) {
    const r = hit(e),
      hover = $("#hover");
    hover.hidden = !r;
    if (r) {
      const rect = canvas.getBoundingClientRect();
      hover.textContent =
        r.id + (r.name === "Unconfirmed desk" ? "" : " · " + r.name);
      hover.style.left =
        Math.min(e.clientX - rect.left + 12, rect.width - 210) + "px";
      hover.style.top = e.clientY - rect.top - 35 + "px";
    }
    mapCursor.set(canvas, placing ? "place" : r ? "hover" : "default");
  }
});
onMap("pointerup", async (e) => {
  if (!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  const clicked =
    drag && !drag.moved && !drag.orbit && drag.button === 0 && e.button === 0;
  drag = null;
  pinchDistance = 0;
  if (canvas.hasPointerCapture?.(e.pointerId))
    canvas.releasePointerCapture(e.pointerId);
  mapCursor.set(canvas, placing ? "place" : hit(e) ? "hover" : "default");
  if (!clicked) return;
  if (placing) {
    const rect = canvas.getBoundingClientRect(),
      p = inversePoint(e.clientX - rect.left, e.clientY - rect.top),
      f = data.floors.find((x) => x.level === floor),
      [x, y] = sourcePoint(p);
    if (x < 0 || x > 1 || y < 0 || y > f.height / 1800)
      return toast("Choose a point inside the source plan");
    const next =
      placing === "move" && selected
        ? { ...selected, x, y, verified: false }
        : {
            id: "custom-" + crypto.randomUUID(),
            layout: "official",
            floor,
            name: "Unconfirmed desk",
            team: "Unassigned",
            occupancy: "unconfirmed",
            kind: "desk",
            angle: 270,
            x,
            y,
            verified: false,
            revision: 0,
          };
    if (await saveRecord(next)) {
      placing = false;
      mapCursor.set(canvas, "hover");
      $("#add").textContent = "＋ Add location";
      $("#detail").style.visibility = "";
      selectRecord(next.id);
    }
  } else {
    const r = hit(e);
    if (r) selectRecord(r.id);
  }
});
onMap("pointercancel", cancelMapGesture);
onMap("lostpointercapture", (e) => {
  if (pointers.has(e.pointerId)) cancelMapGesture();
});
window.addEventListener("blur", cancelMapGesture);
onMap("pointerleave", () => ($("#hover").hidden = true));
onMap("contextmenu", (e) => {
  e.preventDefault();
  if (draggedContext) return;
  const r = hit(e);
  if (r) deskMenu(e, r);
});
onMap(
  "wheel",
  (e) => {
    e.preventDefault();
    clearLocator();
    const rect = canvas.getBoundingClientRect();
    const pixels =
      e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? rect.height : 1);
    zoomCamera(Math.exp(-Math.max(-400, Math.min(400, pixels)) * 0.001), [
      e.clientX - rect.left,
      e.clientY - rect.top,
    ]);
  },
  { passive: false },
);
function hit(e) {
  const rect = canvas.getBoundingClientRect(),
    x = e.clientX - rect.left,
    y = e.clientY - rect.top;
  return screenRecords
    .map((o) => {
      const p = world(o.r),
        a = (deskLayoutAngle(o.r) * Math.PI) / 180,
        c = Math.cos(a),
        sn = Math.sin(a);
      const corners = [
        [-1.28, -0.8],
        [1.28, -0.8],
        [1.28, 1.5],
        [-1.28, 1.5],
      ].map(([dx, dz]) =>
        projected([p[0] + dx * c - dz * sn, 0.85, p[2] + dx * sn + dz * c]),
      );
      let inside = false;
      for (let i = 0, j = 3; i < 4; j = i++) {
        const u = corners[i],
          v = corners[j];
        if (
          u[1] > y !== v[1] > y &&
          x < ((v[0] - u[0]) * (y - u[1])) / (v[1] - u[1]) + u[0]
        )
          inside = !inside;
      }
      return { ...o, inside, d: Math.hypot(x - o.p[0], y - o.p[1]) };
    })
    .filter((o) => o.inside || o.d < Math.max(10, Math.min(24, cam.scale * 3)))
    .sort((a, b) => a.d - b.d)[0]?.r;
}

let contextMenu = null;
function deskMenu(e, r) {
  if (!r) return;
  e.preventDefault();
  contextMenu?.remove();
  stopFocus();
  selected = r;
  renderDetail();
  search();
  const menu = document.createElement("div");
  menu.className = "desk-menu";
  menu.setAttribute("role", "menu");
  menu.innerHTML = `<strong>${esc(r.id)} · ${esc(r.name === "Unconfirmed desk" ? r.id : r.name)}</strong><button data-action="edit" role="menuitem">Edit desk / joiner</button><button data-action="move" role="menuitem">Move occupant…</button><button data-action="vacate" role="menuitem">Leaver / mark vacant…</button><button data-action="rotate" role="menuitem">Rotate desk 90°</button><button data-action="history" role="menuitem">View history</button>`;
  if (readOnly) menu.replaceChildren();
  const groupsButton = document.createElement("button");
  groupsButton.type = "button";
  groupsButton.textContent = "See groups";
  groupsButton.setAttribute("role", "menuitem");
  groupsButton.onclick = async () => {
    groupsButton.disabled = true;
    groupsButton.textContent = "Finding account…";
    try {
      const response = await fetch(
        "/api/desks/" + encodeURIComponent(r.id) + "/context",
      );
      if (!response.ok) throw Error("Could not resolve the directory account.");
      const data = await response.json();
      const user = data.user;
      if (!user || data.match_method === "ambiguous")
        throw Error(
          "Open this desk and choose the correct directory account first.",
        );
      menu.remove();
      AtlasGroups.open("user", user.user_name || user.email || "");
    } catch (error) {
      groupsButton.textContent = error.message;
      groupsButton.disabled = false;
    }
  };
  menu.prepend(groupsButton);
  menu.style.left =
    Math.max(8, Math.min(e.clientX, window.innerWidth - 270)) + "px";
  menu.style.top =
    Math.max(8, Math.min(e.clientY, window.innerHeight - 270)) + "px";
  menu.onclick = async (event) => {
    const action = event.target.dataset.action;
    if (!action) return;
    menu.remove();
    $("#detail").classList.add("open");
    if (action === "move") moveDialog(r);
    if (action === "vacate") vacateDesk(r);
    if (action === "rotate")
      await saveRecord({
        ...r,
        angle: ((r.angle || 0) + 90) % 360,
        verified: false,
      });
    if (action === "history") $("#history").click();
    if (["edit", "history", "move", "vacate"].includes(action))
      document.querySelector(".ops-desk-editor").open = true;
    if (action === "edit") $('#record-form [name="name"]').focus();
  };
  document.body.append(menu);
  contextMenu = menu;
  menu.querySelector("button").focus();
}
$("#map-labels").addEventListener("contextmenu", (e) => {
  const b = e.target.closest("[data-person]");
  if (b)
    deskMenu(
      e,
      records.find((r) => r.id === b.dataset.person),
    );
});
window.addEventListener("pointerdown", (e) => {
  if (contextMenu && !contextMenu.contains(e.target)) contextMenu.remove();
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") contextMenu?.remove();
});
// Both renderers use the same world coordinates, selection and hit testing.

let moving = false,
  motionKey = "",
  motionTimer = 0;
const metrics = { renderMs: 0, labelsMs: 0, intervals: [], lastFrame: 0 };
function trackMotion() {
  if (metrics.mode !== view) {
    metrics.mode = view;
    metrics.intervals = [];
    metrics.lastFrame = 0;
  }
  const next = JSON.stringify([
    view,
    floor,
    cam,
    canvas.clientWidth,
    canvas.clientHeight,
  ]);
  if (motionKey && next !== motionKey) {
    moving = true;
    clearTimeout(motionTimer);
    motionTimer = setTimeout(settleMotion, 160);
  }
  motionKey = next;
}
function settleMotion() {
  if (pointers.size) {
    motionTimer = setTimeout(settleMotion, 160);
    return;
  }
  moving = false;
  draw();
}
function finishFrame(start) {
  const end = performance.now(),
    delta = end - metrics.lastFrame;
  metrics.renderMs = end - start;
  if (moving && metrics.lastFrame && delta < 250) {
    metrics.intervals.push(delta);
    if (metrics.intervals.length > 90) metrics.intervals.shift();
  }
  metrics.lastFrame = end;
  const output = $("#map-metrics");
  if (output.hidden) return;
  const sorted = [...metrics.intervals].sort((a, b) => a - b),
    p95 = sorted.length
      ? sorted[
          Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))
        ].toFixed(1)
      : "—";
  output.textContent = `Atlas 7.0.0 · studio map · ${view === "plan" ? "Canvas 2D" : "Simple WebGL"}\nDraw + labels: ${metrics.renderMs.toFixed(1)} ms\nLabel layout: ${metrics.labelsMs.toFixed(1)} ms\nMovement frame interval p95: ${p95} ms\nBuffer: ${canvas.width} × ${canvas.height}\n${moving ? "Moving · names follow desks" : "Idle"}\nFrame interval includes event scheduling.\nRemote-display latency is not measured.`;
}

const officialImages = new Map();
function officialImage(level) {
  if (!officialImages.has(level)) {
    const img = new Image();
    img.onload = () => {
      const raster = document.createElement("canvas");
      raster.width = img.naturalWidth;
      raster.height = img.naturalHeight;
      raster.getContext("2d").drawImage(img, 0, 0);
      img.raster = raster;
      draw();
      if (!performance.getEntriesByName("atlas-map-ready").length)
        performance.mark("atlas-map-ready");
    };
    img.onerror = () => toast("Plan image could not load.");
    img.src = `studio-floor-${level}.svg?v=3`;
    officialImages.set(level, img);
    if (officialImages.size > 2)
      officialImages.delete(officialImages.keys().next().value);
  }
  return officialImages.get(level);
}
function renderPlan() {
  const w = canvas.clientWidth,
    h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const c = ctx2d,
    unit = Math.min(w / 112, h / 78) * cam.scale,
    b = getBasis();
  c.setTransform(1, 0, 0, 1, 0, 0);
  c.clearRect(0, 0, w, h);
  const origin = projected([0, 0, 0]);
  c.setTransform(
    b.right[0] * unit,
    -b.up[0] * unit,
    b.right[2] * unit,
    -b.up[2] * unit,
    origin[0],
    origin[1],
  );
  const paper = officialImage(floor);
  if (paper.raster)
    c.drawImage(
      paper.raster,
      -50,
      -data.floors.find((f) => f.level === floor).height / 36,
      100,
      data.floors.find((f) => f.level === floor).height / 18,
    );
  paintArchitecture(c);
  const matches = new Set(lastMatches.map((r) => r.id)),
    filtering =
      $("#search").value ||
      $("#team").value !== "all" ||
      $("#scope").value !== "all";
  screenRecords = [];
  for (const r of records) {
    if (r.floor !== floor) continue;
    const p = world(r),
      screen = projected(p),
      active = selected?.id === r.id,
      dim = filtering && !matches.has(r.id);
    if (
      !dim &&
      (active ||
        (screen[0] >= -100 &&
          screen[0] <= w + 100 &&
          screen[1] >= -100 &&
          screen[1] <= h + 100))
    )
      screenRecords.push({ r, p: screen });
    if (
      screen[0] < -100 ||
      screen[0] > w + 100 ||
      screen[1] < -100 ||
      screen[1] > h + 100
    )
      continue;
    c.save();
    c.translate(p[0], p[2]);
    c.rotate((deskLayoutAngle(r) * Math.PI) / 180);
    c.globalAlpha = dim ? 0.25 : 1;
    if (active || r.occupancy === "assigned") {
      c.beginPath();
      c.arc(0, 0, active ? 0.48 : 0.24, 0, Math.PI * 2);
      if (!active) {
        c.fillStyle = "#007eae";
        c.fill();
      }
      c.lineWidth = 0.1;
      c.strokeStyle = active ? "#e47b18" : "#fff";
      c.stroke();
    }
    c.restore();
  }
  c.setTransform(1, 0, 0, 1, 0, 0);
  renderNames();
}

setFloor(2);
setView(view);

{
  $("#site-info").addEventListener("pointerdown", (event) =>
    event.stopPropagation(),
  );
  $("#site-info").onclick = (event) => {
    event.stopPropagation();
    openSiteInfo();
  };
  const { installCommandPalette } = await import("./command-palette.js");
  const { commandUrl, MAP_COMMANDS, COMMANDS } =
    await import("./command-registry.js");
  const viewerHelp = () => {
    const { body } = AtlasUI.dialog("Keyboard shortcuts");
    body.innerHTML =
      "<p><kbd>Ctrl+K</kbd> / <kbd>Cmd+K</kbd> — Search Atlas</p><p><kbd>/</kbd> — Focus map search</p><p><kbd>Enter</kbd> — Locate a search result</p><p><kbd>↑</kbd> <kbd>↓</kbd> — Navigate palette results</p><p><kbd>Esc</kbd> — Close a dialog</p><p>Use person:, machine:, desk: or &gt; to narrow palette results.</p>";
  };
  const handlers = {
    "remote-registry": async () =>
      (await import("./service-actions.js")).openRemoteRegistry(
        operations.getTarget(),
      ),
    vlans: () => openSiteInfo("vlans"),
    contacts: () => openSiteInfo("contacts"),
    atlas: () =>
      document.querySelector("#viewport").scrollIntoView({ block: "nearest" }),
    lookup: () =>
      readOnly
        ? operations.openLookup()
        : atlasMapNavigate(commandUrl("lookup")),
    catalogue: () =>
      readOnly
        ? atlasMapNavigate("/installer?command=catalogue")
        : $("#ops-catalog").click(),
    settings: () => $("#ops-settings").click(),
    database: () => atlasMapNavigate("/manage-database"),
    view: () => $("#three-d-toggle").click(),
    reset: () => $("#reset").click(),
    refresh: () => location.reload(),
    export: () => $("#export").click(),
    daas: () => openSiteInfo("daas"),
    vdi: () => openSiteInfo("vdi"),
    animations: () =>
      document.querySelector(".atlas-motion-toggle input").click(),
    ...(readOnly ? { shortcuts: viewerHelp } : {}),
  };
  const runCommand = (id) => {
    if (
      readOnly &&
      !COMMANDS.some((command) => command.id === id && command.viewer)
    )
      return;
    if (handlers[id]) return handlers[id]();
    atlasMapNavigate(
      commandUrl(
        id,
        operations.getTarget() ||
          (!selected
            ? new URLSearchParams(location.search).get("machine")
            : "") ||
          "",
      ),
    );
  };
  installCommandPalette({
    readOnly,
    getRecords: () => records,
    onSelect: (id) => {
      $("#search").value = "";
      $("#scope").value = "all";
      $("#team").value = "all";
      selectRecord(id);
    },
    toast,
    runCommand,
    triggerParent: document.querySelector(".header-right"),
    openPerson: (value) =>
      readOnly
        ? operations.openPerson(value)
        : atlasMapNavigate(
            "/installer?" + new URLSearchParams({ person: value }),
          ),
    openMachine: (value) =>
      readOnly
        ? operations.openMachine(value)
        : atlasMapNavigate(
            "/installer?" + new URLSearchParams({ machine: value }),
          ),
  });
  const params = new URLSearchParams(location.search),
    desk = params.get("desk"),
    command = params.get("command");
  if (desk && records.some((r) => r.id === desk)) selectRecord(desk);
  if (
    command &&
    (readOnly
      ? COMMANDS.some((c) => c.id === command && c.viewer)
      : MAP_COMMANDS.has(command))
  ) {
    const url = new URL(location.href);
    url.searchParams.delete("command");
    history.replaceState(null, "", url);
    runCommand(command);
  }
  if (readOnly && params.get("person"))
    operations.openPerson(params.get("person"));
  else if (readOnly && params.get("machine"))
    operations.openMachine(params.get("machine"));
}
