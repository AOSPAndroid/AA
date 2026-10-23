// Actual map/profile handlers with fictional Citrix snapshots. No Windows operations.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { fixture, root } = require("./ui_fixture.cjs");
const settle = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};
const source = JSON.parse(
  fs.readFileSync(root + "/atlas/official-data.json", "utf8"),
);
const user = {
  id: 901,
  name: "Fictional VDI User",
  full_name: "Fictional VDI User",
  user_name: "fict.vdi",
  canonical_key: "uid:fict.vdi",
  email: "fict.vdi@example.test",
};
const other = { id: 902, name: "Fictional Shared User", user_name: "fict.shared" };
const desk = {
  ...source.records.find((record) => record.kind === "desk"),
  name: user.name,
  occupancy: "assigned",
  hostname: "FICT-PHYSICAL-PC",
};
const vdi = {
  id: "fictional-vdi-key",
  name: "GBRGLOIVB-FICT001.example.test",
  model_category: "VDI",
  device_kind: "vdi",
  windows_remote_supported: 1,
  assigned_relationship: 1,
  relationship_group: "Assigned to user",
  match_type: "Citrix assigned",
  source: "Citrix",
  vdi_key: "fictional-vdi-key",
  vdi_fqdn: "GBRGLOIVB-FICT001.example.test",
  vdi_catalog: "Fictional shared catalog",
  vdi_delivery_group: "Fictional shared delivery group",
  vdi_registration_state: "Unregistered",
  vdi_power_state: "On",
  vdi_maintenance_mode: "On",
  vdi_user_change_persistence: "Discard",
  vdi_user_display_names: user.name + "; " + other.name,
  vdi_assigned_users: ["EXAMPLE\\fict.vdi", "EXAMPLE\\fict.shared"],
  vdi_assignment_count: 2,
  vdi_imported_at: "2026-10-07T09:00:00Z",
};
const laptop = {
  name: "FICT-PHYSICAL-PC",
  model_id: "Fictional laptop",
  model_category: "Laptop",
  assigned_to: user.user_name,
  assigned_relationship: 1,
  relationship_group: "Assigned to user",
};
const response = (data) => ({ ok: true, json: async () => data });

(async () => {
  for (const readonly of [false, true]) {
    for (const display of ["standard", "citrix"]) {
      const requests = [], navigations = [], quickChecks = [];
      let manualHealth = false;
      const f = await fixture({
        html: "atlas/official-index.html",
        url: "http://127.0.0.1:8892/",
        fetch: async (url, options = {}) => {
          url = String(url);
          assert.equal(options.method || "GET", "GET", "Fixture forbids writes");
          requests.push(url);
          if (url.startsWith("/api/machine-health/")) {
            assert(manualHealth, "Only explicit Scan health may query the fictional VDI");
            const [, , , computer, metric] = url.split("/");
            assert.equal(decodeURIComponent(computer), vdi.name);
            return response({ computer: vdi.name, metric, state: "ready", data: { available: true }, checked_at: "2026-10-07T09:05:00Z" });
          }
          if (url.includes("official-data.json"))
            return response({ ...source, records: [desk] });
          if (url === "/api/official/state")
            return response({ records: [desk], legacy: [], mappings: {}, read_only: readonly });
          if (url.endsWith("/context"))
            return response({ desk, user, candidates: [user], machines: [laptop, vdi], match_method: "confirmed", deployments: [] });
          if (url.startsWith("/api/catalog")) return response({ items: [] });
          if (url.startsWith("/api/machine/")) {
            assert.equal(decodeURIComponent(url.split("/").at(-1)), vdi.name);
            return response({ machine: vdi, users: [{ ...user, assigned_relationship: 1 }, { ...other, assigned_relationship: 1 }], desks: [] });
          }
          if (url.startsWith("/api/user/")) {
            assert.equal(url, "/api/user/uid%3Afict.vdi", "Viewer must preserve the canonical user key");
            return response({ user, machines: [laptop, vdi], desks: [], desk_matches: [] });
          }
          throw Error("Unexpected VDI map request: " + url);
        },
      });
      const { w } = f, d = w.document;
      if (readonly) {
        const meta = d.createElement("meta");
        meta.name = "atlas-mode";
        meta.content = "viewer";
        d.head.append(meta);
      }
      w.HTMLCanvasElement.prototype.getContext = () => null;
      w.requestAnimationFrame = () => 1;
      w.cancelAnimationFrame = () => {};
      w.AtlasNavigate = (url) => { navigations.push(url); return true; };
      // Observe the real quick-check adapter; all possible reads stay inside this fixture.
      const quick = w.AtlasHealth.quick;
      w.AtlasHealth.quick = (...args) => {
        quickChecks.push(args[1]);
        return quick(...args);
      };
      w.AtlasUI.performance.setDisplay(display);
      const map = await f.map("\nexport { selectRecord, operations };");
      map.selectRecord(desk.id);
      await settle();
      assert.equal(d.documentElement.dataset.atlasDisplay, display);
      assert.equal(quickChecks.length, 0, "Imported state cannot start a health check");
      const host = d.getElementById(readonly ? "ops-context" : "ops-panel");
      const card = host.querySelector('[data-machine-kind="vdi"]');
      assert(card, "VDI is rendered beside physical devices");
      assert(card.textContent.includes("VDI"));
      const details = card.querySelector(".atlas-machine-details");
      for (const value of [vdi.vdi_catalog, vdi.vdi_delivery_group, vdi.vdi_registration_state, vdi.vdi_power_state, vdi.vdi_user_change_persistence, other.name])
        assert(details.textContent.includes(value), "Shared VDI details include " + value);
      assert.match(details.textContent, /snapshot|imported/i, "Citrix state is identified as stored evidence");
      assert.equal(details.querySelectorAll(".atlas-vdi-assigned-accounts li").length, 2, "Shared VDI shows every assigned account");
      assert(card.textContent.includes("Shared (2)"));
      assert.equal(details.querySelector('[data-export-kind="vdi"]').dataset.exportKey, vdi.vdi_key);
      const filter = host.querySelector('.atlas-machine-filters [data-kind="vdi"]');
      assert(filter, "Shared device filters include VDI");
      filter.click();
      assert.equal(card.hidden, false);
      assert.equal(host.querySelector('[data-machine-kind="laptop"]').hidden, true);
      assert.equal(quickChecks.length, 0, "Filtering VDI snapshots does not probe machines");
      const targetCard = readonly ? card : card.querySelector(".ops-machine");
      const openActions = () => {
        targetCard.dispatchEvent(new w.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
        const menu = d.querySelector(".atlas-ad-context");
        assert(menu);
        return menu;
      };
      let menu = openActions();
      assert.equal(menu.querySelector('[data-cmd="ad-groups"]').disabled, false);
      if (readonly) assert.equal(menu.querySelector('[data-cmd="ad-compare"]').disabled, true);
      menu.querySelector('[data-cmd="ad-groups"]').click();
      await settle();
      let route = new URL(navigations.at(-1), w.location.origin);
      assert.equal(route.pathname, "/installer");
      assert.equal(route.searchParams.get("adkind"), "computer");
      assert.equal(route.searchParams.get("adidentity"), vdi.name);
      assert.equal(route.searchParams.get("command"), "ad-open");
      if (readonly) {
        assert(!d.querySelector("#ops-deploy, #ops-package, #history, #record-form"));
        const deskPerson = host.querySelector("[data-person]");
        assert.equal(deskPerson.dataset.person, user.canonical_key);
        deskPerson.click();
        await settle();
        let lookup = d.querySelector(".viewer-lookup-dialog");
        assert(lookup.open);
        assert.equal(requests.at(-1), "/api/user/uid%3Afict.vdi", "Desk profile click uses its canonical key");
        assert(lookup.querySelector('[data-machine-kind="vdi"]'));
        lookup.close();
        card.querySelector("[data-machine]").click();
        await settle();
        lookup = d.querySelector(".viewer-lookup-dialog");
        assert(lookup.open);
        assert(lookup.querySelector(".atlas-machine-details").open);
        assert(lookup.textContent.includes(other.name), "Shared VDI preserves its linked users");
        const linkedPerson = lookup.querySelector("[data-person]");
        assert.equal(linkedPerson.dataset.person, user.canonical_key);
        linkedPerson.click();
        await settle();
        assert.equal(requests.at(-1), "/api/user/uid%3Afict.vdi", "Machine profile click uses its canonical key");
        assert(lookup.textContent.includes(user.name));
        assert(lookup.querySelector('[data-machine-kind="vdi"]'), "Person profile retains its VDI assignment");
        assert.equal(quickChecks.length, 0, "Readonly VDI inspection never invokes Windows health");
      } else {
        const radio = card.querySelector('input[name="ops-machine"]');
        assert.equal(radio.disabled, false, "VDI remains a Windows support target even if imported registration is Unregistered");
        radio.checked = true;
        radio.dispatchEvent(new w.Event("change", { bubbles: true }));
        assert.equal(map.operations.getTarget(), vdi.name);
        assert.equal(d.getElementById("ops-target-label").textContent, vdi.name);
        assert.equal(quickChecks.length, 0, "Selecting a Citrix snapshot does not automatically scan the VDI");
        const healthHost = d.getElementById("ops-target-health");
        assert.equal(healthHost.querySelector(":scope > p").textContent, w.AtlasUI.machineSnapshotNote(vdi), "VDI prompt reuses the shared snapshot/manual-check wording");
        assert.equal(requests.filter(url => url.startsWith("/api/machine-health/")).length, 0);
        manualHealth = true;
        healthHost.querySelector("[data-health-refresh]").click();
        await settle();
        manualHealth = false;
        assert.equal(requests.filter(url => url.startsWith("/api/machine-health/")).length, 8, "Explicit VDI Health remains available");
        const physical = host.querySelector('[data-machine-kind="laptop"] input');
        physical.checked = true;
        physical.dispatchEvent(new w.Event("change", { bubbles: true }));
        assert.deepEqual(quickChecks, [laptop.name], "Physical PC selection retains its existing quick checks");
        radio.checked = true;
        radio.dispatchEvent(new w.Event("change", { bubbles: true }));
        assert.equal(map.operations.getTarget(), vdi.name);
        assert.deepEqual(quickChecks, [laptop.name], "Returning to VDI still avoids automatic checks");
        await new Promise(resolve => setTimeout(resolve, 300));
        assert.equal(requests.filter(url => url.startsWith("/api/machine-health/")).length, 8, "VDI mounting cancels a pending physical-target quick scan");
        menu = openActions();
        assert.equal(menu.querySelector('[data-cmd="admin"]').disabled, false);
        menu.querySelector('[data-cmd="admin"]').click();
        await settle();
        route = new URL(navigations.at(-1), w.location.origin);
        assert.equal(route.searchParams.get("machine"), vdi.name);
        assert.equal(route.searchParams.get("command"), "admin");
      }
      assert(requests.every((url) => !/performance|active-directory|remote-registry|\/deploy/.test(url)), "Profiles and navigation do not invoke privileged operations");
      assert.equal(f.errors.length, 0, f.errors.join("\n"));
      w.close();
    }
  }
  console.log("PASS: Admin and readonly maps share VDI details/filtering, shared assignments and hostname/AD navigation across Standard/Citrix profiles; imported state creates no probes.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
