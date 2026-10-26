---
name: atlas-directory
description: Find people, PCs and their inventory links; resolve a support target from Atlas records.
---
# Atlas people and computers

Use for who owns a PC, which machines a person has, account/email lookup, or choosing a support target.

1. Reuse an exact record already returned in this conversation. Otherwise call `search_atlas` with the user's name, account, email or PC name and `kind` of `people`, `computers` or `all`.
2. Read the selected result with `read_atlas_record`, using its returned `kind` and `id`. Follow `next_offset` only if another page is needed. Do not invent an ID or silently choose between people or devices.
3. Distinguish assigned devices from last-logged-on links. Include relevant directory/import dates and missing values. Neither relationship proves who is signed in now, current ownership or connectivity.
4. For a Windows support task, select only a real hostname. A record with `windows_remote_supported=false` is inventory only; phones, Macs and synthetic asset IDs cannot be passed to Windows tools. Ask which eligible PC to use if several remain.
5. Use `find_desk` only if seating is relevant. Use `inspect_computer` only when the request needs live state. A selected map desk or Workspace target supplies context, not authorization for a change.

Return the matched person/PC, the relationship that supports the answer, and any ambiguity. Keep private records out of web tools. These tools do not edit inventory, assignments or the floor plan. For imports, VDI-specific records or assignment corrections, direct the operator to Atlas's corresponding inventory/import UI; never write its database through the shell.

If Atlas lookup tools are unavailable, explain that the inventory connection is unavailable and ask for the exact needed identity. Do not locate another database to work around it.
