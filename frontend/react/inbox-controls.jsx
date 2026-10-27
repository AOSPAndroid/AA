import React, { useEffect, useRef, useState } from "react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Input } from "./components/ui/input";
import { Switch } from "./components/ui/switch";
import { Alert, AlertDescription } from "./components/ui/alert";
import { Field, FieldGroup, FieldLabel, FieldDescription, FieldSet, FieldLegend } from "./components/ui/field";

const labels = { running: "Collector task connected", attention: "Collector needs attention", stopped: "Collectors stopped", stopping: "Stopping collectors", unresponsive: "Collector not responding", error: "Setup needs attention", not_configured: "Connect collectors" };
const sources = [["outlook", "Email watcher"], ["notifications", "Notification watcher"]];
// Watcher switches stay in view; the rarely used setup folds away once collectors are connected.
export function InboxControls({ active, onChange, children }) {
  // Demo never reads or changes the collectors; the switches and setup stay visible but disabled.
  const readonly = !!window.AtlasReadOnly;
  const [control, setControl] = useState(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [readError, setReadError] = useState("");
  const [editing, setEditing] = useState(false), [setupOpen, setSetupOpen] = useState(null);
  const [mailUser, setMailUser] = useState(""), [python, setPython] = useState("");
  const version = useRef(0), working = useRef(false), mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => {
    if (!active || readonly) return;
    let current = true, timer;
    const abort = new AbortController();
    async function poll() {
      const token = version.current;
      if (!working.current) {
        try {
          const next = await window.AtlasClient.request("/api/inbox/control", { signal: abort.signal, atlasSilent: true });
          if (current && token === version.current) { setControl(next); setReadError(""); }
        } catch (failure) { if (current && token === version.current && failure.name !== "AbortError") setReadError(failure.message); }
      }
      if (current) timer = setTimeout(poll, 3000);
    }
    poll();
    return () => { current = false; abort.abort(); clearTimeout(timer); };
  }, [active]);
  async function send(body, setup = false) {
    if (working.current) return;
    version.current++; working.current = true; setBusy(true); setError("");
    try {
      const next = await window.AtlasClient.request("/api/inbox/control" + (setup ? "/setup" : ""), {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), atlasSilent: true,
      });
      if (mounted.current) { setControl(next); if (setup) setEditing(false); onChange(); }
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { working.current = false; if (mounted.current) setBusy(false); }
  }
  const configured = !!control?.configured, desired = control?.desired || {};
  const attention = !!control && (!configured || editing || ["error", "unresponsive", "attention"].includes(control.state));
  return <div className="inbox-controls" data-inbox-controls>
    <FieldSet className="inbox-watcher-switches"><FieldLegend variant="label">Live watchers</FieldLegend><FieldGroup className="inbox-source-fields">
      {sources.map(([key, label]) => <Field orientation="horizontal" data-disabled={busy || !configured} key={key}>
        <Switch id={"inbox-source-" + key} size="sm" checked={!!(desired.running && desired[key])} disabled={busy || !configured} onCheckedChange={value => send({ action: "source", [key]: value })} />
        <FieldLabel htmlFor={"inbox-source-" + key}>{label}</FieldLabel>
        <span className="inbox-muted" aria-hidden="true">{desired.running && desired[key] ? "On" : "Off"}</span>
      </Field>)}
    </FieldGroup>{!configured && control && <span className="inbox-muted">Connect collectors to enable these switches.</span>}</FieldSet>
    {(error || readError) && <Alert variant="destructive"><AlertDescription>{error || readError}</AlertDescription></Alert>}
    {control?.detail && (control.state === "error" || control.state === "unresponsive" || (desired.running && !control.agent_running)) && <Alert><AlertDescription>{control.detail}</AlertDescription></Alert>}
    {Object.entries(control?.errors || {}).map(([source, message]) => <Alert key={source}><AlertDescription><strong>{source === "outlook" ? "Outlook emails" : "Notification listener"}</strong>{message}</AlertDescription></Alert>)}
    {configured && control.pending && desired.running && <p role="status" className="inbox-muted">Start requested. Waiting for the collector task in your signed-in mail account.</p>}
    <details className="inbox-setup" open={setupOpen ?? attention} onToggle={event => setSetupOpen(event.currentTarget.open)}>
      <summary><span role="status"><Badge variant="outline" data-tone={control?.state === "running" ? "good" : ["error", "unresponsive", "attention"].includes(control?.state) ? "bad" : undefined}>{readonly ? "Atlas Admin only" : control ? labels[control.state] || "Connecting collectors" : "Checking collector setup…"}</Badge></span><span>Collectors and alerts</span>{configured && <span className="inbox-muted">{control.mail_user}</span>}</summary>
      {configured && <div className="inbox-control-actions">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => send({ action: "start" })}>Start collectors</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => send({ action: "stop" })}>Stop collectors</Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => send({ action: "show" })}>Listener settings</Button>
      </div>}
      {configured && !editing ? <div className="inbox-connection">
        <FieldSet><FieldLegend variant="label">Notification sources</FieldLegend><FieldGroup className="inbox-source-fields">
          <Field orientation="horizontal" data-disabled={busy}>
            <Switch id="inbox-source-outlook_previews" size="sm" checked={!!desired.outlook_previews} disabled={busy} onCheckedChange={value => send({ action: "preferences", outlook_previews: value })} />
            <FieldLabel htmlFor="inbox-source-outlook_previews">Include Outlook previews alongside Teams</FieldLabel>
          </Field>
        </FieldGroup></FieldSet>
        <p>Atlas: <strong>{control.atlas_user}</strong> · Outlook and Teams: <strong>{control.mail_user}</strong>. Keep that account signed in. Closing this page keeps collecting; Stop Atlas requests collector shutdown.</p>
        <p>Open classic Outlook for full emails. For notifications, use Listener settings → Allow access and start once. Windows consent and app source selection appear in your normal account.</p>
        <p className="inbox-muted">Queue: {control.directory}</p>
        <Button size="sm" variant="outline" disabled={busy || control.agent_running} onClick={() => { setMailUser(control.mail_user); setPython(control.python || ""); setEditing(true); }}>Change connection</Button>
        {control.agent_running && <p className="inbox-muted">Stop collectors before changing the account or Python path.</p>}
      </div> : <form className="inbox-connection" onSubmit={event => { event.preventDefault(); send({ mail_user: mailUser.trim(), python: python.trim() || control?.default_python || null }, true); }}>
        <FieldGroup className="inbox-setup-fields">
          <Field data-disabled={busy}><FieldLabel htmlFor="inbox-mail-user">Outlook / Teams Windows account</FieldLabel><Input id="inbox-mail-user" autoComplete="off" placeholder="DOMAIN\username" required value={mailUser} disabled={busy || readonly} onChange={event => setMailUser(event.target.value)} /><FieldDescription>Use the normal Windows account, not its email address.</FieldDescription></Field>
          <Field data-disabled={busy}><FieldLabel htmlFor="inbox-python">Python available to that account</FieldLabel><Input id="inbox-python" autoComplete="off" placeholder={control?.default_python || "C:\\Python312\\python.exe"} value={python} disabled={busy || readonly} onChange={event => setPython(event.target.value)} /><FieldDescription>Leave blank to use Atlas’s Python. Both accounts must be able to read the Atlas folder.</FieldDescription></Field>
        </FieldGroup>
        <p>Run Atlas elevated for this setup. It creates a private queue and a task that runs with your normal account’s existing sign-in.</p>
        <p>In that normal account, run <strong>Install-Inbox-Collectors.bat</strong> once for the Outlook dependency and the approved notification package. No Outlook app needs to be open during setup.</p>
        <div className="inbox-control-actions"><Button type="submit" size="sm" disabled={busy || !control}>{busy ? "Connecting…" : editing ? "Save and start collectors" : "Connect and start collectors"}</Button>
          {editing && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>}</div>
      </form>}
      {children}
    </details>
  </div>;
}
