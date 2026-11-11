# Axis inside AA

Start **AA\Start AA.bat** first, then **axis\Start Agent.bat** for a terminal onto
the same Axis used by the map. The terminal does not execute its own Windows tools or
start a second model. `--resume` continues the latest saved chat; `--plain` uses simple
terminal output. Changes retain the same approvals, audit, identity and target guards.

Models remain separate from the release. Supply the full GGUF, or use **Join Model.bat**
to join downloaded parts with checkpoints/checksums. Select the model when starting AA.
Optional **Configure Firecrawl.bat** stores the key in the Windows profile; never commit
it or send private directory information to public search tools.

`/help`, `/status`, `/jobs`, `/memory` and `/skills` expose the shared Admin-backed
state. Custom workflow guides live in `<runtime>/axis/skills/NAME/SKILL.md`; see
[the AA skill guide](../docs/axis-skills.md). Model context, private source handling,
approvals and verification stay authoritative over any guide.

The standalone engine is retained for upstream compatibility, but the supported AA
terminal is the Admin client. For standalone Axis instructions, use the
[upstream guide](https://github.com/AOSPAndroid/Axis/blob/main/docs/GUIDE.md).
See [AA's README](../README.md) for setup and [updating AA](../docs/updating-atlas.md)
for workspace preservation. Shared-engine changes must still be ported to standalone
Axis as described by AGENTS.md; this maintenance change adapts only AA's client/guide.
