---
name: package-deployment
description: Install, repair, uninstall or copy an exact repository package to explicit Windows targets.
---
# Package deployment

Use for Atlas Workspace/Bulk deploy style package actions through Axis.

1. Establish the requested action (`Install`, `Repair` or `Uninstall`) and explicit Windows PCs. Resolve people to eligible hostnames through Atlas when necessary. Never turn a team, desk or ambiguous user into an assumed bulk target list.
2. Call `find_packages` with the supplied package query and action. A unique match may already contain the scripts: reuse that result. Several versions or action scripts require the user's selection unless an existing local procedure makes it unambiguous. List order does not identify the newest version.
3. Use the exact returned package and action-specific script. Do not guess switches, synthesize an uninstall command or fall back to another version because a script is absent.
4. Use `deploy_package` with `computers`, `package`, `script` and `action`. Mode `full` copies and executes; `copy` only stages; `execute` uses an existing staged package. Choose a non-default mode only when it matches the request. At most 25 explicit PCs; each becomes its own Atlas deployment, and they may run in parallel.
5. Briefly state the change and let the tool present its approval. Atlas checks the target and runs only the approved script, refusing a changed or different staged copy; do not duplicate those checks routinely. Atlas and Axis share one per-PC guard. A blocked or unknown prior operation is not permission to bypass it.
6. A returned job ID means queued; the job appears in Atlas's Deployments, marked Axis. Give the ID, then return unless asked to wait or verify. For a requested wait, call `it_job_status` with `wait_seconds=10` and read each job's `outcome`.

Report the outcome field: "launched" with an exit code means the script ran (0 is not proof the application works; 3010/1641 needs a restart, never an automatic one); "complete" is a finished copy-only run; "unknown" means no result was read. Never automatically retry an unknown outcome; use the job-recovery workflow. Atlas's Retry, Queue and deployment kits are UI actions; do not claim to have used them.
