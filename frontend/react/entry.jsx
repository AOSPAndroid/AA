import React from "react";
import { createRoot } from "react-dom/client";
import { Packages } from "./packages.jsx";
import { LiveInbox } from "./live-inbox.jsx";
import "./styles.css";

// Shared React islands; existing screens, APIs and map tables retain ownership.
function install() {
  if (!window.AtlasUI || window.AtlasInteractions) return;
  const packagesHost = document.getElementById("packageBrowser");
  const packagesRoot = packagesHost ? createRoot(packagesHost) : null;
  packagesRoot?.render(<Packages />);
  const inboxHost = document.getElementById("liveInbox");
  const inboxRoot = inboxHost ? createRoot(inboxHost) : null;
  inboxRoot?.render(<LiveInbox />);
  window.AtlasInteractions = { ready: true };
  window.addEventListener(
    "pagehide",
    (event) => {
      if (!event.persisted) {
        packagesRoot?.unmount();
        inboxRoot?.unmount();
      }
    },
    { once: true },
  );
}
install();
