/* Server-owned reboot watches survive closing the drawer or refreshing the page. */
(() => {
  let rows = [], timer, polling = false, closed = false;
  const active = new Set(['requesting', 'waiting_offline', 'waiting_online']);
  const labels = {requesting: 'Requesting reboot', waiting_offline: 'Waiting to go offline',
    waiting_online: 'Waiting to return', complete: 'Reboot complete', cancelled: 'Monitoring stopped',
    timeout: 'Not confirmed', failed: 'Check failed'};
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const readonly = () => !!window.AtlasReadOnly || document.querySelector('meta[name="atlas-mode"]')?.content === 'viewer';
  function count() {
    const badge = document.querySelector('#queueCount');
    if (!badge) return;
    const n = rows.filter(r => active.has(r.state)).length;
    badge.dataset.reboots = n;
    if (window.AtlasActions) return window.AtlasActions.updateCount();
    badge.textContent = Number(badge.dataset.deployments || 0) + n;
    document.querySelector('#queueToggle')?.classList.toggle('has-active', n > 0);
  }
  function render(data) {
    rows = data.reboots || [];
    const host = document.querySelector('#rebootMonitors');
    if (!host) return;
    host.innerHTML = rows.map(row => `<article class="reboot-card"><header><strong>${escape(row.target)}</strong><span class="reboot-state ${row.state === 'complete' ? 'status-ok' : ['timeout', 'failed'].includes(row.state) ? 'status-bad' : row.state === 'cancelled' ? 'status-neutral' : 'status-warn'}">${escape(labels[row.state] || row.state)}</span></header><p>${escape(row.message)}</p><pre aria-label="Ping output for ${escape(row.target)}">${escape((row.events || []).map(e => `[${e.time}] ${e.message}`).join('\n'))}</pre><button data-stop-reboot="${escape(row.id)}">${active.has(row.state) ? 'Stop monitoring' : 'Dismiss'}</button></article>`).join('');
    host.querySelectorAll('pre').forEach(pre => pre.scrollTop = pre.scrollHeight);
    host.querySelectorAll('[data-stop-reboot]').forEach(button => button.onclick = async () => {
      button.disabled = true;
      try {
        await AtlasClient.request('/api/reboots/' + encodeURIComponent(button.dataset.stopReboot) + '/stop', {method:'POST'});
        refresh();
      } catch (error) { button.disabled = false; showError(error.message); }
    });
    count();
  }
  function showError(message) {
    const status = document.querySelector('#rebootMonitorStatus');
    if (status) status.textContent = message;
  }
  async function refresh() {
    if (readonly() || closed || polling) return;
    clearTimeout(timer);
    polling = true;
    try {
      render(await AtlasClient.request('/api/reboots'));
      showError('Replies confirm network reachability; Windows sign-in and applications may still be starting.');
    } catch (error) {
      showError('Updates unavailable: ' + error.message + '. Monitoring continues while Atlas Admin is running.');
    } finally {
      polling = false;
      if (!closed && (rows.length || document.querySelector('#queueDrawer')?.classList.contains('open')))
        timer = setTimeout(refresh, 2000);
    }
  }
  async function start(computer) {
    if (readonly()) throw Error('Reboot monitoring requires Atlas Admin.');
    const result = await AtlasClient.request('/api/reboot', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({computer})});
    document.querySelector('#queueDrawer')?.classList.add('open');
    // Seed the watch so a concurrent refresh cannot leave a newly started reboot unpolled.
    rows.push({id:result.job, target:result.target, state:'requesting', events:[], message:'Requesting reboot'});
    count();
    await refresh();
    clearTimeout(timer); timer = setTimeout(refresh, 2000);
    return result;
  }
  window.AtlasReboots = {start, refresh, updateCount:count};
  window.addEventListener('pagehide', () => {closed = true; clearTimeout(timer);});
  window.addEventListener('pageshow', () => {closed = false; refresh();});
  document.addEventListener('DOMContentLoaded', () => {
    if (readonly()) showError('Live reboot monitoring is available in Atlas Admin.');
    else refresh();
    document.querySelector('#queueToggle')?.addEventListener('click', refresh);
  });
})();
