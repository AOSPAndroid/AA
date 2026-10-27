# AA integration

AA is the separate combined Atlas + Axis application. The original repositories
and Atlas's existing hosted preview are separate products; AA changes and releases
must not deploy over them.

- Ship shared Axis improvements in both AOSPAndroid/Axis (`agent/`) and AA
  (`axis/` plus its Admin adapters). Carry over relevant tests, model metadata,
  documentation and bundle changes together. Record the companion change or
  source commits. Preserve the standalone engine in Axis and the Admin-backed
  engine/client in AA; adapt workflows to each engine instead of copying files
  over AA's integration. AA-only map/inbox features can remain AA-specific.
- Keep the Atlas map as the homepage. Preserve map geometry and existing operations.
- Keep the interface compact and use the existing shared design-system tokens.
- Axis executes only through the local Admin backend. Never expose its chat,
  approvals, model control or tools through the read-only LAN Viewer.
- Keep Axis's work visible — streamed tool activity and approvals — and reuse its
  existing tool approval and verification rules. The model's private reasoning may
  be toggled (off by default in the browser chat); tool activity and approvals are
  never hidden. A selected desk supplies context, not permission to make changes.
- Use the active Atlas database and package repository for the embedded agent.
- Keep model files, credentials, runtime state and logs out of Git. The imported
  Atlas seed database and static data are upstream source assets, not runtime state.
- Run tests with disposable databases and simulated operations; never use tests
  to change a real Windows target or the source database.
- Prefer the existing Python standard library / FastAPI / vanilla JavaScript
  stack. Add dependencies only when the feature needs them.

The Windows release is built from main. Verify its source commit marker and
runtime contents before reporting the download updated.
