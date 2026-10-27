import React, { useEffect, useRef, useState } from "react";
import { LazyMotion, MotionConfig, domMax, m } from "motion/react";
import * as Tabs from "@radix-ui/react-tabs";
import { useAtlasMotion } from "./actions-hub.jsx";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription } from "./components/ui/empty";
import { Skeleton } from "./components/ui/skeleton";
import { Package } from "lucide-react";

const coverageLabels = {
  matched: "Source + data",
  "source-only": "No package data",
  "metadata-only": "Metadata only",
  ambiguous: "Ambiguous name",
};
function StateBadge({ state }) {
  const text = state || "State not supplied";
  const tone = /^live$/i.test(state)
    ? "live"
    : /progress|packaging/i.test(state)
      ? "progress"
      : "unknown";
  return <Badge variant={tone === "live" ? "default" : "secondary"} data-tone={tone}>{text}</Badge>;
}
export function Packages() {
  const section = document.getElementById("packages");
  const [visible, setVisible] = useState(() =>
    section.classList.contains("active"),
  );
  const [query, setQuery] = useState(""),
    [state, setState] = useState(""),
    [coverage, setCoverage] = useState("");
  const [offset, setOffset] = useState(0),
    [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(null),
    [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [copying, setCopying] = useState(false),
    [copyFeedback, setCopyFeedback] = useState("");
  const copyRequest = useRef(0);
  const readonly = !!window.AtlasReadOnly;
  const reduced = useAtlasMotion();
  useEffect(() => {
    copyRequest.current += 1;
    setCopying(false);
    setCopyFeedback("");
    return () => {
      copyRequest.current += 1;
    };
  }, [selected?.id, visible]);
  useEffect(() => {
    const update = () => setVisible(section.classList.contains("active"));
    const observer = new MutationObserver(update);
    observer.observe(section, { attributes: true, attributeFilter: ["class"] });
    const open = () => setRefresh((value) => value + 1);
    window.addEventListener("atlas:packages-open", open);
    // A fast readonly command can open the page between render and this effect.
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener("atlas:packages-open", open);
    };
  }, [section]);
  useEffect(() => {
    if (!visible) return;
    let current = true;
    const controller = new AbortController();
    setBusy(true);
    setError("");
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          term: query,
          state,
          coverage,
          offset: String(offset),
          limit: "100",
        });
        const next = await window.AtlasClient.request(
          "/api/package-data?" + params,
          { signal: controller.signal, atlasSilent: true },
        );
        if (!current) return;
        if (next.total && offset >= next.total) {
          setOffset(0);
          return;
        }
        setData(next);
        setSelected((previous) =>
          previous
            ? next.items.find((item) => item.id === previous.id) || null
            : null,
        );
      } catch (e) {
        if (current && e.name !== "AbortError") {
          setData(null);
          setSelected(null);
          setError(e.message);
        }
      } finally {
        if (current) setBusy(false);
      }
    }, 180);
    return () => {
      current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [visible, query, state, coverage, offset, refresh]);
  const filter = (setter, value) => {
    setter(value);
    setOffset(0);
    setSelected(null);
  };
  const stats = data?.stats;
  const copyIdentifier = async (field, label) => {
    const value = selected?.[field];
    if (!value || busy || copying) return;
    const request = ++copyRequest.current;
    setCopying(true);
    setCopyFeedback("");
    try {
      const copied = await window.AtlasContext.copy(value, label);
      if (request === copyRequest.current)
        setCopyFeedback(
          copied ? `${label} copied.` : "Copy the selected text in the dialog.",
        );
    } catch {
      if (request === copyRequest.current)
        setCopyFeedback(
          "Copy unavailable. Select the value and copy it manually.",
        );
    } finally {
      if (request === copyRequest.current) setCopying(false);
    }
  };
  const inspect = () =>
    window.dispatchEvent(
      new CustomEvent("atlas:package-inspect", {
        detail: { folder: selected.folder },
      }),
    );
  return (
    <LazyMotion features={domMax}>
      <MotionConfig reducedMotion={reduced ? "always" : "user"}>
        <div className="package-browser atlas-shadcn">
          <div className="package-toolbar">
            <label className="package-search">
              Search packages
              <input
                aria-label="Search package data"
                value={query}
                maxLength={200}
                onChange={(e) => filter(setQuery, e.target.value)}
                placeholder="Short name, application, EPP ID, packager…"
              />
            </label>
            <label>
              Package state
              <select
                value={state}
                onChange={(e) => filter(setState, e.target.value)}
              >
                <option value="">All states</option>
                {data?.states.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              Coverage
              <select
                value={coverage}
                onChange={(e) => filter(setCoverage, e.target.value)}
              >
                <option value="">All packages</option>
                {Object.entries(coverageLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="outline" size="sm"
              type="button"
              onClick={() => setRefresh((value) => value + 1)}
              disabled={busy}
            >
              Refresh
            </Button>
            {/* Demo shows it greyed out (readonly-console.js). */}
            <a
              className="atlas-return"
              href="/manage-database#package-data-import"
            >
              Upload package data
            </a>
          </div>
          <p className="package-counts" role="status" aria-live="polite">
            {busy
              ? "Loading packages…"
              : error
                ? "Packages unavailable: " + error
                : stats
                  ? `${stats.source_packages.toLocaleString()} source packages · ${stats.metadata_packages.toLocaleString()} metadata records · ${stats.matched.toLocaleString()} matched · ${stats.source_only.toLocaleString()} without data · ${stats.metadata_only.toLocaleString()} metadata only${stats.ambiguous ? ` · ${stats.ambiguous} ambiguous source names` : ""}`
                  : "Open Packages to browse status and ownership."}
          </p>
          {data?.note && <p className="package-source-note">{data.note}</p>}
          <div className="package-browser-layout">
            <div className="package-list-panel" aria-busy={busy}>
              <div
                className="package-table-scroll"
                tabIndex={0}
                aria-label="Package list"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Package / short name</th>
                      <th>State</th>
                      <th>Packager</th>
                      <th>Build</th>
                      <th>Coverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {busy && !data && Array.from({ length: 5 }, (_, row) => (
                      <tr key={`loading-${row}`} aria-hidden="true">{Array.from({ length: 5 }, (_, col) => <td key={col}><Skeleton className="atl:h-3 atl:w-full" /></td>)}</tr>
                    ))}
                    {!busy && !data?.items.length && (
                      <tr>
                        <td colSpan={5}>
                          {error
                            ? "Use Refresh to try again."
                            : query || state || coverage
                              ? "No packages match these filters."
                              : readonly
                                ? "No package metadata in this view. Ask an Atlas Admin operator to import package data; SharePoint availability is checked in Admin."
                                : "No package data yet. Upload the ServiceNow CSV in the database updater; source packages appear when the SharePoint folder is connected."}
                        </td>
                      </tr>
                    )}
                    {data?.items.map((item) => (
                      <tr
                        key={item.id}
                        className={selected?.id === item.id ? "selected" : ""}
                      >
                        <td>
                          <button
                            type="button"
                            className="package-row-select"
                            aria-pressed={selected?.id === item.id}
                            disabled={busy}
                            onClick={() => setSelected(item)}
                          >
                            <strong>{item.display_name}</strong>
                            <code>
                              {item.short_name || "Short name not supplied"}
                            </code>
                          </button>
                        </td>
                        <td>
                          <StateBadge state={item.state} />
                        </td>
                        <td>{item.packager || "—"}</td>
                        <td>{item.build || "—"}</td>
                        <td>
                          <Badge variant="outline">
                            {coverageLabels[item.coverage]}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="package-pagination">
                <span>
                  {data?.total
                    ? `${offset + 1}–${Math.min(offset + data.limit, data.total)} of ${data.total.toLocaleString()}`
                    : "0 packages"}
                </span>
                <button
                  type="button"
                  disabled={busy || offset === 0}
                  onClick={() => {
                    setOffset((value) => Math.max(0, value - 100));
                    setSelected(null);
                  }}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={busy || !data || offset + data.limit >= data.total}
                  onClick={() => {
                    setOffset((value) => value + 100);
                    setSelected(null);
                  }}
                >
                  Next
                </button>
              </div>
            </div>
            <m.aside
              className="package-detail panel"
              aria-label="Package details"
              animate={{ opacity: busy ? 0.65 : 1 }}
              transition={{ duration: reduced ? 0 : 0.12 }}
            >
              {!selected ? (
                <Empty>
                  <EmptyHeader>
                  <EmptyMedia variant="icon"><Package aria-hidden="true" /></EmptyMedia>
                  <EmptyTitle>Select a package</EmptyTitle>
                  <EmptyDescription>
                    Review its state, ownership, build and source coverage here.
                  </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <>
                  <div className="package-detail-heading">
                    <h3>{selected.display_name}</h3>
                    <button
                      type="button"
                      onClick={() => setSelected(null)}
                      aria-label="Close package details"
                    >
                      ×
                    </button>
                  </div>
                  <code>
                    {selected.short_name || "Short name not supplied"}
                  </code>
                  <div
                    className="package-detail-actions"
                    role="group"
                    aria-label="Copy package identifiers"
                  >
                    <button
                      type="button"
                      data-package-copy="short_name"
                      disabled={!selected.short_name || busy || copying}
                      onClick={() => copyIdentifier("short_name", "Short name")}
                    >
                      Copy short name
                    </button>
                    <button
                      type="button"
                      data-package-copy="package_id"
                      disabled={!selected.package_id || busy || copying}
                      onClick={() => copyIdentifier("package_id", "Package ID")}
                    >
                      Copy ID
                    </button>
                  </div>
                  <p
                    className="package-copy-status"
                    role="status"
                    aria-live="polite"
                  >
                    {copyFeedback}
                  </p>
                  {selected.metadata_note && (
                    <p className="package-source-note">
                      {selected.metadata_note}
                    </p>
                  )}
                  <p>
                    <StateBadge state={selected.state} />{" "}
                    <span className="package-coverage">
                      {coverageLabels[selected.coverage]}
                    </span>
                  </p>
                  <Tabs.Root defaultValue="details" key={selected.id}>
                    <Tabs.List
                      className="package-detail-tabs"
                      aria-label="Package information"
                    >
                      <Tabs.Trigger value="details">Details</Tabs.Trigger>
                      <Tabs.Trigger value="source">
                        Source &amp; import
                      </Tabs.Trigger>
                    </Tabs.List>
                    <Tabs.Content value="details">
                      <dl>
                        {[
                          ["Package ID", selected.package_id],
                          ["Packager", selected.packager],
                          ["Requester", selected.requester],
                          ["Domain", selected.domain],
                          ["Build", selected.build],
                          ["Created", selected.created],
                          ["Version", selected.version],
                        ].map(([label, value]) => (
                          <React.Fragment key={label}>
                            <dt>{label}</dt>
                            <dd>{value || "Not supplied"}</dd>
                          </React.Fragment>
                        ))}
                      </dl>
                    </Tabs.Content>
                    <Tabs.Content value="source">
                      <dl>
                        <dt>Package source</dt>
                        <dd>
                          {selected.source_present
                            ? "SharePoint synced folder"
                            : readonly
                              ? "Check source in Atlas Admin"
                              : "No matching source folder"}
                        </dd>
                        <dt>Metadata file</dt>
                        <dd>{selected.source || "No matching CSV row"}</dd>
                        <dt>Imported</dt>
                        <dd>{selected.imported_at || "Not imported"}</dd>
                      </dl>
                      <p>
                        Short names match exactly, ignoring case and outer
                        spaces. Package state comes from the imported extract.
                      </p>
                    </Tabs.Content>
                  </Tabs.Root>
                  {selected.ambiguous && (
                    <p className="package-source-note">
                      Multiple source folders share this short name. Metadata is
                      kept separate until the ambiguity is resolved.
                    </p>
                  )}
                  {!selected.metadata_present && (
                    <p className="package-source-note">
                      This package has no matching CSV row. Its live or
                      packaging state is unknown.
                    </p>
                  )}
                  {selected.source_present && !selected.ambiguous && (
                    <button
                      type="button"
                      onClick={inspect}
                      disabled={busy || readonly}
                      title={readonly ? window.AtlasReadOnly.reason : undefined}
                    >
                      Inspect source scripts
                    </button>
                  )}
                  {!selected.source_present && !readonly && (
                    <p className="package-source-note">
                      Metadata only. Deployment needs an existing package folder
                      and valid script.
                    </p>
                  )}
                </>
              )}
            </m.aside>
          </div>
        </div>
      </MotionConfig>
    </LazyMotion>
  );
}
