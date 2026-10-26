---
name: performance-triage
description: Triage a slow PC or application and hand detailed CPU, RAM and session capture to Atlas.
---
# Slow PC and application triage

Use when a PC freezes, an application is slow, or the operator needs evidence for a performance incident.

1. Resolve the exact affected PC. Establish whether the symptom concerns the whole PC, one application or a Citrix/remote-display session, and when it happens. Ask only for information that changes the next diagnostic step.
2. Use `inspect_computer` with `view=overview` for OS/memory facts or `view=disks` when storage is relevant. `view=processes` lists the 30 processes using the most CPU; narrow it with `query` when one is implicated. Reuse observations already obtained for the current decision.
3. Treat one process snapshot as one observation. Do not invent CPU percentages, a trend, GPU/session latency, a causal diagnosis or current usage from cumulative counters. Do not stop the largest process just because it is large.
4. For detailed time-series evidence, direct the operator to **Workspace → Remote Admin → Performance**, select the exact PC and start a manual capture while reproducing the issue. Ask them to provide the resulting evidence if needed. Axis cannot start or stop Atlas's performance capture through its current tools.
5. Distinguish remote-display symptoms from the target's resource state. Atlas's Citrix mode reduces UI animation; it does not diagnose or repair the remote session. Never claim it changed the target's performance.
6. Summarize observed facts, plausible causes with their uncertainty, and the next check. Only use service/process changes or reboot when the user requests that action; use the structured tool and its snapshot/approval requirements.

An installer exit code or a restarted process does not establish that slowness is fixed. Report verified state and ask for an application-level reproduction when that is the remaining evidence.
