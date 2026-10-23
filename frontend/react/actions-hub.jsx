import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  LazyMotion,
  MotionConfig,
  domMax,
  m,
} from "motion/react";
import * as Collapsible from "@radix-ui/react-collapsible";
import * as Tabs from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import { activateControl, collectControls, pageContext } from "./controls.js";

export function useAtlasMotion() {
  const read = () =>
    window.AtlasUI.motion.isReduced() || window.AtlasUI.performance.isCitrix();
  const [reduced, setReduced] = useState(read);
  useEffect(() => {
    const update = () => setReduced(read());
    window.addEventListener("atlas-motion-change", update);
    return () => window.removeEventListener("atlas-motion-change", update);
  }, []);
  return reduced;
}
function SparkIcon({ expanded }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      {expanded ? (
        <path d="m6 6 12 12M6 18 18 6" />
      ) : (
        <>
          <path d="M12 3v4m0 10v4M3 12h4m10 0h4m-15-6 3 3m6 6 3 3m-12 0 3-3m6-6 3-3" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  );
}
export function ActionsHub() {
  const [open, setOpen] = useState(false),
    [entries, setEntries] = useState([]),
    [query, setQuery] = useState(""),
    [tab, setTab] = useState("actions");
  const [context, setContext] = useState(() => pageContext(document));
  const [message, setMessage] = useState("");
  const trigger = useRef(),
    search = useRef();
  const reduced = useAtlasMotion();
  const refresh = useCallback(() => {
    const current = collectControls(document);
    setEntries(current);
    setContext(pageContext(document));
    return current;
  }, []);
  const changeOpen = (value) => {
    if (value) {
      const current = refresh();
      setQuery("");
      setMessage("");
      setTab(current.some((entry) => !entry.field) ? "actions" : "fields");
    }
    setOpen(value);
  };
  useEffect(() => {
    if (open) search.current?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const escape = (event) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus({ preventScroll: true });
      }
    };
    const changed = () => {
      setOpen(false);
    };
    // Observe page navigation only while expanded. Record tables remain unobserved.
    const observer = new MutationObserver(() => {
      const next = pageContext(document);
      if (next.title !== context.title) changed();
      else if (next.target !== context.target) refresh();
    });
    const title = document.getElementById("pageTitle");
    if (title) observer.observe(title, { childList: true, subtree: true });
    const target = document.getElementById("barTarget");
    if (target) observer.observe(target, { childList: true, subtree: true });
    const account = document.getElementById("adSelection");
    if (account) observer.observe(account, { childList: true, subtree: true });
    const onInput = (event) => {
      if (event.target.id === context.targetField) refresh();
    };
    document.addEventListener("input", onInput);
    document.addEventListener("keydown", escape);
    window.addEventListener("hashchange", changed);
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", escape);
      document.removeEventListener("input", onInput);
      window.removeEventListener("hashchange", changed);
    };
  }, [open, context.title, context.target, context.targetField, refresh]);
  const activate = (entry) => {
    const ok = activateControl(entry, () => setOpen(false));
    if (!ok) {
      refresh();
      setMessage("This control changed. Choose an available action.");
    }
  };
  const matches = entries.filter(
    (entry) =>
      entry.field === (tab === "fields") &&
      `${entry.label} ${entry.context}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const groups = new Map();
  for (const entry of matches) {
    const key = entry.context || context.title;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  const duration = reduced ? 0 : 0.2;
  const transition = reduced
    ? { duration: 0 }
    : { type: "spring", stiffness: 380, damping: 34, mass: 0.7 };
  return (
    <LazyMotion features={domMax} strict>
      <MotionConfig
        reducedMotion={reduced ? "always" : "never"}
        transition={transition}
      >
        <Tooltip.Provider delayDuration={350}>
          <Collapsible.Root open={open} onOpenChange={changeOpen} asChild>
            <m.section
              layout
              className={`atlas-tools-shell atl:ml-auto ${open ? "atlas-tools-expanded" : ""}`}
              transition={transition}
              aria-label="Atlas tools"
            >
              <m.div
                layout="position"
                className="atlas-tools-heading atl:flex atl:items-center atl:justify-between atl:gap-2"
              >
                {open && (
                  <div className="atlas-tools-context atl:flex atl:min-w-0 atl:items-center atl:gap-1.5">
                    <span className="atlas-tools-orb" aria-hidden="true" />
                    <strong>{context.title}</strong>
                    <span className="atlas-tools-context-label">
                      {context.target ||
                        (context.readonly ? "Read-only" : "On this page")}
                    </span>
                  </div>
                )}
                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <Collapsible.Trigger asChild>
                      <m.button
                        ref={trigger}
                        type="button"
                        className="atlas-tools-trigger atl:flex atl:items-center atl:justify-center atl:gap-1.5"
                        whileTap={reduced ? undefined : { scale: 0.97 }}
                        aria-label={open ? "Close tools" : "Open tools"}
                      >
                        <m.span
                          animate={{ rotate: open ? 90 : 0 }}
                          transition={{ duration }}
                        >
                          <SparkIcon expanded={open} />
                        </m.span>
                        <span>{open ? "Close" : "Tools"}</span>
                        {!open && (
                          <span className="atlas-tools-short-label">
                            on this page
                          </span>
                        )}
                      </m.button>
                    </Collapsible.Trigger>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content
                      sideOffset={6}
                      className="atlas-tools-tooltip"
                    >
                      {open
                        ? "Close this panel · Escape"
                        : "Find actions and fields on this screen"}
                      <Tooltip.Arrow />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>
              </m.div>
              <AnimatePresence initial={false}>
                {open && (
                  <Collapsible.Content forceMount asChild>
                    <m.div
                      key="tools-body"
                      className="atlas-tools-body"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration, ease: [0.22, 1, 0.36, 1] }}
                    >
                      <div className="atlas-tools-content atl:grid atl:gap-2">
                        <div className="atlas-tools-search-row atl:flex atl:items-center atl:gap-1.5">
                          <input
                            ref={search}
                            type="search"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Find a tool or field…"
                            aria-label="Find a tool or field"
                            className="atl:min-w-0 atl:flex-1"
                          />
                          <button
                            type="button"
                            onClick={refresh}
                            aria-label="Refresh available tools"
                          >
                            Refresh
                          </button>
                        </div>
                        <Tabs.Root value={tab} onValueChange={setTab}>
                          <div className="atlas-tools-toolbar atl:flex atl:flex-wrap atl:items-center atl:justify-between atl:gap-1.5">
                            <Tabs.List
                              aria-label="Tool type"
                              className="atlas-tools-tabs atl:flex atl:gap-1"
                            >
                              {[
                                ["actions", "Actions"],
                                ["fields", "Fields"],
                              ].map(([value, label]) => (
                                <Tabs.Trigger key={value} value={value} asChild>
                                  <m.button
                                    type="button"
                                    whileTap={
                                      reduced ? undefined : { scale: 0.97 }
                                    }
                                  >
                                    {label}
                                    {tab === value && (
                                      <m.span
                                        layoutId="atlas-tools-active-tab"
                                        className="atlas-tools-tab-mark"
                                        aria-hidden="true"
                                      />
                                    )}
                                  </m.button>
                                </Tabs.Trigger>
                              ))}
                            </Tabs.List>
                            <span role="status" className="atlas-tools-count">
                              {message ||
                                `${matches.length} ${tab} · ${context.readonly ? "Read-only access" : "Current screen"}`}
                            </span>
                          </div>
                          <Tabs.Content
                            value={tab}
                            tabIndex={-1}
                            className="atlas-tools-results"
                            aria-label={`${tab === "fields" ? "Fields" : "Actions"} on this page`}
                          >
                            {[...groups].map(([title, rows]) => (
                              <section
                                key={title}
                                className="atlas-tools-group"
                              >
                                <h3>{title}</h3>
                                <div className="atlas-tools-grid atl:grid atl:gap-1.5">
                                  {rows.map((entry, index) => (
                                    <m.button
                                      key={entry.id}
                                      type="button"
                                      data-tool-id={entry.node.id || undefined}
                                      disabled={entry.disabled}
                                      onClick={() => activate(entry)}
                                      className="atlas-tools-action atl:flex atl:min-w-0 atl:flex-col atl:items-center atl:justify-center atl:gap-1"
                                      initial={
                                        reduced ? false : { opacity: 0, y: 4 }
                                      }
                                      animate={{ opacity: 1, y: 0 }}
                                      transition={{
                                        duration: reduced ? 0 : 0.12,
                                        delay: reduced
                                          ? 0
                                          : Math.min(index, 5) * 0.015,
                                      }}
                                      whileHover={
                                        reduced || entry.disabled
                                          ? undefined
                                          : { y: -1 }
                                      }
                                      whileTap={
                                        reduced || entry.disabled
                                          ? undefined
                                          : { scale: 0.98 }
                                      }
                                      title={
                                        entry.disabled
                                          ? entry.node.title ||
                                            "Unavailable on this screen"
                                          : entry.label
                                      }
                                    >
                                      <span>{entry.label}</span>
                                      <small>
                                        {entry.disabled
                                          ? "Unavailable"
                                          : entry.field
                                            ? "Focus field"
                                            : entry.node.tagName === "SUMMARY"
                                              ? "Expand / collapse"
                                              : "Open / run"}
                                      </small>
                                    </m.button>
                                  ))}
                                </div>
                              </section>
                            ))}
                            {!matches.length && (
                              <p className="atlas-tools-empty">
                                {query
                                  ? "No matching controls. Try a shorter search."
                                  : "No visible controls in this category yet."}
                              </p>
                            )}
                          </Tabs.Content>
                        </Tabs.Root>
                      </div>
                    </m.div>
                  </Collapsible.Content>
                )}
              </AnimatePresence>
            </m.section>
          </Collapsible.Root>
        </Tooltip.Provider>
      </MotionConfig>
    </LazyMotion>
  );
}
