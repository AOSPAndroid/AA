/* Console state. Feature scripts initialize once after loading. */
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)],
  api = (u, o = {}) => AtlasClient.request(u, o),
  esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
let S = {
  users: [],
  machines: [],
  user: null,
  target: "",
  job: null,
  bulk: null,
  rows: [],
  processes: [],
};
const prefs = () =>
    JSON.parse(localStorage.getItem("wmiPrefs") || '{"favs":[],"recent":[]}'),
  save = (p) => localStorage.setItem("wmiPrefs", JSON.stringify(p));
let lookupSequence = 0;
const scriptRequest = AtlasClient.latest(),
  bulkScriptRequest = AtlasClient.latest(),
  packageRequest = AtlasClient.latest(),
  bulkPackageRequest = AtlasClient.latest();
let deploySubmitting = false;
let queueRunning = false;
let deploymentQueue = [];
let activeQueueId = null;
let sharedPalette = null,
  sharedPaletteReady;
let deploymentMonitorTimer = null;
let deploymentMonitorMode = "active";
let shortcutRegistry = [];
const softwareState = {
  software: new Map(),
  currentSoftware: [],
  softwareTarget: "",
};
const navigationIcons = Object.fromEntries(
  ['workspace','inbox','clipboard','active-directory','packages','admin','bulk','personas','history','terminal','scripts','psexec','knowledge']
    .map(name => [name, AtlasUI.icon(name)]),
);

const masterState = { status: null, resolution: null, running: false };
let consoleCatalogueRequest = 0;
