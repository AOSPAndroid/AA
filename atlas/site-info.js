/* Site reference supplied by the owner; shared by Admin, Demo and private preview. */
export const VLANS = [
  [101, "USER_ACCESS", "Desktops, printers"],
  [102, "AP_MGMT", "Wireless AP"],
  [200, "BUILD", "SCCM PXE"],
  [301, "VOICE", "Voice"],
  [302, "SPEAKERBUS", "Speakerbus"],
  [303, "UNIGY", "IPC dealerboards"],
  [400, "MULTIMEDIA", "Multimedia"],
  [401, "AV", "AV"],
  [601, "SECURITY_VLAN_601", "Security"],
  [602, "SECURITY_CCTV_VLAN_602", "CCTV"],
  [999, "SUSPEND_VLAN", "Suspended port"],
];
export const CONTACTS = [
  ["Security", "+33 1 44 58 31 10", "+33144583110"],
  ["Reception", "+33 1 44 58 32 32", "+33144583232"],
  ["Print room", "+33 1 44 58 31 14", "+33144583114"],
  ["AV/VC", "+44 20 7773 5553", "+442077735553"],
];
// Transcribed from the owner's reference photos, 1 October 2026.
export const TENANTS = [
  ['Preprod Tenant','https://citrix.cloud.com/go/preprodtenant'],
  ['Global Tenant (RPC)','https://citrix.cloud.com/go/globaltenant'],
  ['DaaS · Prod Tenant','https://citrix.cloud.com/go/prodtenant'],
];
export const DAAS = [
  ['Gloucester','fGLB-DAAS-PRD-RPC-GLO','fGLBGLOPRODRPCRL'],
  ['Northolt','fGLB-DAAS-PRD-RPC-NHT','fGLBNHTPRODRPCRL'],
  ['Slough','fGLB-DAAS-PRD-RPC-SLO','fGLBSLOPRODRPCRL'],
];
export const CLOUD_GROUPS = ['EMEA','AMER','APAC'].flatMap(region => [
  [region,'Client',`CLIENT\\GLO-CLI-SEC-${region}_DAAS_Global-RPC`,
    [1,...(region==='EMEA'?[2]:[])].map(n=>`GLO-CLI-SEC-${region}_DAAS_Client_Global_RL${n}`)],
  [region,'Intranet',`INTRANET\\fGLB-${region}_DAAS_Global-RPC`,
    [1,...(region==='EMEA'?[2]:[])].map(n=>`fGLB_${region}_DAAS_Intranet_Global_RL${n}`)],
]);
export const VDI = [
  ['Gloucester','GBRGLOIBV*','GLO'],['Northolt','GBRNHTIBV*','NHT'],
  ['PSC','NYKPSCIBV*','PSC'],['CRN','NYKCRNIBV*','CRN'],
].map(([place,host,dc])=>[place,host,`fGLB-${dc}_DaaS_Trader_Prod_VDI`,`fGLB-${dc}_DaaS_TVDI_Prod_VDI`]);
export const VDI_MACHINES = [
  ['EMEA (GLO/NHT)','fGLB_EMEA_DaaS_Trader_Intranet_Prod_RL',['Fglbglopreprodrpcrl','Fglbnhtpreprodrpcrl']],
  ['AMER (PSC/CRN)','fGLB_AMER_DaaS_Trader_Intranet_Prod_RL',['fGLB_PSC_DaaS_Trader_Intranet_PreProd_RL']],
];
export const MFA = [
  ['INTRANET','fGLBAZADCTXUsers'],['CLIENT','GLO-CLI-SEC-LAM-AZAD-Citrix-Users'],
];
let current;
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
};
export function openSiteInfo(section = "vlans") {
  section = ["vlans","contacts","daas","vdi"].includes(section) ? section : "vlans";
  if (current?.element.isConnected) {
    current.select(section);
    return current.element;
  }
  const { element, body } = AtlasUI.dialog("Site information");
  element.classList.add("atlas-site-info");
  const style = node("style");
  style.textContent = `
    .atlas-site-info {width:min(700px,94vw);max-height:85dvh;box-sizing:border-box;}
    .atlas-site-info .site-intro {color:#617b8d;font-size:13px;margin:0 0 16px;}
    .atlas-site-info .site-tabs {display:flex;gap:6px;padding:4px;background:#edf4f8;border-radius:12px;margin-bottom:18px;}
    .atlas-site-info .site-tabs button {flex:1;border:1px solid transparent;border-radius:9px;background:transparent;color:#47657a;padding:10px 16px;font:600 13px system-ui;}
    .atlas-site-info .site-tabs button[aria-selected=true] {background:white;color:#007da5;border-color:#c9e3ee;box-shadow:0 2px 5px #1733460a;}
    .atlas-site-info .site-table-wrap {overflow:auto;}
    .atlas-site-info table {border-collapse:collapse;width:100%;font-size:13px;text-align:left;}
    .atlas-site-info th {padding:10px 8px;color:#5c7485;font-size:10px;letter-spacing:.06em;text-transform:uppercase;}
    .atlas-site-info td {padding:12px 8px;border-top:1px solid #e5edf2;line-height:1.4;}
    .atlas-site-info td:first-child {color:#007da5;font-weight:700;}
    .atlas-site-info .site-network-name {font:12px/1.5 Consolas,monospace;overflow-wrap:anywhere;}
    .atlas-site-info .site-contact {display:flex;justify-content:space-between;align-items:center;gap:16px;border:1px solid #dbe7ef;border-radius:12px;padding:15px 16px;margin:10px 0;background:#fff;}
    .atlas-site-info .site-contact strong {display:block;margin-bottom:6px;font-size:14px;}
    .atlas-site-info .site-contact a {color:#007da5;font-size:16px;text-decoration:none;white-space:nowrap;}
    .atlas-site-info .site-contact a:hover {text-decoration:underline;}
    .atlas-site-info .site-copy {border:1px solid #cbdde8;border-radius:8px;background:#fff;padding:8px 11px;font-size:12px;color:#244c65;}
    .atlas-site-info .site-status {min-height:18px;color:#557587;font-size:12px;margin:12px 0 0;}
    .atlas-site-info button:focus-visible,.atlas-site-info a:focus-visible {outline:2px solid #0084ad;outline-offset:3px;}
    .atlas-site-info [hidden] {display:none!important;}
    @media(max-width:480px){.atlas-site-info td {padding:10px 5px;font-size:12px;}.atlas-site-info .site-network-name {font-size:10px;}.atlas-site-info .site-contact{padding:12px;gap:8px;}.atlas-site-info .site-contact a {font-size:14px;}}
  `;
  body.append(
    style,
    node("p", "Network, contacts and virtual desktop references", "site-intro"),
  );
  const tabs = node("div", null, "site-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Site information sections");
  const panes = {},
    buttons = {};
  for (const [id, title] of [
    ["vlans", "VLANs"],
    ["contacts", "Contacts"],
    ["daas", "DaaS"],
    ["vdi", "VDI"],
  ]) {
    const button = node("button", title);
    button.id = "site-info-tab-" + id;
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "site-info-" + id);
    const pane = node("section");
    pane.id = "site-info-" + id;
    pane.setAttribute("role", "tabpanel");
    pane.setAttribute("aria-labelledby", button.id);
    button.onclick = () => select(id);
    button.onkeydown = (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const ids=['vlans','contacts','daas','vdi'];
      const index=ids.indexOf(id);
      select(event.key==='Home'?ids[0]:event.key==='End'?ids.at(-1):ids[(index+(event.key==='ArrowRight'?1:3))%4]);
    };
    tabs.append(button);
    buttons[id] = button;
    panes[id] = pane;
  }
  body.append(tabs, ...Object.values(panes));
  const wrap = node("div", null, "site-table-wrap"),
    table = node("table"),
    head = node("thead"),
    header = node("tr"),
    rows = node("tbody");
  for (const title of ["VLAN", "Name", "Purpose"]) {
    const cell = node("th", title);
    cell.scope = "col";
    header.append(cell);
  }
  head.append(header);
  table.append(head, rows);
  wrap.append(table);
  panes.vlans.append(wrap);
  for (const vlan of VLANS) {
    const row = node("tr");
    vlan.forEach((value, index) =>
      row.append(
        node("td", String(value), index === 1 ? "site-network-name" : ""),
      ),
    );
    rows.append(row);
  }
  const status = node("p", "", "site-status");
  status.setAttribute("role", "status");
  for (const [name, display, number] of CONTACTS) {
    const card = node("div", null, "site-contact"),
      details = node("div"),
      link = node("a", display),
      copy = node("button", "Copy", "site-copy");
    link.href = "tel:" + number;
    link.setAttribute("aria-label", "Call " + name + " " + display);
    copy.type = "button";
    copy.setAttribute("aria-label", "Copy " + name + " phone number");
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(number);
        status.textContent = name + " number copied.";
      } catch {
        status.textContent =
          "Clipboard unavailable. Select the phone number to copy it.";
      }
    };
    details.append(node("strong", name), link);
    card.append(details, copy);
    panes.contacts.append(card);
  }
  panes.contacts.append(status);

  const referenceStatus=node('p','','site-status');
  referenceStatus.setAttribute('role','status');body.append(referenceStatus);
  function copyValue(value) {
    const row=node('div',null,'site-group-value');
    const code=node('code',value),copy=node('button','Copy','site-copy');
    copy.type='button';copy.setAttribute('aria-label','Copy '+value);
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(value);referenceStatus.textContent='Copied '+value;}catch{referenceStatus.textContent='Clipboard unavailable. Select the group name to copy it.';}};
    row.append(code,copy);return row;
  }
  function referenceTable(pane,title,headers,records,groupColumns) {
    pane.append(node('h3',title));const wrap=node('div',null,'site-table-wrap'),table=node('table'),head=node('thead'),row=node('tr'),body=node('tbody');
    for(const text of headers){const th=node('th',text);th.scope='col';row.append(th);}head.append(row);table.append(head,body);
    for(const record of records){const tr=node('tr');record.forEach((value,i)=>{const td=node('td');for(const text of Array.isArray(value)?value:[value])td.append(groupColumns.includes(i)?copyValue(text):node('span',text));tr.append(td);});body.append(tr);}
    wrap.append(table);pane.append(wrap);
  }
  for(const id of ['daas','vdi']) {
    const pane=panes[id];pane.append(node('p','Reference transcribed from supplied screenshots · 1 October 2026. Group membership is not checked or changed here.','site-reference-note'));
    const links=node('div',null,'site-tenant-links');
    for (const [title, url] of TENANTS) {
      const link = node('a', title, 'site-tenant-button');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.setAttribute('aria-label', title + ' (opens in a new tab)');
      links.append(link);
    }
    pane.append(links);
    referenceTable(pane,'MFA · cloud.com portal (barclayspvdi)',['Domain','User group'],MFA,[1]);
  }
  panes.daas.append(node('p','User visibility: the reference specifies a data-centre broker group plus MFA. The device also needs its matching DDC registration group.','site-reference-note'));
  referenceTable(panes.daas,'DaaS · INTRANET',['Data centre','User visibility group','Device registration (DDC)'],DAAS,[1,2]);
  const cloud=node('details');cloud.append(node('summary','Citrix Cloud · Global tenant groups by region'));
  referenceTable(cloud,'Global tenant (RPC)',['Region','Domain','User AD group','Machine GPO details'],CLOUD_GROUPS,[2,3]);panes.daas.append(cloud);
  referenceTable(panes.vdi,'Trader VDI · Current Prod tenant',['Location','Machine prefix','User group'],VDI.map(r=>r.slice(0,3)),[2]);
  referenceTable(panes.vdi,'VDI · Machine groups',['Region','Current Prod group'],VDI_MACHINES.map(r=>r.slice(0,2)),[1]);
  panes.vdi.append(node('p','Paris reference: fGLB-GLO_DaaS_Trader_Prod_VDI. Match the user group to the desktop location.','site-reference-note'));
  const legacy=node('details');legacy.append(node('summary','Legacy / Pre-Prod reference'));
  referenceTable(legacy,'Legacy user groups',['Location','Group'],VDI.map(r=>[r[0],r[3]]),[1]);
  referenceTable(legacy,'Legacy machine groups',['Region','Group'],VDI_MACHINES.map(r=>[r[0],r[2]]),[1]);
  legacy.append(node('p','The supplied notes identify the old fGLB-DAAS-PRD-TVDI-NHT/SLO groups as legacy from the 2025 pilot.','site-reference-note'));panes.vdi.append(legacy);
  function select(id) {
    for (const key of Object.keys(panes)) {
      panes[key].hidden = key !== id;
      buttons[key].setAttribute("aria-selected", String(key === id));
      buttons[key].tabIndex = key === id ? 0 : -1;
    }
    buttons[id].focus();
  }
  current = { element, select };
  element.addEventListener(
    "close",
    () => {
      current = null;
    },
    { once: true },
  );
  select(section);
  return element;
}

// Reference checks use the complete lookup result, never the filtered group list.
export function mountAccessCheck(host, getObjects) {
  const profiles=[
    ...DAAS.map(([place,group])=>({label:'DaaS · '+place+' · INTRANET',groups:[group,MFA[0][1]]})),
    ...VDI.map(([place,,group])=>({label:'VDI · '+place+' · INTRANET',groups:[group,MFA[0][1]]})),
    ...CLOUD_GROUPS.map(([region,domain,group])=>({label:'Global RPC · '+region+' · '+domain,groups:[group.split('\\').at(-1),MFA[domain==='Client'?1:0][1]]})),
  ];
  host.className='ad-access-check';
  const label=node('label','Access reference '),select=node('select');
  select.setAttribute('aria-label','DaaS or VDI access profile');
  const empty=node('option','Choose DaaS / VDI profile');empty.value='';select.append(empty);
  profiles.forEach((p,i)=>{const o=node('option',p.label);o.value=String(i);select.append(o);});label.append(select);
  const output=node('div',null,'ad-access-results'),note=node('small','Reference only · uses returned direct, primary and nested memberships. Directory scope may be incomplete; effective access is not verified.');
  host.append(label,output,note);
  function refresh(){
    output.replaceChildren();
    if(select.value===''){output.append(node('span','Not checked · choose the expected profile','ad-access-unknown'));return;}
    const expected=profiles[Number(select.value)].groups;
    for(const [index,data] of getObjects().entries()){
      const card=node('details',null,'ad-access-user'),summary=node('summary');
      const name=data?.details?.Account || data?.details?.Name || (index?'Comparison user':'User');
      if(!data || data.kind!=='user'){
        summary.textContent=name+' · '+(!data?'Not checked': 'Not applicable · machine');card.append(summary);output.append(card);continue;
      }
      const names=new Set((data.groups||[]).map(g=>String(g.name||'').split('\\').at(-1).toLowerCase()));
      const absent=expected.filter(g=>!names.has(g.toLowerCase()));
      const partial=(data.warnings||[]).length>0 || data.nested_complete===false;
      const badge=node('span',partial?'Incomplete lookup':absent.length?absent.length+' not found':'All listed',partial?'ad-access-unknown':absent.length?'ad-access-missing':'ad-access-present');
      summary.append(node('strong',name),badge);card.append(summary);
      for(const group of expected){const found=names.has(group.toLowerCase());const row=node('div',null,'ad-access-row');row.append(node('span',found?'✓ Listed':partial?'? Unknown':'! Not found',found?'ad-access-present':partial?'ad-access-unknown':'ad-access-missing'),node('code',group));card.append(row);}
      if(partial)card.append(node('small','Lookup warnings prevent a complete assessment.'));
      output.append(card);
    }
  }
  select.onchange=refresh;refresh();return refresh;
}
