// xterm.js mirror for Terminal and PsTools output, with a stand-in terminal (jsdom cannot draw one).
const assert = require('node:assert/strict'), fs = require('node:fs'), { JSDOM } = require('jsdom');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const dom = new JSDOM(fs.readFileSync('frontend/index.html', 'utf8'), { runScripts: 'outside-only', url: 'http://127.0.0.1/installer' });
  const w = dom.window, d = w.document, writes = [];
  class FakeTerminal {
    constructor(options) { this.options = options; this.resets = 0; }
    loadAddon() {} open(host) { this.host = host; } write(text) { writes.push(text); }
    reset() { this.resets++; writes.length = 0; } clearSelection() {} scrollToBottom() {}
  }
  const searched = [];
  w.Terminal = FakeTerminal;
  w.FitAddon = { FitAddon: class { fit() {} } };
  w.SearchAddon = { SearchAddon: class { findNext(term) { searched.push(term); return term === 'Spooler'; } findPrevious() { return false; } } };
  const appended = [];
  const original = w.HTMLHeadElement.prototype.append;
  w.HTMLHeadElement.prototype.append = function (...nodes) { appended.push(...nodes); return original.apply(this, nodes); };
  w.eval(fs.readFileSync('frontend/assets/terminal-view.js', 'utf8'));
  const pre = d.getElementById('termOutput');
  assert.equal(pre.dataset.xterm, undefined, 'Nothing mounts until the Terminal page opens');
  assert.equal(appended.length, 0, 'No xterm files are requested at start-up');

  d.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  d.getElementById('terminal').classList.add('active');
  await sleep(20);
  assert.equal(pre.dataset.xterm, 'ready');
  const view = w.AtlasTerminalView.terminals.get('termOutput');
  assert.equal(view.term.options.disableStdin, true, 'Output only; commands are typed in the Atlas editor');
  assert.equal(view.term.options.convertEol, true);
  assert(pre.classList.contains('atlas-xterm-source'), 'The original output stays for screen readers and Copy');
  assert.equal(d.querySelector('.atlas-xterm').getAttribute('aria-hidden'), 'true');

  pre.textContent = 'line 1\n'; await sleep(10);
  pre.textContent = 'line 1\nline 2\n'; await sleep(10);
  assert.deepEqual(writes, ['line 1\n', 'line 2\n'], 'Only new output is appended');
  pre.textContent = '[Earlier output trimmed]\nline 2\n'; await sleep(10);
  assert.deepEqual(writes, ['[Earlier output trimmed]\nline 2\n'], 'Changed earlier output redraws from the start');
  pre.textContent = ''; await sleep(10);
  assert.equal(view.term.resets, 3, 'First output, redraw and Clear output each start from an empty terminal');

  const input = d.querySelector('.atlas-xterm-search input');
  input.value = 'Spooler'; input.dispatchEvent(new w.Event('input'));
  assert.deepEqual(searched, ['Spooler']);
  input.value = 'missing'; input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
  assert.equal(d.querySelector('.atlas-xterm-search [role="status"]').textContent, 'Not found');

  d.getElementById('terminal').classList.remove('active'); d.getElementById('psexec').classList.add('active');
  await sleep(20);
  assert.equal(d.getElementById('pxOutput').dataset.xterm, 'ready', 'PsTools output gets the same view');
  w.close();

  // If xterm cannot load, the plain output stays and nothing breaks.
  const dom2 = new JSDOM(fs.readFileSync('frontend/index.html', 'utf8'), { runScripts: 'outside-only', url: 'http://127.0.0.1/installer' });
  const w2 = dom2.window;
  w2.HTMLHeadElement.prototype.append = function (node) { setTimeout(() => node.onerror?.()); };
  w2.eval(fs.readFileSync('frontend/assets/terminal-view.js', 'utf8'));
  w2.document.getElementById('terminal').classList.add('active');
  await sleep(30);
  assert.equal(w2.document.getElementById('termOutput').dataset.xterm, '');
  assert(!w2.document.getElementById('termOutput').classList.contains('atlas-xterm-source'));
  w2.close();

  // A loaded renderer can still fail to open. Restore plain output, clean up, and allow a retry.
  const dom3 = new JSDOM(fs.readFileSync('frontend/index.html', 'utf8'), { runScripts: 'outside-only', url: 'http://127.0.0.1/installer' });
  const w3 = dom3.window, d3 = w3.document;
  let disposed = 0;
  w3.Terminal = class extends FakeTerminal {
    open() { throw Error('Renderer unavailable'); }
    dispose() { disposed++; }
  };
  w3.FitAddon = { FitAddon: class { fit() {} } };
  w3.SearchAddon = { SearchAddon: class {} };
  w3.eval(fs.readFileSync('frontend/assets/terminal-view.js', 'utf8'));
  d3.getElementById('terminal').classList.add('active');
  await sleep(20);
  const pre3 = d3.getElementById('termOutput');
  assert.equal(pre3.dataset.xterm, '');
  assert(!pre3.classList.contains('atlas-xterm-source'), 'Failed initialization keeps plain output visible');
  assert.equal(d3.querySelectorAll('.atlas-xterm, .atlas-xterm-search').length, 0, 'No partial terminal UI remains');
  assert.equal(disposed, 1, 'The failed renderer releases its resources');
  assert.equal(w3.AtlasTerminalView.terminals.size, 0);
  w3.Terminal = FakeTerminal;
  w3.AtlasTerminalView.check();
  await sleep(20);
  assert.equal(pre3.dataset.xterm, 'ready', 'Opening the page can retry initialization');
  assert.equal(d3.querySelectorAll('.atlas-xterm').length, 1);
  assert.equal(d3.querySelectorAll('.atlas-xterm-search').length, 1);
  w3.close();
  console.log('PASS: terminal view loads xterm only when Terminal/PsTools opens, appends new output, redraws trimmed output, clears, searches, keeps the <pre> accessible and falls back to plain output');
})().catch(e => { console.error(e); process.exit(1); });
