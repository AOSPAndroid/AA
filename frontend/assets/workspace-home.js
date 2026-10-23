/* Workspace activity is local history only; never starts a machine scan. */
(() => {
  const host = document.getElementById('workspaceActivity');
  if (!host) return;
  const readonly = () => !!window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content === 'viewer';
  const visible = () => !document.hidden && document.getElementById('workspace')?.classList.contains('active');
  let busy = false, last = 0, rows = [], error = '', loaded = false;
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function recent() {
    try { const values = JSON.parse(localStorage.getItem('wmiTargetPrefs') || '{}').recent;
      return Array.isArray(values) ? values.filter(x => typeof x === 'string').slice(0, 6) : [];
    } catch { return []; }
  }
  function render() {
    const machines = recent();
    host.innerHTML = `<section class="workspace-activity-card"><header><h3>Recent machines</h3><small>This browser</small></header><ul>${machines.map(pc => `<li><button type="button" data-home-machine="${safe(pc)}"><span data-atlas-icon="machines" aria-hidden="true"></span><strong>${safe(pc)}</strong><span aria-hidden="true">↗</span></button></li>`).join('')}</ul>${machines.length ? '' : '<p class="muted">Machines you select will appear here.</p>'}</section>
      <section class="workspace-activity-card"><header><h3>Today’s deployments</h3><button type="button" data-home-refresh ${busy || readonly() ? 'disabled' : ''}>${busy ? 'Loading…' : 'Refresh'}</button></header><div role="status">${readonly() ? '<p class="muted">Deployment activity is available in Atlas Admin.</p>' : error ? `<p class="muted">${safe(error)}</p>` : !loaded ? '<p class="muted">Loading deployment activity…</p>' : rows.length ? `<ul>${rows.map(row => `<li class="workspace-deployment-row"><div><strong>${safe(row.target)}</strong><small>${safe(row.package)} · ${safe(row.action)}</small></div><span class="workspace-state" data-state="${safe(row.state)}">${safe(row.state || 'Unknown')}</span></li>`).join('')}</ul><small class="muted">Latest ${rows.length} today · Atlas server time</small>` : '<p class="muted">No deployments today.</p>'}</div><button type="button" data-home-history>View deployment history →</button></section>`;
    host.querySelectorAll('[data-home-machine]').forEach(button => button.onclick = () => {
      const pc = button.dataset.homeMachine;
      // Reuse the existing selection path, including its health refresh policy.
      setTarget(pc, 'Recent target');
      document.getElementById('search').value = pc;
    });
    host.querySelector('[data-home-refresh]').onclick = () => refresh(true);
    host.querySelector('[data-home-history]').onclick = () => page('history');
  }
  async function refresh(force = false) {
    if (busy || readonly() || (!force && (!visible() || Date.now() - last < 30000))) return;
    busy = true; render();
    try {
      const result = await api('/api/history?today=true&limit=6');
      if (!Array.isArray(result)) throw Error('Unexpected response');
      rows = result; error = ''; loaded = true;
    } catch { error = 'Activity could not be loaded. Use Refresh to retry.'; }
    finally { busy = false; last = Date.now(); render(); }
  }
  const observer = new MutationObserver(() => { render(); refresh(); });
  observer.observe(document.getElementById('recentTargets'), {childList: true});
  observer.observe(document.getElementById('workspace'), {attributes: true, attributeFilter: ['class']});
  const timer = setInterval(() => refresh(), 30000);
  document.addEventListener('visibilitychange', () => refresh());
  window.addEventListener('pagehide', () => { clearInterval(timer); observer.disconnect(); }, {once: true});
  render(); refresh();
})();
