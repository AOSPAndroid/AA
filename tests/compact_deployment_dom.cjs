// Deployment UI exercises use a simulated transport; no host is contacted.
const assert = require("node:assert/strict");
const fs = require("node:fs"),
  path = require("node:path");
const { fixture, root } = require("./ui_fixture.cjs");
const settle = () => new Promise((resolve) => setTimeout(resolve, 15));
(async () => {
  const writes = [];
  let slowSearch, submit, job, bulkSubmit;
  const bulkWrites = [];
  const row = (folder) => ({
    folder,
    display_name: "Application " + folder,
    version: "1",
  });
  const f = await fixture({
    fetch: async (url, options = {}) => {
      url = String(url);
      const reply = (data) => ({
        ok: true,
        status: 200,
        json: async () => data,
      });
      if (url === "/api/health")
        return reply({ identity: "FIXTURE", users: 0, machines: 0 });
      if (url === "/api/session") return reply({ token: "test" });
      if (url.includes("/palette/desks"))
        return { ...reply({ records: [] }), headers: { get: () => null } };
      if (url.startsWith("/api/catalog?")) {
        const term = new URL(url, "http://localhost").searchParams.get("term");
        if (term === "slow")
          return new Promise((resolve) => {
            slowSearch = () => resolve(reply({ items: [row("B")] }));
          });
        return reply({ items: (term ? [term] : ["A", "B"]).map(row) });
      }
      if (url.startsWith("/api/scripts?")) {
        const query = new URL(url, "http://localhost").searchParams;
        return reply({
          scripts: [query.get("package") + "_" + query.get("action") + ".ps1"],
        });
      }
      if (url === "/api/bulk/deploy") {
        bulkWrites.push(JSON.parse(options.body));
        return new Promise(resolve => { bulkSubmit = () => resolve(reply({job:"bulk-test"})); });
      }
      if (url === "/api/bulk/job/bulk-test") return reply({state:"complete",results:[]});
      if (url === "/api/deploy") {
        writes.push(JSON.parse(options.body));
        return new Promise((resolve) => {
          submit = () => resolve(reply({ job: "test-job" }));
        });
      }
      if (url === "/api/job/test-job")
        return new Promise((resolve) => {
          job = (state) =>
            resolve(
              reply({
                state,
                events: [
                  { time: "11:59", message: "SIMULATED process launch", pid: 1234 },
                  { time: "12:00", message: "SIMULATED " + state },
                ],
              }),
            );
        });
      return reply({ deployments: [], available: false, items: [] });
    },
  });
  await f.console();
  await settle();
  const { w, run } = f,
    doc = w.document;
  const style = doc.createElement("style");
  style.textContent = fs.readFileSync(
    path.join(root, "frontend/assets/atlas-theme.css"),
    "utf8",
  );
  doc.head.append(style);
  for (const id of ["fresh", "bulkFresh"]) {
    const control = doc.getElementById(id);
    assert.equal(control.getAttribute("role"), "switch");
    assert.equal(w.getComputedStyle(control).width, "36px");
    assert.equal(w.getComputedStyle(control).height, "22px");
    assert.equal(control.checked, false);
    control.click();
    assert.equal(
      control.checked,
      true,
      "native switch changes its checked state",
    );
    control.click();
    assert.equal(control.checked, false);
  }
  assert.equal(
    w.getComputedStyle(doc.getElementById("softwareCache")).width,
    "16px",
  );
  if (!doc.querySelector("#deploymentPanel").dataset.installed) {
    doc.dispatchEvent(new w.Event("DOMContentLoaded"));
    await settle();
  }
  const panel = doc.querySelector("#deploymentPanel"),
    picker = doc.querySelector("#packagePicker"),
    select = doc.querySelector("#pkg");
  const originalMedia = w.matchMedia;
  w.matchMedia = (query) =>
    query.includes("760px") ? { matches: false } : originalMedia(query);
  run("S.target='PC-A';syncDeploymentPanel()");
  assert.equal(panel.parentElement.id, "workspace");
  assert(!panel.hidden);
  assert.strictEqual(doc.querySelector("#workspace #deploymentPanel"), panel);
  assert.equal(select.value, "A");
  assert.equal(
    doc.querySelector("#packageSelection").textContent,
    "Application A · 1",
  );
  assert(doc.querySelector("#deploymentProgress").hidden);
  assert.equal(doc.querySelector("#log").textContent, "");
  assert(!doc.querySelector(".deployment-advanced").open);
  assert(doc.querySelector("#copyOnly").closest(".deployment-advanced"));

  picker.open = true;
  await settle();
  doc.querySelector("#pkgSearch").value = "B";
  await run("packages()");
  assert.equal(select.value, "A", "filtering retains the current package");
  select.value = "B";
  select.dispatchEvent(new w.Event("change", { bubbles: true }));
  await settle();
  assert(!picker.open, "selection commits immediately");
  doc.body.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
  assert.equal(select.value, "B", "outside click never restores the old package");
  assert.equal(doc.querySelector("#script").value, "B_Install.ps1");
  assert(!doc.querySelector("#choosePackage"));
  picker.open = true;
  await settle();
  doc.querySelector("#pkgSearch").value = "slow";
  const pendingSearch = run("packages()");
  run("cancelPackageChoice()");
  await settle();
  slowSearch();
  await pendingSearch;
  assert.equal(
    select.value,
    "B",
    "a cancelled search cannot replace the package",
  );

  picker.open = true;
  await settle();
  doc.querySelector("#pkgSearch").value = "B";
  await run("packages()");
  select.value = "B";
  select.dispatchEvent(new w.Event("change", { bubbles: true }));
  await settle();
  assert(!picker.open);
  assert.equal(select.value, "B");
  assert.equal(
    doc.querySelector("#packageSelection").textContent,
    "Application B · 1",
  );
  doc.querySelector("#favBtn").click();
  assert.equal(
    doc.querySelector("#favBtn").getAttribute("aria-pressed"),
    "true",
  );
  picker.open = true;
  await settle();
  doc.querySelector("#pkgSearch").value = "A";
  await run("packages()");
  doc.querySelector('[data-recent="B"]').click();
  await settle();
  assert.equal(
    select.value,
    "B",
    "a favourite outside filtered results can be selected",
  );
  doc.querySelector('[data-deploy-action="Repair"]').click();
  await settle();
  assert.equal(doc.querySelector("#action").value, "Repair");
  assert.equal(doc.querySelector("#script").value, "B_Repair.ps1");
  assert.equal(
    doc
      .querySelector('[data-deploy-action="Repair"]')
      .getAttribute("aria-pressed"),
    "true",
  );

  run('page("bulk")');
  await settle();
  const bulk = doc.querySelector("#bulkPkg");
  bulk.value = "B";
  bulk.dispatchEvent(new w.Event("change", { bubbles: true }));
  await settle();
  doc.querySelector("#bulkSearch").value = "A";
  await run("bulkPackages()");
  assert.equal(bulk.value, "B", "bulk filtering retains selection");
  doc.querySelector('[data-bulk-action="Uninstall"]').click();
  await settle();
  assert.equal(doc.querySelector("#bulkScript").value, "B_Uninstall.ps1");
  assert.equal(doc.querySelector('[data-bulk-action="Uninstall"]').getAttribute("aria-pressed"), "true");
  assert(doc.querySelector("#bulkStart").disabled, "no targets cannot launch");
  doc.querySelector("#bulkTargets").value = "PC-A PC-A PC-B";
  run("refreshBulkSelection()");
  assert.equal(doc.querySelector("#bulkStart").textContent, "Uninstall on 2 machines");
  assert(!doc.querySelector("#bulkStart").disabled);
  const bulkRun = run("startBulk()");
  await settle();
  await run("startBulk()");
  assert.equal(bulkWrites.length, 1, "double submit starts only one bulk job");
  bulk.value = "A";
  assert.equal(bulkWrites[0].folder, "B", "submitted package is immutable");
  assert.equal(bulkWrites[0].action, "Uninstall");
  assert.deepEqual(bulkWrites[0].computers, ["PC-A", "PC-B"]);
  bulkSubmit();
  await bulkRun;
  run('page("workspace")');
  doc.querySelector("#fresh").click();
  const deployment = run("deploy()");
  await settle();
  assert(doc.querySelector("#deploy").disabled);
  await run("deploy()");
  assert.equal(writes.length, 1, "submitting cannot create duplicate jobs");
  run("S.target='PC-B';syncDeploymentPanel()");
  submit();
  await deployment;
  await settle();
  assert.equal(writes[0].computer, "PC-A");
  assert.equal(writes[0].folder, "B");
  assert.equal(writes[0].action, "Repair");
  assert.equal(writes[0].script, "B_Repair.ps1");
  assert.equal(
    writes[0].fresh,
    true,
    "Fresh-copy choice reaches the deployment payload",
  );
  job("failed");
  await settle();
  assert(
    doc.querySelector("#deploymentProgress").hidden,
    "PC-A's result is not shown as PC-B's result",
  );
  run("S.target='PC-A';syncDeploymentPanel()");
  assert(!doc.querySelector("#deploymentProgress").hidden);
  assert.equal(doc.querySelector("#deploymentJobTarget").textContent, "PC-A");
  assert.equal(doc.querySelector("#deploymentState").textContent, "Failed", "the final failure takes precedence over an earlier PID event");
  assert(doc.querySelector("#deploymentLog").open);
  assert.match(doc.querySelector("#log").textContent, /SIMULATED failed/);
  run("clearLookup()");
  assert(panel.hidden);
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(f.errors.length, 0, f.errors.join("\n"));
  w.close();
  console.log(
    "PASS: Workspace deployment column, searchable picker cancellation/favourites, action selection, immutable submission, duplicate prevention and target-specific progress",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
