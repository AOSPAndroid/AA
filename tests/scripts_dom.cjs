const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { spawnSync } = require('node:child_process');
const { fixture, root } = require('./ui_fixture.cjs');
(async () => {
  const library = {
    builtin: [
      { id: 'services-disable', name: 'Stop and disable services', category: 'Services', changes: true, description: 'Stops and disables.',
        params: [{ name: 'Services', label: 'Services', kind: 'list', default: "" }], code: "foreach ($c in $Computers) { Get-Wmi $c 'Win32_Service' ''; Write-Ok $c }" },
      { id: 'uptime', name: 'Uptime and last restart', category: 'Health', changes: false, description: 'Boot time.',
        params: [{ name: 'MaxDays', label: 'Warn after', kind: 'choice', options: ['7', '8'], default: '8' }], code: 'Get-Date' },
      { id: 'online', name: 'Online check', category: 'Health', changes: false, description: 'DNS and ping.',
        params: [], code: 'foreach ($c in $Computers) { Write-Ok $c }' },
    ],
    saved: [],
    export_helpers: "function Write-Ok([string]$Text) { Write-Host $Text }\nfunction Get-Wmi([string]$Computer, [string]$Class, [string]$Filter) { }\n",
  };
  const posts = [], puts = [];
  let job = null;
  const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
  const f = await fixture({ fetch: async (url, options = {}) => {
    if (url === '/api/session') return response({ token: 'fixture' });
    if (url === '/api/script-library') return response(library);
    if (url === '/api/script-library/runs') return response(job ? [job] : []);
    if (url === '/api/psexec/runs') return response([]);
    if (url === '/api/script-library/run') {
      const body = JSON.parse(options.body); posts.push(body);
      job = { id: body.id, title: 'Stop and disable services', target: '2 machines', state: 'running', exit_code: null,
        output: 'Atlas > 2 machines · Stop and disable services\n[OK] PC1 · Example Service · disabled\n[FAIL] PC2 · cannot reach WMI: RPC server unavailable\n[WARN] PC1 · PrintService · not found\n' };
      return response(job);
    }
    if (job && url === '/api/script-library/runs/' + job.id) return response({ ...job });
    if (url.startsWith('/api/script-library/saved/')) {
      const body = JSON.parse(options.body); puts.push([url, body]);
      const item = { id: url.split('/').pop(), ...body, revision: body.revision + 1 };
      library.saved = [item];
      return response(item);
    }
    return response({});
  } });
  const { w, run } = f, d = w.document, get = (id) => d.getElementById('script' + id), settle = () => new Promise((r) => setTimeout(r, 20));
  const downloads = [];
  w.Blob = class { constructor(parts) { this.text = parts.join(''); } };
  w.URL.createObjectURL = (blob) => { downloads.push(blob.text); return 'blob:fixture'; };
  w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = () => {};
  await f.console(); await settle();
  run('function toast(){}');
  assert(d.querySelector('nav [data-page="scripts"]'), 'Scripts replaces PsTools in the sidebar');
  assert(!d.querySelector('nav [data-page="psexec"]'));
  run("page('scripts')"); await settle();
  assert.equal(d.querySelector('#pageTitle').textContent, 'Scripts');
  assert.deepEqual([...get('List').querySelectorAll('h3')].map((h) => h.textContent), ['Services', 'Health']);
  assert.equal(get('Name').value, 'Online check', 'Opening Scripts selects a harmless check, even with mutating entries listed first');
  assert.equal(posts.length, 0, 'Opening Scripts never runs a task');
  assert.equal(get('Targets').value, '', 'No machines are preselected');
  assert(get('Code').readOnly, 'Built-in code is read-only');
  d.querySelector('[data-script="services-disable"]').click();
  assert.equal(get('Params').querySelector('[data-param="Services"]').value, '');

  get('Targets').value = 'PC1, pc1\nPC2;bad!name';
  get('Targets').dispatchEvent(new w.Event('input'));
  assert.match(get('TargetCount').textContent, /2 machines · 1 not valid: bad!name/);
  await get('Run').onclick();
  assert.equal(posts.length, 0, 'Invalid names stop the run');
  assert.match(get('Message').textContent, /Fix these machine names/);

  get('Targets').value = 'PC1, pc1\nPC2'; get('Targets').dispatchEvent(new w.Event('input'));
  w.confirm = () => { throw Error('Blank service names must be rejected before confirmation'); };
  get('Params').querySelector('[data-param="Services"]').value = ' \n,; ';
  await get('Run').onclick();
  assert.equal(posts.length, 0);
  assert.match(get('Message').textContent, /Services: enter at least one value/);
  get('Params').querySelector('[data-param="Services"]').value = 'Example Service\nPrintService';
  let asked = '';
  w.confirm = (text) => { asked = text; return false; };
  await get('Run').onclick();
  assert.equal(posts.length, 0, 'Cancelling the confirmation runs nothing');
  assert.match(asked, /will change 2 machines:\n\nPC1\nPC2/);
  w.confirm = () => true;
  await get('Run').onclick(); await settle();
  assert.deepEqual([posts[0].script, posts[0].targets, posts[0].confirmed, posts[0].values.Services], ['services-disable', 'PC1\nPC2', true, "Example Service\nPrintService"]);
  assert(!('code' in posts[0]), 'Built-ins never send code');
  const tones = [...get('Output').querySelectorAll('span')].map((s) => s.dataset.tone || '').filter(Boolean);
  assert.deepEqual(tones, ['atlas', 'good', 'bad', 'warn']);
  assert.equal(get('Summary').textContent, '1 OK 1 failed 1 warning');
  assert(get('Run').disabled && !get('Stop').disabled, 'One run at a time');
  job.state = 'complete'; job.exit_code = 0;
  await new Promise((r) => setTimeout(r, 1100));
  assert.match(get('Status').textContent, /complete · exit 0/);
  assert.equal(get('Status').dataset.tone, 'good');
  assert(!get('Run').disabled);

  get('Params').querySelector('[data-param="Services"]').value = "Spooler\nO'Brien";
  get('Download').onclick();
  assert(downloads[0].startsWith('param(\n'), 'Standalone built-ins put their parameter block first');
  assert.match(downloads[0], /\[string\[\]\]\$Services = @\('Spooler', 'O''Brien'\)/);
  assert(downloads[0].includes(library.export_helpers.trim()), 'Downloaded built-ins include the helper definitions they call');
  assert(!downloads[0].includes('function Read-Host'), 'Standalone exports preserve native PowerShell prompts');
  get('Params').querySelector('[data-param="Services"]').value = '';
  get('Download').onclick();
  assert.match(downloads[1], /\[Parameter\(Mandatory=\$true\)\]\[ValidateNotNullOrEmpty\(\)\]\[string\[\]\]\$Services/);
  get('Params').querySelector('[data-param="Services"]').value = "Spooler\nO'Brien";
  get('Duplicate').onclick();
  assert(!get('Code').readOnly);
  assert(get('Code').value.startsWith("$Services = @('Spooler', 'O''Brien')\nforeach"), 'A copy keeps the chosen values as PowerShell lines');
  assert.equal(get('Name').value, 'Stop and disable services (copy)');
  get('Name').value = 'Example task';
  await get('Save').onclick(); await settle();
  assert.equal(puts[0][0], '/api/script-library/saved/example-task');
  assert.deepEqual([puts[0][1].name, puts[0][1].changes, puts[0][1].revision], ['Example task', true, 0]);
  assert.deepEqual([...get('List').querySelectorAll('h3')].map((h) => h.textContent), ['My scripts', 'Services', 'Health']);
  assert.equal(d.querySelector('#scriptList [aria-current="true"]').dataset.script, 'example-task');

  get('Changes').checked = false;
  w.confirm = () => { throw Error('Read-only scripts run without asking'); };
  await get('Run').onclick(); await settle();
  assert.equal(posts.at(-1).script, 'example-task');
  assert(posts.at(-1).code.includes("'O''Brien'"), 'Saved scripts send the editor code');

  get('Download').onclick();
  assert(downloads[2].includes(library.export_helpers.trim()), 'Custom scripts also get Atlas helper definitions');
  assert(downloads[2].includes(get('Code').value.trim()), 'Custom script contents are preserved');
  get('New').onclick();
  const custom = "param([string]$Message = 'hello')\nWrite-Ok $Message\nRead-Host 'Enter a value'";
  get('Code').value = custom;
  get('Download').onclick();
  assert(downloads[3].includes('& {\n' + custom + '\n} @args'), 'A custom param block stays first in its own scope, with arguments forwarded');
  d.querySelector('[data-script="uptime"]').click();
  get('Download').onclick();
  assert.match(downloads[4], /\[ValidateSet\('7', '8'\)\]\[string\]\$MaxDays = '8'/);
  // Parse all generated exports; never execute any script body or remote action.
  const check = '$sources = [Console]::In.ReadToEnd() | ConvertFrom-Json; foreach ($source in $sources) { $errors = $null; [void][System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$errors); $errors | ForEach-Object { $_.Message } }';
  let parsed = spawnSync('pwsh', ['-NoProfile', '-NonInteractive', '-Command', check], { input: JSON.stringify(downloads), encoding: 'utf8', timeout: 30000 });
  if (parsed.error?.code === 'ENOENT') parsed = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', check], { input: JSON.stringify(downloads), encoding: 'utf8', timeout: 30000 });
  if (parsed.error?.code !== 'ENOENT') {
    assert.equal(parsed.error, undefined);
    assert.equal(parsed.status, 0, parsed.stderr);
    assert.equal(parsed.stdout.trim(), '', 'Generated built-in and custom exports parse as PowerShell');
  }

  d.querySelector('#scripts .scripts-pstools').click();
  assert(d.getElementById('psexec').classList.contains('active'), 'PsTools commands stay one click away');
  assert.equal(d.querySelector('nav [aria-current="page"]').dataset.page, 'scripts');
  await settle();
  assert.deepEqual(f.errors, []);
  w.close();
  console.log('PASS: Scripts opens on a read-only check; blank service guard; machine-name check; confirmation; coloured output; duplicate/save; standalone helpers and parameter blocks; PowerShell parse-only export checks; PsTools link');
})().catch((error) => { console.error(error); process.exit(1); });
