# React interaction layer

Atlas now bundles React, Motion, Tailwind CSS and Radix UI locally. The first shared component is a Tools button that morphs into an inline panel: searchable actions and fields, animated cards, and a moving tab indicator. It runs in the console and map, Admin, Demo, the prepared Preview, and the Admin database manager.

The panel stays in document flow. Workspace and Active Directory remain separate, and opening Tools never queries a directory, scans a machine, stops a service, or starts a deployment. Action cards invoke the original visible control; the current visibility and disabled state are checked again at activation. Read-only restrictions and existing confirmation dialogs remain authoritative. Large inventory and process tables keep their existing renderers.

Radix Collapsible, Tabs and Tooltip provide accessible component behavior. Motion adds size/layout transitions, card entrances, button press feedback and menu entrances. Animations respect Atlas's existing animation preference, the operating-system preference, and Citrix display mode. Effects finish promptly; there is no idle animation loop or table-wide mutation observer. Keyboard users can select tabs with arrow keys, use the search field, and close Tools with Escape. Activating a field retains focus after the closing animation.

Tailwind utilities use the `atl:` prefix and omit Preflight. Component geometry and Atlas tokens remain in `frontend/assets/design-system.css`, loaded after the generated CSS. Map labels and Draw.io remain unchanged.

## Development

Use a Node version supported by the pinned Vite release (Node 22.12+ or newer; this work was built with Node 24).

```sh
npm ci
npm run build:ui
```

Sources live in `frontend/react/` and `vite.config.mjs`. Build output is the committed, single-file ES2020 browser module `frontend/assets/atlas-interactions.js` plus `atlas-interactions.css`. Windows Admin and Demo require no Node installation to run Atlas. Keep the generated assets synchronized when changing source. `npm run watch:ui` rebuilds while editing.

The production JavaScript budget is 500 KiB uncompressed and 160 KiB gzipped. The first build is approximately 436 kB / 139 kB gzipped. It has no runtime CDN imports or extra JavaScript chunks. Existing revalidation/versioned asset serving covers the bundle.

If the module cannot load, the existing action index remains available as an inline fallback. A late React mount removes that fallback and its event listeners, preventing duplicate controls.

## Verification

`tests/react_controls_dom.cjs` checks control discovery, source labels, map controls, restrictions and stale/replaced nodes. `tests/react_interactions_dom.cjs` executes the actual production React/Radix/Motion bundle, including filtering, original handlers, field focus, Escape, navigation and disabled-state changes, with no service requests. `tests/react_bundle_dom.cjs` checks the local bundle, performance budget, utility prefix and stylesheet order. The standard frontend runner includes all three.

Browser checks cover Admin, Demo, Preview, maps, database and Desktop at 1366, 768 and 390 pixels, along with reduced motion and zero background remote calls. Directory/context menu tests also pass with Motion enabled. Preview source and saved versions preserve the real-data snapshot and current access policy.
