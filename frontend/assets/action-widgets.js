/* One lightweight activity feed; reading it never contacts a remote machine. */
(() => {
  const active = new Set(['queued','running','paused','monitoring','starting','stopping']);
  const local = new Map();
  let timer, busy=false, closed=false, rows=[], failures=0;
  const readonly=()=>!!window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content==='viewer';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function updateCount() {
    const badge=document.querySelector('#queueCount');
    if(!badge)return;
    const count=['deployments','reboots','actions'].reduce((n,key)=>n+Number(badge.dataset[key]||0),0);
    badge.textContent=count;
    document.querySelector('#queueToggle')?.classList.toggle('has-active',count>0);
  }
  function render() {
    const now=Date.now();
    for(const [id,row] of local)if(row.expires && now>row.expires)local.delete(id);
    const all=[...local.values(),...rows.filter(row=>!(local.has('diagnostics') && row.title==='Performance scan · diagnose'))];
    const host=document.querySelector('#actionWidgets');
    if(!host)return;
    const opened=new Set([...host.querySelectorAll('details[open]')].map(x=>x.dataset.actionLog));
    host.innerHTML=all.map(row=>`<article class="action-widget ${active.has(row.state)?'is-active':''}"><header><div><strong>${esc(row.title)}</strong><small>${esc(row.target||'Atlas')}</small></div><span>${esc(row.state==='launched'?'Launched':row.state)}</span></header><p>${esc(row.message||'In progress')}</p>${row.log?`<details data-action-log="${esc(row.id)}" ${opened.has(row.id)?'open':''}><summary>Live output</summary><pre>${esc(row.log)}</pre></details>`:''}<footer><button data-action-view="${esc(row.view||'admin')}" data-action-id="${esc(row.id)}">Open</button>${(row.controls||[]).map((c,i)=>`<button data-action-control="${esc(row.id)}" data-control-index="${i}">${esc(c.label)}</button>`).join('')}${active.has(row.state)?'':`<button data-action-dismiss="${esc(row.id)}">Dismiss</button>`}</footer></article>`).join('') || '<p class="empty">No ongoing actions</p>';
    host.querySelectorAll('[data-action-view]').forEach(button=>button.onclick=()=>{
      const row=all.find(r=>r.id===button.dataset.actionId);
      if(row?.target && /^[A-Za-z0-9_.-]{1,64}$/.test(row.target) && typeof setTarget==='function')setTarget(row.target,'',false);
      if(typeof page==='function')page(button.dataset.actionView);
      if(row?.id.startsWith('job-') && row.view==='workspace' && typeof poll==='function')poll(row.id.slice(4),row.target);
      if(row?.id.startsWith('job-') && row.view==='bulk' && typeof bulkPoll==='function')bulkPoll(row.id.slice(4));
      document.querySelector('#queueDrawer')?.classList.remove('open');
    });
    host.querySelectorAll('[data-action-control]').forEach(button=>button.onclick=async()=>{
      const row=all.find(r=>r.id===button.dataset.actionControl);
      const control=row?.controls[Number(button.dataset.controlIndex)];
      if(!control || readonly())return;
      button.disabled=true;
      try {
        if(control.run)control.run();
        else await AtlasClient.request(control.url,{method:'POST'});
        await refresh();
      }catch(error){status(error.message);button.disabled=false;}
    });
    host.querySelectorAll('[data-action-dismiss]').forEach(button=>button.onclick=async()=>{
      const id=button.dataset.actionDismiss;
      try{
        if(local.has(id)){local.delete(id);render();}
        else{await AtlasClient.request('/api/actions/'+encodeURIComponent(id)+'/dismiss',{method:'POST'});await refresh();}
      }catch(error){status(error.message);}
    });
    const badge=document.querySelector('#queueCount');
    if(badge)badge.dataset.actions=all.filter(r=>active.has(r.state)).length;
    updateCount();
  }
  function status(message){const el=document.querySelector('#actionWidgetsStatus');if(el)el.textContent=message;}
  async function refresh(){
    if(readonly()||closed||busy)return;
    clearTimeout(timer);busy=true;
    try{
      rows=(await AtlasClient.request('/api/actions')).actions||[];failures=0;render();
      status('Live activity · completed items clear automatically');
    }catch(error){failures++;status('Updates unavailable — last known activity shown. '+error.message);}
    finally{
      busy=false;
      if(!closed)timer=setTimeout(refresh,failures?Math.min(30000,2000*2**failures):document.hidden?10000:rows.length||local.size?2000:8000);
    }
  }
  function put(row){if(readonly())return;local.set(row.id,row);render();}
  window.AtlasActions={refresh,updateCount,put};
  window.addEventListener('atlas:activity',event=>{
    if(readonly())return;
    if(event.detail?.open)document.querySelector('#queueDrawer')?.classList.add('open');
    refresh();
  });
  window.addEventListener('pagehide',()=>{closed=true;clearTimeout(timer);});
  window.addEventListener('pageshow',()=>{closed=false;refresh();});
  document.addEventListener('DOMContentLoaded',()=>{
    if(readonly())status('Live actions require Atlas Admin.');else refresh();
    document.querySelector('#queueToggle')?.addEventListener('click',refresh);
  });
})();
