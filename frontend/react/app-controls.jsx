import React, { useEffect, useState } from "react";
import { Button } from "./components/ui/button";
import { Switch } from "./components/ui/switch";
import { Field, FieldLabel } from "./components/ui/field";

export function AppControls() {
  const app = window.AtlasApp;
  const [state, setState] = useState(() => app?.snapshot() || {});
  const [busy, setBusy] = useState(false);
  useEffect(() => app?.subscribe(setState), [app]);
  async function alerts(value) {
    setBusy(true);
    try { await app?.setAlerts(value); } finally { setBusy(false); }
  }
  return <div className="inbox-app-controls">
    <div className="inbox-controls-bar">
      <Field orientation="horizontal" data-disabled={busy || !state.supported}>
        <Switch id="atlas-desktop-alerts" size="sm" checked={!!state.enabled} disabled={busy || !state.supported} onCheckedChange={alerts} />
        <FieldLabel htmlFor="atlas-desktop-alerts">Atlas desktop alerts</FieldLabel>
        <span className="inbox-muted" aria-hidden="true">{state.enabled ? "On" : "Off"}</span>
      </Field>
      <Button size="sm" variant="outline" disabled={!state.available || state.installed} onClick={() => app?.install()}>{state.installed ? "Atlas app installed" : "Install Atlas app"}</Button>
    </div>
    <p className={state.error ? "inbox-error" : "inbox-muted"} role="status">{state.error || state.status || "Open Atlas in Edge or Chrome for app controls."}</p>
    <details className="inbox-connection"><summary>App and alert settings</summary>
      <p>Keep Atlas open, including minimized, for new-item alerts. Closing every Atlas window stops these alerts; the connected collectors can keep running. Browser or Windows settings may delay or silence alerts.</p>
      <p>Installation adds a window and taskbar shortcut. Start the Atlas server with your usual BAT file before opening it. The Python email watcher and Windows notification listener still run in your normal Outlook/Teams account.</p>
      <p>Alerts show counts only. Click an alert to open Live Inbox. This switch applies to this browser profile; Windows may ask for notification permission.</p>
    </details>
  </div>;
}
