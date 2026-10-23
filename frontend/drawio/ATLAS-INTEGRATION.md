# Bundled Draw.io

Upstream: https://github.com/jgraph/drawio
Release: v31.5.3
Artifact: https://github.com/jgraph/drawio/releases/download/v31.5.3/draw.war
SHA-256: 6c4ab25145c3479bf0097e4fccd20c602968615986bc999af8a214719fabd3f4

Static release assets only; Java WEB-INF, META-INF and connect integrations are omitted. The upstream LICENSE and library-specific license files are retained. Atlas changes: index.html adds a local-only CSP; PreConfig.js disables external integrations; bootstrap.js loads atlas-bridge.js before editor initialization. atlas-bridge.js adds the small set of Atlas command-palette shape actions. No minified upstream editor code is modified.

The iframe exchanges Draw.io XML with Atlas through the upstream JSON embed protocol. Do not enable external services or publish Admin knowledge.sqlite3 with these static files. To update, verify a new official release digest, replace static assets and reapply/review these four integration changes, then rerun the integration tests.

Unused standalone integrate.min.js and unbundled js/diagramly developer sources are omitted to stay within the hosting archive limit. Production uses app.min.js.
