# UI ownership

The map and console use the existing vanilla JavaScript renderers. The command palette
and contextual actions use `atlas/command-registry.js`; Viewer presentation capabilities
are declared once in `atlas/action-capabilities.js`. The Viewer backend independently
rejects mutations and private Admin endpoints.

React islands handle packages, Workspace launchers and Live Inbox. The redundant
DOM-scanning Tools panel and its fallback have been removed. Islands mount only when
an appropriate host exists. Motion respects reduced-motion and Citrix settings.

Use `npm ci --ignore-scripts` and `npm run build:ui`. Sources live in `frontend/react`,
with committed local browser assets in `frontend/assets`. Windows users need no Node
installation. CI rebuilds and checks parity with the committed output.

The interaction bundle budget is 500 KiB raw / 160 KiB gzip, enforced against the actual
production bundle. Third-party Markdown/Mermaid/terminal libraries load only when needed
and are copied with licenses by `npm run vendor:sync`.

`ui-tokens.css` owns shared colors and appearance variables, theme/shell files own global
layout, and `design-system.css` owns final component geometry. Retired editor and Tools
styles have been removed. Generated map geometry and vendor code are excluded from
formatting; regenerate them using their source tools. After stylesheet color changes,
run `python tools/build_dark_overrides.py`.
