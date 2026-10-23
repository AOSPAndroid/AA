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
  const meta = w.document.createElement("meta");
  meta.name = "atlas-mode";
  meta.content = "viewer";
  w.document.head.append(meta);
  w.HTMLCanvasElement.prototype.getContext = () => null;
  // This test exercises UI routes and controls; map rendering has its own suites.
  w.requestAnimationFrame = () => 1;
  w.cancelAnimationFrame = () => {};
  await f.map();
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
  await sleep(20);
  assert(
    w.document.querySelector("#detail").textContent.includes("Alice Example"),
  );
  assert(w.document.querySelector("#ops-context .atlas-person"));
  assert(!w.document.querySelector("#record-form"));
  trigger.focus();
  trigger.click();
  await sleep(0);
  type("person:Bob");
  await sleep(220);
  key("Enter");
  await sleep(20);
  let dialog = w.document.querySelector(".viewer-lookup-dialog");
  assert(dialog.open);
  assert(dialog.textContent.includes("Bob Unmapped"));
  assert.equal(w.location.pathname, "/");
  dialog.close();
  await sleep(0);
  assert.equal(rootEl.activeElement, trigger, "shared dialog returns focus");
  trigger.focus();
  trigger.click();
  await sleep(0);
  type("machine:PC");
  await sleep(220);
  key("Enter");
  await sleep(20);
  dialog = w.document.querySelector(".viewer-lookup-dialog");
  assert(dialog.textContent.includes("Fixture laptop"));
  assert(dialog.textContent.includes("Assigned to user"));
  const details = dialog.querySelector(".atlas-machine-details");
  assert(details.open);
  assert.equal(details.querySelector("summary").textContent, "Device details");
  assert(details.textContent.includes("SERIAL-1"));
  assert(details.textContent.includes("CI-1"));
  assert(details.textContent.includes("Fixture discovery"));
  let copied = "";
  Object.defineProperty(w.navigator, "clipboard", {
    value: {
      writeText: async (value) => {
        copied = value;
      },
    },
    configurable: true,
  });
  details.open = false;
  dialog.querySelector("[data-copy-report]").click();
  await sleep(0);
  assert(
    copied.includes("Serial number: SERIAL-1"),
    "copy includes collapsed inventory",
  );
  assert(copied.includes("Correlation ID: CI-1"));
  dialog.querySelector("[data-person]").click();
  await sleep(20);
  assert(dialog.textContent.includes("Alice Example"));
  // Closing a lookup invalidates even a transport that ignores AbortSignal.
  const search = dialog.querySelector("input");
  search.value = "slow";
  dialog
    .querySelector("form")
    .dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  dialog.close();
  w.document.querySelector("#viewer-lookup").click();
  const reopened = w.document.querySelector(".viewer-lookup-dialog");
  await sleep(400);
  assert.equal(reopened.querySelector(".viewer-results").textContent, "");
  reopened.close();
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
        !/session|preflight|software-tools|deploy|ops\/settings/.test(url),
    ),
  );
  assert.equal(f.errors.length, 0, f.errors.join("\n"));
  await sleep(0);
  w.close();
  console.log(
    "PASS: viewer uses shared palette, safe commands, person/desk/machine navigation, shared cards/dialogs, focus return, stale cancellation and animation switch without privileged requests",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
