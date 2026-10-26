# Sources

AA combines two projects owned by AOSPAndroid:

- [Atlas](https://github.com/AOSPAndroid/Atlas), commit
  `3bf1490fed2ec2f43062e58e8b2e1b13dbcc14aa`, supplies the map, directory,
  operations console, database, viewer and frontend assets at the repository root.
  Its original guide is preserved as [README-ATLAS.md](README-ATLAS.md).
- [Axis](https://github.com/AOSPAndroid/Axis), commit
  `2cd232947c816b3c9635da9ab88e680379cc29ab`, supplies the local agent,
  tools, terminal interface and model launcher under [axis/](axis/).

AA adds the browser chat adapter, map chat panel and combined launcher. Upstream
copyright and third-party notices remain with their source files. No model
weights or API credentials are included in Git.

Shared Axis improvements incorporated after the initial import:

- `a9029f0a6f86bc27bec2308bf0e3465d3d9d328a`: the standalone skills port,
  corresponding to AA's skill library and engine-specific guides.
- `9ac7ba8` and `507aac9c6c477f4a73f503f1c397c30f3bab3e4c`: the Flash variant,
  published part checksums and shared model-file preparation, ported with their
  regression tests while preserving AA's launcher/client integration.
