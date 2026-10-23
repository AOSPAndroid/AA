// Group actions keep the exact DN and server captured from the displayed result.
window.AtlasADRows = (() => {
 let menu,origin;
 const close=(restore=false)=>{menu?.remove();menu=null;const previous=origin;origin=null;if(restore&&previous?.isConnected)previous.focus({preventScroll:true});};
 const server=(returned,requested='')=>{const value=String(returned||requested).trim();return value==='Default domain discovery'?'':value;};
 function button(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=fn;return b;}
 // Small object icons in the style of Active Directory Users and Computers.
 const paths={
  group:'<circle cx="5.5" cy="5" r="2.3" fill="#3a7bd5"/><path d="M1.5 12.5c0-2.4 1.8-4 4-4s4 1.6 4 4z" fill="#3a7bd5"/><circle cx="10.5" cy="5.5" r="2" fill="#2bb3a3"/><path d="M8.2 12.5c.2-2 1.2-3.4 2.3-3.4 1.9 0 3.5 1.4 3.5 3.4z" fill="#2bb3a3"/>',
  user:'<circle cx="8" cy="5" r="2.8" fill="#3a7bd5"/><path d="M2.5 14c0-3 2.4-5 5.5-5s5.5 2 5.5 5z" fill="#3a7bd5"/>',
  computer:'<rect x="1.5" y="2.5" width="13" height="8.5" rx="1" fill="#e8eef5" stroke="#5b6b7c"/><rect x="5" y="12.5" width="6" height="1.5" fill="#5b6b7c"/>',
  ou:'<path d="M1.5 4.5h4.5l1.5 1.5h7v7.5h-13z" fill="#e8b84a" stroke="#b8862b" stroke-width=".8"/><rect x="5" y="8" width="6" height="3.5" rx=".5" fill="#fff8e6" stroke="#b8862b" stroke-width=".6"/>',
  container:'<path d="M1.5 4.5h4.5l1.5 1.5h7v7.5h-13z" fill="#e8b84a" stroke="#b8862b" stroke-width=".8"/>',
  domain:'<circle cx="8" cy="8" r="6" fill="#dbe9f7" stroke="#3a7bd5"/><path d="M2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12" stroke="#3a7bd5" fill="none" stroke-width=".8"/>'};
 const kinds={organizationalUnit:'ou',container:'container',builtinDomain:'container',domainDNS:'domain'};
 function icon(kind){const span=document.createElement('span');span.className='ad-icon';span.setAttribute('aria-hidden','true');span.innerHTML='<svg viewBox="0 0 16 16" width="16" height="16">'+(paths[kinds[kind]||kind]||paths.container)+'</svg>';return span;}
 const typeNames={organizationalUnit:'Organizational Unit',container:'Container',builtinDomain:'Container',domainDNS:'Domain',user:'User',computer:'Computer',group:'Group',contact:'Contact'};
 const typeName=kind=>typeNames[kind]||kind||'Object';
 function attach(row,nameCell,actions,object,server,open){
  const isGroup=object.kind==='group';
  const caption=isGroup?'See members':'See groups';
  const invoke=()=>{if(!window.AtlasReadOnly)return open();};
  const link=button(object.name,invoke);link.className='ad-object-link';link.disabled=!!window.AtlasReadOnly;
  link.title=caption+' · '+object.name;nameCell.replaceChildren(icon(object.kind),link);
  // Like the Windows console: double-click opens the object.
  row.addEventListener('dblclick',event=>{if(!event.target.closest('button,summary,input,a'))invoke();});
  const copy=button('Copy',async()=>{
   const text=object.name;
   try{await navigator.clipboard.writeText(text);copy.textContent='Copied';setTimeout(()=>copy.textContent='Copy',1500);}
   catch{actions.querySelector('input')?.remove();const input=document.createElement('input');input.readOnly=true;input.value=text;input.setAttribute('aria-label','Copy group name manually');actions.append(input);input.focus();input.select();}
  });
  copy.setAttribute('aria-label','Copy '+object.name);
  if(isGroup)actions.append(copy);
  const view=button(caption,invoke);view.disabled=!!window.AtlasReadOnly;actions.append(view);
  const showMenu=event=>{
   event.preventDefault();event.stopPropagation();close();
   origin=event.target.closest?.('button:not(:disabled)')||row;
   menu=document.createElement('div');menu.className='atlas-ad-context';menu.setAttribute('role','menu');menu.setAttribute('aria-label','Actions for '+object.name);
   if(isGroup){const c=button('Copy group name',()=>{close(true);copy.click();});c.setAttribute('role','menuitem');c.tabIndex=-1;menu.append(c);}
   const v=button(caption,()=>{close();invoke();});v.disabled=!!window.AtlasReadOnly;v.setAttribute('role','menuitem');menu.append(v);
   v.tabIndex=-1;(row.closest('dialog[open]')||document.body).append(menu);
   const box=menu.getBoundingClientRect(),anchor=origin.getBoundingClientRect(),keyboard=event.type==='keydown'||(!event.clientX&&!event.clientY);
   menu.style.left=Math.max(8,Math.min(keyboard?anchor.left:event.clientX,innerWidth-box.width-8))+'px';menu.style.top=Math.max(8,Math.min(keyboard?anchor.bottom:event.clientY,innerHeight-box.height-8))+'px';
   menu.onkeydown=e=>{
    const buttons=[...menu.querySelectorAll('button:not(:disabled)')],current=buttons.indexOf(document.activeElement);let next;
    if(e.key==='ArrowDown')next=(current+1)%buttons.length;
    if(e.key==='ArrowUp')next=(current-1+buttons.length)%buttons.length;
    if(e.key==='Home')next=0;if(e.key==='End')next=buttons.length-1;
    if(next!==undefined&&buttons.length){e.preventDefault();e.stopPropagation();buttons[next].focus({preventScroll:true});}
   };
   menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
  };
  row.tabIndex=-1;row.addEventListener('contextmenu',showMenu);
  row.addEventListener('keydown',event=>{if(event.key==='ContextMenu'||(event.key==='F10'&&event.shiftKey))showMenu(event);});
 }
 document.addEventListener('pointerdown',e=>{if(menu&&!menu.contains(e.target))close();});
 document.addEventListener('keydown',e=>{if(!menu)return;if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}else if(e.key==='Tab')close(true);});
 window.addEventListener('hashchange',()=>close());window.addEventListener('resize',()=>close());
 return {attach,server,icon,typeName};
})();
(() => {
  const by = (id) => document.getElementById("ad" + id);
  if (!by("Form")) return;
  let busy = false, revision = 0, pending = null, selectionKey = "", selectionPromise = null;
  const el = (tag, text) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = String(text);
    return n;
  };
  function controls() {
    by("Lookup").disabled = busy || !!window.AtlasReadOnly;
    by("Results").querySelectorAll('[data-ad-compare]').forEach(n => n.disabled = busy || !!window.AtlasReadOnly);
  }
  function render(data) {
    const result = by("Results");
    result.replaceChildren();
    if (window.AtlasAD) window.AtlasAD.groupActions = null;
    const overview=el('details');overview.className='workspace-ad-details';
    overview.append(el('summary','Account health & properties'));
    const content=el('div');content.id='adOverview';overview.append(content);result.append(overview);
    const evidence=el('details');evidence.className='workspace-ad-evidence';evidence.append(el('summary','Membership scope & lookup evidence'));
    evidence.append(el('p',`Queried ${data.queried_at || 'Time unavailable'} · ${data.server || 'Server unavailable'} · ${data.operator || 'Operator unavailable'}`),el('p',data.membership_note));
    for (const warning of data.warnings || []) evidence.append(el('p', warning));
    result.append(evidence);
    renderGroups(data, result);
  }
  const valueText = value => value == null || value === '' ? 'Unavailable' : String(value);
  function healthItems(data) {
    const d=data.details, user=data.kind==='user';
    const yes=(key,good,bad)=>[d[key]===true?good:d[key]===false?bad:'Unknown',d[key]===true?'good':d[key]===false?'bad':'unknown'];
    const enabled=yes('Enabled','Enabled','Disabled');
    const items=[['AD object','Found','good'],['Account',...enabled]];
    if(user){
      items.push(['Lockout',d['Locked out']===true?'Locked':d['Locked out']===false?'Not locked':'Unknown',d['Locked out']===true?'bad':d['Locked out']===false?'good':'unknown']);
      const expiration=d['Account expiration'];
      const now=Date.parse(data.queried_at)||Date.now(),date=Date.parse(expiration);
      items.push(['Account expiry',!Object.hasOwn(d,'Account expiration')?'Unknown':expiration==null?'No expiry recorded':Number.isFinite(date)?date<=now?'Expired':new Date(date).toLocaleDateString():'Unknown',Number.isFinite(date)&&date<=now?'bad':'unknown']);
      const expiry=Date.parse(d['Password expires']);
      items.push(['Password',d['Password expired']===true?'Expired':Number.isFinite(expiry)?(expiry<=now?'Expired ':'Expires ')+new Date(expiry).toLocaleDateString():d['Password never expires']===true?'Never expires':d['Password expiry status']||'Unknown',d['Password expired']===true||(Number.isFinite(expiry)&&expiry<=now)?'bad':Number.isFinite(expiry)&&expiry-now<7*86400000?'warn':'unknown']);
    }
    items.push([user?'Password changed':'Machine password changed',valueText(d['Password last set']),'unknown']);
    items.push(['Nested groups',data.nested_complete===true?'Resolved in queried scope':data.nested_complete===false?'Partial':'Not checked',data.nested_complete===true?'good':'warn']);
    return items;
  }
  const nameOf = data => data?.details?.Account || data?.details?.Name || 'AD object';
  function renderOverview() {
    const root=by('Overview');if(!root)return;root.replaceChildren();
    const actions=el('div');actions.className='ad-group-tools';const copy=el('button','Copy support summary');copy.type='button';copy.id='adCopySummary';const status=el('span');status.setAttribute('role','status');
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(supportSummary());status.textContent='Summary copied.';}catch{status.textContent='Clipboard unavailable. Select the summary below.';const text=el('textarea');text.value=supportSummary();text.readOnly=true;text.setAttribute('aria-label','Support summary');root.append(text);text.select();}};
    actions.append(copy,status);root.append(actions);
    const cards=el('div');cards.className='ad-health-comparison';
    for(const data of [primary,...others]){
      const card=el('section');card.className='ad-health-card';card.append(el('h3',nameOf(data)),el('small',`${data.kind} · ${data.server||'Server unavailable'} · ${data.queried_at||'Time unavailable'}`));
      const strip=el('div');strip.className='ad-health-strip';
      for(const [label,value,tone] of healthItems(data)){const badge=el('span');badge.className='ad-health-'+tone;badge.append(el('strong',label+': '),el('span',value));strip.append(badge);}
      card.append(strip,el('p','OU: '+valueText(data.details['OU / parent container'])));
      if(data.kind==='computer')card.append(el('p',valueText(data.details['DNS hostname'])+' · '+valueText(data.details['Operating system'])));
      card.append(el('small','Last logon (replicated, approximate): '+valueText(data.details['Last logon (replicated, approximate)'])));
      for(const warning of data.warnings||[])card.append(el('small',warning));cards.append(card);
    }
    root.append(cards);
    const detail=el('details');detail.className='ad-object-details';detail.open=!!others.length;detail.append(el('summary',others.length?'Side-by-side properties · differences highlighted':'All AD properties'));
    const table=el('table');table.className='ad-details';const head=el('tr');head.append(el('th','Property'));
    for(const data of [primary,...others])head.append(el('th',nameOf(data)));table.append(head);
    for(const name of new Set([primary,...others].flatMap(data=>Object.keys(data.details)))){
      const row=el('tr'),values=[primary,...others].map(data=>valueText(data.details[name]));
      if(others.length&&new Set(values).size>1)row.className='ad-property-different';row.append(el('th',name));values.forEach(v=>row.append(el('td',v)));table.append(row);
    }
    detail.append(table);root.append(detail);
  }
  const groupKey = g => String(g.dn || g.name).toLowerCase();
  function supportSummary() {
    const lines=['Atlas · AD support summary'];
    for(const data of [primary,...others]){
      lines.push('',`${data.kind}: ${nameOf(data)}`,`Queried: ${data.queried_at||'Unavailable'} | Server: ${data.server||'Unavailable'}`);
      for(const [key,value] of Object.entries(data.details))lines.push(key+': '+valueText(value));
      lines.push('Membership scope: '+(data.membership_note||'Not supplied'));
      for(const warning of data.warnings||[])lines.push('Warning: '+warning);
      for(const group of data.groups)lines.push(`[${group.membership||'Unknown'}] ${group.name} | ${group.description??'Description unavailable'} | ${group.dn||''}`);
    }
    if(others.length){
      const a=new Set(primary.groups.map(groupKey)),names=g=>g.map(x=>x.name).join(', ')||'none';
      lines.push('');
      for(const other of others){
        const b=new Set(other.groups.map(groupKey));
        lines.push(`Missing from ${nameOf(primary)} (${nameOf(other)} has): `+names(other.groups.filter(g=>!a.has(groupKey(g)))),
                   `Only ${nameOf(primary)} (not ${nameOf(other)}): `+names(primary.groups.filter(g=>!b.has(groupKey(g)))));
      }
    }
    const access=document.querySelector('.ad-access-check');if(access)lines.push('','Access reference: '+(document.querySelector('[aria-label="DaaS or VDI access profile"]')?.selectedOptions[0]?.textContent||''),access.querySelector('.ad-access-results')?.textContent||'Not checked');
    lines.push('','Read-only evidence. Replicated logon is approximate; group membership is not proof of effective access.');return lines.join('\n');
  }
  let primary = null,
    others = [];
  const MAX_COMPARE = 5;
  function csvCell(value) {
    let s = String(value ?? "");
    if (/^[\s]*[=+@-]/.test(s) || /^[\t\r\n]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  // Who has what: one row per group, one coloured cell per compared object.
  function presenceOf(inFirst, count, total) {
    if (!total) return 'first';
    if (!inFirst) return 'second';
    return count === total ? 'both' : count ? 'partial' : 'first';
  }
  function comparisonText(g) {
    const a = nameOf(primary), total = others.length;
    if (g.presence === 'both') return total > 1 ? 'Everyone has it' : 'In both';
    if (g.presence === 'first') return 'Only ' + a;
    if (g.presence === 'partial') return `${a} + ${g.count} of ${total}`;
    return `Missing from ${a} · ` + (total > 1 ? `${g.count} of ${total} have it` : nameOf(others[0]) + ' has it');
  }
  function renderGroups(data, result) {
    primary = data;
    others = [];
    renderOverview();
    const accessDetails = el('details');accessDetails.className='workspace-ad-access';accessDetails.append(el('summary','Access reference'));
    const access = el('div');accessDetails.append(access);
    result.append(accessDetails);
    let refreshAccess = () => {};
    import('/site-info.js?v=3').then(({mountAccessCheck})=>{
      if(access.isConnected) refreshAccess=mountAccessCheck(access,()=>[primary,...(others.length?others:[null])]);
    }).catch(()=>{access.textContent='Access reference unavailable.';});
    const bar = el("div");
    bar.className = "ad-group-tools ad-group-filter";
    const search = el("input");
    search.type = "search";
    search.placeholder = "Group name";
    search.setAttribute("aria-label", "Filter AD groups");
    const mode = el("select");
    mode.setAttribute("aria-label", "Group name match");
    for (const [v, t] of [
      ["contains", "Contains"],
      ["starts", "Starts with"],
      ["ends", "Ends with"],
      ["exact", "Equals"],
      ["excludes", "Does not contain"],
    ]) {
      const o = el("option", t);
      o.value = v;
      mode.append(o);
    }
    const view = el("select");
    view.setAttribute("aria-label", "Membership comparison");
    const views = {};
    for (const v of ["all", "diff", "second", "first", "partial", "both"]) {
      const o = el("option");
      o.value = v;
      views[v] = o;
      view.append(o);
    }
    view.disabled = true;
    const download = el("button", "Export CSV");
    download.type = "button";
    const copyMissing = el("button", "Copy missing groups");
    copyMissing.type = "button";copyMissing.className = "ad-copy-missing";copyMissing.hidden = true;
    const copyStatus = el("span");copyStatus.setAttribute("role", "status");copyStatus.className = "ad-copy-status";
    // Large directories (200+ groups): fold the list into sections by name prefix (APP-, FS-, VPN-...).
    const sectioned = el("label");sectioned.className = "ad-section-option";
    const sectionBox = el("input");sectionBox.type = "checkbox";sectionBox.checked = true;sectionBox.setAttribute("aria-label", "Group by name prefix");
    sectioned.append(sectionBox, " Group by prefix");sectioned.hidden = true;
    bar.append(search, mode, view, sectioned, copyMissing, copyStatus);
    result.prepend(bar);
    // Always-visible object summary, like the title area of an AD properties sheet.
    const header=el('div');header.className='ad-object-header';
    const who=el('div');who.className='ad-object-name';
    who.append(AtlasADRows.icon(data.kind==='computer'?'computer':'user'),el('strong',data.details.Name||data.details.Account||'AD object'));
    if(data.details.Account&&data.details.Account!==data.details.Name)who.append(el('span',data.details.Account));
    const where=el('small',data.details['Canonical path']||data.details['OU / parent container']||'');where.title=data.details['Distinguished name']||'';
    const strip=el('div');strip.className='ad-health-strip';
    for(const [label,value,tone] of healthItems(data).slice(1)){const badge=el('span');badge.className='ad-health-'+tone;badge.append(el('strong',label+': '),el('span',value));strip.append(badge);}
    header.append(who,where,strip);result.prepend(header);
    const secondaryTools=el('div');secondaryTools.className='ad-group-tools';secondaryTools.append(download);result.append(secondaryTools);
    const compare = el("form");
    compare.className = "ad-group-tools ad-group-compare";
    const kind = el("select");
    kind.setAttribute("aria-label", "Compare object type");
    for (const v of ["user", "computer"]) {
      const o = el("option", v);
      o.value = v;
      kind.append(o);
    }
    kind.value = data.kind || by("Kind").value;
    const identity = el("input");
    identity.required = true;
    identity.maxLength = 700;
    identity.placeholder = "Compare with colleagues or machines · up to 5, comma separated";
    identity.setAttribute("aria-label", "Compare AD object");
    const server = el("input");
    server.maxLength = 128;
    server.placeholder = "Domain / controller (optional)";
    server.value = primary.queryServer;
    server.setAttribute("aria-label", "Comparison domain or controller");
    const go = el("button", "Compare groups");
    go.dataset.adCompare = "";go.disabled = !!window.AtlasReadOnly;
    const status = el("p");
    status.setAttribute("role", "status");
    compare.append(kind, identity, server, go);
    status.className = "ad-compare-status";
    // Coloured counts double as filters: click one to list just those groups.
    const chips = el("div");chips.className = "ad-compare-summary";chips.setAttribute("role", "group");chips.setAttribute("aria-label", "Membership summary");
    const count = el("p");count.className='ad-group-count';count.setAttribute('role','status');
    const list = el("div");
    list.className = "ad-groups ad-group-list";
    list.tabIndex=0;list.setAttribute('aria-label','Scrollable AD group list');
    // Compare sits above the list: pick colleagues first, then read the gaps.
    const heading=el('h3','Compare with other users or machines');heading.className='ad-compare-heading';
    bar.before(heading,compare,status);
    bar.after(chips,count,list);
    result.append(by('Overview').parentElement, result.querySelector('.workspace-ad-evidence'), accessDetails);
    let rows = [], all = [];
    const collapsed = new Set(), SECTION_MIN = 40;
    const labels = () => {
      const a = nameOf(primary), many = others.length > 1;
      views.all.textContent = "All groups";
      views.diff.textContent = "Differences only";
      views.diff.hidden = views.diff.disabled = !others.length;
      views.second.textContent = "Missing from " + a;
      views.first.textContent = "Only " + a;
      views.both.textContent = many ? "Everyone has it" : "In both";
      views.partial.textContent = "Partly shared";
      views.partial.hidden = views.partial.disabled = !many;
    };
    const chip = (text, n, tone, value) => {
      const b = el("button");b.type = "button";b.className = "ad-chip ad-chip-" + tone;b.dataset.view = value;
      b.append(el("strong", n), el("span", text));b.setAttribute("aria-pressed", String(view.value === value));
      b.disabled = !n && value !== "all";
      b.onclick = () => {view.value = view.value === value ? "all" : value;filter();};
      return b;
    };
    const summary = () => {
      chips.replaceChildren();
      if (!others.length) {
        const kinds = {Direct: "has", Nested: "nested", Primary: "primary"};
        for (const [kindName, tone] of Object.entries(kinds)) {
          const n = primary.groups.filter(g => g.membership === kindName).length;
          if (n) {const s = el("span");s.className = "ad-chip ad-chip-" + tone;s.append(el("strong", n), el("span", kindName.toLowerCase()));chips.append(s);}
        }
        return;
      }
      const tally = v => all.filter(g => g.presence === v).length, a = nameOf(primary);
      chips.append(chip("differences", all.filter(g => g.presence !== "both").length, "diff", "diff"),
                   chip("missing from " + a, tally("second"), "missing", "second"), chip("only " + a, tally("first"), "only", "first"));
      if (others.length > 1) chips.append(chip("partly shared", tally("partial"), "partial", "partial"));
      chips.append(chip(others.length > 1 ? "everyone has" : "in both", tally("both"), "shared", "both"), chip("all groups", all.length, "all", "all"));
    };
    const cell = (group, name, owner) => {
      const td = el("td");td.className = "ad-matrix";
      const badge = el("span");
      if (group) {badge.className = "ad-cell ad-cell-" + ({Nested: "nested", Primary: "primary"}[group.membership] || "has");badge.textContent = "✓ " + (group.membership || "Member");}
      else {badge.className = "ad-cell ad-cell-missing" + (owner ? " ad-cell-target" : "");badge.textContent = "✗ Missing";}
      badge.title = name + (group ? " is a member" + (group.via ? " via " + group.via : "") : " is not a member");
      td.append(badge);return td;
    };
    const filter = () => {
      const maps = [primary, ...others].map(o => new Map(o.groups.map(g => [groupKey(g), g])));
      const [a, ...rest] = maps;
      all = [...new Set(maps.flatMap(m => [...m.keys()]))].map(k => {
        const owner = maps.findIndex(m => m.has(k)), count = rest.filter(m => m.has(k)).length;
        return {
          ...maps[owner].get(k),
          members: maps.map(m => m.get(k) || null),
          sourceServer: [primary, ...others][owner].queryServer,
          firstMembership: a.get(k)?.membership || "",
          secondMembership: rest[0]?.get(k)?.membership || "",
          count,
          presence: presenceOf(a.has(k), count, rest.length),
        };
      });
      labels();summary();
      const term = search.value.trim().toLowerCase();
      // Missing groups first, so gaps are seen before anything else.
      const order = {second: 0, partial: 1, first: 2, both: 3};
      rows = all
        .filter((g) => {
          const n = String(g.name || "").toLowerCase();
          return (
            (!term ||
              {
                contains: () => n.includes(term),
                starts: () => n.startsWith(term),
                ends: () => n.endsWith(term),
                exact: () => n === term,
                excludes: () => !n.includes(term),
              }[mode.value]()) &&
            (view.value === "all" || g.presence === view.value || (view.value === "diff" && g.presence !== "both"))
          );
        })
        .sort((x, y) => (others.length ? order[x.presence] - order[y.presence] || y.count - x.count : 0) || String(x.name).localeCompare(String(y.name)));
      list.replaceChildren();
      const missing = all.filter(g => g.presence === "second");
      copyMissing.hidden = !others.length;copyMissing.disabled = !missing.length;
      copyMissing.textContent = missing.length ? `Copy ${missing.length} missing group${missing.length === 1 ? "" : "s"}` : "Nothing missing";
      count.textContent =
        rows.length +
        " matching groups" +
        (others.length
          ? " · Comparing " + nameOf(primary) + " with " + others.map(nameOf).join(", ")
          : "");
      const table = el('table');
      table.setAttribute('aria-label','AD group memberships');
      if (others.length) table.className = 'ad-matrix-table';
      const head=el('thead'), header=el('tr');
      // Comparing: the group type moves into the ⓘ details to leave room for one column per person.
      const columns = others.length ? ['Name',...[primary, ...others].map(nameOf),'Comparison','Description','Actions'] : ['Name','Type','Membership','Description','Actions'];
      for(const [i, text] of columns.entries()){const th=el('th',text);th.scope='col';if(others.length&&i>=1&&i<=others.length+1){th.className='ad-matrix-head'+(i===1?' ad-matrix-target':'');th.title=text;}header.append(th);}
      head.append(header);table.append(head);const body=el('tbody');table.append(body);
      const renderRow = (g) => {
        const row=el('tr'),name=el('td'),description=el('td');
        const actions=el('td');actions.className='ad-row-actions';
        AtlasADRows.attach(row,name,actions,{...g,kind:'group'},g.sourceServer,()=>AtlasAD.browseMembers(g.dn,g.sourceServer));
        const detail=el('details');detail.className='ad-group-record';
        // A small inline toggle keeps each group on one line, like the Windows console.
        const summaryToggle=el('summary');summaryToggle.title='Group details';summaryToggle.setAttribute('aria-label','Group details for '+g.name);summaryToggle.append(el('span','i'));detail.append(summaryToggle);
        const properties=el('dl');
        for(const [label,value] of [['Description',g.description==null?'Description unavailable':g.description||'No description recorded'],['Directory path',g.dn],['Scope',g.scope],['Category',g.category]])properties.append(el('dt',label),el('dd',value||'Unavailable'));
        detail.append(properties);name.append(detail);
        description.className='ad-group-description';
        description.textContent=g.description==null?'Description unavailable':g.description||'No description recorded';description.title=description.textContent;
        const known=value=>value&&value!=='Unavailable';
        const type=el('td',known(g.category)?`${g.category} Group${known(g.scope)?' - '+g.scope:''}`:'Group');type.className='ad-type';
        row.title=g.dn||'';
        row.append(name);
        if(!others.length)row.append(type);
        if(others.length){
          row.className='ad-row-'+g.presence+(g.presence==='second'&&g.count===others.length?' ad-row-all-others':'');
          [primary,...others].forEach((o,i)=>row.append(cell(g.members[i],nameOf(o),i===0)));
          const verdict=el('td');verdict.className='ad-verdict';const tag=el('span',comparisonText(g));tag.className='ad-verdict-'+g.presence;verdict.append(tag);row.append(verdict);
        } else {
          const m=el('td');const tag=el('span',g.membership||'—');tag.className='ad-cell ad-cell-'+({Nested:'nested',Primary:'primary'}[g.membership]||'has');m.append(tag);row.append(m);
        }
        row.append(description,actions);body.append(row);
      };
      sectioned.hidden = all.length < SECTION_MIN;
      if (sectioned.hidden || !sectionBox.checked) rows.forEach(renderRow);
      else {
        // Small prefixes join "Other" so sections stay meaningful.
        const prefixOf = g => (String(g.name || "").match(/^([A-Za-z0-9]+)[-_. ]/)?.[1] || "").toUpperCase();
        const sizes = {};
        for (const g of all) sizes[prefixOf(g)] = (sizes[prefixOf(g)] || 0) + 1;
        const sections = new Map();
        for (const g of rows) {
          const p = sizes[prefixOf(g)] >= 3 && prefixOf(g) ? prefixOf(g) : "Other";
          if (!sections.has(p)) sections.set(p, []);
          sections.get(p).push(g);
        }
        const gaps = list => list.filter(g => g.presence === "second").length;
        const ordered = [...sections].sort(([a, x], [b, y]) => (a === "Other") - (b === "Other") || gaps(y) - gaps(x) || a.localeCompare(b));
        for (const [prefix, members] of ordered) {
          const head = el("tr");head.className = "ad-section";
          const cell = el("td");cell.colSpan = columns.length;
          const toggle = el("button");toggle.type = "button";toggle.className = "ad-section-toggle";
          const open = !collapsed.has(prefix);
          toggle.setAttribute("aria-expanded", String(open));
          toggle.append(el("span", open ? "▾" : "▸"), el("strong", prefix === "Other" ? "Other groups" : prefix + "-…"), el("small", members.length + " group" + (members.length === 1 ? "" : "s")));
          if (others.length) for (const [presence, label] of [["second", "missing"], ["first", "only " + nameOf(primary)], ["partial", "partly shared"], ["both", "everyone has"]]) {
            const n = members.filter(g => g.presence === presence).length;
            if (n) {const tag = el("span", n + " " + label);tag.className = "ad-section-count ad-verdict-" + presence;toggle.append(tag);}
          }
          toggle.onclick = () => {open ? collapsed.add(prefix) : collapsed.delete(prefix);filter();};
          cell.append(toggle);head.append(cell);body.append(head);
          if (open) members.forEach(renderRow);
        }
        const fold = el("span");fold.className = "ad-section-all";
        const collapseAll = el("button", "Collapse all"), expandAll = el("button", "Expand all");
        collapseAll.type = expandAll.type = "button";
        collapseAll.onclick = () => {for (const [prefix] of ordered) collapsed.add(prefix);filter();};
        expandAll.onclick = () => {collapsed.clear();filter();};
        fold.append(collapseAll, expandAll);count.append(fold);
      }
      if(rows.length)list.append(table);else list.append(el('p','No matching groups.'));
      // Differences view: say how much is hidden so nothing looks lost.
      const hidden = view.value === "diff" ? all.filter(g => g.presence === "both").length : 0;
      if (hidden) {
        const note = el("p");note.className = "ad-hidden-note";
        const show = el("button", "Show them");show.type = "button";show.onclick = () => {view.value = "all";filter();};
        note.append(`${hidden} group${hidden === 1 ? "" : "s"} everyone has ${hidden === 1 ? "is" : "are"} hidden · `, show);list.append(note);
      }
      download.disabled = !rows.length;
    };
    search.oninput = filter;
    mode.onchange = filter;
    view.onchange = filter;
    sectionBox.onchange = filter;
    copyMissing.onclick = async () => {
      const text = all.filter(g => g.presence === "second").map(g => g.name).join("\n");
      try {await navigator.clipboard.writeText(text);copyStatus.textContent = "Copied.";}
      catch {copyStatus.textContent = "Clipboard unavailable.";const box = el("textarea");box.value = text;box.readOnly = true;box.setAttribute("aria-label", "Missing groups");copyStatus.replaceChildren(box);box.select();}
      setTimeout(() => {if (copyStatus.textContent === "Copied.") copyStatus.textContent = "";}, 2000);
    };
    download.onclick = () => {
      const names = [primary, ...others].map(nameOf);
      const columns = [
        "Group name",
        "Comparison",
        ...names,
        "Description",
        "Distinguished name",
        "Scope",
        "Category",
      ];
      const records = rows.map((g) => [
        g.name,
        others.length ? comparisonText(g) : "Not compared",
        ...g.members.map((m) => m ? m.membership || "Member" : "Missing"),
        g.description,
        g.dn,
        g.scope,
        g.category,
      ]);
      const csv =
        "﻿" +
        [columns, ...records]
          .map((row) => row.map(csvCell).join(","))
          .join("\r\n");
      const url = URL.createObjectURL(
        new Blob([csv], { type: "text/csv;charset=utf-8" }),
      );
      const link = el("a");
      link.href = url;
      link.download = "atlas-ad-groups.csv";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    compare.onsubmit = async (e) => {
      e.preventDefault();
      if (busy || window.AtlasReadOnly) return;
      const wanted = [...new Set(identity.value.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean))];
      if (!wanted.length) return;
      if (wanted.length > MAX_COMPARE) {status.textContent = `Compare up to ${MAX_COMPARE} at once.`;return;}
      const current = ++revision;
      pending?.abort();pending = new AbortController();
      busy = true;
      controls();
      others = [];
      view.value = "all";
      view.disabled = true;
      filter();renderOverview();refreshAccess();
      const inputs = [
        kind,
        identity,
        server,
        go,
        by("Kind"),
        by("Identity"),
        by("Server"),
        by("Selected"),
      ];
      inputs.forEach((n) => (n.disabled = true));
      const failed = [], found = [];
      try {
        for (const [index, name] of wanted.entries()) {
          status.textContent = wanted.length > 1 ? `Comparing memberships… ${index + 1} of ${wanted.length} (${name})` : "Comparing memberships…";
          const payload={kind:kind.value,identity:name,server:server.value.trim()};
          try {
            const compared = await AtlasClient.request("/api/active-directory/lookup", {
              method: "POST",
              signal: pending.signal,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            if (current !== revision || !compare.isConnected) return;
            found.push({...compared,kind:payload.kind,queryServer:AtlasADRows.server(compared.server,payload.server)});
          } catch (error) {
            if (current !== revision || error.name === "AbortError") return;
            failed.push(name + ": " + error.message);
          }
        }
        others = found;
        view.disabled = !others.length;
        // With hundreds of groups the gaps are what matter: start on the differences.
        if (others.length) view.value = "diff";
        status.textContent = others.length
          ? "Comparison complete. " + [...others.flatMap(o => o.warnings || []), ...failed].join(" ")
          : failed.join(" ");
        filter();renderOverview();refreshAccess();
      } finally {
        if (current !== revision) return;
        pending = null;busy = false;
        inputs.forEach((n) => (n.disabled = false));
        controls();
      }
    };
    for (const n of [kind, identity, server])
      n.oninput = () => {
        others = [];
        view.value = "all";
        view.disabled = true;
        status.textContent =
          "Comparison changed. Click Compare groups to refresh.";
        filter();renderOverview();refreshAccess();
      };
    window.AtlasAD.groupActions = {
      filter: () => search.focus(),
      compare: () => identity.focus(),
      export: () => download.click(),
      summary: () => by("CopySummary")?.click(),
      properties: () => {
        const details = by("Results").querySelector(".workspace-ad-details");
        details.open = true;
        details.querySelector("summary").focus();
        details.scrollIntoView({block: "nearest"});
      },
    };
    filter();controls();
  }

  const fields = ['Kind','Identity','Server','Selected'];
  function reset() {
    revision++;pending?.abort();pending=null;busy=false;
    primary=null;others=[];selectionKey='';selectionPromise=null;
    by('Results').replaceChildren();
    by('Results').setAttribute('aria-busy','false');
    if(window.AtlasAD) window.AtlasAD.groupActions=null;
    fields.forEach(id=>by(id).disabled=false);controls();
  }
  function selectedTitle(kind,identity) {
    const title=document.getElementById('adSelection');
    if(title)title.textContent=identity ? `${kind==='user'?'User':'Machine'} · ${identity}` : 'Select a user or machine';
  }
  async function lookup() {
    if(window.AtlasReadOnly) return;
    const payload={kind:by('Kind').value,identity:by('Identity').value.trim(),server:by('Server').value.trim()};
    reset();selectionKey=JSON.stringify(payload);
    const current=++revision;pending=new AbortController();busy=true;controls();
    fields.forEach(id=>by(id).disabled=true);
    selectedTitle(payload.kind,payload.identity);
    by('Status').textContent='Loading groups for '+payload.identity+'…';
    by('Results').setAttribute('aria-busy','true');
    try {
      const result=await AtlasClient.request('/api/active-directory/lookup',{method:'POST',signal:pending.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(current!==revision)return;
      render({...result,kind:payload.kind,queryServer:AtlasADRows.server(result.server,payload.server)});
      by('Status').textContent=(result.warnings || []).join(' ');
    } catch(error) {
      if(current===revision) by('Status').textContent='Groups unavailable for '+payload.identity+'. '+error.message;
    } finally {
      if(current!==revision)return;
      pending=null;busy=false;fields.forEach(id=>by(id).disabled=false);controls();
      by('Results').setAttribute('aria-busy','false');
    }
  }
  by('Selected').onclick=()=>{
    reset();by('Kind').value='computer';by('Identity').value=S.target||'';
    selectedTitle('computer',S.target);
    by('Status').textContent=S.target?'Selected machine copied. Click Look up AD.':'Select a machine in Workspace first.';
  };
  for(const id of ['Kind','Identity','Server'])by(id).addEventListener('input',()=>{
    reset();selectedTitle(by('Kind').value,by('Identity').value.trim());
    by('Status').textContent='Selection changed. Click Look up AD to refresh.';
  });
  by('Form').onsubmit=event=>{event.preventDefault();if(busy||window.AtlasReadOnly)return;return selectionPromise=lookup();};
  window.AtlasAD = {
    select(kind,identity,run=true) {
      identity=String(identity||'').trim();
      const payload={kind,identity,server:by('Server').value.trim()};
      if(selectionKey===JSON.stringify(payload) && (primary || busy))return selectionPromise;
      reset();by('Kind').value=kind;by('Identity').value=identity;
      selectedTitle(kind,identity);
      if(!identity){by('Status').textContent='No AD account supplied for this selection.';return;}
      selectionKey=JSON.stringify(payload);
      if(window.AtlasReadOnly){this.open();return;}
      if(run)return selectionPromise=lookup();
      by('Status').textContent='Selected '+identity+'. Click Look up AD to load groups.';
    },
    clear() {
      reset();by('Results').setAttribute('aria-busy','false');
      by('Identity').value='';selectedTitle('', '');
      by('Status').textContent='Select a user or machine to load its groups. Use AD lookup for another account or controller.';
      if(window.AtlasReadOnly)this.open();
    },
    async show(kind, identity, run = true, action = "groups") {
      page('active-directory');
      const result=this.select(kind,identity,run);
      if(!run||!identity){by('Identity').focus();}
      const selectedRevision = revision;
      await result;
      // A delayed shortcut must never act on a different selection's results.
      if (run && selectedRevision === revision && !window.AtlasReadOnly && ["compare", "properties", "export", "summary", "filter"].includes(action))
        this.groupActions?.[action]?.();
    },
    command(id) {
      if(id === "ad-browser"){page("active-directory");const browser=document.getElementById("adBrowser");browser.open=true;browser.scrollIntoView({block:"start"});const input=document.querySelector(".ad-browser-tools input");input?.focus();return;}
      if (id === "ad-user-groups")
        return this.show("user", S.user?.user_name || S.user?.email || "");
      if (id === "ad-machine-groups")
        return this.show("computer", S.target || "");
      page("active-directory");
      const action = {
        "ad-compare": "compare",
        "ad-support-summary": "summary",
        "ad-filter-groups": "filter",
        "ad-export-groups": "export",
      }[id];
      if (this.groupActions?.[action]) {
        this.groupActions[action]();
      }
      else {
        by("Status").textContent =
          "Look up an AD object first to " +
          (action || "view") +
          " its groups.";
        by("Identity").focus();
      }
    },
    open() {
      controls();
      if (window.AtlasReadOnly)
        by("Status").textContent =
          "Live AD lookup is available only in local Admin. Demo and Preview do not query the directory.";
    },
  };
  controls();
})();
// Read-only directory navigation shares the same authenticated AD transport.
(() => {
 const form=document.getElementById('adForm'); if(!form)return;
 const host=document.createElement('details');host.className='ad-browser';host.id='adBrowser';
 host.innerHTML='<summary>Directory browser · OUs, users, computers and groups</summary><form class="ad-browser-tools"><label>Domain / controller<input name="server" placeholder="Default domain discovery" maxlength="128"></label><label>Search within current OU<input name="query" placeholder="Name, account or employee ID" maxlength="128"></label><label>Type<select name="kind"><option value="all">All objects</option><option value="user">Users</option><option value="computer">Computers</option><option value="group">Groups</option><option value="ou">OUs / containers</option></select></label><button type="submit">Search</button><button type="button" data-root>Domain root</button><button type="button" data-back disabled>Back</button><button type="button" data-up disabled>Parent OU</button></form><p role="status">Click Domain root to browse, or search. Live AD requires Atlas Admin.</p><div class="ad-browser-path"></div><div class="ad-browser-results"></div><button type="button" data-more hidden>Load more</button>';
 document.getElementById('adResults').after(host);
 const tools=host.querySelector('form'),status=host.querySelector('[role="status"]'),results=host.querySelector('.ad-browser-results'),path=host.querySelector('.ad-browser-path');
 const more=host.querySelector('[data-more]'),back=host.querySelector('[data-back]'),up=host.querySelector('[data-up]');
 let current=null,parent='',history=[],busy=false;
 const make=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);return n;};
 const control=(label,fn)=>{const b=make('button',label);b.type='button';b.onclick=fn;return b;};
 // "OU=Paris,DC=corp,DC=example" -> "corp.example › Paris", as the console tree shows it.
 const crumbs=dn=>{
  const parts=String(dn||'').split(/,(?=(?:[A-Za-z]+)=)/).map(part=>part.split('=')).filter(part=>part.length>1);
  const domain=parts.filter(([k])=>k.toUpperCase()==='DC').map(([,v])=>v).join('.');
  const names=parts.filter(([k])=>k.toUpperCase()!=='DC').map(([,...v])=>v.join('=').replace(/\\(.)/g,'$1')).reverse();
  return [domain||'Directory',...names].join(' › ');
 };
 const containers=['organizationalUnit','container','domainDNS','builtinDomain'];
 async function load(request,remember=true){
  if(busy||window.AtlasReadOnly)return;
  busy=true;status.textContent='Reading directory…';host.setAttribute('aria-busy','true');
  const old=current;results.replaceChildren();more.hidden=true;
  const payload={operation:'children',kind:tools.elements.kind.value,query:tools.elements.query.value.trim(),server:tools.elements.server.value.trim(),base:'',limit:200,...request};
  for(const n of tools.elements)n.disabled=true;
  try{
   const data=await AtlasClient.request('/api/active-directory/browse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
   if(remember&&old)history.push(old);
   const resultServer=AtlasADRows.server(data.server,payload.server);
   tools.elements.server.value=resultServer;
   current={...payload,base:data.base,server:resultServer};parent=data.parent||'';path.textContent=data.base?crumbs(data.base):'';path.title=data.base||'';
   if(data.details){const dl=make('dl');dl.className='ad-browser-properties';for(const [k,v] of Object.entries(data.details)){dl.append(make('dt',k),make('dd',v||'—'));}results.append(dl);}
   const table=make('table');table.innerHTML='<thead><tr><th>Name</th><th>Type</th><th>Description</th><th>Directory path</th><th>Actions</th></tr></thead>';const body=make('tbody');table.append(body);
   for(const item of data.items){
    const row=make('tr'),name=make('td'),kind=make('td',AtlasADRows.typeName(item.kind)),dn=make('td',item.dn),actions=make('td');
    name.append(AtlasADRows.icon(item.kind),make('span',item.name));
    const account=item.account?make('small',item.account):null;if(account)account.className='ad-account';
    kind.className='ad-type';dn.className='ad-dn';dn.title=item.dn||'';
    if(containers.includes(item.kind)){
     const open=()=>load({base:item.dn,operation:'children',server:resultServer});
     actions.append(control('Open',open));
     row.addEventListener('dblclick',event=>{if(!event.target.closest('button'))open();});
    }
    if(['user','computer','group'].includes(item.kind)){
     actions.className='ad-row-actions';
     AtlasADRows.attach(row,name,actions,item,resultServer,()=>{
      if(item.kind==='group')return AtlasAD.browseMembers(item.dn,resultServer);
      document.getElementById('adServer').value=resultServer;AtlasAD.show(item.kind,item.guid||item.account||item.name);document.getElementById('adForm').scrollIntoView({block:'start'});
     });
    }
    if(account)name.append(account);
    actions.append(control('Properties',()=>load({operation:'details',base:item.dn,server:resultServer})));
    row.append(name,kind,make('td',item.description||'—'),dn,actions);body.append(row);
   }
   const wrap=make('div');wrap.className='tablewrap';wrap.append(table);results.append(wrap);
   status.textContent=`${data.items.length} ${payload.operation==='details'?'parent groups':'objects'}${data.more?' · More available; load more or narrow the search.': ''} · ${data.note||''}`;
   more.hidden=!data.more;more.disabled=payload.limit>=5000;more.textContent=more.disabled?'Narrow the search to see additional objects':'Load more';
  }catch(error){status.textContent=error.message;current=null;parent='';}
  finally{busy=false;host.removeAttribute('aria-busy');for(const n of tools.elements)n.disabled=!!window.AtlasReadOnly;back.disabled=!history.length||!!window.AtlasReadOnly;up.disabled=!parent||!!window.AtlasReadOnly;}
 }
 window.AtlasAD.browseMembers=(dn,server='')=>{if(window.AtlasReadOnly)return;page('active-directory');host.open=true;tools.elements.server.value=server;host.scrollIntoView({block:'start'});return load({operation:'members',base:dn,server});};
 tools.onsubmit=e=>{e.preventDefault();load({operation:'search',base:current?.server===tools.elements.server.value.trim()?(['members','details'].includes(current?.operation)?parent:current?.base)||'':''});};
 host.querySelector('[data-root]').onclick=()=>load({operation:'children',base:''});
 back.onclick=()=>{const previous=history.pop();if(previous)return load(previous,false);};
 up.onclick=()=>load({operation:'children',base:parent,server:current?.server||''});
 more.onclick=()=>{if(current)return load({...current,limit:Math.min(5000,current.limit+200)},false);};
 if(window.AtlasReadOnly)for(const n of tools.elements)n.disabled=true;
})();
