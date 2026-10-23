const assert = require('node:assert/strict');
const fs = require('node:fs');
const {fixture} = require('./ui_fixture.cjs');
(async () => {
  for (const readonly of [false, true]) {
    const f = await fixture(), {w, run} = f, calls = [], selected = [];
    w.localStorage.setItem('wmiTargetPrefs', JSON.stringify({recent:['PC-ONE','PC-TWO']}));
    w.api = async path => { calls.push(path); return [{target:'PC-ONE', package:'<img src=x>', action:'Install', state:'launched'}]; };
    w.setTarget = pc => selected.push(pc);
    w.page = id => selected.push(id);
    if (readonly) w.AtlasReadOnly = {};
    run(fs.readFileSync('frontend/assets/workspace-home.js','utf8'));
    await new Promise(resolve => setTimeout(resolve, 20));
    const host = w.document.getElementById('workspaceActivity');
    assert.equal(host.querySelectorAll('[data-home-machine]').length,2);
    host.querySelector('[data-home-machine]').click();
    assert.equal(selected[0],'PC-ONE');
    assert.equal(host.querySelectorAll('img').length,0);
    if (readonly) { assert.equal(calls.length,0); assert.match(host.textContent,/available in Atlas Admin/); }
    else {
      assert.deepEqual(calls,['/api/history?today=true&limit=6']);
      assert.match(host.textContent,/launched/);
      w.api = async () => { throw Error('Offline'); };
      host.querySelector('[data-home-refresh]').click();
      await new Promise(resolve => setTimeout(resolve,20));
      assert.match(host.textContent,/could not be loaded/);
    }
    w.dispatchEvent(new w.Event('pagehide')); w.close();
  }
  console.log('PASS workspace activity: recent selection, status, safe text, retry, read-only isolation');
})().catch(e => { console.error(e);process.exitCode=1; });
