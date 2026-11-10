import React from "react";
import { createRoot } from "react-dom/client";
import { Packages } from "./packages.jsx";
import { WorkspaceStart } from "./workspace-start.jsx";
import { LiveInbox } from "./live-inbox.jsx";
import { installMotionBridge } from "./motion-bridge.js";
import "./styles.css";

// Shared React islands; existing screens, APIs and map tables retain ownership.
function install() {
  if (!window.AtlasUI || window.AtlasInteractions) return;
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
        packagesRoot?.unmount();
        workspaceRoot?.unmount();
        inboxRoot?.unmount();
      }
    },
    { once: true },
  );
}
install();
