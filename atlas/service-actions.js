export function openRemoteRegistry(computer) {
  const pc = String(computer || "")
    .trim()
    .toUpperCase();
  const { body } = AtlasUI.dialog("Enable Remote Registry");
  const description = document.createElement("p");
  description.textContent = pc
    ? `${pc}: start Remote Registry. If disabled, change startup to Manual; otherwise keep its existing startup setting. Remote administrator rights are required.`
    : "Select a machine first, then open this action again.";
  const button = document.createElement("button");
  button.textContent = "Enable Remote Registry";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  const viewer =
    !!window.AtlasReadOnly ||
    document.querySelector('meta[name="atlas-mode"]')?.content === "viewer";
  button.disabled = !pc || viewer;
  if (viewer)
    status.textContent =
      "Available only in Atlas Admin running with remote administrator rights.";
  button.onclick = async () => {
    button.disabled = true;
    status.textContent = `${pc}: enabling Remote Registry…`;
    try {
      const result = await AtlasClient.request("/api/remote-registry/enable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ computer: pc }),
      });
      status.textContent = `${pc}: Remote Registry ${result.state} · Startup: ${result.start_mode}`;
    } catch (error) {
      status.textContent = `${pc}: ${error.message}`;
      button.disabled = false;
    }
  };
  body.append(description, button, status);
}
