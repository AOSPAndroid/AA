const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  path = require("node:path");
const { fixture, root } = require("./ui_fixture.cjs");
const settle = () => new Promise((r) => setTimeout(r, 30));
(async () => {
  for (const readOnly of [false, true]) {
    const effects = [],
      requests = [];
    const f = await fixture({
      fetch: async (url, options = {}) => {
        requests.push([url, options.method || "GET"]);
        let data;
        if (url === "/api/health")
          data = {
            identity: "TEST",
            version: "7",
            users: 2,
            machines: 2,
            database: true,
          };
        else if (url === "/api/master/status")
          data = { available: true, users: 2, machines: 2, assignments: 2 };
        else if (url.startsWith("/api/catalog"))
          data = { available: true, items: [], total: 0 };
        else if (url === "/api/database-freshness") data = {};
        else if (url === "/api/deployments/active")
          data = { deployments: [], count: 0 };
        else if (url.startsWith("/api/user/"))
          data = {
            user: { id: 1, name: "Example Person", user_name: "example" },
            machines: [{ name: "PC-A" }, { name: "PC-B" }],
          };
        else throw Error("Unexpected request " + url);
        return { ok: true, json: async () => data };
      },
    });
    const { w, run } = f,
      d = w.document;
    if (readOnly) {
      const meta = d.createElement("meta");
      meta.name = "atlas-mode";
      meta.content = "viewer";
      d.head.append(meta);
      run(
        fs.readFileSync(
          path.join(root, "frontend/assets/readonly-console.js"),
          "utf8",
        ),
      );
    }
    let mobile = false;
    w.matchMedia = () => ({ matches: mobile, addEventListener() {} });
    w.AtlasUI.motion.toggle();
    w.HTMLElement.prototype.animate = function (frames, options) {
      const animation = {
        element: this,
        frames,
        options,
        cancelled: false,
        cancel() {
          this.cancelled = true;
          this.oncancel?.();
        },
      };
      effects.push(animation);
      return animation;
    };
    await f.console();
    await settle();
    if (!d.querySelector("#deploymentPanel").dataset.installed) {
      d.dispatchEvent(new w.Event("DOMContentLoaded"));
      await settle();
    }
    await run('loadUser("id:1")');
    await settle();
    const kyc = effects.find((e) => e.element.id === "kyc");
    assert(kyc);
    assert.equal(kyc.frames[0].transform, "translateY(32px) scale(0.995)");
    assert.equal(kyc.options.duration, 280);
    assert.equal(
      kyc.frames.at(-1).transform,
      "translateY(0) scale(1)",
      "Panel settles at its normal position",
    );
    assert.equal(
      kyc.options.fill,
      "none",
      "No persistent transform remains after the entrance",
    );
    assert.equal(
      d.documentElement.dataset.atlasSurface,
      "workspace",
      "The console receives the lightweight workspace motion profile",
    );
    d.querySelector('[data-machine="0"]').click();
    const panel = d.querySelector("#deploymentPanel"),
      entrances = () => effects.filter((e) => e.element === panel);
    assert(!panel.hidden);
    assert.equal(entrances().length, 1);
    run("syncDeploymentPanel();refreshConsoleSummary()");
    assert.equal(
      entrances().length,
      1,
      "Data refresh does not replay entrance",
    );
    d.querySelector('[data-machine="1"]').click();
    assert.equal(entrances().length, 2);
    assert(entrances()[0].cancelled, "Rapid selections cancel earlier motion");
    assert.equal(d.querySelector("#deployTarget").textContent, "PC-B");
    d.querySelector('[data-machine="1"]').click();
    assert.equal(
      entrances().length,
      2,
      "Repeated target click does not bounce",
    );
    const count = effects.length;
    w.AtlasUI.motion.reveal(panel.querySelector("button"));
    assert.equal(effects.length, count, "Nested reveals do not stack");
    w.AtlasUI.motion.toggle();
    assert(entrances().at(-1).cancelled);
    d.querySelector('[data-machine="0"]').click();
    assert.equal(effects.length, count, "Motion off uses immediate selection");
    assert(!panel.hidden);
    w.AtlasUI.motion.toggle();
    w.AtlasUI.performance.setDisplay("citrix");
    d.querySelector('[data-machine="1"]').click();
    assert.equal(effects.length, count, "Citrix skips slide effects");
    w.AtlasUI.performance.setDisplay("standard");
    mobile = true;
    run("clearLookup()");
    await run('loadUser("id:1")');
    d.querySelector('[data-machine="0"]').click();
    assert(
      !panel.hidden,
      "Machine selection opens the mobile deployment sheet",
    );
    assert.equal(
      d.querySelector("#deploymentToggle").getAttribute("aria-expanded"),
      "true",
    );
    d.querySelector("#closeDeploymentPanel").click();
    assert(panel.hidden);
    d.querySelector("#deploymentToggle").click();
    assert(!panel.hidden);
    assert(
      requests.every(
        ([url, method]) =>
          method === "GET" &&
          !/machine-health|performance|preflight|psexec/.test(url),
      ),
      "Animation creates no remote checks",
    );
    assert.equal(f.errors.length, 0, f.errors.join("\n"));
    w.close();
  }
  console.log(
    "PASS: user and deployment slide-up, rapid selection cancellation, stable refreshes, mobile open/close, reduced motion and Citrix fallback in Admin/Demo.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
