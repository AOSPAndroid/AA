---
name: ad-access
description: Read exact AD identities and group evidence; compare access without changing membership.
---
# Active Directory and access evidence

Use for account/computer/group lookup, lockout or account-health evidence, and comparing returned memberships.

1. Resolve the exact account, UPN, computer or group identity. Atlas person records can supply account context but are not live AD results. Ask which identity or domain/controller is intended if ambiguous; never guess across domains.
2. Call `directory_lookup` with `kind=user` or `computer` and the exact `identity`, or `kind=group` to find groups by name (up to 25). Supply `server` only when the operator specifies the intended domain/controller. The tool uses the current Windows identity and requires RSAT's ActiveDirectory module.
3. Report only properties and memberships actually returned. Preserve missing values, lookup errors and any partial-result warnings. Replicated logon timestamps are approximate, not precise current activity.
4. For a requested comparison, look up only the explicit accounts and compare the returned groups by stable identifiers when available. Distinguish direct, primary or nested membership only when the results label it. Axis uses Atlas's read-only lookup, not its full AD browser or nested-membership traversal.
5. A group difference is evidence for an access request, not proof of effective permissions or the cause of an application failure. Do not add/remove memberships, unlock an account, reset a password, change OU/permissions or infer an approved baseline from a colleague.
6. Hand richer comparison, directory-tree browsing, filtered CSV export or **Copy support summary** to Atlas's **Active Directory** page. Explain which exact identities to enter; do not claim that Axis clicked the page or exported its data.

Missing RSAT, domain connectivity or permission remains a reported limitation. Do not install RSAT, alter credentials or security settings, or try another controller to bypass a denial. No AD data belongs in a public web query.
