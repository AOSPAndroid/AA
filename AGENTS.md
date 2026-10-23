# AA integration

AA is the separate combined Atlas + Axis application. The original repositories
and Atlas's existing hosted preview are separate products; AA changes and releases
must not deploy over them.

- Keep the Atlas map as the homepage. Preserve map geometry and existing operations.
- Keep the interface compact and use the existing shared design-system tokens.
- Axis executes only through the local Admin backend. Never expose its chat,
  approvals, model control or tools through the read-only LAN Viewer.
- Keep thinking visible and reuse Axis's existing tool approval and verification
  rules. A selected desk supplies context, not permission to make changes.
- Use the active Atlas database and package repository for the embedded agent.
- Keep model files, credentials, runtime state and logs out of Git. The imported
  Atlas seed database and static data are upstream source assets, not runtime state.
- Run tests with disposable databases and simulated operations; never use tests
  to change a real Windows target or the source database.
- Prefer the existing Python standard library / FastAPI / vanilla JavaScript
  stack. Add dependencies only when the feature needs them.

The Windows release is built from main. Verify its source commit marker and
runtime contents before reporting the download updated.
