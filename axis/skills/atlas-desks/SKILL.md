---
name: atlas-desks
description: Locate a person, PC, asset or team on the floor plan and show the exact recorded desk.
---
# Atlas desks and map

Use for where a person sits, who is at a desk, where a PC is recorded, or locating a team.

1. Call `find_desk` with the supplied person, exact desk ID, hostname, asset tag or team. Reuse a relevant desk result already returned; do not query every floor.
2. Preserve the returned floor and `desk_id` exactly. Where several desks match, show the few relevant choices or ask which person/PC the user means. Use pagination only when needed.
3. Report the stored occupant, machine and occupancy fields that answer the question. Empty or conflicting fields remain unknown. Seating is the saved floor plan, not live attendance, a current login or proof a machine is online.
4. The browser renders a **Show on map** action for returned desks. Refer to that action. In the terminal, give the floor and exact desk ID for the operator to find on Atlas's map; do not claim to have moved the map yourself.
5. If the user then requests PC support, resolve an eligible Windows hostname with the Atlas directory tools. A desk selection does not approve deployment, reboot or a seating change.

Axis has no seating-write or map-edit tool. For desk moves, plan editing, occupancy corrections or imports, hand off to the Atlas map/seating UI. Never invent a move API, edit the SQLite database, or infer an occupant from a nearby desk.
