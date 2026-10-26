---
name: job-recovery
description: Inspect deployment/reboot outcomes, logs and shared PC blocks before any retry or acknowledgement.
---
# Jobs, operation recovery and staging

Use for a queued deployment, reboot status, failed/unknown outcome, retry request or a PC blocked by prior work.

1. Use the supplied Axis job ID with `it_job_status`; if no ID is known, list jobs and select the relevant returned job. Acknowledge nothing during discovery. `/jobs ID` also reads status without model inference.
2. Read each relevant target's state, exit code, monitoring details and log. Use `read_tool_output` with a returned `output_id` and character offsets if essential sections were omitted. Poll with `wait_seconds=10` only when asked to wait.
3. Separate queued/running, copied, script success, reboot required, failure, unknown and verified reboot. Unknown can mean work continued after monitoring stopped. Never report success or start another attempt from an absent exit record.
4. For an unknown outcome, inspect the actual PC and relevant evidence. Explain what remains uncertain. Use `acknowledge_unknown=true` only after the operator explicitly confirms inspection and requests release, through the normal approval. It releases the reservation; it does not cancel, retry or prove the old action succeeded.
5. Atlas and Axis share per-PC guards. If Atlas owns the unresolved operation, direct the operator to Atlas's **Operation recovery** and the corresponding logs. Never delete jobs/locks, edit history or use shell execution to bypass a block.
6. Retry only the explicitly requested, resolved action with the package-deployment workflow. Atlas history's **Retry** / **Queue** are UI actions; do not claim to have used them from Axis.

For requested staging cleanup, `computer_action` with `action=cleanup_packages` deletes only Axis's staging on the explicit PC and keeps job evidence. Atlas's package-cleanup UI handles both apps' staging. Do not substitute broad temp-folder deletion or prune active/unresolved jobs. Closing chat or stopping a local shell does not guarantee remote work stopped.
