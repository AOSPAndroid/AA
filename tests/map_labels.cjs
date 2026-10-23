// Exercise the real shared label layout with anonymous, closely spaced desks.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { fixture, root } = require("./ui_fixture.cjs");

function visible(w, selector) {
  return [...w.document.querySelectorAll(selector)].filter(
    (el) => !el.hidden && !el.parentElement.hidden,
  );
}
function rectangle(el) {
  const result = Object.fromEntries(
    ["left", "top", "width", "height"].map((key) => [
      key,
      Number.parseFloat(el.style[key]),
    ]),
  );
  assert(
    Object.values(result).every(Number.isFinite),
    "Visible tags have explicit layout bounds",
  );
  return { ...result, text: el.textContent };
}
function assertNoOverlap(w) {
  const labels = visible(w, ".map-name, .amenity-tag").map(rectangle);
  for (let i = 0; i < labels.length; i++) {
    const a = labels[i];
    for (const b of labels.slice(i + 1)) {
      assert(
        !(
          a.left < b.left + b.width &&
          a.left + a.width > b.left &&
          a.top < b.top + b.height &&
          a.top + a.height > b.top
        ),
        `Tags from all layers avoid overlap: ${a.text} / ${b.text}`,
      );
    }
  }
}

(async () => {
  for (const readOnly of [false, true]) {
    const data = JSON.parse(
      fs.readFileSync(path.join(root, "atlas/official-data.json"), "utf8"),
    );
    const f = await fixture({
      html: "atlas/official-index.html",
      url: "http://127.0.0.1:8892/",
      fetch: async (url) => ({
        ok: true,
        json: async () =>
          String(url).includes("official-data.json")
            ? data
            : {
                records: data.records,
                legacy: [],
                mappings: {},
                token: "test",
              },
      }),
    });
    const { w } = f;
    if (readOnly) {
      const meta = w.document.createElement("meta");
      meta.name = "atlas-mode";
      meta.content = "viewer";
      w.document.head.append(meta);
    }
    const frames = new Map();
    let frameId = 0;
    w.requestAnimationFrame = (callback) => {
      frames.set(++frameId, callback);
      return frameId;
    };
    w.cancelAnimationFrame = (id) => frames.delete(id);
    const ctx = new Proxy({}, { get: () => () => ({}) });
    const gl = new Proxy(
      { getShaderParameter: () => true, getProgramParameter: () => true },
      { get: (target, key) => target[key] || (() => ({})) },
    );
    w.HTMLCanvasElement.prototype.getContext = (type) =>
      type === "webgl" ? gl : ctx;
    const viewport = { width: 900, height: 650 };
    for (const [property, key] of [
      ["clientWidth", "width"],
      ["clientHeight", "height"],
    ]) {
      Object.defineProperty(w.HTMLCanvasElement.prototype, property, {
        get: () => viewport[key],
      });
    }
    w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: viewport.width,
      height: viewport.height,
      right: viewport.width,
      bottom: viewport.height,
    });
    const t = await f.map(`
      export function installLabelScenario(mode = 'plan', spacing = 1.8) {
        setView(mode); floor = 2; selected = null; moving = false;
        const fit = fitTarget();
        records = Array.from({length: 63}, (_, i) => {
          const point = sourcePoint([fit.cx + (i % 9 - 4) * spacing, fit.cz + (Math.floor(i / 9) - 3) * spacing]);
          return {id:'test-desk-' + i, name:'Person ' + String(i).padStart(2,'0'), floor:2,
            kind:'desk', occupancy:'assigned', x:point[0], y:point[1]};
        });
        const amenities = [
          ['print', 'Print & stationery', -5, -3, 'print-stationery'], ['wc', 'Toilets', 5, -3, 'toilets-left'],
          ['kitchen', 'Kitchen & coffee', -5, 3, 'kitchen-coffee'], ['stairs', 'Stairs', 5, 3, 'stairs-centre'],
          ['lift', 'Elevators', 0, 0, 'elevator-bank'], ['room', 'Main entrance', 0, 5, 'main-entrance'],
        ];
        const geometry = data.floors.find(f => f.level === floor).geometry;
        geometry.rooms = [];
        geometry.wayfinding = amenities.map(([kind, name, x, y, id]) => {
          const point = sourcePoint([fit.cx + x, fit.cz + y]).map(v => v * 1800);
          return {id, kind, name, anchor:point,
            points:[[point[0]-2,point[1]-2],[point[0]+2,point[1]-2],[point[0]+2,point[1]+2],[point[0]-2,point[1]+2]]};
        });
        document.querySelector('#search').value = ''; lastMatches = [];
      }
      export function labelPose(zoom, selection = null, inMotion = false) {
        selected = records.find(r => r.id === selection) || null;
        moving = inMotion; const fit = fitTarget(); cam = {...fit, scale:fit.scale * zoom};
        screenRecords = records.map(r => ({r, p:projected(world(r))}));
        renderNames();
      }
      export function realFloorScenario(mode) {
        setView(mode); floor = 3; selected = null; moving = false;
        records = data.records.filter(r => r.floor === floor).map((r,i) => ({...r, name:'Colleague Example ' + i, occupancy:'assigned'}));
        document.querySelector('#search').value = ''; lastMatches = [];
      }
      export function searchLabelScenario() {
        document.querySelector('#search').value = 'Person'; lastMatches = records.slice(0,3);
      }
      export function labelSize(name, width = 420) {
        return nameLabelSize(name, width, width - 75);
      }
    `);
    assert(
      t.labelSize("Arnaud ROUVIER").height >= 38,
      "A short two-word name that wraps on narrow maps reserves two full lines",
    );
    assert(
      t.labelSize("Salim NADIR").height <= 28,
      "A name that fits remains compact",
    );
    for (const mode of ["plan", "3d"]) {
      t.installLabelScenario(mode);
      t.labelPose(1);
      const overviewNames = visible(w, ".map-name").length;
      assert(
        overviewNames >= 12 && overviewNames <= 32,
        `${mode}: crowded overview makes room for more names`,
      );
      const overviewAmenities = visible(w, ".amenity-tag");
      assert(
        overviewAmenities.length <= 4,
        `${mode}: overview keeps a small selection of landmark tags`,
      );
      assert(
        overviewAmenities.some((el) => el.textContent.includes("Elevators")),
        `${mode}: elevators take priority over lower-value amenities`,
      );
      assertNoOverlap(w);

      t.labelPose(2);
      const middleNames = visible(w, ".map-name").length;
      assert(
        middleNames > overviewNames && middleNames <= 60,
        `${mode}: names appear gradually at intermediate zoom`,
      );
      const middleAmenities = visible(w, ".amenity-tag").length;
      assertNoOverlap(w);
      t.labelPose(4.2);
      const closeNames = visible(w, ".map-name").length;
      assert(
        closeNames > middleNames,
        `${mode}: zooming closer reveals more of the same desk cluster`,
      );
      assert(
        visible(w, ".amenity-tag").length >= middleAmenities,
        `${mode}: nearby facility labels become available as space grows`,
      );
      assertNoOverlap(w);

      t.labelPose(1);
      assert.equal(
        visible(w, ".map-name").length,
        overviewNames,
        `${mode}: zooming out restores the smaller overview`,
      );
      assert.equal(
        [...w.document.querySelectorAll("#label-lines line")].filter(
          (el) => el.style.display !== "none",
        ).length,
        overviewNames,
        `${mode}: connectors only remain for visible names`,
      );

      t.labelPose(1, "test-desk-31");
      const chosen = visible(w, ".map-name.chosen");
      assert.equal(
        chosen.length,
        1,
        `${mode}: overview retains the selected person`,
      );
      assert.equal(chosen[0].dataset.person, "test-desk-31");
      assert(chosen[0].classList.contains("chosen"));
      assertNoOverlap(w);

      // Toggling amenities must recompute name placement at an unchanged camera pose.
      const facilities = w.document.querySelector('[data-layer="facilities"]');
      facilities.click();
      t.labelPose(4.2, "test-desk-31");
      assert.equal(visible(w, ".amenity-tag").length, 0);
      facilities.click();
      t.labelPose(4.2, "test-desk-31");
      assert(visible(w, ".amenity-tag").length > 0);
      assertNoOverlap(w);

      const tagControl = w.document.querySelector("#name-tags");
      const namesBeforeToggle = visible(w, ".map-name").map(
        (el) => el.dataset.person,
      );
      tagControl.click();
      t.labelPose(4.2, "test-desk-31");
      assert.equal(
        visible(w, ".map-name").length,
        0,
        `${mode}: Name tags off hides the name layer`,
      );
      assert(
        visible(w, ".amenity-tag").length > 0,
        `${mode}: amenities remain independent of Name tags`,
      );
      tagControl.click();
      t.labelPose(4.2, "test-desk-31");
      assert.deepEqual(
        visible(w, ".map-name").map((el) => el.dataset.person),
        namesBeforeToggle,
        `${mode}: Name tags on restores the same layout without moving the map`,
      );
      assertNoOverlap(w);

      t.labelPose(1);
      t.labelPose(1.37);
      assert(
        visible(w, ".map-name").length <= 32,
        `${mode}: small movement retains the overview budget`,
      );
      t.labelPose(1.43);
      assert(
        visible(w, ".map-name").length > 0,
        `${mode}: a deliberate zoom reveals names`,
      );
      for (const zoom of [1.33, 1.37, 1.33]) {
        t.labelPose(zoom);
        assert(
          visible(w, ".map-name").length > 0,
          `${mode}: small zoom reversals retain the current label level`,
        );
      }
      t.labelPose(1.27);
      assert(
        visible(w, ".map-name").length > 0 &&
          visible(w, ".map-name").length <= 32,
        `${mode}: zooming out retains a few useful names`,
      );

      t.searchLabelScenario();
      t.labelPose(1);
      assert(
        visible(w, ".map-name").length > 0 &&
          visible(w, ".map-name").length <= 3,
        `${mode}: search exposes a few matches without flooding the overview`,
      );
    }

    // A spread-out floor can use the larger allowance; dense clusters still avoid collisions.
    t.installLabelScenario("plan", 4);
    t.labelPose(1);
    assert(
      visible(w, ".map-name").length >= 20 &&
        visible(w, ".map-name").length <= 32,
    );
    assertNoOverlap(w);

    // Fit-relative behavior should remain quiet on a phone-sized viewport.
    viewport.width = 420;
    viewport.height = 600;
    t.installLabelScenario("plan");
    t.labelPose(1);
    assert(
      visible(w, ".map-name").length >= 8 &&
        visible(w, ".map-name").length <= 16,
    );
    assert(visible(w, ".amenity-tag").length <= 2);
    assertNoOverlap(w);
    for (const [width, height] of [
      [420, 340],
      [420, 600],
      [900, 650],
    ]) {
      viewport.width = width;
      viewport.height = height;
      for (const mode of ["plan", "3d"]) {
        t.realFloorScenario(mode);
        t.labelPose(1);
        const count = visible(w, ".map-name").length;
        console.log("Full-floor names", width + "x" + height, mode, count);
        assert(
          count >= (width < 500 ? (height < 400 ? 8 : 14) : 24),
          `${mode}: real floor remains populated at ${width}px`,
        );
        assertNoOverlap(w);
      }
    }
    assert.equal(f.errors.length, 0, f.errors.join("\n"));
    w.close();
  }
  console.log(
    "PASS: Admin/Demo progressive name tags, landmark priority, selected-label retention and shared collision layout in 2D/3D",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
