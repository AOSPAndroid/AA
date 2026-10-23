import React from "react";
import { createRoot } from "react-dom/client";
import { Packages } from "./packages.jsx";
import { ActionsHub } from "./actions-hub.jsx";
import { WorkspaceStart } from "./workspace-start.jsx";
import { LiveInbox } from "./live-inbox.jsx";
import { installMotionBridge } from "./motion-bridge.js";
import "./styles.css";

// Shared React islands; existing screens, APIs and map tables retain ownership.
function install() {
  const main = document.querySelector("main");
  if (
    !main ||
    !window.AtlasUI ||
    document.querySelector(".atlas-interactions-host")
  )
    return;
  window.AtlasReachableFallback?.destroy();
  const host = document.createElement("div");
  host.className = "atlas-interactions-host";
  host.dataset.atlasReact = "tools";
  const heading = main.querySelector(
    ":scope > .console-page-heading, :scope > .map-heading, :scope > header",
  );
  if (heading) heading.append(host);
  else main.prepend(host);
  const root = createRoot(host);
  root.render(<ActionsHub />);
  const packagesHost = document.getElementById("packageBrowser");
  const packagesRoot = packagesHost ? createRoot(packagesHost) : null;
  packagesRoot?.render(<Packages />);
  const workspaceHost = document.querySelector(".workspace-launchers");
  const workspaceRoot = workspaceHost ? createRoot(workspaceHost) : null;
  workspaceHost?.classList.add("atlas-shadcn");
  workspaceRoot?.render(<WorkspaceStart />);
  const inboxHost = document.getElementById("liveInbox");
  const inboxRoot = inboxHost ? createRoot(inboxHost) : null;
  inboxRoot?.render(<LiveInbox />);
  window.AtlasInteractions = { ready: true, ...installMotionBridge() };
  window.addEventListener(
    "pagehide",
    (event) => {
      if (!event.persisted) {
        root.unmount();
        packagesRoot?.unmount();
        workspaceRoot?.unmount();
        inboxRoot?.unmount();
      }
    },
    { once: true },
  );
}
install();
