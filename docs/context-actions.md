# User and device context actions

Right-click a user or machine in Workspace, the map, or the shared viewer. With keyboard focus on a record, use the Context Menu key or Shift+F10. Arrow keys, Home, and End move between available actions; Escape closes the menu and returns focus. Menus scroll within the viewport and work inside modal dialogs.

User actions include group lookup, comparison, account health/properties, group CSV export, AD support summaries, assigned devices/desks, manager/team/office searches, and account/email copy shortcuts. Stored summaries identify their source as imported data.

Windows machine actions include the same directory shortcuts, inventory details, serial/asset copy, Remote Admin, explicit CPU/memory scans, services, remote tools, and deployment. The map offers inventory/directory actions and links into the console for Remote Admin and deployment. Opening a menu performs no lookup, scan, deployment, or machine change.

Directory shortcuts use the clicked account as the primary object. Comparison focuses the second account field after the primary lookup succeeds. Concurrent shortcuts reuse a pending lookup, and superseded results cannot update the current record or steal focus. Directory actions do not change the deployment target. Diagnostic and deployment shortcuts explicitly select the clicked machine; opening deployment does not execute a package.

Demo and Preview allow stored inventory/copy actions. Live directory and remote operations require local Admin. iPhones and other inventory-only assets keep stored details, serial/asset copy, and reports available while computer-directory, Windows diagnostics, and deployment actions remain disabled. Service stopping, package execution, and other state changes retain their existing confirmations and safeguards.

Validation uses fictional records and simulated directory/Windows responses: shared user context actions, asynchronous comparison isolation, exact diagnostic targets, keyboard navigation, viewport clamping, modal/shadow-root menus, phones, and read-only restrictions. No real AD or Windows host is contacted during these checks.
