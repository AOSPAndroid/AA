// Native cursor images stay responsive without a pointer-following DOM layer or RAF.
export function installMapCursor({ viewport, canvases }) {
  function cursor(shape, hotspot, fallback) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" shape-rendering="crispEdges"><path d="${shape}" fill="white" stroke="white" stroke-width="5" stroke-linejoin="miter"/><path d="${shape}" fill="white" stroke="#007eae" stroke-width="2.5" stroke-linejoin="miter"/></svg>`;
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${hotspot}, ${fallback}`;
  }
  const arrow =
      "M3 2V29H8V22H12L17 30L22 27L17 19H28V15H24V13H21V11H18V9H15V7H12V5H8V2Z",
    hand =
      "M11 2H16V13H18V8H22V14H24V10H28V20H26V26H23V29H12V27H9V24H7V21H5V17H9V5H11Z";
  const styles = {
    default: cursor(arrow, "3 2", "default"),
    hover: cursor(hand, "12 2", "pointer"),
    drag: cursor(hand, "12 2", "grabbing"),
    place: "crosshair",
  };
  viewport.style.setProperty("--atlas-map-arrow", styles.default);
  viewport.style.setProperty("--atlas-map-hover", styles.hover);
  function set(element, state) {
    if (element.dataset.mapCursor === state) return;
    element.dataset.mapCursor = state;
    element.style.cursor = styles[state] || styles.default;
  }
  function reset() {
    for (const element of canvases) set(element, "default");
  }
  viewport.addEventListener("pointercancel", reset);
  window.addEventListener("blur", reset);
  window.addEventListener("pagehide", reset);
  reset();
  return { set, reset };
}
