# Axis skills

Skills are reusable local workflow guides. Axis sees a small catalogue in its
system prompt and reads the relevant `SKILL.md` with `read_skill` before following
that workflow. The rest of the guides stay out of the conversation.

In browser chat or the terminal:

- `/skills` lists available guides, including any skipped guides and their errors.
- `/skills pc-health` reads the full guide without contacting the model or a PC.
- Ask "Use pc-health to check the selected PC" to use it for a task. If the target
  is missing or ambiguous, Axis asks which PC you mean.

Reading a skill never runs code or starts an operation. Windows actions still use
Axis's tools and approvals; inside AA those tools run Atlas's own operations, with
Atlas's per-PC guard. Skills
cannot grant extra access, bypass a blocked operation or expose execution to the
LAN Viewer. Applying a guide requires a running model; slash-command listing and
reading work without one.

## Included workflows

| Skill | Atlas feature and behavior |
| --- | --- |
| `atlas-directory` | Find people/PCs and distinguish assigned devices from last-logged-on links. |
| `atlas-desks` | Find recorded seating and use the returned Show on map action. |
| `pc-health` | Select the needed live inspection and open requested remote-support tools. |
| `performance-triage` | Collect supported observations and hand detailed captures to Remote Admin. |
| `package-deployment` | Resolve exact scripts, install/repair/uninstall or copy to explicit PCs. |
| `service-process` | Inspect snapshots, perform requested service/process actions and check printing. |
| `ad-access` | Read exact identities, compare returned membership evidence and hand off richer AD browsing. |
| `request-triage` | Read attached inbox/clipboard evidence, resolve identities and suggest the next diagnostic. |
| `job-recovery` | Inspect jobs/logs and resolve unknown outcomes before release or retry. |
| `atlas-knowledge` | Find Axis notes and draft a runbook for the operator to save in Knowledge Base. |

Tool availability depends on the session: Windows IT tools need Windows, Atlas
lookups need its configured database, and inbox/clipboard tools belong to AA's
local Admin browser chat. Skills name unsupported UI actions as handoffs. They do
not add Knowledge Base database access, map writes, detailed performance capture,
AD changes or automated UI interaction.

## Add a custom skill

For AA, create `data/axis/skills/<name>/SKILL.md` under your AA installation. This
folder is used by the one Axis that the browser chat and the AA terminal both talk
to, and it stays out of Git.
Copy it when updating AA. Do not edit the bundled `axis/skills` files for local
customizations; give your custom skill a distinct name.

Standalone Axis uses `<state-dir>/skills`, or another custom root given with
`--skills DIR`, alongside the bundled guides. Inside AA, Axis runs in the Admin
backend and always uses `data/axis/skills`; the terminal's `--skills` does not
apply there.

For example, create `data/axis/skills/printer-check/SKILL.md`:

```markdown
---
name: printer-check
description: Diagnose a stopped print spooler on an explicit Windows PC.
---
# Printer check

1. Resolve the exact affected Windows hostname. Ask if ambiguous.
2. Use inspect_computer with view=services and query=Spooler.
3. Report its returned state. Restart only when the operator requests it,
   using computer_action and the returned service snapshot.
4. A running service does not verify printing. Ask for a test print when needed.
```

Use a lowercase, hyphenated folder/name of at most 64 characters. Front matter
supports exactly `name` and `description`, once each, on single lines; optional
matching quotes are accepted. This is a small format, not a general YAML parser.
Keep the description within 160 characters and the body within 2,400 characters
so the complete guide fits a normal tool result. UTF-8 and Windows CRLF work.
At most 24 guides load, bundled first; custom names cannot replace bundled ones.
Files above 12,000 bytes, invalid metadata and linked skill folders/files are
skipped and reported by `/skills`. Skills are immediate subfolders, not recursive.
Extra scripts or reference files are not executed or automatically loaded.

Use `/skills` to check the file, then `/reset` to refresh the model's catalogue
after adding/removing a guide or changing its description. `read_skill` and
`/skills NAME` read current file contents. In-progress conversations may retain
earlier instructions as history; reset after changing a procedure you are using.

Write each guide around existing tools and exact returned values. Include the
trigger, minimum inputs, procedure, verification and any necessary handoff. Avoid
hardcoded target lists, credentials, automatic reboots or instructions to override
approval. Only add guides you trust. A guide is workflow guidance, not permission
to expand the operator's request.
