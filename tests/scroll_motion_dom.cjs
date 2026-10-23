const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const settle = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  const dom = new JSDOM(
    '<!doctype html><body><article class="machine">Visible content</article></body>',
    {
      url: "http://localhost",
      runScripts: "outside-only",
      pretendToBeVisual: true,
    },
  );
  const w = dom.window,
    watched = new Set(),
    effects = [];
  let intersect;
  w.matchMedia = () => ({ matches: false, addEventListener() {} });
  w.IntersectionObserver = class {
    constructor(callback) {
      intersect = callback;
    }
    observe(element) {
      watched.add(element);
    }
    unobserve(element) {
      watched.delete(element);
    }
    disconnect() {
      watched.clear();
    }
  };
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
  w.eval(
    fs.readFileSync(
      path.join(__dirname, "../frontend/assets/shared-ui.js"),
      "utf8",
    ),
  );
  await settle();
  const card = w.document.querySelector(".machine");
  assert(watched.has(card));
  assert.equal(
    card.style.opacity,
    "",
    "scroll effects never hide readable content before observation",
  );
  intersect([{ target: card, isIntersecting: false }]);
  assert.equal(effects.length, 0);
  intersect([{ target: card, isIntersecting: true }]);
  assert.equal(effects.length, 1);
  assert(!watched.has(card), "a card reveals only once");
  assert.equal(effects[0].options.duration, 320);
  w.AtlasUI.motion.toggle();
  assert(
    effects[0].cancelled,
    "switching animations off cancels in-flight scroll effects",
  );
  assert.equal(watched.size, 0);
  const second = w.document.createElement("article");
  second.className = "viewer-machine";
  second.textContent = "Viewer machine";
  w.document.body.append(second);
  await settle();
  assert.equal(watched.size, 0, "no scroll observer runs with animations off");
  w.AtlasUI.motion.reveal(second);
  assert.equal(effects.length, 1);
  w.AtlasUI.motion.toggle();
  assert(watched.has(second));
  assert(!watched.has(card));
  intersect([{ target: second, isIntersecting: true }]);
  assert.equal(effects.length, 2);
  second.remove();
  await settle();
  assert(effects[1].cancelled);
  const cards = Array.from({ length: 12 }, () => {
    const element = w.document.createElement("div");
    element.className = "atlas-health-item";
    w.document.body.append(element);
    return element;
  });
  await settle();
  const count = effects.length;
  intersect(cards.map((target) => ({ target, isIntersecting: true })));
  assert.equal(
    effects.length - count,
    6,
    "large batches limit simultaneous effects",
  );
  assert.equal(watched.size, 0);
  assert.deepEqual(
    effects.slice(count).map((e) => e.options.delay),
    [0, 32, 64, 96, 128, 160],
    "Stagger is bounded so a long list cannot delay reading",
  );
  const panel = w.document.createElement("section");
  w.document.body.append(panel);
  panel.append(cards[0]);
  const cardEffect = effects[count];
  w.AtlasUI.motion.slideUp(panel);
  assert(
    cardEffect.cancelled,
    "A parent entrance replaces active child motion",
  );
  const panelEffect = effects.at(-1),
    nestedCount = effects.length;
  w.AtlasUI.motion.reveal(cards[0]);
  assert.equal(
    effects.length,
    nestedCount,
    "Child effects cannot stack inside a moving panel",
  );
  panelEffect.onfinish();
  w.AtlasUI.motion.reveal(cards[0]);
  assert.equal(
    effects.length,
    nestedCount + 1,
    "Completed effects release the panel",
  );
  Object.defineProperty(w.document, "hidden", {
    configurable: true,
    value: true,
  });
  w.document.dispatchEvent(new w.Event("visibilitychange"));
  assert(effects.at(-1).cancelled, "Leaving the tab cancels running motion");
  Object.defineProperty(w.document, "hidden", {
    configurable: true,
    value: false,
  });
  w.dispatchEvent(new w.Event("pagehide"));
  assert(effects.every((effect) => effect === panelEffect || effect.cancelled));
  w.AtlasUI.performance.setDisplay("citrix");
  const remoteCard = w.document.createElement("div");
  remoteCard.className = "machine";
  w.document.body.append(remoteCard);
  await settle();
  assert.equal(watched.size, 0, "Citrix mode disconnects scroll observation");
  const remoteCount = effects.length;
  w.AtlasUI.motion.reveal(remoteCard);
  assert.equal(
    effects.length,
    remoteCount,
    "Citrix mode skips decorative Web Animations",
  );
  assert.equal(
    w.AtlasUI.motion.isReduced(),
    false,
    "Display profile preserves the separate animation preference",
  );
  w.AtlasUI.performance.setDisplay("standard");
  assert(watched.has(remoteCard), "Standard mode restores scroll observation");
  w.dispatchEvent(new w.Event("pagehide"));
  w.close();
  console.log(
    "PASS: shared scroll reveals, readable fallback, reduced motion, single entry, removed-card cleanup and bounded batches",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
