---
name: job-recovery
description: Inspect deployment/reboot outcomes, logs and shared PC blocks before any retry or acknowledgement.
---
# Jobs, operation recovery and staging

Use for a queued deployment, reboot status, failed/unknown outcome, retry request or a PC blocked by prior work.

1. Use the supplied job ID with `it_job_status`; if none is known, list jobs (Atlas deployments and reboots, plus any earlier Axis jobs) and select the relevant one. Acknowledge nothing during discovery. `/jobs ID` also reads status without model inference.
2. Read the job's `outcome`, exit code, recorded activity and installer log. Use `read_tool_output` with a returned `output_id` and character offsets if essential sections were omitted. Poll with `wait_seconds=10` only when asked to wait.
3. Separate in progress, copied, launched with an exit code, failed before the script ran, and unknown. Unknown, or `recovery_required`, means no result was read or installers were still running at the timeout (`installer_activity.still_running`); work may have continued. Atlas's reboot monitor follows ping only: compare the boot time from `inspect_computer` overview before saying a PC restarted.
4. For an unknown outcome, inspect the actual PC and relevant evidence. Explain what remains uncertain. Use `acknowledge_unknown=true` only after the operator explicitly confirms inspection and requests release, through the normal approval; it releases the PC in Atlas's **Operation recovery**. It does not cancel, retry or prove the old action succeeded.
5. Atlas and Axis share one per-PC guard. Never delete jobs/locks, edit history or use shell execution to bypass a block.
6. Retry only the explicitly requested, resolved action with the package-deployment workflow. Atlas history's **Retry** / **Queue** are UI actions; do not claim to have used them from Axis.

For requested staging cleanup, `computer_action` with `action=cleanup_packages` deletes the package staging folders Atlas deploys into on the explicit PC. Do not substitute broad temp-folder deletion or prune active/unresolved jobs. Closing chat or stopping a local shell does not guarantee remote work stopped.
