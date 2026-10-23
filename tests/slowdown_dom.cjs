const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const {snapshot} = require('./performance_sample.cjs');
(async () => {
  let now = 0, id = 0, mode = 'normal', calls = 0;
  const timers = new Map(), pending = [], copied = [];
  const clone = value => JSON.parse(JSON.stringify(value));
  function sample(cpu = 88, elapsed = 0) {
    const s = clone(snapshot);
    s.kind = 'diagnose';
    s.elapsed = elapsed;
    s.collection={profile:'light',duration_ms:1500,query_count:12};
    Object.assign(s.summary, {cpu_percent: cpu, memory_percent: 50, page_reads_sec: 0, commit_percent: 50, gpu_percent: null, disks: []});
    s.summary.cores=s.summary.cores.map(core=>({...core,percent:cpu}));
    s.items = [{...s.items[0], Process: 'EXCEL.EXE', CPU: cpu, Threads: 10000}];
    return s;
  }
  const f = await fixture({fetch: async url => {
    assert(url.includes('kind=diagnose'), url); calls++;
    if (mode === 'pending') return new Promise(resolve => pending.push(data => resolve({ok: true, json: async () => data})));
    if (mode === 'failure') throw Error('WMI unavailable');
    const s = sample(mode==='busy'?95:88);
    if (mode === 'unsafe') s.items[0].Process = '<img src=x onerror=bad()>';
    if (mode === 'wmibusy') Object.assign(s.items[0],{Process:'WmiPrvSE.exe',CPU:6});
    if (mode === 'slow') s.collection.duration_ms=11000;
    return {ok: true, json: async () => s};
  }});
  const {w, run} = f, get = id => w.document.getElementById(id);
  w.setTimeout = (fn, ms) => { const key = ++id; timers.set(key, {fn, at: now + ms}); return key; };
  w.clearTimeout = key => timers.delete(key);
  Object.defineProperty(w.performance, 'now', {value: () => now});
  const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  async function advance(ms) {
    const end = now + ms;
    for (let guard = 0; guard < 100; guard++) {
      const next = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      timers.delete(next[0]); now = next[1].at; next[1].fn(); await settle();
    }
    now = end; await settle();
  }
  for (const file of ['app.js', 'console-processes.js', 'slowdown-diagnostics.js']) run(fs.readFileSync(path.join(root, 'frontend/assets', file), 'utf8'));
  w.copyFixture = text => copied.push(text);
  run('function toast(){}; function copy(text){copyFixture(text)}; bindProcessControls()');
  assert.equal(calls,0,'loading Remote Admin does not start a scan');
  get('adminPc').value='TESTPC';get('adminPc').dispatchEvent(new w.Event('input'));
  await advance(120000);
  assert.equal(calls,0,'selecting a machine and waiting does not start a scan');
  assert.equal(get('diagnoseSlowness').textContent.trim(),'Scan for slowness');
  const analyze = w.AtlasDiagnostics.analyze;
  // Repeated pressure versus an isolated spike; no diagnosis based on thread count.
  const repeated = [0, 4, 8, 12].map(t => sample(95, t));
  const result = analyze(repeated);
  assert.equal(result[0].id, 'cpu'); assert.equal(result[0].support, 'Repeated evidence');
  assert(result[0].evidence.includes('EXCEL.EXE'));
  assert.equal(analyze([sample(95, 0), ...[4,8,12,16].map(t => sample(10, t))])[0].support, 'Brief spike');
  assert.equal(analyze([sample(10)]).length, 0, 'large thread count is not a cause');
  const busyCore=sample(12);busyCore.summary.cores[0].percent=99;
  assert.equal(analyze([busyCore])[0].id,'core');
  assert.equal(analyze([{summary:{cpu_percent:null, memory_percent:null, gpu_percent:null}, items:[], elapsed:0}]).length, 0);
  const policy=w.AtlasDiagnostics.probePolicy;
  assert.equal(policy(sample()).delay,10000);
  assert.equal(policy(sample(95)).delay,20000);
  const delayed=sample();delayed.collection.duration_ms=6000;
  assert.equal(policy(delayed).delay,20000);
  delayed.collection.duration_ms=11000;assert(policy(delayed).stop.includes('collection is slow'));
  const busyWmi=sample();busyWmi.items[0].Process='WmiPrvSE.exe';busyWmi.items[0].CPU=2;busyWmi.summary.logical_processors=32;
  assert(policy(busyWmi).stop.includes('WMI provider activity'));
  const ram=sample(20);ram.summary.memory_percent=95;ram.summary.page_reads_sec=100;
  assert.equal(analyze([ram])[0].id,'memory-paging');
  ram.summary.page_reads_sec=null;assert.equal(analyze([ram])[0].id,'memory');
  const disk=sample(20);disk.summary.disks=[{read_ms:100,write_ms:100,read_bytes_sec:0,write_bytes_sec:0}];
  assert.equal(analyze([disk]).length,0,'inactive disk is not a latency diagnosis');
  disk.summary.disks[0].read_bytes_sec=1024;assert.equal(analyze([disk])[0].id,'disk');
  // Bounded capture, automatic stop, readable evidence and report.
  get('diagnoseSlowness').click();await settle();
  assert(!get('slowdownPanel').hidden);assert(get('diagnoseSlowness').disabled);
  get('slowdownFindings').querySelector('details').open=true;
  get('adminOverview').querySelector('details').open=true;
  await advance(60000);
  assert(get('slowdownFindings').querySelector('details').open);
  assert(get('adminOverview').querySelector('details').open);
  assert.equal(calls,6);assert(!get('diagnoseSlowness').disabled);assert(get('stopDiagnosis').hidden);
  assert.equal(get('adminOverview').querySelectorAll('.perf-donut').length,2);
  assert(get('adminOverview').textContent.includes('Deeper checks'));
  assert(get('slowdownFindings').textContent.includes('Repeated evidence'));
  assert.equal(get('slowdownFindings').querySelectorAll('tbody tr').length,6);
  get('copyDiagnosis').click();assert(copied.at(-1).includes('Citrix session latency'));assert(copied.at(-1).includes('EXCEL.EXE'));
  await advance(60000);assert.equal(calls,6,'no polling after completion');
  mode='busy';const busyCalls=calls;await w.AtlasDiagnostics.start();
  await advance(19000);assert.equal(calls,busyCalls+1);
  await advance(41000);assert.equal(calls,busyCalls+3,'busy machines rest 20 seconds');
  for(const selectedMode of ['wmibusy','slow']) {
    mode=selectedMode;await w.AtlasDiagnostics.start();const stoppedCount=calls;
    assert(get('stopDiagnosis').hidden);await advance(60000);assert.equal(calls,stoppedCount);
    assert(get('slowdownStatus').textContent.includes(selectedMode==='wmibusy'?'WMI provider activity':'collection is slow'));
  }
  // Unsafe data is escaped, not interpreted as HTML.
  mode='unsafe';await w.AtlasDiagnostics.start();
  assert(!get('slowdownFindings').querySelector('img'));assert(get('slowdownFindings').textContent.includes('<img'));
  w.AtlasDiagnostics.stop();
  // Only one request at a time; target change rejects late responses.
  mode='pending';const starting=w.AtlasDiagnostics.start();await settle();const before=calls;
  await advance(20000);assert.equal(calls,before);
  get('adminPc').value='OTHERPC';get('adminPc').dispatchEvent(new w.Event('input'));
  pending.shift()(sample());await starting;
  assert(get('slowdownPanel').hidden);assert.equal(get('adminOut').textContent,'');
  assert.equal(w.AtlasDiagnostics.report(),'');
  // Deadline also ends a hung browser request and discards its late result.
  get('adminPc').value='TESTPC';const timed=w.AtlasDiagnostics.start();await settle();
  await advance(60000);assert(get('stopDiagnosis').hidden);assert(get('copyDiagnosis').disabled);
  pending.shift()(sample());await timed;assert(get('copyDiagnosis').disabled);
  // Stop cancels future samples, leaving completed evidence available.
  mode='normal';await w.AtlasDiagnostics.start();w.AtlasDiagnostics.stop();const stopped=calls;
  await advance(60000);assert.equal(calls,stopped);assert(!get('copyDiagnosis').disabled);
  mode='failure';await w.AtlasDiagnostics.start();const failed=calls;await advance(12000);
  assert.equal(calls,failed);assert(get('slowdownStatus').textContent.includes('no automatic retries'));
  assert.equal(get('slowdownTitle').textContent,'Cause not established');
  assert(get('slowdownFindings').textContent.includes('WMI unavailable'));
  mode='normal';await w.AtlasDiagnostics.start();
  Object.defineProperty(w.document,'hidden',{configurable:true,value:true});
  w.document.dispatchEvent(new w.Event('visibilitychange'));assert(get('stopDiagnosis').hidden);
  assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();
  console.log('PASS: light capture, adaptive rest, WMI/slow-response guards, no retries, manual deeper checks, evidence ranking, cancellation, stale target, safe rendering and reports');
})().catch(error=>{console.error(error);process.exitCode=1});
