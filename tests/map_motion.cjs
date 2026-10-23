// Real map handlers with a deterministic clock; no network or remote actions.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { fixture, root } = require("./ui_fixture.cjs");

(async () => {
  for (const readOnly of [false, true]) {
    const data = JSON.parse(
      fs.readFileSync(path.join(root, "atlas/official-data.json"), "utf8"),
    );
    const f = await fixture({
      html: "atlas/official-index.html",
      url: "http://127.0.0.1:8892/",
      fetch: async (url) => {
        const desk = data.records.find((r) => String(url).includes(r.id));
        return {
          ok: true,
          json: async () =>
            String(url).includes("official-data.json")
              ? data
              : desk
                ? {
                    desk,
                    user: null,
                    candidates: [],
                    machines: [
                      {name:'GBRPWMF123',assigned_relationship:1,relationship_group:'Assigned to user'},
                      {name:'PARPWMK123',assigned_relationship:1,relationship_group:'Assigned to user'},
                      {name:'NYKPWMK456',relationship_group:'Last logged on (inventory)'},
                      {name:'SGPPWMVDI123',relationship_group:'Last logged on (inventory)'}
                    ],
                    deployments: [],
                    match_method: "unmatched",
                  }
                : {
                    records: data.records,
                    legacy: [],
                    mappings: {},
                    token: "test",
                  },
        };
      },
    });
    const { w } = f;
    if (readOnly) {
      const meta = w.document.createElement("meta");
      meta.name = "atlas-mode";
      meta.content = "viewer";
      w.document.head.append(meta);
    }
    const entrances=[];
    w.HTMLElement.prototype.animate=function(keyframes,options){
      const animation={element:this,keyframes,options,cancel(){this.oncancel?.()}};
      entrances.push(animation);return animation;
    };
    let clock = 0,
      id = 0,
      uploads = 0;
    const frames = new Map();
    assert.equal(
      w.AtlasUI.motion.isReduced(),
      true,
      "System respects reduced motion",
    );
    w.AtlasUI.motion.install(w.document.body);
    const motionControl = w.document.querySelector(
      ".atlas-motion-toggle input",
    );
    assert.equal(motionControl.checked, false);
    motionControl.click();
    assert.equal(
      w.AtlasUI.motion.isReduced(),
      false,
      "Explicit On overrides system preference",
    );
    assert.equal(w.localStorage.getItem("atlas-motion"), "full");
    assert.equal(w.document.documentElement.dataset.atlasMotion, "full");
    w.performance.now = () => clock;
    w.requestAnimationFrame = (fn) => {
      frames.set(++id, fn);
      return id;
    };
    w.cancelAnimationFrame = (key) => frames.delete(key);
    const step = (ms) => {
      clock += ms;
      const pending = [...frames];
      frames.clear();
      for (const [, fn] of pending) fn(clock);
    };
    let gpuAvailable = true, shaderWorks = true, gpuDraws = 0;
    const gl = new Proxy(
      {
        bufferData: () => uploads++,
        getShaderParameter: () => shaderWorks,
        getShaderInfoLog: () => "Simulated shader failure",
        drawArrays: () => gpuDraws++,
        getProgramParameter: () => true,
      },
      { get: (o, k) => o[k] || (() => ({})) },
    );
    const ctx = new Proxy({}, { get: () => () => ({}) });
    w.HTMLCanvasElement.prototype.getContext = (type) =>
      type === "webgl" ? (gpuAvailable ? gl : null) : type === "2d" ? ctx : null;
    const captures = new Map();
    w.HTMLCanvasElement.prototype.setPointerCapture = function (id) {
      captures.set(id, this);
    };
    w.HTMLCanvasElement.prototype.hasPointerCapture = function (id) {
      return captures.get(id) === this;
    };
    w.HTMLCanvasElement.prototype.releasePointerCapture = function (id) {
      captures.delete(id);
      const event = new w.Event("lostpointercapture");
      Object.defineProperty(event, "pointerId", { value: id });
      this.dispatchEvent(event);
    };
    const viewport = { clientWidth: 900, clientHeight: 650 };
    let resize;
    w.ResizeObserver = class { constructor(callback) { resize = callback; } observe() {} };
    w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: viewport.clientWidth,
      height: viewport.clientHeight,
      right: viewport.clientWidth,
    });
    for (const [key, value] of [
      ["clientWidth", 900],
      ["clientHeight", 650],
    ])
      Object.defineProperty(w.HTMLCanvasElement.prototype, key, {
        get: () => viewport[key],
      });
    const t = await f.map(`
    export {fitTarget, mapArea, modelPoint, resetCam, selectRecord, renderDetail, setFloor, setView, focusTarget, cameraMotion, inversePoint, projected, world, deskLayoutAngle, settleMotion, draw};
    export function graphicsState(){return {ready:glReady,error:glError,view}}
    export function state(){return {...cam}}
    export function currentCanvas(){return canvas}
    export function setCamera(value){cam = {...cam, ...value}; draw()}
    export function selection(){return selected?.id}
  `);
    const close = (a, b) => {
      for (const key of Object.keys(a))
        assert(Math.abs(a[key] - b[key]) < 1e-8, key);
    };
    step(0);
    const people = data.records.filter(
      (r) => r.floor === 2 && r.kind === "desk",
    );
    assert(people.length > 1);
    const angledDesk = data.records.find((r) => r.id === "03R023070");
    assert(angledDesk);
    assert(t.deskLayoutAngle(angledDesk) > 25 && t.deskLayoutAngle(angledDesk) < 70,
      "An angled desk bank produces an angled selection footprint");
    const initial = t.state();
    t.selectRecord(people[0].id);
    const inspector = w.document.querySelector("#detail");
    const panelEntrances=()=>entrances.filter(e=>e.element===inspector);
    assert.equal(panelEntrances().length,1,'Clicking a person slides up the right panel');
    assert.equal(panelEntrances()[0].keyframes[0].transform,'translateY(58px) scale(0.985)');
    inspector.scrollTop = 320;
    t.renderDetail();
    assert.equal(panelEntrances().length,1,"Refreshing details does not replay selection motion");
    assert.equal(
      inspector.scrollTop,
      320,
      "rerendering an existing inspector preserves its reading position",
    );
    t.selectRecord(people[0].id);
    assert.equal(
      inspector.scrollTop,
      0,
      "reselecting the current desk reveals its inspector heading",
    );
    assert(inspector.classList.contains("open"));
    close(t.state(), initial);
    assert(t.cameraMotion.active);
    step(360);
    assert.notDeepEqual(t.state(), initial, "focus changes over time");
    assert.equal(frames.size, 1, "only one render callback owns camera motion");
    // A newer selection continues from the current position and owns the endpoint.
    const middle = t.state();
    inspector.scrollTop = 320;
    t.selectRecord(people[1].id);
    assert.equal(
      inspector.scrollTop,
      0,
      "selecting another desk reveals its inspector heading",
    );
    close(t.state(), middle);
    const goal = t.focusTarget(people[1]);
    step(720);
    close(t.state(), goal);
    assert.equal(t.cameraMotion.active, false);
    assert.equal(frames.size, 0, "completed flight leaves no camera loop");

    t.selectRecord(people[0].id);
    step(100);
    const interrupted = t.state();
    t.currentCanvas().dispatchEvent(
      new w.MouseEvent("pointerdown", {
        clientX: 400,
        clientY: 250,
        button: 0,
      }),
    );
    assert.equal(t.cameraMotion.active, false);
    assert.equal(t.currentCanvas().dataset.mapCursor, "drag");
    step(900);
    close(t.state(), interrupted);
    t.currentCanvas().dispatchEvent(
      new w.MouseEvent("pointerup", { button: 2 }),
    );
    assert.notEqual(t.currentCanvas().dataset.mapCursor, "drag");

    t.selectRecord(people[0].id);
    t.setFloor(4);
    assert.equal(
      t.cameraMotion.active,
      false,
      "floor change cancels old destination",
    );
    step(0);
    w.document.querySelector("#zoom-in").click();
    w.document.querySelector("#zoom-in").click();
    const zoomStart = t.state().scale;
    step(200);
    assert(
      Math.abs(t.state().scale - zoomStart * 1.25 ** 2) < 1e-8,
      "rapid zoom clicks accumulate",
    );

    const anchor = [330, 240],
      beforeAnchor = t.inversePoint(...anchor);
    t.currentCanvas().dispatchEvent(
      new w.WheelEvent("wheel", {
        clientX: anchor[0],
        clientY: anchor[1],
        deltaY: -100,
        cancelable: true,
      }),
    );
    step(200);
    const afterAnchor = t.inversePoint(...anchor);
    assert(
      Math.hypot(...beforeAnchor.map((n, i) => n - afterAnchor[i])) < 1e-8,
      "wheel zoom preserves cursor anchor",
    );

    t.setView("3d", true);
    assert.equal(t.currentCanvas().dataset.mapCursor, "default");
    assert(t.currentCanvas().style.cursor.includes("data:image/svg+xml"));
    assert(t.currentCanvas().style.cursor.endsWith("3 2, default"));
    const hoverCursor = w.document.querySelector("#viewport").style.getPropertyValue("--atlas-map-hover");
    assert(hoverCursor.includes("data:image/svg+xml"));
    assert(hoverCursor.endsWith("12 2, pointer"));
    assert.notEqual(hoverCursor, t.currentCanvas().style.cursor);
    step(480);
    const uploadCount = uploads;
    w.document.querySelector("#rotate").click();
    for (let i = 0; i < 24; i++) step(16);
    assert.equal(uploads, uploadCount, "animation reuses WebGL geometry");
    assert.equal(frames.size, 0);

    const pointer = (type, x, y, options = {}, target = t.currentCanvas()) => {
      const event = new w.MouseEvent(type, {
        clientX: x,
        clientY: y,
        button: 0,
        cancelable: true,
        ...options,
      });
      Object.defineProperty(event, "pointerId", {
        value: options.pointerId || 1,
      });
      target.dispatchEvent(event);
    };
    // The grabbed point follows the pointer exactly, at different zooms and angles.
    for (const mode of ["plan", "3d"]) {
      t.setView(mode);
      for (const scale of [0.5, 2, 8]) {
        t.setCamera({ scale, yaw: mode === "3d" ? 1.1 : 0 });
        step(0);
        const start = [620, 220],
          end = [697, 271],
          grabbed = t.inversePoint(...start),
          before = t.state();
        const selection = t.selection();
        pointer("pointerdown", ...start);
        pointer("pointermove", 650, 240);
        // Changing Shift after the drag begins must not switch modes or jump.
        pointer("pointermove", ...end, { shiftKey: true });
        close(t.inversePoint(...end), grabbed);
        assert.equal(
          t.state().yaw,
          before.yaw,
          "left-drag pans without rotation",
        );
        assert.equal(t.state().tilt, before.tilt);
        assert.equal(t.state().scale, scale);
        pointer("pointerup", ...end);
        assert.equal(
          t.selection(),
          selection,
          "dragging does not select a desk",
        );
        assert.equal(captures.size, 0);
        step(0);
        assert.equal(frames.size, 0, "dragging adds no idle animation loop");
      }
    }

    for (const orbitButton of [{ button: 2 }, { button: 0, shiftKey: true }]) {
      t.setCamera({ scale: 2, yaw: 0.7, tilt: 0.9 });
      step(0);
      const pivot = [680, 210],
        floorPoint = t.inversePoint(...pivot),
        beforeOrbit = t.state();
      const orbitUploads = uploads;
      const orbitSelection = t.selection();
      pointer("pointerdown", ...pivot, orbitButton);
      pointer("pointermove", 740, 250, { shiftKey: false });
      close(t.inversePoint(...pivot), floorPoint);
      assert.notEqual(t.state().yaw, beforeOrbit.yaw);
      assert.notEqual(t.state().tilt, beforeOrbit.tilt);
      assert.notEqual(
        t.state().cx,
        beforeOrbit.cx,
        "rotation uses the grabbed point, not a fixed centre",
      );
      pointer("pointermove", 760, 2000);
      close(t.inversePoint(...pivot), floorPoint);
      assert(
        t.state().tilt < Math.PI / 2,
        "tilt stays above the floor without flipping",
      );
      pointer("pointermove", 760, -2000);
      close(t.inversePoint(...pivot), floorPoint);
      assert(t.state().tilt > 0, "tilt never reaches the singular horizon");
      pointer("pointerup", 760, -2000, { button: orbitButton.button });
      if (orbitButton.button === 2) {
        pointer("contextmenu", 760, -2000, { button: 2 });
        assert.equal(
          w.document.querySelector(".desk-menu"),
          null,
          "right-drag does not open a desk menu",
        );
        assert.equal(
          t.selection(),
          orbitSelection,
          "right-drag does not inspect another desk",
        );
        assert.equal(t.cameraMotion.active, false);
      }
      step(0);
      assert.equal(
        uploads,
        orbitUploads,
        "manual rotation reuses cached geometry",
      );
      assert.match(
        w.document.querySelector("#hint").textContent,
        /Right-drag to rotate/,
      );
    }

    // The instructions remain visible when names are hidden, too.
    w.document.querySelector("#name-tags").click();
    step(0);
    assert.match(
      w.document.querySelector("#hint").textContent,
      /Right-drag to rotate/,
    );
    w.document.querySelector("#name-tags").click();

    // Normal clicks retain selection; several tiny moves form a drag, not a click.
    t.setFloor(2);
    t.selectRecord(people[1].id);
    step(720);
    const clickPoint = t.projected(t.world(people[0])).slice(0, 2);
    pointer("pointerdown", ...clickPoint);
    pointer("pointerup", ...clickPoint);
    assert.equal(
      t.selection(),
      people[0].id,
      "a simple click still selects a desk",
    );
    step(720);
    let deskPoint = t.projected(t.world(people[0])).slice(0, 2);
    pointer("pointerdown", ...deskPoint, { button: 2 });
    pointer("pointermove", deskPoint[0] + 25, deskPoint[1] + 15);
    pointer("pointerup", deskPoint[0] + 25, deskPoint[1] + 15, { button: 2 });
    step(0);
    deskPoint = t.projected(t.world(people[0])).slice(0, 2);
    // Context-menu events can arrive on release, directly over a real desk.
    pointer("contextmenu", ...deskPoint, { button: 2 });
    assert.equal(w.document.querySelector(".desk-menu"), null);
    assert.equal(
      t.cameraMotion.active,
      false,
      "right-drag does not refocus a desk in the viewer",
    );
    const beforeRightClick = t.state();
    pointer("pointerdown", ...deskPoint, { button: 2 });
    pointer("pointerup", ...deskPoint, { button: 2 });
    close(t.state(), beforeRightClick);
    pointer("contextmenu", ...deskPoint, { button: 2 });
    if (readOnly) {
      assert.equal(
        t.selection(),
        people[0].id,
        "viewer right-click still inspects the desk",
      );
      const menu = w.document.querySelector(".desk-menu");
      assert(menu, "viewer right-click exposes the stored-directory group lookup");
      assert.equal(menu.querySelectorAll("button").length, 1);
      assert.equal(menu.querySelector("button").textContent, "See groups");
      assert.equal(menu.querySelector("[data-action]"), null, "viewer has no desk editing actions");
    } else {
      assert(
        w.document.querySelector(".desk-menu"),
        "admin right-click still opens desk actions",
      );
      w.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape" }));
    }
    pointer("pointerdown", ...deskPoint);
    for (let delta = 1; delta <= 8; delta++)
      pointer("pointermove", deskPoint[0] + delta, deskPoint[1]);
    pointer("pointerup", deskPoint[0] + 8, deskPoint[1]);
    assert.equal(
      t.cameraMotion.active,
      false,
      "slow dragging is not mistaken for a click",
    );

    for (const interrupt of [
      "pointercancel",
      "lostpointercapture",
      "blur",
      "view",
      "floor",
    ]) {
      t.setView("3d");
      const oldCanvas = t.currentCanvas();
      pointer("pointerdown", 430, 310);
      pointer("pointermove", 450, 330);
      if (interrupt === "view") t.setView("plan");
      else if (interrupt === "floor") t.setFloor(4);
      else if (interrupt === "blur") w.dispatchEvent(new w.Event("blur"));
      else pointer(interrupt, 450, 330);
      const stopped = t.state();
      pointer("pointermove", 540, 400, {}, oldCanvas);
      pointer("pointerup", 540, 400, {}, oldCanvas);
      close(t.state(), stopped);
      assert.equal(captures.size, 0, interrupt + " releases capture");
      assert.notEqual(oldCanvas.dataset.mapCursor, "drag");
    }

    t.selectRecord(people[0].id);
    const reducedGoal = t.focusTarget(people[0]);
    motionControl.click();
    assert(
      [...w.document.querySelectorAll(".atlas-motion-toggle input")].every(
        (el) => !el.checked,
      ),
    );
    close(t.state(), reducedGoal);
    assert.equal(
      t.cameraMotion.active,
      false,
      "changing motion preference completes current flight",
    );
    t.selectRecord(people[1].id);
    close(t.state(), t.focusTarget(people[1]));
    assert.equal(t.cameraMotion.active, false, "reduced motion is immediate");
    step(0);
    assert.equal(frames.size, 0);
    assert.equal(
      w.localStorage.getItem("atlas-motion"),
      "reduce",
      "Off is remembered",
    );
    w.localStorage.setItem("atlas-motion", "full");
    w.dispatchEvent(new w.StorageEvent("storage", { key: "atlas-motion" }));
    assert(
      [...w.document.querySelectorAll(".atlas-motion-toggle input")].every(
        (el) => el.checked,
      ),
      "Switches follow changes in another tab",
    );
    await new Promise(setImmediate);
    const display = w.document.querySelector('.atlas-display-mode select');
    assert(display, 'Display mode available in shared admin/viewer header');
    display.value='citrix';display.dispatchEvent(new w.Event('change'));
    assert(w.AtlasUI.performance.isCitrix());
    assert.equal(w.localStorage.getItem('atlas-display-mode'),'citrix');
    t.setView('3d');step(34);
    t.selectRecord(people[0].id);step(140);
    assert(t.cameraMotion.active);
    assert.equal(t.currentCanvas().width,675,'Moving 3D uses 75% resolution');
    assert.equal(w.document.querySelectorAll('.map-name:not([hidden]):not(.chosen)').length,0,'Only selected person label moves in remote mode');
    step(150);assert(!t.cameraMotion.active,'Remote camera completes within 280ms');
    close(t.state(),t.focusTarget(people[0]));
    t.settleMotion();step(34);
    assert.equal(t.currentCanvas().width,900,'Full resolution returns when settled');
    assert.equal(frames.size,0,'No idle rendering loop');
    const beforeFrames=gpuDraws, beforeUploads=uploads;
    for(let i=0;i<120;i++){ t.setCamera({cx:t.state().cx+.01});step(1000/120); }
    assert((gpuDraws-beforeFrames)/2<=31,'Remote rendering capped around 30 frames/s at 120Hz input');
    assert((gpuDraws-beforeFrames)/2>=29,'Latest pointer input continues rendering');
    assert.equal(uploads,beforeUploads,'Remote motion does not re-upload geometry');
    t.settleMotion();step(34);
    assert.equal(frames.size,0);
    w.localStorage.setItem('atlas-display-mode','standard');
    w.dispatchEvent(new w.StorageEvent('storage',{key:'atlas-display-mode'}));
    assert(!w.AtlasUI.performance.isCitrix());assert.equal(display.value,'standard');
    // Lost contexts rebuild cached buffers only after an explicit retry.
    const lostCanvas=t.currentCanvas(), loss=new w.Event('webglcontextlost',{cancelable:true});
    lostCanvas.dispatchEvent(loss);assert(loss.defaultPrevented);
    assert.equal(t.graphicsState().view,'plan');assert(!t.graphicsState().ready);
    gpuAvailable=false;t.setView('3d');assert(!t.graphicsState().ready);
    assert(t.graphicsState().error.includes('context creation failed'));
    gpuAvailable=true;shaderWorks=false;t.setView('3d');
    assert(t.graphicsState().error.includes('Simulated shader failure'));
    shaderWorks=true;lostCanvas.dispatchEvent(new w.Event('webglcontextrestored'));
    assert.equal(t.graphicsState().view,'plan','Recovery does not force 3D');
    t.setView('3d');step(34);assert(t.graphicsState().ready,'Explicit retry succeeds without reloading');
    assert.equal(t.graphicsState().view,'3d');assert(uploads>beforeUploads,'Recovered context gets fresh buffers');
    await new Promise(setImmediate);
    // Fit every floor in both renderers, including narrow / short remote windows.
    for (const [width, height] of [[420, 380], [900, 650], [1600, 440]]) {
      viewport.clientWidth = width; viewport.clientHeight = height;
      for (const mode of ["plan", "3d"]) {
        t.setView(mode);
        for (const floor of data.floors) {
          t.setFloor(floor.level); step(600);
          const area = t.mapArea();
          for (const point of floor.geometry.outline) {
            for (const elevation of mode === "3d" ? [0, 4] : [0]) {
              const [x, y] = t.projected(t.modelPoint(...point, floor.level, elevation));
              assert(x >= area.left - .01 && x <= area.right + .01, "Floor fits horizontally");
              assert(y >= area.top - .01 && y <= area.bottom + .01, "Floor fits vertically");
            }
          }
        }
      }
    }
    t.setFloor(2); t.setView("plan"); step(600);
    viewport.clientWidth = 600; resize(); step(600);
    close(t.state(), t.fitTarget());
    assert.equal(t.focusTarget(people[0]).scale, Math.min(3.025, t.fitTarget().scale * 2.2385),
      "Desk focus uses the second additional ten-percent zoom");
    t.selectRecord(people[0].id); step(430);
    assert(!t.cameraMotion.active, "Gentle focus completes within 420 ms");
    assert(t.state().scale <= 3.025, "Desk focus respects its zoom ceiling");
    const area = t.mapArea(), point = t.projected(t.world(people[0]));
    assert(Math.abs(point[0] - (area.left + area.right) / 2) < 1);
    assert(Math.abs(point[1] - (area.top + area.bottom) / 2) < 1);
    const manual = t.state(); viewport.clientWidth = 800; resize(); step(600);
    close(t.state(), manual); // Resizing must not undo a user's focused/panned view.
    await new Promise(setImmediate);
    const machineHost=w.document.querySelector(readOnly ? '#ops-context [data-machine-list]' : '.ops-machines');
    assert(machineHost, 'Both map modes expose filterable linked machines');
    const shown=()=>[...machineHost.querySelectorAll('[data-machine-kind]:not([hidden])')].map(row=>row.dataset.machineKind);
    machineHost.querySelector('[data-kind="kiosk"]').click();
    assert.deepEqual(shown(),['kiosk','kiosk']);
    machineHost.querySelector('[data-kind="vdi"]').click();
    assert.deepEqual(shown(),['kiosk','kiosk','vdi']);
    machineHost.querySelector('[data-kind="all"]').click();
    assert.deepEqual(shown(),['desktop','kiosk','kiosk','vdi']);

    assert.equal(f.errors.length, 0, f.errors.join("\n"));
    w.close();
  }
  console.log(
    "PASS: admin/viewer grab-to-pan, anchored 3D rotation, click/drag distinction, capture cleanup, animated focus, zoom anchoring, cached rendering and reduced motion",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
