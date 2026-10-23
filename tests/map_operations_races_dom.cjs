// Actual map/operations handlers with delayed fictional reads; no deployment runs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { fixture, root } = require("./ui_fixture.cjs");
const settle = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};
const response = (data) => ({ ok: true, status: 200, json: async () => data });
const source = JSON.parse(
  fs.readFileSync(path.join(root, "atlas/official-data.json"), "utf8"),
);
const desks = source.records
  .filter((record) => record.kind === "desk" && record.floor === 2)
  .slice(0, 2);
const packages = ["A", "B"].map((folder) => ({
  folder,
  display_name: "Package " + folder,
  version: "1",
}));

(async () => {
  for (const readonly of [false, true]) {
    const requests = [],
      catalogs = [],
      previews = [],
      histories = [];
    let delayCatalog = false;
    const f = await fixture({
      html: "atlas/official-index.html",
      fetch: async (url, options = {}) => {
        url = String(url);
        assert.equal(
          options.method || "GET",
          "GET",
          "The regression fixture must never write",
        );
        requests.push(url);
        if (url === "official-data.json")
          return response(structuredClone(source));
        if (url === "/api/official/state")
          return response({
            records: source.records,
            legacy: [],
            mappings: {},
            token: "fixture",
          });
        if (url.startsWith("/api/desks/") && url.endsWith("/context")) {
          const desk = source.records.find((record) =>
            url.includes(encodeURIComponent(record.id)),
          );
          return response({
            desk,
            user: null,
            candidates: [],
            machines: [],
            deployments: [],
            match_method: "unmatched",
          });
        }
        if (url.startsWith("/api/catalog?")) {
          assert(
            !readonly,
            "Readonly maps must not inspect the package repository",
          );
          if (delayCatalog)
            return new Promise((resolve) =>
              catalogs.push(() => resolve(response({ items: packages }))),
            );
          return response({ items: packages });
        }
        if (url.startsWith("/api/catalog/details?"))
          return response({
            display_name: "Fixture",
            scripts: {
              Install: ["shared.ps1", "alternate.ps1"],
              Repair: ["shared.ps1"],
              Uninstall: [],
            },
            files_checked: 1,
            complete: true,
          });
        if (url.startsWith("/api/scripts?"))
          return response({ scripts: ["shared.ps1", "alternate.ps1"] });
        if (url.startsWith("/api/package-script?"))
          return new Promise((resolve) =>
            previews.push({
              url,
              finish: (content) => resolve(response({ content })),
            }),
          );
        if (url.startsWith("/api/history/"))
          return new Promise((resolve) =>
            histories.push({
              url,
              finish: (action) =>
                resolve(
                  response({
                    history: [
                      {
                        action,
                        at: "2026-10-06T10:00:00Z",
                        after: { name: "Fixture occupant" },
                      },
                    ],
                  }),
                ),
            }),
          );
        throw Error("Unexpected map fixture request: " + url);
      },
    });
    const { w } = f,
      d = w.document;
    if (readonly) {
      const meta = d.createElement("meta");
      meta.name = "atlas-mode";
      meta.content = "viewer";
      d.head.append(meta);
    }
    w.HTMLCanvasElement.prototype.getContext = () => null;
    w.requestAnimationFrame = () => 1;
    w.cancelAnimationFrame = () => {};
    const map = await f.map("\nexport { selectRecord };");
    const choose = (id, value) => {
      const field = d.getElementById(id);
      assert(field, id);
      field.value = value;
      field.dispatchEvent(new w.Event("change", { bubbles: true }));
    };
    const preview = () => {
      const count = previews.length;
      d.getElementById("ops-preview").click();
      assert.equal(previews.length, count + 1);
      return previews.at(-1);
    };
    const history = () => {
      const count = histories.length;
      d.getElementById("history").click();
      assert.equal(histories.length, count + 1);
      return histories.at(-1);
    };
    if (readonly) {
      map.selectRecord(desks[0].id);
      await settle();
      assert(d.querySelector("#ops-context"));
      assert(
        !d.querySelector("#ops-deploy, #ops-preview, #ops-package, #history"),
      );
      assert(
        !requests.some((url) =>
          /^\/api\/(catalog|scripts|package-script|deploy|history)/.test(url),
        ),
      );
    } else {
      delayCatalog = true;
      map.selectRecord(desks[0].id);
      await settle();
      assert.equal(catalogs.length, 1);
      choose("ops-action", "Repair");
      catalogs.shift()();
      await settle();
      delayCatalog = false;
      assert.equal(
        d.getElementById("ops-package").value,
        "A",
        "Changing action while catalog loads cannot discard the catalog",
      );
      assert.equal(d.getElementById("ops-script").value, "shared.ps1");
      assert(
        requests.some((url) =>
          url.startsWith("/api/scripts?package=A&action=Repair"),
        ),
      );

      const oldPackage = preview();
      choose("ops-package", "B");
      await settle();
      oldPackage.finish("OLD PACKAGE A");
      await settle();
      assert.equal(
        d.getElementById("ops-script-content").hidden,
        true,
        "A response for the same filename from another package stays hidden",
      );
      assert(
        !d
          .getElementById("ops-script-content")
          .textContent.includes("OLD PACKAGE A"),
      );
      const currentPackage = preview();
      currentPackage.finish("CURRENT PACKAGE B");
      await settle();
      assert.equal(
        d.getElementById("ops-script-content").textContent,
        "CURRENT PACKAGE B",
      );
      assert.equal(d.getElementById("ops-script-content").hidden, false);

      const oldAction = preview();
      choose("ops-action", "Install");
      await settle();
      oldAction.finish("OLD REPAIR ACTION");
      await settle();
      assert.equal(
        d.getElementById("ops-script-content").hidden,
        true,
        "Action changes invalidate an outstanding preview even with the same filename",
      );
      assert(
        !d
          .getElementById("ops-script-content")
          .textContent.includes("OLD REPAIR ACTION"),
      );

      const oldScript = preview();
      choose("ops-script", "alternate.ps1");
      oldScript.finish("OLD SCRIPT");
      await settle();
      assert.equal(d.getElementById("ops-script-content").hidden, true);
      assert(
        !d
          .getElementById("ops-script-content")
          .textContent.includes("OLD SCRIPT"),
      );

      const firstPreview = preview(),
        latestPreview = preview();
      latestPreview.finish("LATEST PREVIEW");
      await settle();
      firstPreview.finish("OLDER PREVIEW");
      await settle();
      assert.equal(
        d.getElementById("ops-script-content").textContent,
        "LATEST PREVIEW",
        "Repeated previews reject older responses",
      );

      const oldDeskPreview = preview();
      delayCatalog = true;
      map.selectRecord(desks[0].id);
      await settle();
      map.selectRecord(desks[1].id);
      await settle();
      assert.equal(catalogs.length, 2);
      catalogs[1]();
      await settle();
      choose("ops-package", "B");
      await settle();
      catalogs[0]();
      oldDeskPreview.finish("OLD DESK PREVIEW");
      await settle();
      assert.equal(
        d.getElementById("ops-package").value,
        "B",
        "An old desk catalog cannot replace the current selection",
      );
      assert.equal(d.getElementById("ops-script-content").hidden, true);
      assert(
        !d
          .getElementById("ops-script-content")
          .textContent.includes("OLD DESK PREVIEW"),
      );

      delayCatalog = false;
      map.selectRecord(desks[0].id);
      await settle();
      const firstHistory = history(),
        latestHistory = history();
      assert(firstHistory.url.endsWith(encodeURIComponent(desks[0].id)));
      latestHistory.finish("LATEST HISTORY");
      await settle();
      firstHistory.finish("OLDER HISTORY");
      await settle();
      assert(
        d.getElementById("history-list").textContent.includes("LATEST HISTORY"),
      );
      assert(
        !d.getElementById("history-list").textContent.includes("OLDER HISTORY"),
      );

      const oldDeskHistory = history();
      map.selectRecord(desks[1].id);
      await settle();
      oldDeskHistory.finish("OTHER DESK HISTORY");
      await settle();
      assert(
        !d
          .getElementById("history-list")
          .textContent.includes("OTHER DESK HISTORY"),
        "A prior desk response cannot populate the current inspector",
      );

      const replacedInspectorHistory = history();
      map.selectRecord(desks[1].id);
      await settle();
      replacedInspectorHistory.finish("REPLACED INSPECTOR HISTORY");
      await settle();
      assert.equal(
        d.getElementById("history-list").textContent,
        "",
        "Even the same desk must use its current inspector host",
      );

      const closedInspectorHistory = history();
      d.getElementById("close-detail").click();
      closedInspectorHistory.finish("CLOSED INSPECTOR HISTORY");
      await settle();
      assert(!d.getElementById("history-list"));
      assert(
        !d
          .getElementById("detail")
          .textContent.includes("CLOSED INSPECTOR HISTORY"),
      );
    }
    assert.deepEqual(f.errors, []);
    w.dispatchEvent(new w.Event("pagehide"));
    w.close();
  }
  console.log(
    "PASS: map catalog/script generations are independent; previews and desk history reject stale requests and inspectors; readonly maps retain directory-only reads",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
