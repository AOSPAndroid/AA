# Citrix VDI imports

In **Data management → Citrix VDI data**, select the raw Citrix CSV or XLSX export, choose **Validate and preview**, then **Back up and apply**. The command palette also includes **Update VDI data**.

Atlas accepts the console headers shown in the SingleSessionMachines export: **Name**, **Machine Catalog**, **Delivery Group**, **User**, **User Display Name**, **Maintenance Mode**, **User Change Persistence**, **Power State** and **State**. Unknown columns and every original row are retained for Admin inspection. Repeated machine identities use the whole last row; you do not need to clean the export first.

The **User** field matches directory account identifiers, including domain-qualified usernames and the confirmed G-number export to X-number Windows-login convention. Several accounts separated by commas, semicolons, pipes or newlines link the same VDI to every uniquely matched user. Display names are labels, not identity matches. Unmatched, invalid and ambiguous accounts are reported in the preview; they do not block importing other records. Import users first when adding new accounts. Later users-and-devices imports automatically rebuild VDI links against the updated directory.

The default update mode replaces each supplied VDI and its assignments, keeps omitted VDIs, and leaves ServiceNow users and devices intact. An empty User field clears that VDI’s old assignments. Select **Replace the VDI inventory** only for a complete Citrix snapshot; this removes omitted Citrix records without removing ServiceNow inventory. The review shows removals before saving. Saving creates a VDI-only gzip JSON backup beside the active database in `backups/` and records import history.

Profiles include the VDI filter, a shared assignment count and expandable Citrix details. Power and connection states are labelled as an **imported snapshot**; they do not establish current connectivity or prove an active session. Selecting a Citrix device does not start health checks. Use **Scan health** explicitly in Windows Admin when needed.

Fully qualified machine names stay qualified. Ambiguous short names require selecting an exact record. Invalid or colliding target names remain inventory records and cannot enable Windows remote operations. Demo can read matched profiles and known Citrix fields; importing and remote operations require Admin.
