// Retry and re-queue: History rows, Deployments drawer cards and the Deploy panel's progress widget.
const assert = require('node:assert/strict');
const { fixture } = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, timeout = 4000) {
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(15)) if (check()) return;
  throw Error('Deployment actions did not update in time');
}
const response = (data, status = 200) => ({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
const payload = id => ({ computer: 'PC-' + id, folder: 'Example App', script: 'setup_i.ps1', action: 'Install', fresh: true, threads: 16, mode: 'full' });

(async () => {
  const calls = [];
  const f = await fixture({ fetch: async (url, options = {}) => {
    const path = new URL(url, 'http://localhost').pathname, method = options.method || 'GET';
    calls.push(method + ' ' + path);
    if (path === '/api/session') return response({ token: 'fixture' });
    if (path === '/api/health') return response({ identity: 'FIXTURE', version: 'test', database: true, users: 1, machines: 1, repository: true });
    if (path === '/api/packages') return response({ packages: ['Example App'], available: true, total: 1 });
    if (path === '/api/history') return response([
      { id: 'h1', started: '2026-10-20 15:00', target: 'PC-H1', package: 'Example App', action: 'Install', mode: 'full', state: 'failed', exit_code: '1603', operator: 'CORP\\op (Axis)' },
      { id: 'h2', started: '2026-10-20 14:00', target: 'PC-H2', package: 'Example App', action: 'Install', mode: 'full', state: 'complete', exit_code: '0' }]);
    let match = path.match(/^\/api\/deploy\/([^/]+)\/(retry|payload)$/);
    if (match) return match[2] === 'retry' ? response({ job: 'new-' + match[1], target: 'PC-OTHER', package: 'Example App', action: 'Install' }) : response(payload(match[1]));
    if (path === '/api/deployments/recent') return response({ deployments: [
      { id: 'd1', kind: 'single', state: 'failed', target: 'PC-D1', package: 'Example App', action: 'Install', retry: true, events: [], requested_by: 'Axis' },
      { id: 'd2', kind: 'single', state: 'complete', target: 'PC-D2', package: 'Example App', action: 'Install', retry: true, events: [] },
      { id: 'b1', kind: 'single', state: 'failed', target: 'PC1, PC2', package: 'Example App', action: 'Install', retry: false, events: [] }] });
    if (path === '/api/deployments/active') return response({ deployments: [], count: 0 });
    if (path.startsWith('/api/job/')) return response({ state: 'failed', events: [{ time: '15:01', message: 'Installer exit 1603' }] });
    return response({});
  } });
  const { w, run } = f, d = w.document, $ = id => d.getElementById(id);
  await f.console(); d.dispatchEvent(new w.Event('DOMContentLoaded')); await sleep(80);
  run('function toast(){}');

  // History: failed rows can be retried; any row can go back in the queue with its saved options.
  await w.eval('loadDeploymentHistory()');
  const rows = [...d.querySelectorAll('#historyBody tr')];
  // Axis chat deployments share this history and are marked.
  assert.equal(rows[0].querySelector('.history-source')?.textContent, 'Axis');
  assert.equal(rows[1].querySelector('.history-source'), null);
  assert.deepEqual(rows.map(r => [...r.querySelectorAll('.history-actions button')].map(b => b.textContent)), [['Retry', 'Queue'], ['Queue']]);
  rows[0].querySelector('[data-history-retry]').click();
  await until(() => calls.includes('POST /api/deploy/h1/retry'));
  rows[1].querySelector('[data-history-queue]').click();
  await until(() => $('queueCount').textContent === '1');
  assert.match($('queueItems').textContent, /PC-h2[\s\S]*Example App · Install · waiting/);
  assert.equal(w.eval('deploymentQueue[0].threads'), 16, 'The queued item keeps the original options');

  // Deployments drawer: Retry on failed single deployments, Add to queue on any single one.
  w.eval('openDeploymentMonitor("recent")');
  await until(() => d.querySelectorAll('.deployment-monitor-card').length === 3);
  const cards = [...d.querySelectorAll('.deployment-monitor-card')];
  // A deployment Axis started is an ordinary Atlas deployment, marked with where it came from.
  assert.deepEqual(cards.map(c => c.querySelector('.history-source')?.textContent || ''), ['Axis', '', '']);
  assert.deepEqual(cards.map(c => [...c.querySelectorAll('.deployment-card-actions button')].map(b => b.textContent)), [['Retry', 'Add to queue'], ['Add to queue'], []]);
  cards[0].querySelector('[data-deployment-retry]').click();
  await until(() => calls.includes('POST /api/deploy/d1/retry'));
  // A retry switches the drawer to the live view to follow the new run; back to Recent to queue another.
  w.eval('openDeploymentMonitor("recent")');
  await until(() => d.querySelectorAll('[data-deployment-queue]').length === 2);
  d.querySelectorAll('[data-deployment-queue]')[1].click();
  await until(() => $('queueCount').textContent === '2');

  // The Deploy panel: Add to queue under the main button, Retry and Add to queue under a failed run.
  assert($('deployQueue') && $('deployOpenQueue'));
  $('deployOpenQueue').click();
  assert($('queueDrawer').classList.contains('open'));
  run("S.target='PC-P1'; poll('p1','PC-P1'," + JSON.stringify(payload('p1')) + ')');
  await until(() => !$('deploymentRetry').hidden);
  $('deploymentRequeue').click();
  assert.equal($('queueCount').textContent, '3');
  assert.equal(calls.filter(c => c === 'GET /api/deploy/p1/payload').length, 0, 'The current run re-queues from what it sent');
  $('deploymentRetry').click();
  await until(() => calls.includes('POST /api/deploy/p1/retry'));
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: retry failed deployments and re-queue past ones from History, the Deployments drawer and the Deploy panel progress widget; Add to queue under the Deploy button');
  process.exit(0);
})().catch(error => { console.error(error); process.exit(1); });
