---
name: service-process
description: Inspect and safely change a service or process, including print-spooler troubleshooting.
---
# Services, processes and printing

Use for a stopped service, an application process or print-spooler troubleshooting on an exact Windows PC.

1. Establish the explicit target and requested diagnostic or change. A fault report alone does not authorize restarting a service or terminating a process.
2. Call `inspect_computer` with `view=services` or `view=processes` and a narrow `query`. For printing, inspect the actual `Spooler` service. Use the returned service name/PID and snapshot ID, not a guessed display name or an old PID.
3. If the user requested a supported change, call `computer_action` with the exact `computer`, `action` and `snapshot`: `service_start`, `service_stop` or `service_restart` uses `name`; `process_stop` uses `pid`. A stale or changed identity needs a fresh inspection.
4. The tool rechecks identity, handles approval and verifies final state. Reuse that verification; inspect again only if a needed check is missing, failed or uncertain. Never replace a refused structured action with a shell command.
5. For printing, a running Spooler proves service state, not a working printer or cleared queue. Ask for a test print or the specific remaining error if necessary. Deleting spool files, reinstalling drivers and clearing queues are separate changes; never do them as an automatic follow-up.

For a requested start, stop or restart of one named service across up to 50 explicit PCs, use `bulk_service_action`. One approval lists every target; each PC keeps its lock, identity and protected-service checks. Report each result; pending or unknown changes are not successes and need inspection before retrying.

Never stop protected Windows services/processes. Do not change service startup types unless requested. `enable_remote_registry` is a separate explicit, approved action; do not enable it just because a software query failed. For Event Viewer or Computer Management, use `open_remote_tool` only when requested, and report the UI launch separately from diagnosis or connection success.
