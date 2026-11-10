# AA maintenance release

The unused Draw.io workspace and its bundled vendor tree are removed. Knowledge Base
keeps Markdown articles and Mermaid previews. The duplicate Tools discovery panel is
removed; contextual actions and the command palette remain.

Admin and Axis changes share operation admission/locks, alias-aware recovery and durable
unknown-outcome records. Reboot requests survive application restarts as recovery records;
accepted work is never replayed automatically. Chat save failures are now visible.

The distribution contains fictional users, machines and seating names. The old directory
workbook and real names in the desk-move template are no longer included. Existing
runtime data is preserved. Old Git history and published downloads require separate
repository-owner cleanup.

Configure one stable `runtime_folder` or `AA_DATA_HOME`, and use workspace export/import
when moving installations. Explicit external database and collector paths remain supported.
Viewer sharing is now opt-in. Use **Start AA.bat** / **Stop AA.bat** and follow
`docs/updating-atlas.md` when upgrading from older split data locations.

Updated local browser libraries, a smaller interaction bundle, formatting/lint/distribution
checks and an extracted-bundle smoke test strengthen release verification. Releases carry
immutable source tags, `BUNDLE-COMMIT.txt`, `BUNDLE-MANIFEST.json` and a ZIP checksum.
Models and API keys remain separate.
