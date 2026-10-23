import { animate } from "motion";

export function installMotionBridge() {
  const running = new Map();
  const reduced = () =>
    window.AtlasUI.motion.isReduced() || window.AtlasUI.performance.isCitrix();
  function stop(node) {
    const animation = running.get(node);
    if (!animation) return;
    animation.stop();
    running.delete(node);
    node.style.removeProperty("transform");
    node.style.removeProperty("opacity");
  }
  function clear() {
    for (const node of [...running.keys()]) stop(node);
  }
  function play(node, frames, duration) {
    if (!node?.isConnected || reduced() || document.hidden) return;
    stop(node);
    const animation = animate(node, frames, {
      duration,
      ease: [0.22, 1, 0.36, 1],
    });
    running.set(node, animation);
    animation.then(() => {
      if (running.get(node) === animation) {
        running.delete(node);
        node.style.removeProperty("transform");
        node.style.removeProperty("opacity");
      }
    });
  }
  document.addEventListener("pointerdown", (event) => {
    const button = event.target.closest?.("button");
    if (
      !button ||
      button.disabled ||
      button.closest(
        ".atlas-interactions-host, #map-labels, .atlas-command-host",
      ) ||
      event.button !== 0
    )
      return;
    play(button, { scale: [1, 0.97, 1] }, 0.16);
  });
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest?.(".toolmenu-btn");
    if (!trigger) return;
    requestAnimationFrame(() => {
      const content = trigger
        .closest(".menu-open")
        ?.querySelector(".toolmenu-content");
      if (content) play(content, { opacity: [0, 1], scale: [0.985, 1] }, 0.14);
    });
  });
  window.addEventListener("atlas-motion-change", () => {
    if (reduced()) clear();
  });
  window.addEventListener("pagehide", clear);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clear();
  });
  return {
    animateMenu: (node) =>
      play(node, { opacity: [0.4, 1], scale: [0.985, 1] }, 0.14),
  };
}
