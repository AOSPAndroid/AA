// Native dialog close events are queued. All actions here use fictional local UI.
const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  path = require("node:path"),
  vm = require("node:vm"),
  { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, ".."),
  settle = () => new Promise((resolve) => setTimeout(resolve, 10));
async function moduleFor(file, context, cache = new Map()) {
  if (cache.has(file)) return cache.get(file);
  const module = new vm.SourceTextModule(fs.readFileSync(file, "utf8"), {
    context,
    identifier: file,
  });
  cache.set(file, module);
  await module.link((spec) =>
    moduleFor(path.resolve(path.dirname(file), spec), context, cache),
  );
  await module.evaluate();
  return module;
}
async function fixture({ readOnly = false } = {}) {
  const dom = new JSDOM(
      '<header></header><iframe id="editor"></iframe><textarea id="notes"></textarea><button id="dock">Notes</button>',
      {
        url: "http://127.0.0.1:8770/",
        runScripts: "outside-only",
        pretendToBeVisual: true,
      },
    ),
    w = dom.window,
    d = w.document;
  const deepFocus = () => {
    let el = d.activeElement;
    while (el?.shadowRoot?.activeElement) el = el.shadowRoot.activeElement;
    return el;
  };
  w.HTMLElement.prototype.scrollIntoView = function () {};
  // Emulate native synchronous focus restoration followed by its queued event.
  w.HTMLDialogElement.prototype.showModal = function () {
    this.returnFocus = deepFocus();
    this.open = true;
  };
  w.HTMLDialogElement.prototype.close = function () {
    if (!this.open) return;
    this.open = false;
    this.returnFocus?.focus();
    setTimeout(() => this.dispatchEvent(new w.Event("close")), 0);
  };
  const { namespace } = await moduleFor(
    path.join(root, "atlas/command-palette.js"),
    dom.getInternalVMContext(),
  );
  let run = () => {};
  const palette = namespace.installCommandPalette({
    triggerParent: d.querySelector("header"),
    getRecords: () => [],
    toast: (text) => {
      throw Error(text);
    },
    onSelect() {},
    openPerson() {},
    openMachine() {},
    runCommand: (id) => run(id),
    readOnly,
  });
  return {
    w,
    d,
    palette,
    deepFocus,
    setRun: (value) => {
      run = value;
    },
    async choose(action) {
      await palette.open("> " + action);
      const rows = [...palette.root.querySelectorAll("[role=option]")];
      assert.equal(rows.length, 1, "Fixture selects one real action");
      assert.equal(rows[0].getAttribute("aria-disabled"), "false");
      rows[0].click();
      await settle();
    },
    close() {
      w.close();
    },
  };
}
(async () => {
  let f = await fixture();
  f.d.getElementById("editor").focus();
  f.setRun((id) => {
    assert.equal(id, "kb-notes");
    f.d.getElementById("notes").focus();
  });
  await f.choose("Write notes");
  assert.equal(
    f.deepFocus().id,
    "notes",
    "Queued close must preserve command-selected notes focus",
  );
  f.close();

  f = await fixture({ readOnly: true });
  f.d.getElementById("notes").focus();
  f.setRun((id) => {
    assert.equal(id, "kb-focus", "Viewer exposes the safe focus command");
    f.d.getElementById("notes").hidden = true;
    f.d.getElementById("dock").focus();
  });
  await f.choose("Focus knowledge editor");
  assert.equal(
    f.deepFocus().id,
    "dock",
    "A collapsed pane cannot regain focus after a command",
  );
  f.close();

  f = await fixture();
  f.d.getElementById("notes").focus();
  f.setRun(() => f.d.getElementById("editor").focus());
  await f.choose("Fit diagram");
  assert.equal(
    f.deepFocus().id,
    "editor",
    "Queued close must preserve iframe focus",
  );
  f.close();

  f = await fixture();
  const host = f.d.createElement("div"),
    shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = '<button id="shadow">Shadow target</button>';
  f.d.body.append(host);
  const shadowButton = shadow.querySelector("button");
  shadowButton.focus();
  await f.palette.open();
  f.palette.dialog.dispatchEvent(new f.w.Event("cancel"));
  f.palette.dialog.close();
  await settle();
  assert.equal(
    f.deepFocus(),
    shadowButton,
    "Cancel returns to the original connected shadow control",
  );
  f.close();

  for (const unavailable of [
    "hidden",
    "removed",
    "inert",
    "css-hidden",
    "closed-dialog",
  ]) {
    f = await fixture();
    const prior = f.d.getElementById("notes");
    prior.focus();
    await f.palette.open();
    if (unavailable === "hidden") prior.hidden = true;
    else if (unavailable === "removed") prior.remove();
    else if (unavailable === "inert") prior.inert = true;
    else if (unavailable === "css-hidden") prior.style.display = "none";
    else {
      const closed = f.d.createElement("dialog");
      closed.append(prior);
      f.d.body.append(closed);
    }
    f.palette.close();
    await settle();
    assert.equal(
      f.deepFocus(),
      f.palette.root.querySelector("#atlas-commands"),
      unavailable + " previous target uses visible palette trigger",
    );
    f.close();
  }

  f = await fixture();
  f.d.getElementById("notes").focus();
  f.setRun(() => {
    const modal = f.d.createElement("dialog");
    modal.innerHTML = '<input id="confirmation">';
    f.d.body.append(modal);
    modal.showModal();
    modal.querySelector("input").focus();
  });
  await f.choose("Fit diagram");
  assert.equal(
    f.deepFocus().id,
    "confirmation",
    "Opening another modal preserves its own focus",
  );
  f.close();

  f = await fixture();
  f.d.getElementById("notes").focus();
  await f.palette.open();
  f.palette.close();
  await f.palette.open("> Write notes");
  await settle();
  assert(f.palette.dialog.open);
  assert.equal(
    f.deepFocus(),
    f.palette.root.querySelector("input"),
    "Old queued close cannot steal focus from a reopened palette",
  );
  assert.equal(f.palette.root.querySelectorAll("[role=option]").length, 1);
  f.close();
  console.log(
    "PASS: queued palette close preserves Notes/editor/modal command focus, cancel returns safely across shadow roots, hidden/disconnected targets use a visible fallback, and reopen ignores obsolete close events",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
