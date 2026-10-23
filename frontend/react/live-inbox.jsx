import React, { useEffect, useRef, useState } from "react";
import { Inbox, Monitor, UserRound, ArrowUpRight, RefreshCw } from "lucide-react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "./components/ui/card";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription } from "./components/ui/empty";
import { Skeleton } from "./components/ui/skeleton";
import { InboxControls } from "./inbox-controls";
import { AppControls } from "./app-controls";
import { RequestCard, MachineActions, SimilarCard, sendInboxAction } from "./inbox-request";
import { ScreenReader } from "./screen-reader";

const matchTones = { email: "good", name: "warn", ambiguous: "warn", unmatched: "bad" };
const matchLabels = { email: "Email match", name: "Name match · verify", ambiguous: "Choose a person", unmatched: "No Atlas match" };
const states = { watching: "Watching Outlook", scanning: "Checking Outlook", starting: "Starting watcher", stopped: "Watcher stopped", waiting_for_outlook: "Waiting for Outlook", retrying: "Retrying Outlook", error: "Watcher needs attention" };
const notificationStates = { watching: "Listening for notifications", starting: "Waiting for Windows permission", stopped: "Notifications paused", not_started: "Notifications not connected", permission_required: "Notification permission needed", retrying: "Retrying notifications", error: "Notification listener needs attention" };
const sourceLabel = item => item?.content_kind === "notification" ? (item.channel === "teams" ? "Teams preview" : "Outlook preview") : "Outlook email";
const date = value => value ? new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "Not yet";
const request = (url, signal) => window.AtlasClient.request(url, { signal, atlasSilent: true });
function EmptyInbox({ title, children }) {
  return <Empty><EmptyHeader><EmptyMedia variant="icon"><Inbox aria-hidden="true" /></EmptyMedia><EmptyTitle>{title}</EmptyTitle><EmptyDescription>{children}</EmptyDescription></EmptyHeader></Empty>;
}
// Machines and people found in the message are highlighted; a click opens them in the request tools.
const termKey = (text) => text.toLowerCase().replace(/[,\s]+/g, " ");
function highlight(text, analysis, user) {
  const terms = new Map();
  for (const m of analysis?.machines || []) for (const t of [m.name, m.written_as]) if (t) terms.set(termKey(t), { machine: m.name });
  for (const p of analysis?.people || []) terms.set(termKey(p.written), p.ambiguous ? { shared: p.candidates.length } : { person: p });
  if (!terms.size) return text;
  const pattern = new RegExp("(" + [...terms.keys()].sort((a, b) => b.length - a.length).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "[,\\s]+")).join("|") + ")", "i");
  return text.split(pattern).map((part, i) => {
    const hit = i % 2 ? terms.get(termKey(part)) : null;
    if (!hit) return part;
    if (hit.shared) return <mark key={i} className="inbox-entity" title={hit.shared + " people in Atlas share this name"}>{part}</mark>;
    return <button key={i} type="button" className="inbox-entity" data-entity={hit.machine ? "machine" : "person"} title={hit.machine ? "Open " + hit.machine + " in the request tools" : "Open " + (hit.person.full_name || hit.person.name) + " in the request tools"}
      onClick={() => hit.machine ? sendInboxAction("target", { machine: hit.machine, user }) : sendInboxAction("person", { user: hit.person })}>{part}</button>;
  });
}
function MessageBody({ message, analysis, user }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [message.id]);
  const body = message.body || (message.content_kind === "notification" ? "No message preview was supplied by Windows." : "No plain-text body was supplied.");
  const long = body.length > 1400 || body.split("\n").length > 18;
  return <><pre className="inbox-body" data-collapsed={long && !open ? "" : undefined}>{highlight(body, analysis, user)}</pre>
    {long && <Button variant="ghost" size="sm" onClick={() => setOpen(!open)}>{open ? "Show less" : "Show the whole message"}</Button>}</>;
}
const deskText = (person) => person?.desks?.length ? "Desk " + person.desks.map((desk) => desk.id).join(", ") : "";
function NamedPeople({ people }) {
  if (!people.length) return null;
  return <div className="inbox-named-people"><h3>Named in the message</h3><ul>{people.map((p) => <li key={p.id || p.written} data-named-person={p.full_name || p.written}>{p.ambiguous ? <>
    <div><strong>{p.written}</strong><Badge variant="outline" data-tone="warn">{p.candidates.length} people share this name</Badge></div>
    <div className="inbox-machine-actions">{p.candidates.map((c) => <Button key={c.id} size="sm" variant="outline" onClick={() => sendInboxAction("person", { user: c })}>{c.email || c.user_name || c.full_name}</Button>)}</div>
  </> : <>
    <div><strong>{p.full_name || p.name}</strong>{termKey(p.written) !== termKey(p.full_name || "") && <small className="inbox-read-as">written "{p.written}"</small>}</div>
    <p className="inbox-muted">{[p.user_name, p.department, deskText(p)].filter(Boolean).join(" · ") || p.email}</p>
    <p className="inbox-muted">{p.machines?.length ? p.machines.map((m) => m.name || m.machine_name).join(", ") : "No linked machine"}</p>
    <div className="inbox-machine-actions"><Button size="sm" variant="outline" onClick={() => sendInboxAction("person", { user: p })}>Details</Button><Button size="sm" variant="outline" disabled={!p.user_name && !p.email} onClick={() => sendInboxAction("user-groups", { user: p })}>Groups</Button></div>
  </>}</li>)}</ul></div>;
}
function merge(previous, incoming) {
  const rows = new Map(previous.map(row => [row.id, row]));
  incoming.forEach(row => rows.set(row.id, row));
  return [...rows.values()].sort((a, b) => b.id - a.id);
}
export function LiveInbox() {
  const section = document.getElementById("inbox"), readonly = !!window.AtlasReadOnly;
  const [visible, setVisible] = useState(() => section.classList.contains("active"));
  const [items, setItems] = useState([]), [total, setTotal] = useState(0), [watcher, setWatcher] = useState(null);
  const [notifications, setNotifications] = useState(null);
  const [selected, setSelected] = useState(null), [chosen, setChosen] = useState(null), [detail, setDetail] = useState(null);
  const [error, setError] = useState(""), [detailError, setDetailError] = useState(""), [pending, setPending] = useState(0);
  const [loaded, setLoaded] = useState(false), [older, setOlder] = useState(false), [refresh, setRefresh] = useState(0);
  const cursor = useRef(0), initialized = useRef(false), session = useRef(0), selection = useRef(selected);
  selection.current = selected;
  useEffect(() => {
    const update = () => setVisible(section.classList.contains("active"));
    const observer = new MutationObserver(update);
    observer.observe(section, { attributes: true, attributeFilter: ["class"] });
    update();
    return () => observer.disconnect();
  }, [section]);
  useEffect(() => {
    if (!visible || readonly) return;
    let current = true, timer;
    const controller = new AbortController();
    session.current += 1;
    async function poll() {
      let delay = 2000;
      try {
        const next = await request("/api/inbox/messages?limit=50&after_id=" + cursor.current, controller.signal);
        if (!current) return;
        if (initialized.current && next.newest_id < cursor.current) {
          cursor.current = 0; initialized.current = false;
          setItems([]); setSelected(null); setChosen(null); setPending(0);
          delay = 0;
        } else {
          setItems(previous => merge(previous, next.items));
          if (!initialized.current) {
            if (selection.current === null && next.items.length) setSelected(next.items[0].id);
            cursor.current = next.newest_id;
            initialized.current = true;
          } else {
            if (selection.current === null && next.items.length) setSelected(next.items.at(-1).id);
            setPending(count => count + next.items.length);
            cursor.current = Math.max(cursor.current, next.next_after);
            if (next.has_more) delay = 0;
          }
        }
        setTotal(next.total); setWatcher(next.watcher); setNotifications(next.notifications || null); setLoaded(true); setError("");
      } catch (failure) {
        if (current && failure.name !== "AbortError") { setError(failure.message); setLoaded(true); }
      }
      if (current) timer = setTimeout(poll, delay);
    }
    poll();
    return () => { current = false; session.current += 1; controller.abort(); clearTimeout(timer); };
  }, [visible, readonly, refresh]);
  useEffect(() => {
    if (!visible || readonly || selected === null) return;
    let current = true;
    const controller = new AbortController();
    setDetail(null); setDetailError("");
    request("/api/inbox/messages/" + selected + (chosen ? "?user_id=" + chosen : ""), controller.signal)
      .then(value => { if (current) { setDetail(value); window.dispatchEvent(new CustomEvent("atlas:inbox-detail", { detail: value })); } })
      .catch(failure => { if (current && failure.name !== "AbortError") setDetailError(failure.message); });
    return () => { current = false; controller.abort(); };
  }, [selected, chosen, visible, readonly, refresh]);
  function choose(id) { setSelected(id); setChosen(null); }
  // Search results and "Seen before" open a specific message, even one not loaded in the list.
  useEffect(() => {
    const open = (event) => { const id = Number(event.detail?.id); if (Number.isSafeInteger(id) && id > 0) choose(id); };
    window.addEventListener("atlas:inbox-open", open);
    return () => window.removeEventListener("atlas:inbox-open", open);
  }, []);
  async function loadOlder() {
    const token = session.current;
    setOlder(true);
    try {
      const next = await request("/api/inbox/messages?limit=50&before_id=" + items.at(-1).id);
      if (token === session.current) { setItems(previous => merge(previous, next.items)); setTotal(next.total); setError(""); }
    } catch (failure) { if (token === session.current) setError(failure.message); }
    finally { setOlder(false); }
  }
  if (readonly) return <EmptyInbox title="Live inbox is available in Atlas Admin">Open Atlas Admin on the Windows PC running Outlook and Teams. Email and notification previews stay in the local queue and are not shared with Demo or Preview.</EmptyInbox>;
  const live = watcher?.running && !watcher.stale && ["watching", "scanning"].includes(watcher.state) && !error;
  const stateLabel = error ? "Connection interrupted" : watcher?.stale ? "Outlook check is taking longer" : states[watcher?.state] || "Connecting…";
  const notificationsLive = notifications?.running && !notifications.stale && notifications.state === "watching" && !error;
  const notificationLabel = error ? "Connection interrupted" : notifications?.stale ? "Notification listener is not responding" : notificationStates[notifications?.state] || "Notifications not connected";
  const match = detail?.match, user = match?.user, message = detail?.message;
  const mentioned = (detail?.analysis?.machines || []).filter(machine => !machine.linked);
  return <div className="live-inbox">
    <div className="inbox-toolbar">
      <div role="status" aria-live="polite"><Badge variant={live ? "default" : "secondary"} data-tone={live ? "good" : error || watcher?.stale || watcher?.state === "error" ? "bad" : undefined} data-inbox-status>{stateLabel}</Badge><Badge variant={notificationsLive ? "default" : "secondary"} data-tone={notificationsLive ? "good" : error || notifications?.stale || ["error", "permission_required"].includes(notifications?.state) ? "bad" : undefined} data-notification-status>{notificationLabel}</Badge><span className="inbox-muted">{total.toLocaleString()} collected · {watcher?.config?.mailbox || "Default Inbox"}{watcher?.config?.subfolder ? " / " + watcher.config.subfolder : ""}</span></div>
      <Button variant="outline" size="sm" onClick={() => setRefresh(value => value + 1)}><RefreshCw data-icon="inline-start" />Refresh now</Button>
    </div>
    {error && <p role="alert" className="inbox-error">{error} Retrying automatically; displayed messages may be out of date.</p>}
    <InboxControls active={visible} onChange={() => setRefresh(value => value + 1)}>
      <AppControls />
      <details className="inbox-connection">
        <summary>Connection details · Outlook {date(watcher?.last_success_at)} · notifications {date(notifications?.last_success_at)}</summary>
        <p>{watcher?.detail || "Connect the collectors above, then open classic Outlook in your normal Windows account."}</p>
        <p>Run the watcher under the same Windows account and elevation level as Outlook. Atlas checks the local feed every 2 seconds; Outlook is checked every {watcher?.interval || 5} seconds. The watcher keeps collecting when you leave this page.</p>
        <p>{notifications?.detail || "Use Listener settings above to grant Windows notification permission and check the Teams source."}</p>
        <p>Notifications are checked every 2 seconds. The listener’s source check shows whether Windows exposes Teams alerts. Previews may be incomplete; app-only banners and messages without notifications are not captured. Outlook previews are optional because the mail watcher already reads complete emails.</p>
        <p>Connection settings are saved on this PC and used by every Atlas launcher. Setup guide: docs/inbox-integration.md in the Atlas folder.</p>
      </details>
    </InboxControls>
    <ScreenReader />
    <div className="inbox-grid">
      <div className="inbox-mail-list">
        <div className="inbox-list-heading"><h2>Incoming messages</h2>{pending > 0 && <Button variant="secondary" size="sm" onClick={() => { choose(items[0].id); setPending(0); }}>Show newest ({pending})</Button>}</div>
        {!loaded ? <Skeleton className="inbox-loading" /> : !items.length ? <EmptyInbox title="Waiting for incoming messages">Emails and notification previews appear when their collectors are connected. Collection begins when each collector first starts.</EmptyInbox> : <ul aria-label="Collected messages">{items.map(item => <li key={item.id}>
          <Button variant="ghost" className="inbox-mail-row" aria-current={selected === item.id ? "true" : undefined} onClick={() => choose(item.id)} data-mail-id={item.id}>
            <span className="inbox-mail-top"><strong>{item.sender_name || item.sender_address || "Sender not supplied"}</strong><time dateTime={item.received_at}>{date(item.received_at)}</time></span>
            <span className="inbox-subject">{item.content_kind === "notification" ? item.preview || "(No message preview)" : item.subject || "(No subject)"}</span>
            <span className="inbox-mail-bottom"><Badge variant="secondary">{sourceLabel(item)}</Badge><span className="inbox-address">{item.sender_address}</span><Badge variant="outline" data-tone={matchTones[item.match.kind]}>{matchLabels[item.match.kind]}</Badge></span>
          </Button>
        </li>)}</ul>}
        {items.length > 0 && items.length < total && <Button variant="outline" size="sm" disabled={older} onClick={loadOlder}>Load older messages ({items.length} of {total})</Button>}
      </div>
      <div className="inbox-context" aria-label="Message and sender details">
        {selected === null ? <EmptyInbox title="Select a message">Its sender and linked machines will appear here.</EmptyInbox> : detailError ? <p role="alert" className="inbox-error">{detailError}</p> : !detail || message.id !== selected ? <Skeleton className="inbox-loading" /> : <>
          <Card className="inbox-message-card"><CardHeader><CardTitle role="heading" aria-level={2}>{message.subject || "(No subject)"}</CardTitle><CardDescription>{sourceLabel(message)} · {message.sender_name}{message.sender_address ? " <" + message.sender_address + ">" : ""} · {date(message.received_at)}</CardDescription></CardHeader><CardContent>{message.content_kind === "notification" && <p className="inbox-match-note">Notification preview from {message.app_name || (message.channel === "teams" ? "Teams" : "Outlook")}. Text may be incomplete or hidden by notification settings. Open the source app for the full conversation.</p>}<MessageBody message={message} analysis={detail.analysis} user={user} />{!!message.body_truncated && <p className="inbox-muted">Showing the first 100,000 characters. Open Outlook for the full message.</p>}</CardContent></Card>
          <Card className="inbox-person-card"><CardHeader><CardTitle role="heading" aria-level={2}><UserRound aria-hidden="true" />People</CardTitle><CardDescription>Sender · {matchLabels[match.kind]}{match.chosen ? " · selected for this view" : ""}</CardDescription></CardHeader><CardContent>
            {match.kind === "ambiguous" && <div className="inbox-candidates"><p>More than one person matches this {match.basis}. Choose the correct record to view machines.</p>{match.candidates.map(candidate => <Button key={candidate.id} size="sm" variant={chosen === candidate.id ? "secondary" : "outline"} onClick={() => setChosen(candidate.id)}>{candidate.name} · {candidate.email || candidate.user_name || candidate.id}</Button>)}</div>}
            {user ? <><h3>{user.full_name || user.name}</h3><p>{[user.user_name, user.email].filter(Boolean).join(" · ")}</p><p className="inbox-muted">{[user.department, user.location, user.job_role, deskText(user)].filter(Boolean).join(" · ") || "No additional directory details"}</p>{match.basis === "name" && <p className="inbox-match-note">{message.content_kind === "notification" ? "Matched the notification title. It may be a chat or group name; verify the sender in Teams or Outlook before taking action." : "Display names can be shared. Verify this person against the sender address before taking action."}</p>}</> : match.kind === "unmatched" && <p>No exact email or full-name match was found in the Atlas database.</p>}
            <NamedPeople people={detail.analysis?.people || []} />
          </CardContent>{user && <CardFooter><Button variant="outline" size="sm" onClick={() => sendInboxAction("person", { user })}>Details</Button><Button variant="outline" size="sm" onClick={() => sendInboxAction("user-groups", { user })}>Groups</Button><Button variant="ghost" size="sm" onClick={() => window.dispatchEvent(new CustomEvent("atlas:inbox-person", { detail: { id: user.id } }))}>Workspace<ArrowUpRight data-icon="inline-end" /></Button></CardFooter>}</Card>
          {(user || mentioned.length > 0) && <Card><CardHeader><CardTitle role="heading" aria-level={2}><Monitor aria-hidden="true" />{user ? "Linked machines" : "Machines named in message"} <Badge variant="secondary">{(user ? detail.machines.length : 0) + mentioned.length}</Badge></CardTitle><CardDescription>Stored inventory relationships and status</CardDescription></CardHeader><CardContent>
            {mentioned.length > 0 && <ul className="inbox-devices" aria-label="Machines named in the message">{mentioned.map(machine => <li key={"named-" + machine.name} data-mentioned-machine={machine.name}><div><strong>{machine.name}</strong><Badge variant="outline">Named in message</Badge>{machine.written_as && machine.written_as !== machine.name.toUpperCase() && <small className="inbox-read-as" title="Found despite look-alike characters such as 0/O or 1/I">read as {machine.written_as}</small>}</div><p>{machine.model_id || "Model not supplied"} · not linked to this sender in inventory, check before acting</p><MachineActions machine={machine} user={user} /></li>)}</ul>}
            {user && (detail.machines.length ? <ul className="inbox-devices">{detail.machines.map((machine, index) => <li key={index}><div><strong>{machine.name || machine.machine_name}</strong><Badge variant="outline">{machine.device_kind || "Device"}</Badge></div><p>{machine.model_id || machine.model_category || "Model not supplied"} · {machine.match_type || "Linked in inventory"}</p><small>{[machine.operational_status && "Inventory: " + machine.operational_status, machine.last_discovered && "Discovered: " + machine.last_discovered].filter(Boolean).join(" · ") || "Inventory timestamp not supplied"}</small><MachineActions machine={{ ...machine, name: machine.name || machine.machine_name }} user={user} /></li>)}</ul> : <p>No linked machines in the current Atlas database.</p>)}
          </CardContent></Card>}
          <RequestCard detail={detail} user={user} />
          <SimilarCard messageId={message.id} />
        </>}
      </div>
    </div>
  </div>;
}
