# UI ownership

The map and console use the existing vanilla JavaScript renderers. The command palette
and contextual actions use `atlas/command-registry.js`; Viewer presentation capabilities
are declared once in `atlas/action-capabilities.js`. The Viewer backend independently
rejects mutations and private Admin endpoints.

React islands handle packages and Live Inbox in the console. The map and data-source
screens use their existing vanilla JavaScript and do not load the React bundle. Workspace
focuses on search and recent activity; its duplicate shortcut cards have been removed.
The Motion dependency and global press/menu animations are removed. Map and panel motion
remain in the existing renderer, including reduced-motion and Citrix preferences.

The console shows six primary sections, with four specialist sections under More tools.
Selecting one through a command or direct route reveals its group. Data sources shows
the automatic feeds first; manual uploads and recovery are folded into one section.
Direct upload links open the section and focus the requested workflow. Active import
reviews, operation activity and Axis approvals remain visible in their existing surfaces.

Use `npm ci --ignore-scripts` and `npm run build:ui`. Sources live in `frontend/react`,
with committed local browser assets in `frontend/assets`. Windows users need no Node
installation. CI rebuilds and checks parity with the committed output.

The interaction bundle budget is 360 KiB raw / 115 KiB gzip, enforced against the actual
production bundle. Third-party Markdown/Mermaid/terminal libraries load only when needed
and are copied with licenses by `npm run vendor:sync`.

`ui-tokens.css` owns shared colors and appearance variables, theme/shell files own global
layout, and `design-system.css` owns final component geometry. Retired editor and Tools
styles have been removed. Generated map geometry and vendor code are excluded from
formatting; regenerate them using their source tools. After stylesheet color changes,
run `python tools/build_dark_overrides.py`.
