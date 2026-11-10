import "./action-capabilities.js";
const shortcuts = {
  workspace: "Alt+1",
  admin: "Alt+2",
  bulk: "Alt+3",
  history: "Alt+4",
  packages: "Alt+6",
  deploy: "Ctrl+D",
  copy: "Ctrl+Shift+D",
  msra: "Ctrl+M",
  cshare: "Ctrl+Shift+C",
  active: "Ctrl+Shift+L",
  queue: "Ctrl+Shift+Q",
  health: "Ctrl+Shift+H",
  summary: "Ctrl+Shift+S",
  software: "Ctrl+Shift+I",
  report: "Ctrl+Shift+R",
  shortcuts: "?",
};
const targeted = new Set([
  "remote-registry",
  "deploy",
  "copy",
  "queue-add",
  "msra",
  "cshare",
  "health",
  "cleanup",
  "summary",
  "software",
  "report",
]);
const viewerCommands = new Set(globalThis.AtlasCapabilities.viewerCommands);
// Add future data uploads here; their command and direct route share this definition.
export const DATABASE_UPDATES = Object.freeze({
  "update-users": {
    section: "directory-import",
    title: "Update users",
    detail: "Upload the complete users and devices workbook (both tabs)",
    keywords:
      "update users user database import upload excel workbook directory",
  },
  "update-devices": {
    section: "directory-import",
    title: "Update devices",
    detail: "Upload the complete users and devices workbook (both tabs)",
    keywords:
      "update devices machines computers laptops phones assets database import upload excel workbook",
  },
  "update-packages": {
    section: "package-data-import",
    title: "Update package data",
    detail: "Upload the ServiceNow CSV with package states and ownership",
    keywords:
      "update packages package data metadata status live packaging csv import upload",
  },
  "update-vdi": {
    section: "vdi-data-import",
    title: "Update VDI data",
    detail:
      "Upload Citrix machines, user associations, catalogues and delivery groups",
    keywords:
      "update vdi citrix virtual desktops machine catalog catalogue delivery group users csv excel import upload",
  },
  "update-floorplans": {
    section: "floorplan-import",
    title: "Update floor plans",
    detail: "Upload bulk seating changes, desk assignments or moves",
    keywords:
      "update floorplan floor plans seating desks moves bulk import upload excel",
  },
});
// The single command catalogue used by the map and IT console.
export const COMMANDS = [
  ...Object.entries(DATABASE_UPDATES).map(([id, update]) => [
    id,
    update.title,
    update.detail,
    update.keywords,
  ]),
  [
    "packages",
    "Packages",
    "Browse package states, ownership and source coverage",
    "package packages live packaging progress epp requester packager status metadata",
  ],
  [
    "ad-browser",
    "AD directory browser",
    "Browse OUs, users, computers, group members and properties",
    "ad browse directory ou tree search group members",
  ],
  [
    "ad-open",
    "See AD groups",
    "Open an exact directory account",
    "ad membership groups",
  ],
  [
    "ad-user-groups",
    "See user groups",
    "Look up the selected user in AD",
    "ad user groups membership",
  ],
  [
    "ad-machine-groups",
    "See machine groups",
    "Look up the selected machine in AD",
    "ad computer machine groups membership",
  ],
  [
    "ad-compare",
    "Compare AD groups",
    "Compare two user or computer memberships",
    "ad compare difference common shared groups",
  ],
  [
    "ad-filter-groups",
    "Filter AD group names",
    "Contains, starts with, ends with or equals",
    "ad groups filter contains ending starts equals excludes",
  ],
  [
    "ad-export-groups",
    "Export AD groups to CSV",
    "Download the current filtered memberships or comparison",
    "ad csv extract export download groups",
  ],

  [
    "active-directory",
    "Active Directory",
    "Look up user/computer groups, OU and account details",
    "ad active directory ou organizational unit groups user computer rsat",
  ],
  [
    "knowledge",
    "Knowledge Base",
    "Read and edit support articles",
    "knowledge base articles runbooks notes",
  ],
  [
    "remote-registry",
    "Enable Remote Registry",
    "Start Remote Registry on the selected machine; enable Manual startup if disabled",
    "remote registry remoteregistry enable service start",
  ],
  [
    "vlans",
    "VLANs",
    "Open site VLAN IDs, names and purposes",
    "vlan network subnet info information",
  ],
  [
    "contacts",
    "Contacts",
    "Open Security, Reception, Print room and AV/VC phone numbers",
    "contacts contact phone telephone reception security print av info",
  ],
  [
    "lookup",
    "User & machine lookup",
    "Find a colleague or stored machine record",
    "directory person user computer lookup",
  ],
  [
    "export",
    "Export records",
    "Download the map records",
    "export download seating json",
  ],
  [
    "ad-support-summary",
    "Copy AD support summary",
    "Copy account or machine health and comparison findings",
    "ad account machine health ticket summary copy",
  ],
  [
    "daas",
    "DaaS reference",
    "Tenant links, broker groups, DDC and MFA",
    "citrix daas cloud groups useful info",
  ],
  [
    "vdi",
    "VDI reference",
    "Trader VDI current and legacy groups",
    "citrix vdi trader groups useful info",
  ],
  [
    "animations",
    "Toggle animations",
    "Turn map and interface animations on or off",
    "motion animation effects",
  ],
  [
    "atlas",
    "Floor atlas",
    "Find desks and people on the office map",
    "map floor seating",
  ],
  [
    "workspace",
    "IT workspace",
    "Directory, machines and application deployment",
    "console install workspace",
  ],
  [
    "inbox",
    "Live Inbox",
    "Incoming emails and notification previews with linked machines",
    "outlook teams email notification listener sender inbox machines",
  ],
  [
    "admin",
    "Remote Admin",
    "Open machine administration controls",
    "remote tools processes reboot",
  ],
  [
    "bulk",
    "Bulk Deploy",
    "Review a multi-machine deployment",
    "bulk rollout deploy",
  ],
  [
    "history",
    "Deployment history",
    "Review recent operations",
    "history results",
  ],
  [
    "terminal",
    "Terminal & PowerShell ISE",
    "Open the local command console and script editor",
    "terminal powershell ise cmd script console",
  ],
  [
    "scripts",
    "Scripts",
    "Run PowerShell scripts on a list of machines: services, processes, health, software",
    "scripts script powershell services disable enable tanium processes kill uptime disk gpupdate restart bulk machines",
  ],
  [
    "psexec",
    "PsTools / PsExec",
    "Open the remote command workbench and terminal",
    "pstools psfile psgetsid psinfo psping pskill pslist psloggedon psloglist pspasswd psservice psshutdown pssuspend uptime psexec ps exec terminal commands workbench",
  ],
  [
    "active",
    "Ongoing deployments",
    "View live deployment progress",
    "ongoing monitor jobs",
  ],
  [
    "recent",
    "Recent deployment logs",
    "Inspect recent job events",
    "logs events",
  ],
  [
    "queue",
    "Deployment queue",
    "Review and manage queued deployments",
    "queue waiting",
  ],
  [
    "catalogue",
    "Package catalogue",
    "Browse applications and scripts",
    "software packages catalogue",
  ],
  [
    "settings",
    "Package settings",
    "Configure the package repository",
    "settings configuration repository",
  ],
  [
    "database",
    "Manage database",
    "Upload users, devices, VDI, package data and floor plan changes",
    "database import excel csv packages metadata moves vdi citrix",
  ],
  ["view", "Switch 2D / 3D map", "Change the map view", "map view 2d 3d"],
  ["reset", "Fit floor", "Fit the current floor", "reset zoom map"],
  [
    "refresh",
    "Refresh records",
    "Reload the latest directory and seating data",
    "refresh reload",
  ],
  [
    "deploy",
    "Deploy selected package",
    "Review the package and target before deployment",
    "deploy install execute",
  ],
  [
    "copy",
    "Copy package only",
    "Review copy-only deployment controls",
    "copy package",
  ],
  [
    "queue-add",
    "Add deployment to queue",
    "Prepare a package and target for the queue",
    "add queue package",
  ],
  [
    "msra",
    "Remote Assistance",
    "Review assistance tools for the selected machine",
    "msra assistance",
  ],
  [
    "cshare",
    "Open C$ share",
    "Review file access tools for the selected machine",
    "c$ share files",
  ],
  [
    "health",
    "Target health",
    "Inspect the selected machine health panel",
    "health status",
  ],
  [
    "cleanup",
    "Clean package folder",
    "Review cleanup controls for the selected machine",
    "clean cleanup packages",
  ],
  [
    "summary",
    "Copy support summary",
    "Open the selected machine support-summary control",
    "copy summary clipboard",
  ],
  [
    "software",
    "Installed software",
    "Open installed-software controls",
    "inventory software applications",
  ],
  [
    "report",
    "Machine report",
    "Open machine reporting controls",
    "copy complete report",
  ],
  [
    "shortcuts",
    "Keyboard shortcuts",
    "View available keyboard shortcuts",
    "help shortcuts keyboard",
  ],
  [
    "recovery",
    "Operation recovery",
    "Review operations interrupted by restart or lost monitoring",
    "recovery interrupted unknown",
  ],
].map(([id, title, detail, keywords]) => ({
  id,
  title,
  detail,
  keywords,
  kind: "Action",
  shortcut: shortcuts[id] || "",
  requiresTarget: targeted.has(id),
  handler: id,
  viewer: viewerCommands.has(id),
}));
export const MAP_COMMANDS = new Set([
  ...Object.keys(DATABASE_UPDATES),
  "vlans",
  "contacts",
  "atlas",
  "catalogue",
  "settings",
  "database",
  "view",
  "reset",
  "refresh",
  "export",
  "animations",
]);
export function commandUrl(id, target = "") {
  if (!COMMANDS.some((c) => c.id === id)) throw Error("Unknown Atlas command");
  if (Object.hasOwn(DATABASE_UPDATES, id))
    return "/manage-database#" + DATABASE_UPDATES[id].section;
  const query = new URLSearchParams({ command: id });
  if (target && id !== "knowledge") query.set("machine", target);
  return (MAP_COMMANDS.has(id) ? "/" : "/installer") + "?" + query;
}
