# Code audit — 6 October 2026

Baseline: `492608b9abae74217e9aa0bee5221657f33754c0`.

## Scope

Reviewed first-party imports, directory matching and restores, database transactions, package metadata, seating, AD, remote processes/services/software, deployment queues and recovery, browser polling and asynchronous updates, map operations, knowledge documents, launchers and release consistency. Independent reviewers reproduced the critical findings with disposable databases and simulated Windows responses. AI integration was deferred as requested.

Python and JavaScript received syntax, undefined-name and unused-import/variable checks. PowerShell source and fixtures received parser checks; portable mocked PowerShell tests ran where supported. Credential-pattern scanning found no candidates in the current tracked first-party source inspected; it did not cover Git history or runtime files. Third-party Draw.io resources and generated UI bundles remain intact because their dynamic loading prevents a reliable unused-file determination.

## Repaired findings

| Severity | Defect | Result |
| --- | --- | --- |
| High | A launched deployment whose monitor failed lost its unresolved-operation guard on restart or retention pruning. | Persist the recovery requirement separately from retained job snapshots; require explicit target acknowledgment before another mutation. |
| High | Originless cross-site API GETs could invoke remote probes. | Reject cross-site Fetch Metadata requests before transport; protect Admin frames with same-origin headers. Existing local and same-origin clients remain supported. |
| High | An import could replace the directory, then fail recording history or metadata. | Validate the reviewed fingerprint under a writer reservation, take the backup, and commit directory, metadata and history together. Failures roll back the replacement. |
| High | Crafted Excel cell references could allocate columns beyond Excel's actual bounds. | Validate row/column references before allocating cells; infer ordinary omitted references without accepting out-of-range coordinates. |
| High | Same-second refreshes and concurrent reads could associate a reused user ID with a replacement person. | Issue a new directory generation on each build/merge and keep related identity reads on one database snapshot. |
| Medium | Cancel/pause could be accepted before a waiting queue row was nevertheless launched. | Check control flags and claim the row atomically under the queue lock. |
| Medium | Recovery status could change while deployment, cleanup or uninstall waited for its target lock. | Recheck readiness after acquiring the lock; release it on rejection. |
| Medium | Unreadable, malformed or incomplete software results after process launch were treated as ordinary failures. | Preserve an unknown outcome and recovery requirement for all post-launch monitoring failures; require an integer exit code for successful mutation records. Explicit reported remote failure remains distinct. |
| Medium | Windows ping could report an unreachable host as available. | Require an IPv4 TTL echo reply consistently in health, preflight and reboot checks. |
| Medium | G-number exports did not match their Windows domain X-number assignment references. | Add conservative account aliases while retaining ambiguity when separate records collide. Align Unicode lookup normalization with imported keys. |
| Medium | Relocated databases still wrote some backups into the installation directory. Restore metadata could accumulate duplicate prefixes. | Store import backups beside the active database, normally `data/backups/`; restore only the correct directory provenance. |
| Medium | An initial shared-database build could leave a partially initialized final file. | Build and validate an adjacent candidate, then publish without overwriting a target created by another process. |
| Medium | Selecting a phone could leave Remote Admin controls bound to the previous PC. | Clear the Admin target before announcing the new selection. |
| Medium | Software polling could continue forever after an unknown outcome or repeated failed reads. | Reuse the bounded shared watcher, stop at terminal states or eight consecutive failed reads, and cancel on page exit. |
| Medium | CSV exports could evaluate formula-like imported values in spreadsheets and lose numeric zeroes. | Escape formula prefixes and preserve zeroes through a shared CSV serializer; release the bulk export URL. |
| Medium | Late map/script/history, PsExec transcript or knowledge-document responses could replace a newer selection or draft. | Validate request generations and current identities before rendering; preserve edits made while a document read is pending. |
| Medium | Historical PID events could override a deployment's terminal failed/interrupted state in the UI. | Give terminal outcomes precedence over launch evidence. |
| Medium | A standalone backend test could migrate the distributed seed during module import. | Bootstrap disposable database copies before backend imports and verify standalone isolation. The inadvertently initialized audit copy was archived and the seed restored byte-for-byte. |
| High, development dependency | `source-map-js` 1.2.1 had source-map denial-of-service advisory GHSA-68fv-2mgg-jv7q. | Update the compatible lockfile entry to 1.2.2; verify the UI build and production/development dependency scans. |
| Low | Expanded AD fields overflowed mobile layouts, a duplicate Desktop Actions control was clipped, and a Tools tooltip intercepted the search button. | Allow AD fields to shrink, keep Desktop's existing controls, and make the noninteractive tooltip and its wrapper ignore pointer events. |

Removed confirmed unused test imports and package-picker snapshots that copied a large option list without reading it. No broad compatibility or vendor deletion was made.

## Scale evidence

A streamed fictional workbook contained 300,000 users and 300,000 devices. The import preserved all 600,000 source rows and 600,000 assignment/logon relationships. It completed in 61.84 seconds with 495.2 MiB peak process RSS; the resulting database was 450.3 MiB. With the existing runtime expression indexes, exact hostname/account/domain-account/email searches took 0.06–1.92 ms. An unmatched broad search took 165 ms. Self-comparison took 5.50 seconds and fingerprinting 3.59 seconds, with no spurious differences.

These are measurements from this Linux workspace, not production throughput promises. Import memory still depends on unique strings and identity indexes. Broad substring searches remain scans; adding an index needs to preserve current matching behavior.

## Verification

- Complete regression runner passed using the pinned production Python requirements: 256 Python tests, 253 passed and three Windows-only skips; all 61 frontend suites passed.
- Production UI build passed and generated assets remained byte-identical. First-party static checks passed with no reviewed JavaScript lint findings; 90 Python files and 10 PowerShell files parsed.
- npm found zero known advisories after the compatible dependency update, including development dependencies. OSV returned no advisories for the 13 resolved production Python packages; `pip check` passed.
- All 15 native Chromium cases passed: Admin, Demo and prepared Preview, each at Classic/Desktop 1366 px, Classic 768 px and Classic/Desktop 390 px. Navigation, expanded AD, packages, dialogs, keyboard focus, tooltips and read-only controls showed no page errors or horizontal overflow. PC-to-phone selection disabled remote controls without starting a probe. All records and operations were fictional or intercepted.
- The final three browser-discovered UI repairs also passed the affected AD, Desktop, utility, reachable-action and actual React/Radix regression suites. Twenty shared preview assets match the application source; all four preview entry points have current cache hashes. The preview retains its read-only map adapter.

The distributed database remains byte-identical to the baseline, SHA256 `ab81ee13af9703a0a9afedbae97060443841669bc65fdd3b08a11501034a4e9a`. Hosted Preview's 358 JSON snapshot files remain byte-identical to their existing snapshot. The existing preview audience is preserved.

## Validation limits

GitHub currently reports `AOSPAndroid/BAtlas` as **public**, while the README assumes a private repository. Its tracked distributed seed contains 18,739 user records (including name/email fields) and 69,289 machines. This is an unresolved data-access issue: review the intended repository audience and the existing Git history. Removing a file in a future commit does not remove historical copies. No repository audience change, history rewrite or snapshot deletion was performed as part of this audit.

No live Windows hosts, AD, PsTools, services or deployments were exercised. Linux PowerShell fixtures mock only the Windows operator-reporting expression; production authorization and Windows source are unchanged. Windows-only counter math, AD browsing and PowerShell 5.1 group serialization still require a Windows check. Ping availability currently uses IPv4; an echo result does not establish application or session health.

Dependency scans report known advisories in their current databases, not an absence of all vulnerabilities. Imported data, domain rights and corporate-network latency may behave differently from fictional fixtures. Local imports update Admin and Demo; the hosted preview continues using its separately published snapshot.
