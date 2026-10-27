const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const { fixture, root } = require("./ui_fixture.cjs");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
(async () => {
  const source = JSON.parse(
    fs.readFileSync(path.join(root, "atlas/official-data.json"), "utf8"),
  );
  const desk = {
    ...source.records[0],
    name: "Alice Example",
    occupancy: "assigned",
    hostname: "PC-1",
  };
  const alice = {
    id: 1,
    full_name: "Alice Example",
    user_name: "alice",
    email: "alice@example.test",
  };
  const bob = { id: 2, full_name: "Bob Unmapped", user_name: "bob" };
  const machine = {
    name: "PC-1",
    model_id: "Fixture laptop",
    operational_status: "Operational",
    assigned_relationship: 1,
    serial_number: "SERIAL-1",
    manufacturer: "Fixture manufacturer",
    correlation_id: "CI-1",
    infrastructure_itsi: "WINDOWS VIRTUAL DESKTOPS",
    discovery_source: "Fixture discovery",
  };
  const requests = [];
  const f = await fixture({
    html: "atlas/official-index.html",
    url: "http://127.0.0.1:8771/",
    fetch: async (url, options = {}) => {
      url = String(url);
      requests.push([url, options.method || "GET"]);
      if (url.includes("slow")) await sleep(350);
      let data;
      if (url.includes("official-data.json"))
        data = { ...source, records: [desk] };
      else if (url === "/api/official/state")
        data = { records: [desk], legacy: [], mappings: {}, read_only: true };
      else if (url.includes("/api/search"))
        data = {
          users: url.includes("machine%3A")
            ? []
            : url.includes("Bob")
              ? [bob]
              : [alice],
          machines: url.includes("machine%3A") ? [machine] : [],
        };
      else if (url.includes("/api/palette/person/"))
        data = {
          desks: url.endsWith("2")
            ? []
            : [
                {
                  id: desk.id,
                  floor: desk.floor,
                  match: "confirmed account link",
                },
              ],
        };
      else if (url.startsWith("/api/user/"))
        data = {
          user: url.endsWith("2") ? bob : alice,
          machines: [machine],
          desks: [],
          desk_matches: [],
        };
      else if (url.startsWith("/api/machine/"))
        data = {
          machine,
          users: [{ ...alice, assigned_relationship: 1 }],
          desks: [
            { id: desk.id, floor: desk.floor, match: "recorded at this desk" },
          ],
        };
      else if (url.includes("/context"))
        data = {
          desk,
          user: alice,
          candidates: [alice],
          machines: [machine],
          match_method: "confirmed",
        };
      else throw Error("Unexpected viewer request: " + url);
      return { ok: true, json: async () => data };
    },
  });
  const { w } = f;
  const navigated = [];
  w.AtlasNavigate = (url) => (navigated.push(url), true);
  const meta = w.document.createElement("meta");
  meta.name = "atlas-mode";
  meta.content = "viewer";
  w.document.head.append(meta);
  f.run(fs.readFileSync(path.join(root, "frontend/assets/readonly-console.js"), "utf8"));
  if (!w.document.body.classList.contains("atlas-readonly-console"))
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  w.HTMLCanvasElement.prototype.getContext = () => null;
  // This test exercises UI routes and controls; map rendering has its own suites.
  w.requestAnimationFrame = () => 1;
  w.cancelAnimationFrame = () => {};
  await f.map();
  await sleep(0);
  const $ = (selector) => w.document.querySelector(selector);
  const greyed = (selector) => {
    const el = $(selector);
    assert(el, selector);
    assert.equal(el.getAttribute("aria-disabled"), "true", selector);
    if ("disabled" in el) assert(el.disabled, selector);
  };
  // Demo is the Admin page: same brand, header actions and Ask Axis, with changes greyed out.
  assert.equal($(".atlas-brand span").textContent, "Atlas");
  for (const selector of ["#axis-chat-toggle", "#import", "#ops-import-atlas", "#ops-settings", "#ops-history", "#backup-db", 'a[href="/manage-database"]'])
    greyed(selector);
  for (const selector of ["#export", "#ops-catalog"])
    assert.equal($(selector).getAttribute("aria-disabled"), null, selector);
  $("#ops-settings").click();
  $("#axis-chat-toggle").click();
  assert.equal($("#axis-chat"), null, "Axis chat never opens in Demo");
  const mount = w.document.querySelector(".atlas-palette-mount"),
    rootEl = mount.shadowRoot,
    trigger = rootEl.querySelector("button"),
    input = rootEl.querySelector("input");
  const key = (value) =>
    input.dispatchEvent(
      new w.KeyboardEvent("keydown", {
        key: value,
        bubbles: true,
        composed: true,
      }),
    );
  const type = (value) => {
    input.value = value;
    input.dispatchEvent(
      new w.Event("input", { bubbles: true, composed: true }),
    );
  };
  trigger.focus();
  trigger.click();
  await sleep(0);
  const commands = [...rootEl.querySelectorAll("[role=option]")].map(
    (el) => el.textContent,
  );
  assert(commands.length > 20);
  for (const name of ["Remote Admin", "PsTools / PsExec", "User & machine lookup"]) {
    const option = [...rootEl.querySelectorAll("[role=option]")].find(el => el.querySelector("strong").textContent === name);
    assert(option, name); assert.equal(option.getAttribute("aria-disabled"), "false");
  }
  const deploy = [...rootEl.querySelectorAll("[role=option]")].find(el => el.textContent.includes("Deploy selected package"));
  assert.equal(deploy.getAttribute("aria-disabled"), "true");
  deploy.click(); assert(rootEl.querySelector("dialog").open);
  assert(rootEl.querySelector("[role=status]").textContent.includes("elevated"));
  type("person:Alice");
  await sleep(220);
  key("Enter");
  await sleep(40);
  // The Admin desk inspector, with its edits and deployment greyed out.
  assert($("#detail").textContent.includes("Alice Example"));
  assert($("#ops-panel .atlas-person"), "directory person card");
  assert($("#record-form fieldset").disabled, "desk record is read only");
  for (const selector of ["#map-previous", "#previous-person", "#record-form button.primary", "#record-form #history", "#ops-deploy", "#ops-preview"])
    greyed(selector);
  assert($("#record-form").textContent.includes("Demo · read only"));
  assert($("#ops-package-status").textContent.includes("Windows Admin"), "package share answered locally");
  // A control the app re-enables stays greyed out.
  $("#ops-deploy").disabled = false;
  await sleep(0);
  greyed("#ops-deploy");
  $("#record-form button.primary").click();
  $("#ops-deploy").click();
  // Desk menu: the same items, greyed out.
  const result = $("#results [data-record]");
  result.dispatchEvent(new w.MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 20, clientY: 20 }));
  await sleep(0);
  const menuItems = [...w.document.querySelectorAll(".desk-menu [data-action]")];
  assert.deepEqual(menuItems.map((b) => b.dataset.action), ["edit", "move", "vacate", "rotate", "history"]);
  assert(menuItems.every((b) => b.disabled && b.getAttribute("aria-disabled") === "true"));
  menuItems[3].click();
  w.document.querySelector(".desk-menu")?.remove();
  // People without a mapped desk and machines open in the console, as in Admin.
  trigger.focus();
  trigger.click();
  await sleep(0);
  type("person:Bob");
  await sleep(220);
  key("Enter");
  await sleep(20);
  assert(navigated.some((url) => url.startsWith("/installer?person=")), navigated.join("\n"));
  trigger.focus();
  trigger.click();
  await sleep(0);
  type("machine:PC");
  await sleep(220);
  key("Enter");
  await sleep(20);
  assert(navigated.includes("/installer?machine=PC-1"), navigated.join("\n"));
  const motion = w.document.querySelector(".atlas-motion-toggle input"),
    before = motion.checked;
  trigger.focus();
  trigger.click();
  await sleep(0);
  type("> Toggle animations");
  key("Enter");
  await sleep(0);
  assert.equal(motion.checked, !before);
  assert(
    requests.every(
      ([url, method]) =>
        method === "GET" &&
        !/session|preflight|software-tools|deploy|ops\/settings|catalog|history|axis/.test(url),
    ),
    JSON.stringify(requests),
  );
  assert.equal(f.errors.length, 0, f.errors.join("\n"));
  await sleep(0);
  w.close();
  console.log(
    "PASS: Demo map is the Admin page with changes, deployment, desk menu and Ask Axis greyed out, the shared palette and console navigation, and no privileged requests",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
