// Simulated responses only: a fake Atlas keeps the checklists; installing records the request.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {fixture, root} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, what = 'Fixture did not settle') {
  for (let i = 0; i < 150; i++) {if (check()) return; await sleep(10)}
  throw Error(what);
}
const requests = [{catalog: 'Application - Magics - EQFIN', ticket: 'REQ93752889-5', notes: ''}, {catalog: 'BARX FX', ticket: 'REQ93752954-2', notes: ''},
  {catalog: '+ bloomberg', ticket: '', notes: 'Needs to be raised from RPM.'}, {catalog: 'XGEN', ticket: 'REQ94086488-1', notes: ''}];
function server() {
  const state = {calls: [], joiners: [], next: 1, installs: 0};
  const reply = (data, status = 200) => ({ok: status < 400, status, headers: {get: () => null}, json: async () => data});
  const personas = [
    {id: 'a00000000001', name: 'Repo Trader', desk: 'Repo Trader', revision: 2, fresh: false, threads: 8,
     items: [{folder: 'Office', script: 'setup_i.ps1', action: 'Install'}, {folder: 'Teams', script: 'teams_i.ps1', action: 'Install'}]},
    {id: 'a00000000002', name: 'Corporate FX Sales', desk: 'Corporate FX Sales', revision: 1, fresh: false, threads: 8, items: []}];
  const desks = [{name: 'Repo Trader', area: 'Rates & Credit (3rd Floor)', requests}, {name: 'Corporate FX Sales', area: 'FX (1st Floor)', requests: requests.slice(0, 2)}];
  const people = [{user: 'uid:p1', name: 'Paris Starter', email: 'paris@example.test', start: '2026-11-03', title: 'Repo Trader - VP', department: 'Rates', location: 'Paris - 52 Avenue Hoche', computer: 'NEWPC01'},
    {user: 'uid:p2', name: 'London Starter', email: 'london@example.test', start: '2026-11-04', title: 'Analyst', department: 'Payments', location: 'London - 1 Churchill Place', computer: ''}];
  async function fetch(url, options = {}) {
    url = String(url);
    const method = options.method || 'GET', body = options.body ? JSON.parse(options.body) : null;
    state.calls.push({url, method, body});
    const {pathname, searchParams} = new URL(url, 'http://127.0.0.1:8892');
    if (pathname === '/api/session') return reply({token: 'fixture'});
    if (pathname === '/api/health') return reply({identity: 'FIXTURE', users: 0, machines: 0});
    if (pathname === '/api/personas') return reply({personas, desks, repository: true, max_items: 40, requests_source: 'ListOfRequests.xlsx', requests_imported: '2026-10-28T08:00:00+00:00'});
    if (pathname === '/api/joiners/starting') return reply({people: people.filter(p => !state.joiners.some(j => j.user === p.user)), site: 'Paris'});
    if (pathname === '/api/search') return reply({users: searchParams.get('term').startsWith('Ale') ? [{id: 7, canonical_key: 'uid:alex', name: 'Alex Morgan', email: 'alex@example.test', department: 'Rates', start_date: '2026-11-10 00:00:00'}] : [], machines: []});
    if (pathname === '/api/user/id:7') return reply({user: {}, machines: [{name: 'ALEXPC07', machine_name: 'ALEXPC07', sys_class_name: 'Computer'}]});
    if (pathname === '/api/joiners' && method === 'GET') return reply({joiners: state.joiners});
    if (pathname === '/api/joiners' && method === 'POST') {
      const persona = personas.find(p => p.id === body.persona), desk = desks.find(d => d.name === persona.desk);
      const joiner = {...body, id: 'b'.repeat(11) + state.next++, computer: body.computer.toUpperCase(), persona_id: persona.id, persona: persona.name,
        desk: desk.name, area: desk.area, done: false, installs: [], install: null,
        requests: desk.requests.map(r => ({catalog: r.catalog, reference: r.ticket, notes: r.notes, ticket: '', raised: false}))};
      state.joiners.unshift(joiner);
      return reply(joiner);
    }
    const one = pathname.match(/^\/api\/joiners\/([a-f0-9]+)(\/install)?$/), joiner = one && state.joiners.find(j => j.id === one[1]);
    if (one && one[2]) {
      state.installs++;
      joiner.install = {queue: 'q'.repeat(32), computer: joiner.computer, count: 2, at: '2026-10-28T09:00:00', state: 'queued', total: 2, finished: 0, failed: 0, cancelled: 0};
      return reply({queue: 'q'.repeat(32), persona: joiner.persona, computer: joiner.computer, count: 2, joiner: joiner.id});
    }
    if (one && method === 'PUT') {
      if (body.computer !== undefined) joiner.computer = body.computer.toUpperCase();
      if (body.done !== undefined) joiner.done = body.done;
      if (body.request) {
        const row = joiner.requests[body.request.index];
        if (body.request.ticket !== undefined) { row.ticket = body.request.ticket.trim(); if (row.ticket && body.request.raised === undefined) row.raised = true; }
        if (body.request.raised !== undefined) row.raised = body.request.raised;
      }
      return reply(joiner);
    }
    if (one && method === 'DELETE') { state.joiners = state.joiners.filter(j => j !== joiner); return reply({deleted: one[1]}); }
    if (pathname.startsWith('/api/deployments/')) return reply({deployments: []});
    if (pathname === '/api/actions') return reply({actions: []});
    return reply({available: false, items: [], deployments: []});
  }
  return {state, fetch};
}
async function open({viewer = false} = {}) {
  const fake = server(), f = await fixture({fetch: fake.fetch});
  const copied = [];
  Object.defineProperty(f.w.navigator, 'clipboard', {value: {writeText: async text => copied.push(text)}});
  if (viewer) {
    const meta = f.w.document.createElement('meta'); meta.name = 'atlas-mode'; meta.content = 'viewer'; f.w.document.head.append(meta);
    f.run(fs.readFileSync(path.join(root, 'frontend/assets/readonly-console.js'), 'utf8'));
  }
  await f.console();
  const get = id => f.w.document.getElementById(id);
  if (!get('deploymentPanel').dataset.installed) f.w.document.dispatchEvent(new f.w.Event('DOMContentLoaded'));
  return {...f, ...fake, get, copied};
}
const writes = state => state.calls.filter(c => c.method !== 'GET' && c.url !== '/api/session');
function fire(w, el, type, value) {
  if (value !== undefined) el.value = value;
  el.dispatchEvent(new w.Event(type, {bubbles: true}));
}

(async () => {
  const f = await open(), {w, run, get, state, copied} = f, d = w.document;
  run('page("joiners")');
  assert(get('joiners').classList.contains('active'));
  await until(() => get('joinerSoonList').querySelector('[data-joiner-start]'), 'Starting soon');
  assert.match(get('joinerEmpty').textContent, /No new joiners yet/);
  // Starting soon shows the configured site first; All sites shows everyone.
  assert.equal(get('joinerSite').value, 'Paris - 52 Avenue Hoche');
  assert.deepEqual([...get('joinerSoonList').querySelectorAll('strong')].map(s => s.textContent), ['Paris Starter']);
  fire(w, get('joinerSite'), 'change', '');
  assert.equal(get('joinerSoonList').querySelectorAll('[data-joiner-start]').length, 2);
  assert.equal(w.localStorage.getItem('atlasJoinerSite'), '', 'The chosen site is remembered');
  fire(w, get('joinerSite'), 'change', 'Paris - 52 Avenue Hoche');

  // Picking someone starting soon fills the form; the persona brings its desk's requests and software.
  get('joinerSoonList').querySelector('[data-joiner-start="uid:p1"]').click();
  assert(!get('joinerForm').hidden);
  assert.deepEqual([get('joinerName').value, get('joinerEmail').value, get('joinerMachine').value], ['Paris Starter', 'paris@example.test', 'NEWPC01']);
  assert(get('joinerCreate').disabled, 'A persona is needed');
  assert.match([...get('joinerPersona').options].map(o => o.textContent).join('|'), /Repo Trader · 4 requests · 2 packages/);
  fire(w, get('joinerPersona'), 'change', 'a00000000001');
  assert.equal(get('joinerPlan').textContent, '4 access requests from Repo Trader · 2 packages to install');
  get('joinerCreate').click();
  await until(() => !get('joinerDetail').hidden && get('joinerRequests').querySelectorAll('.joiners-request').length === 4, 'Checklist');
  assert.deepEqual(writes(state)[0].body, {name: 'Paris Starter', email: 'paris@example.test', user: 'uid:p1', start: '2026-11-03', computer: 'NEWPC01', persona: 'a00000000001'});
  assert.equal(get('joinerTitle').textContent, 'Paris Starter');
  assert.match(get('joinerFacts').textContent, /Repo Trader · Rates & Credit \(3rd Floor\)/);
  assert.equal(get('joinerRequestCount').textContent, '· 0 of 4 raised');
  await until(() => !get('joinerSoonList').querySelector('[data-joiner-start="uid:p1"]'), 'Tracked people leave Starting soon');

  // Step 1: copy the earlier ticket, enter the new one; the next field keeps focus while it saves.
  const rows = () => [...get('joinerRequests').querySelectorAll('.joiners-request')];
  rows()[0].querySelector('.joiners-reference button').click();
  await until(() => copied.includes('REQ93752889-5'), 'Earlier ticket copied');
  const first = rows()[0].querySelector('input:not([type])'), second = rows()[1].querySelector('input:not([type])');
  second.focus();
  fire(w, first, 'change', 'REQ99900001-1');
  await until(() => get('joinerRequestCount').textContent === '· 1 of 4 raised', 'Ticket saved');
  assert.deepEqual(writes(state).at(-1).body, {request: {index: 0, ticket: 'REQ99900001-1'}});
  assert.equal(d.activeElement, second, 'Saving one row does not rebuild the checklist');
  assert.equal(rows()[0].dataset.raised, 'true');
  assert(rows()[0].querySelector('input[type="checkbox"]').checked);
  // Requests raised elsewhere (Bloomberg through RPM) are ticked by hand.
  rows()[2].querySelector('input[type="checkbox"]').click();
  await until(() => get('joinerRequestCount').textContent === '· 2 of 4 raised');
  assert.match(rows()[2].textContent, /Needs to be raised from RPM/);
  get('joinerCopyRemaining').click();
  await until(() => copied.length === 2);
  assert.equal(copied[1], 'BARX FX · REQ93752954-2\nXGEN · REQ94086488-1');
  get('joinerHideRaised').click();
  assert.deepEqual(rows().map(r => r.hidden), [true, false, true, false]);

  // Step 2: one click installs the persona's software on the joiner's machine.
  assert.equal(get('joinerInstall').textContent, 'Install 2 packages on NEWPC01');
  assert.match(get('joinerSoftware').textContent, /Office · Teams/);
  get('joinerInstall').click();
  await until(() => state.installs === 1 && /Installing on NEWPC01/.test(get('joinerInstallStatus').textContent), 'Install started');
  assert.equal(writes(state).at(-1).url, `/api/joiners/${state.joiners[0].id}/install`);
  assert(get('queueDrawer').classList.contains('open'), 'The run shows under Ongoing actions');
  assert(get('joinerInstall').disabled, 'No second install while it runs');
  assert.match(get('joinerProgress').textContent, /2\/4 requests · software started/);
  get('joinerDone').click();
  await until(() => get('joinerDone').textContent === 'Reopen');
  assert.equal(get('joinerList').querySelector('.personas-item span').textContent, 'Done');

  // A new joiner found in the directory: name, email and their linked Windows machine.
  get('joinerNew').click();
  fire(w, get('joinerName'), 'input', 'Ale');
  await until(() => get('joinerMatches').querySelector('button'), 'Directory matches');
  get('joinerMatches').querySelector('button').click();
  await until(() => get('joinerMachine').value === 'ALEXPC07', 'Linked machine');
  assert.deepEqual([get('joinerName').value, get('joinerEmail').value], ['Alex Morgan', 'alex@example.test']);
  fire(w, get('joinerPersona'), 'change', 'a00000000002');
  assert.equal(get('joinerPlan').textContent, '2 access requests from Corporate FX Sales · no software yet');
  get('joinerCreate').click();
  await until(() => state.joiners.length === 2 && get('joinerTitle').textContent === 'Alex Morgan');
  assert.equal(writes(state).at(-1).body.user, 'uid:alex');
  assert(get('joinerInstall').disabled);
  assert.match(get('joinerInstall').title, /no software yet/);
  w.confirm = () => true;
  get('joinerDelete').click();
  await until(() => state.joiners.length === 1 && !get('joinerEmpty').hidden);

  // The Personas page shows each persona's desk requests, from the imported workbook.
  run('page("personas")');
  await until(() => get('personaList').querySelector('[data-persona-id="a00000000001"]'));
  get('personaList').querySelector('[data-persona-id="a00000000001"]').click();
  assert.equal(get('personaAccessCount').textContent, '· Repo Trader · 4 requests');
  assert.equal(get('personaRequests').querySelectorAll('li').length, 4);
  assert.match(get('personaAccessSource').textContent, /From ListOfRequests\.xlsx/);
  assert.match(get('personaList').querySelector('[data-persona-id="a00000000002"]').textContent, /2 requests/);
  fire(w, get('personaDesk'), 'change', 'Corporate FX Sales');
  assert(!get('personaSave').disabled, 'Linking another desk is a change to save');
  fire(w, get('personaDesk'), 'change', 'Repo Trader');
  run('page("joiners")');

  // Names are escaped.
  state.joiners.push({...state.joiners[0], id: 'c'.repeat(12), name: '<img src=x onerror=alert(1)>', requests: [{catalog: '<img src=y>', reference: '', notes: '', ticket: '', raised: false}]});
  await run('AtlasJoiners.load("cccccccccccc")');
  assert.equal(get('joiners').querySelector('img'), null);
  assert.deepEqual(f.errors, []);
  w.close();

  // Demo: the same page, greyed out, without anybody's name.
  const demo = await open({viewer: true});
  demo.run('page("joiners")');
  await sleep(50);
  if (!demo.w.document.body.classList.contains('atlas-readonly-console')) demo.w.document.dispatchEvent(new demo.w.Event('DOMContentLoaded'));
  await sleep(50);
  assert(demo.get('joinerNew').disabled);
  assert.match(demo.get('joinerEmpty').textContent, /tracked in Atlas Admin/);
  assert(!demo.state.calls.some(c => c.url.startsWith('/api/joiners')), 'Demo never asks for new joiners');
  await sleep(300);
  demo.w.close();
  console.log('PASS: new joiners start from the directory or Starting soon, copy their desk requests, track each ticket in place, install the persona software in one click, complete, escape names and stay empty and greyed out in Demo');
})().catch(e => {console.error(e); process.exit(1)});
