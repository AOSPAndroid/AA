// Read visible controls only when requested; never query directory or machines.
export function visible(node) {
  return (
    node.isConnected &&
    !node.closest("[hidden], [inert], .page:not(.active)") &&
    node.getClientRects().length > 0
  );
}
export function disabled(node) {
  return (
    node.matches(":disabled") || node.getAttribute("aria-disabled") === "true"
  );
}
export function collectControls(document) {
  const roots = document.querySelectorAll("main, #ops-panel, #ops-context");
  const nodes = new Set(
    [...roots].flatMap((root) => [
      ...root.querySelectorAll(
        'button, input:not([type="hidden"]), select, textarea, summary',
      ),
    ]),
  );
  return [...nodes]
    .filter(
      (node) =>
        visible(node) &&
        !node.closest(
          "dialog, .atlas-interactions-host, .atlas-reachable-panel",
        ),
    )
    .map((node, index) => {
      const field = /^(INPUT|SELECT|TEXTAREA)$/.test(node.tagName);
      const labelCopy = field ? node.labels?.[0]?.cloneNode(true) : null;
      labelCopy
        ?.querySelectorAll("input,select,textarea,button")
        .forEach((child) => child.remove());
      const label =
        node.getAttribute("aria-label") ||
        (field
          ? labelCopy?.textContent.trim() || node.placeholder
          : node.textContent.trim()) ||
        node.title;
      const contextNode = node.closest(
        "tr, article, .machine-card, .panel, section",
      );
      const workspaceTarget = node.closest("#targetBar")
        ? document.getElementById("barTarget")?.textContent
        : "";
      const context = (
        workspaceTarget
          ? "Workspace target · " + workspaceTarget
          : contextNode?.querySelector("h2,h3,h4,th,td")?.textContent || ""
      )
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 100);
      return {
        id: index,
        node,
        field,
        label: label?.replace(/\s+/g, " ").slice(0, 140),
        context,
        disabled: disabled(node),
      };
    })
    .filter((entry) => entry.label);
}
export function activateControl(entry, beforeActivate) {
  if (!visible(entry.node) || disabled(entry.node)) return false;
  beforeActivate?.();
  entry.node.scrollIntoView({ block: "center", behavior: "instant" });
  entry.node.focus({ preventScroll: true });
  if (!entry.field) entry.node.click();
  return true;
}
export function pageContext(document) {
  const page = document.querySelector(".page.active")?.id;
  const field = document.getElementById(
    page === "admin"
      ? "adminPc"
      : page === "active-directory"
        ? "adIdentity"
        : "",
  );
  return {
    title:
      document.getElementById("pageTitle")?.textContent ||
      (document.querySelector("body.atlas-map") ? "Office map" : "Database"),
    target: field
      ? field.value.trim()
      : document.getElementById("barTarget")?.textContent || "",
    targetField: field?.id || "",
    readonly:
      document.querySelector('meta[name="atlas-mode"]')?.content === "viewer",
  };
}
