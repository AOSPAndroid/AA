---
name: pc-health
description: Check Windows PC health, connectivity, storage or software, and prepare a remote-support handoff.
---
# PC health and remote support

Use for a PC health check, unreachable machine, low storage, software inventory or opening remote support.

1. Establish the exact Windows hostname from the user's request or an unambiguous Atlas record. Inventory-only devices are not remote Windows targets. Ask one question if the target or symptom is unclear.
2. Choose the smallest useful `inspect_computer` view: `preflight` for WMI/admin-share access, `overview` for OS/user/memory facts, `disks` for storage, or `software` with `query` for an application. Do not run every view routinely. Use `offset` only for relevant remaining results.
3. Separate stored inventory from observations made now. Report the returned timestamp, errors and unknown fields where relevant. Access denied is an access failure, not proof the PC is offline. A successful ping or share check alone does not prove WMI or application health.
4. Machine-wide software registry entries do not cover all per-user or MSIX/Appx installations. Never query `Win32_Product` to fill the gap. A listed application is not proof it runs correctly.
5. If requested, use `open_remote_tool` with the exact PC and one of `rdp`, `remote_assistance`, `computer_management`, `event_viewer`, `admin_share`, `temp` or `packages`. The tool's approval handles opening it. Report that the UI was opened, not that a connection or remote session succeeded.

For a requested reboot or staging cleanup, use `computer_action` and its approval, locks and verification. Never treat a health check as permission for cleanup, service changes, enabling RemoteRegistry or reboot. Use Atlas Workspace's **Scan health** for its richer readings when no Axis tool supplies the requested metric. Never bypass an access error with another remote execution method.
