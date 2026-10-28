import React, { useEffect, useState } from "react";
import { ClipboardList, PackagePlus, Wrench, BookOpen, History } from "lucide-react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "./components/ui/card";

const toolLabels = {
  performance: "Performance scan",
  health: "Health check",
  reboot: "Reboot…",
  "user-groups": "User's AD groups",
  "machine-groups": "Machine's AD groups",
};
const machineTools = new Set(["performance", "health", "reboot", "machine-groups"]);
// Why a package was suggested: its catalogue name, a Windows package alias or a close spelling.
const matchReason = (p) => p.reason === "alias" ? `Known as "${p.matched}" (Windows package name)`
  : p.reason === "spelling" ? `Close spelling of "${p.matched}"`
  : p.score >= 0.99 ? "Full name in message" : "Partial name match";
const kindLabels = { software: "Software request", issue: "Issue", other: "General message" };

// Live Inbox actions run in the classic console scripts (inbox-actions.js).
export function sendInboxAction(action, detail) {
  window.dispatchEvent(new CustomEvent("atlas:inbox-action", { detail: { action, ...detail } }));
}
const supportsWindows = (machine) => window.AtlasUI?.supportsWindows ? window.AtlasUI.supportsWindows(machine) : true;

// "read as GBRPWMK2O88I521" when the name was found despite 0/O or 1/I confusion.
export const readAs = (machine) => machine?.written_as && machine.written_as !== String(machine.name).toUpperCase() ? " · read as " + machine.written_as : "";

/** Windows machines for this request: machines named in the message first, then the sender's,
 *  then those of people named in the message (labelled with their owner). */
export function requestMachines(detail) {
  const mentioned = (detail.analysis?.machines || []).map((m) => ({ ...m, mentioned: true }));
  const linked = (detail.machines || []).map((m) => {
    const mention = mentioned.find((x) => x.name.toUpperCase() === String(m.name || m.machine_name).toUpperCase());
    return { ...m, name: m.name || m.machine_name, mentioned: !!mention, written_as: mention?.written_as };
  });
  const rows = [...mentioned.filter((m) => !m.linked), ...linked];
  for (const p of detail.analysis?.people || []) for (const m of p.machines || []) {
    const name = m.name || m.machine_name;
    if (!rows.some((r) => r.name.toUpperCase() === String(name).toUpperCase())) rows.push({ ...m, name, mentioned: false, owner: p.full_name || p.name });
  }
  return rows.filter((m) => m.name && supportsWindows(m)).sort((a, b) => b.mentioned - a.mentioned);
}

export function MachineActions({ machine, user }) {
  if (!supportsWindows(machine)) return <p className="inbox-muted">Inventory only · Windows tools need a PC.</p>;
  const send = (action) => sendInboxAction(action, { machine: machine.name, user });
  return <div className="inbox-machine-actions" role="group" aria-label={"Actions for " + machine.name}>
    <Button size="sm" variant="outline" onClick={() => send("target")}>Select</Button>
    <Button size="sm" variant="outline" onClick={() => send("health")}>Health</Button>
    <Button size="sm" variant="outline" onClick={() => send("machine-groups")}>Groups</Button>
    <Button size="sm" variant="outline" onClick={() => send("reboot")}>Reboot…</Button>
  </div>;
}

// The card is rebuilt whenever the message is refreshed; keep the machine chosen for each message.
const chosenMachines = new Map();

export function RequestCard({ detail, user }) {
  const analysis = detail.analysis || {};
  const machines = requestMachines(detail), id = detail.message.id;
  const initial = () => machines.some((m) => m.name === chosenMachines.get(id)) ? chosenMachines.get(id) : machines[0]?.name || "";
  const [target, setChosen] = useState(initial);
  const [term, setTerm] = useState(analysis.search || "");
  const [persona, setPersona] = useState("");
  const personas = window.AtlasPersonas?.list?.() || [];
  const setTarget = (name) => { chosenMachines.set(id, name); setChosen(name); };
  useEffect(() => { setChosen(initial()); setTerm(analysis.search || ""); setPersona(""); }, [id, machines.length]);
  const action = analysis.action || "Install";
  const send = (name, extra = {}) => sendInboxAction(name, { machine: target, user, ...extra });
  const noMachine = !target, machineTitle = noMachine ? "No Windows machine is linked to or named in this message" : undefined;
  const categories = analysis.categories || [];
  return <Card className="inbox-request-card">
    <CardHeader>
      <CardTitle role="heading" aria-level={2}><ClipboardList aria-hidden="true" />Request <Badge variant="secondary" data-request-kind={analysis.kind}>{kindLabels[analysis.kind] || "Message"}{analysis.kind === "software" ? " · " + action : ""}</Badge></CardTitle>
      <CardDescription>Suggestions from keywords in this message. Check them before acting; nothing runs until you click.</CardDescription>
    </CardHeader>
    <CardContent>
      {categories.length > 0 && <p className="inbox-request-tags">{categories.map((c) => <Badge key={c.id} variant="outline" title={"Matched: " + c.matched.join(", ")}>{c.label}</Badge>)}</p>}
      {machines.length > 1 ? <label className="inbox-request-target">Machine
        <select value={target} onChange={(event) => setTarget(event.target.value)}>{machines.map((m) => <option key={m.name} value={m.name}>{m.name}{m.mentioned ? " · named in message" : m.owner ? " · " + m.owner : ""}{readAs(m)}</option>)}</select>
      </label> : <p className="inbox-muted">{target ? "Machine: " + target + (machines[0]?.mentioned ? " (named in message" + readAs(machines[0]) + ")" : machines[0]?.owner ? " (" + machines[0].owner + ")" : "") : "No Windows machine is linked to or named in this message."}</p>}

      {(analysis.packages || []).length > 0 && <section aria-label="Suggested packages" className="inbox-request-section">
        <h3><PackagePlus aria-hidden="true" />Packages · {action}</h3>
        <ul className="inbox-request-list">{analysis.packages.map((p) => <li key={p.folder} data-package={p.folder}>
          <span><strong>{p.display_name}</strong><small>{matchReason(p)}{p.display_name !== p.folder ? " · " + p.folder : ""}</small></span>
          <Button size="sm" variant="outline" disabled={noMachine} title={machineTitle} onClick={() => send("deploy", { pkg: p, deployAction: action })}>{action}…</Button>
          <Button size="sm" variant="outline" disabled={noMachine} title={machineTitle} onClick={() => send("queue", { pkg: p, deployAction: action })}>Add to queue</Button>
        </li>)}</ul>
      </section>}

      {analysis.kind === "software" && !(analysis.packages || []).length && <section aria-label="Find a package" className="inbox-request-section">
        <h3><PackagePlus aria-hidden="true" />No matching package in the catalogue</h3>
        <div className="inbox-request-row"><input aria-label="Search the package catalogue" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Package name" />
          <Button size="sm" variant="outline" disabled={noMachine} title={machineTitle} onClick={() => send("search", { term })}>Search catalogue</Button></div>
      </section>}

      {analysis.kind === "software" && personas.length > 0 && <section aria-label="Personas" className="inbox-request-section">
        <div className="inbox-request-row"><select aria-label="Persona" value={persona} onChange={(event) => setPersona(event.target.value)}><option value="">Add a persona…</option>{personas.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.items.length} package{p.items.length === 1 ? "" : "s"}</option>)}</select>
          <Button size="sm" variant="outline" disabled={noMachine || !persona} title={machineTitle} onClick={() => send("persona", { persona })}>Add to queue</Button></div>
      </section>}

      {(analysis.tools || []).length > 0 && <section aria-label="Suggested checks" className="inbox-request-section">
        <h3><Wrench aria-hidden="true" />Suggested checks</h3>
        <div className="inbox-request-row">{analysis.tools.map((tool) => {
          const blocked = machineTools.has(tool) ? noMachine : !user;
          return <Button key={tool} size="sm" variant="outline" data-tool-suggestion={tool} disabled={blocked} title={blocked ? (machineTools.has(tool) ? machineTitle : "No Atlas person matched this sender") : undefined} onClick={() => send(tool)}>{toolLabels[tool] || tool}</Button>;
        })}</div>
      </section>}

      {(analysis.knowledge || []).length > 0 && <section aria-label="Knowledge Base" className="inbox-request-section">
        <h3><BookOpen aria-hidden="true" />Knowledge Base</h3>
        <div className="inbox-request-row">{analysis.knowledge.map((doc) => <Button key={doc.id} size="sm" variant="ghost" onClick={() => sendInboxAction("knowledge", { document: doc.id })}>{doc.title}</Button>)}</div>
      </section>}

      {analysis.kind === "other" && !(analysis.machines || []).length && <p className="inbox-muted">No software request or known issue was recognised. Use the machine actions below.</p>}
      {(analysis.warnings || []).map((warning) => <p key={warning} className="inbox-muted" role="note">{warning}</p>)}
    </CardContent>
  </Card>;
}

const markText = (text) => String(text || "").split(/(\u0002[^\u0003]*\u0003)/).map((part, i) =>
  part.startsWith("\u0002") ? <mark key={i}>{part.slice(1, -1)}</mark> : part);

/** Earlier requests and Knowledge Base articles that share distinctive words with this message. */
export function SimilarCard({ messageId }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let current = true;
    setData(null);
    window.AtlasClient.request("/api/search-everything/similar/" + messageId, { atlasSilent: true })
      .then((value) => { if (current) setData({ terms: value?.terms || [], requests: value?.requests || [], articles: value?.articles || [] }); })
      .catch(() => { if (current) setData({ terms: [], requests: [], articles: [] }); });
    return () => { current = false; };
  }, [messageId]);
  if (!data || (!data.requests.length && !data.articles.length)) return null;
  const date = (value) => value ? new Date(value).toLocaleDateString([], { day: "numeric", month: "short" }) : "";
  return <Card className="inbox-similar-card">
    <CardHeader><CardTitle role="heading" aria-level={2}><History aria-hidden="true" />Seen before</CardTitle>
      <CardDescription>Earlier requests and articles with the same key words: {data.terms.slice(0, 5).join(", ")}</CardDescription></CardHeader>
    <CardContent>
      {data.articles.length > 0 && <ul className="inbox-similar-list" aria-label="Related articles">{data.articles.map((a) => <li key={a.kind + a.ref}>
        <Button size="sm" variant="ghost" onClick={() => sendInboxAction("knowledge", { document: a.kind === "article" ? "article:" + a.ref : a.ref })}><BookOpen aria-hidden="true" />{markText(a.title)}</Button></li>)}</ul>}
      {data.requests.length > 0 && <ul className="inbox-similar-list" aria-label="Similar requests">{data.requests.map((r) => <li key={r.ref}>
        <Button size="sm" variant="ghost" data-similar-request={r.ref} onClick={() => window.dispatchEvent(new CustomEvent("atlas:inbox-open", { detail: { id: Number(r.ref) } }))}>
          <span className="inbox-similar-title">{markText(r.title)}</span><small>{[r.extra?.sender, date(r.at)].filter(Boolean).join(" · ")}</small></Button>
        <p className="inbox-muted">{markText(r.snippet)}</p></li>)}</ul>}
    </CardContent>
  </Card>;
}
