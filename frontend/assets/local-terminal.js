(() => {
  const get = name => document.getElementById('term' + name);
  const runTone = ({state, exit_code}) => exit_code != null ? (Number(exit_code) === 0 ? 'good' : 'bad') : /fail|error|timed out|timeout/i.test(state || '') ? 'bad' : '';
  let active = false, runId = null, timer;
  const done = new Set(['complete', 'failed', 'stopped', 'timed_out']);
  const post = (url, body) => AtlasClient.request(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  function controls() {
    get('Run').disabled = get('Selection').disabled = active || !!window.AtlasReadOnly;
    get('Stop').disabled = !active || !runId;
    get('Clear').disabled = active;
    get('Output').setAttribute('aria-busy', String(active));
  }
  async function poll() {
    try {
      const token = await AtlasClient.sessionToken();
      const result = await AtlasClient.request('/api/terminal/runs/' + runId, {headers:{'X-Atlas-Token':token}, atlasSilent:true});
      const output = get('Output'), atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
      output.textContent = (result.truncated ? '[Earlier output trimmed]\n' : '') + result.output;
      if (atBottom) output.scrollTop = output.scrollHeight;
      get('Status').textContent = `${result.target} · ${result.account} · ${result.state}${result.exit_code == null ? '' : ' · exit ' + result.exit_code}`;
      get('Status').dataset.tone = runTone(result);
      active = !done.has(result.state); controls();
      if (active) timer = setTimeout(poll, 1000);
    } catch(error) {
      get('Message').textContent = 'Connection lost: ' + error.message + ' Checking the same run again; no command will be rerun.';
      timer = setTimeout(poll, 5000);
    }
  }
  async function run(selection = false) {
    if (active || window.AtlasReadOnly) return;
    const editor = get('Code');
    const code = selection ? editor.value.slice(editor.selectionStart, editor.selectionEnd) : editor.value;
    if (!code.trim()) { get('Message').textContent = selection ? 'Select some script text first.' : 'Enter a command first.'; return; }
    active = true; runId = null; controls(); get('Message').textContent = '';
    get('Status').textContent = 'Starting…'; get('Status').dataset.tone = '';
    const id = crypto.randomUUID();
    try {
      await post('/api/terminal/run', {id, shell:get('Mode').value === 'script' ? 'powershell' : get('Shell').value, code});
      runId = id; poll();
    } catch(error) {
      // Reconcile only this ID after an uncertain start; never launch it again.
      try {
        await AtlasClient.request('/api/terminal/runs/' + id, {headers:{'X-Atlas-Token':await AtlasClient.sessionToken()}});
        runId = id; poll();
      } catch {
        active = false; get('Status').textContent = 'Start not confirmed';
        get('Message').textContent = error.message; controls();
      }
    }
  }
  get('Reconnect').onclick = async () => {
    if (window.AtlasReadOnly) return;
    try {
      const rows = await AtlasClient.request('/api/terminal/runs', {headers:{'X-Atlas-Token':await AtlasClient.sessionToken()}});
      if (rows.length) {clearTimeout(timer);runId = rows.find(row => !done.has(row.state))?.id || rows[0].id;active = true;controls();poll();}
    } catch(error) {get('Message').textContent = error.message;}
  };
  window.AtlasTerminal = {open:()=>get('Reconnect').onclick()};
  get('Run').onclick = () => run(); get('Selection').onclick = () => run(true);
  get('Code').onkeydown = event => { if (event.ctrlKey && event.key === 'Enter') {event.preventDefault();run();} };
  get('Mode').onchange = () => {
    const script = get('Mode').value === 'script';
    get('Code').rows = script ? 14 : 5; get('ShellLabel').hidden = script;
    get('Run').textContent = script ? 'Run script' : 'Run command';
  };
  get('Stop').onclick = async () => {
    try {await post('/api/terminal/runs/' + runId + '/stop', {});get('Message').textContent = 'Stopping the local process. Child or remote processes may need separate inspection.';}
    catch(error) {get('Message').textContent = error.message;}
  };
  get('Copy').onclick = async () => {try {await navigator.clipboard.writeText(get('Output').textContent);} catch {get('Message').textContent = 'Select the output and copy it manually.';} };
  get('Clear').onclick = () => {if (!active) get('Output').textContent = '';};
  get('Import').onclick = () => get('File').click();
  get('File').onchange = async () => {
    const file = get('File').files[0]; if (!file) return;
    if (file.size > 65536) {get('Message').textContent = 'Choose a script under 64 KB.';return;}
    get('Code').value = await file.text();get('Mode').value = 'script';get('Mode').onchange();
  };
  get('Save').onclick = () => {
    const url = URL.createObjectURL(new Blob([get('Code').value], {type:'text/plain;charset=utf-8'}));
    const link = document.createElement('a');link.href = url;link.download = 'atlas-script.ps1';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  if (window.AtlasReadOnly) get('Message').textContent = 'Execution requires elevated Atlas Admin. You can edit and save scripts here.';
  get('Reconnect').disabled = !!window.AtlasReadOnly;
  get('Mode').onchange();controls();
})();
