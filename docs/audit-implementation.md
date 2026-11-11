# Audit implementation

This change implements the 10 November 2026 audit against AA main (`b17ed9e`).
It removes Draw.io as requested and preserves map geometry, normal Atlas operations,
visible approvals/tool activity, standalone Axis code and the separate Viewer backend.

| Finding | Implementation |
| --- | --- |
| 01: distributed data | Reproducible fictional seed (128 users, 256 PCs), sanitized seating and desk-move template, removed operational workbook, distribution checks. Existing runtime data is not replaced. |
| 02: mutation admission | Admin and Axis share `OperationService`, locks and pre-dispatch admission checks. |
| 03: aliases | Conservative short/FQDN comparisons for guard checks and acknowledgements; distinct qualified domains/IPs remain distinct. |
| 04: unknown outcomes | Durable direct-change/reboot records, recovery after restart, no automatic retries, pending/timeout results require recovery. |
| 05: dependencies | Updated DOMPurify/Mermaid and vulnerable transitive/development packages; regenerated local vendor assets with licenses. |
| 06: runtime paths | Configurable `RuntimePaths`, resolved diagnostics and stopped workspace export/import, including an external main database override. |
| 07: initialization | Supported application factory, explicit lifespan and runtime schema initialization, no writable source-seed fallback. |
| 08: architecture | Explicit operation context/service and read-only directory repository in `backend/services`; route registration remains compatible with existing feature modules. |
| 09: launchers | AA start/stop is authoritative, legacy redirects, verified retained process handles for server shutdown, atomic ownership records. |
| 10: action discovery | Removed the duplicate DOM-scanning Tools/fallback; shared Viewer capability declarations and existing command registry/contextual actions. |
| 11: UI weight/styles | Removed decorative Motion and duplicate workspace cards; lowered bundle limits to 360 KiB/115 KiB. Map/data screens no longer load React. Specialist navigation and manual imports use disclosures; retired editor/Tools styles and assets removed. |
| 12: developer checks | Portable test command, repaired formatting, focused lint, rebuilt asset parity, distribution/dependency checks in CI. |
| 13: unfinished tidy branch | Changes start from reviewed main; the failing broad reorganization was not merged. Only the cohesive shared service package was moved, with fixture and packaging imports updated together. |
| 14: releases | Explicit runtime manifest, archive hashes/source marker, immutable source-identified release tags, extracted-bundle startup test. |
| 15: mail growth | 90-day/10,000-message defaults, bounded seven-day reconciliation, explicit retained-history repair, notification-only agent retention and search-cache pruning. |
| 16: sharing | Viewer binds locally unless sharing is explicitly enabled; private Admin routes remain absent from Viewer. |
| 17: persistence/cleanup | Observable chat-save failure and retry, retired updater reduced to a message, conflicting guides replaced, reviewed unused imports removed. |

The audit's two “unused React components” were referenced through `@/` aliases. The
production build caught the audit error; `label.jsx` and `separator.jsx` are retained.
The AA knowledge skill now drafts Mermaid Markdown instead of sending the operator to
a removed editor. This is an AA-specific workflow adaptation; shared Axis engine/model
code and standalone Atlas behavior were not changed.

## GitHub administration remains separate

Sanitizing the current source does **not** erase old public Git objects or previously
published ZIPs. Repository visibility, history rewriting, removal of old releases and
branch protection were not changed by editing this checkout. Before making a new public
release, follow [historical data cleanup](historical-data-cleanup.md). The immutable
release workflow takes effect only after this source is merged and published.

Use the AA update guide for the one-time consolidation of older split state locations.
Explicit cross-account collector folders retain their paths and Windows permissions;
workspace export does not crawl unrelated external folders.

Runtime downloads are checked against pinned upstream archive digests before release assembly.
The extracted-bundle regression test uses inert runtime placeholders and simulated Windows work.
It proves packaging/startup/import completeness, not real WMI, Outlook/COM or model
inference. Linux regression/browser checks and Windows CI cover the supported layers;
perform a real Windows operator smoke test before rolling the release out.

## Validation

- 651 Atlas/AA Python tests passed with 17 platform skips; 255 Axis tests passed with 16 skips.
- All 84 current frontend regression suites passed. Retired editor/updater tests were removed
  with their implementations; new tests cover policy parity, aliases, timeout/restart recovery,
  workspace snapshots, retention, save failures and extracted-bundle startup.
- Native Chromium: 12 Admin/Viewer map/console cases at 1366, 768 and 390 px, plus four
  Knowledge Base cases. No page errors or overflow; no retired editor requests; Viewer
  made no private knowledge requests and rejected Axis writes.
- Distribution, pinned dependency audit, formatting, lint, workflow YAML and generated UI
  parity checks passed. Original map floor data/coordinates and PDF/SVG geometry are preserved.

Live Windows targets, Outlook/COM and real model inference were not exercised locally.
The release archive is assembled from pinned, checksum-verified CPU/Vulkan runtime inputs;
GitHub publication and irreversible history cleanup remain separate from local packaging.
