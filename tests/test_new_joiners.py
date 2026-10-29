"""New joiners: the requests workbook, personas per desk and each joiner's checklist. No remote command runs."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json, os, tempfile, time, unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.deploy import persona_access
from backend.deploy import personas
from backend import main
from backend.directory.import_folder import ImportFolder, headers, kind_of
from backend.job_service import JobService
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import workbook

TOKEN = {'X-Atlas-Token': 'test-token'}


def requests_workbook(path, extra_desk=False):
    """The layout of the requests workbook: a Main contents sheet, then one sheet per desk."""
    desk = lambda title, rows: [[title + ' — NEW JOINER ACCESS', '', '◀ MAIN'], ['One row per distinct request ticket.'],
                                ['NAVIGATION • Main is the first tab'], ['Catalog Name', 'Request Ticket Number', 'Notes'], *rows]
    sheets = {
        'Main': [['NEW JOINER ACCESS KNOWLEDGE BASE'], ['Choose a desk from the sheet tabs below.'], ['2 DESKS • 5 REQUEST ROWS'], ['CONTENTS'],
                 ['Desk Sheet', 'Area', 'Requests'], ['Repo Trader', 'Rates & Credit (3rd Floor)', '4'], ['Corporate FX Sales', 'FX (1st Floor)', '2']],
        'Repo Trader': desk('Repo Trader', [['Application - Magics - EQFIN', 'REQ93752889-5'], ['BARX FX', 'REQ93752954-2'],
                                           ['+ bloomberg', '', 'Needs to be raised from RPM.'], ['', ''], ['XGEN', 'REQ94086488-1']]),
        'Corporate FX Sales': desk('Corporate FX Sales', [['BARX Sacred', 'REQ93076881-1'], ['BARX Sacred', 'REQ93318085-1']]),
        'Workbook Statistics': [['Desks', '2'], ['Rows', '5']],
    }
    if extra_desk:
        sheets['EM Sales'] = desk('EM Sales', [['EM TMS', 'REQ93756108-9']])
    workbook(path, sheets)
    return path


class Workbook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_each_desk_sheet_becomes_its_requests_with_the_area_from_main(self):
        parsed = persona_access.parse(requests_workbook(self.root / 'ListOfRequests.xlsx'))
        self.assertEqual([(d['name'], d['area'], len(d['requests'])) for d in parsed['desks']],
                         [('Repo Trader', 'Rates & Credit (3rd Floor)', 4), ('Corporate FX Sales', 'FX (1st Floor)', 2)],
                         'Blank rows, title rows and sheets without the request columns are not requests')
        self.assertEqual(parsed['desks'][0]['requests'][2], {'catalog': '+ bloomberg', 'ticket': '', 'notes': 'Needs to be raised from RPM.'})
        self.assertEqual([r['ticket'] for r in parsed['desks'][1]['requests']], ['REQ93076881-1', 'REQ93318085-1'],
                         'The same catalogue item raised twice keeps both tickets')

    def test_the_workbook_is_recognised_by_its_desk_sheets(self):
        path = requests_workbook(self.root / 'anything.xlsx')
        self.assertEqual(kind_of(headers(path)), '', 'Its first row is a title, not an export header')
        self.assertEqual(persona_access.recognise(path), 'access')
        other = self.root / 'other.xlsx'
        workbook(other, {'Sheet1': [['Name', 'Opened'], ['x', 'y']]})
        self.assertEqual(persona_access.recognise(other), '')
        with self.assertRaisesRegex(ValueError, 'No desk sheets'):
            persona_access.parse(other)


class ImportFolderAccess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.folder = root / 'AtlasXL'; self.folder.mkdir()
        self.db = root / 'office_atlas.db'
        with fixture_connect(Path(__file__).resolve().parents[1] / 'office_atlas.db') as a, fixture_connect(self.db) as b:
            a.backup(b)
        self.requests, self.personas = persona_access.Store(root / 'persona-access.json'), personas.Store(root / 'personas.json')
        self.watcher = ImportFolder(self.db, root / 'import-folder.json', access=lambda: (self.requests, self.personas))
        self.watcher.state['folder'] = str(self.folder)

    def save(self, **options):
        path = requests_workbook(self.folder / 'ListOfRequests.xlsx', **options)
        stamp = time.time() - 120
        os.utime(path, (stamp, stamp))

    def test_saving_the_workbook_updates_the_requests_and_adds_a_persona_per_desk(self):
        self.save()
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['access']['result'], 'applied', summary)
        self.assertEqual(summary['groups']['access']['message'], '2 desks, 6 requests; 2 new personas.')
        self.assertEqual([f['kind'] for f in summary['files']], ['access'])
        self.assertEqual(self.requests.read()['source'], 'ListOfRequests.xlsx')
        made = self.personas.all()
        self.assertEqual([(p['name'], p['desk'], p['items']) for p in made], [('Corporate FX Sales', 'Corporate FX Sales', []), ('Repo Trader', 'Repo Trader', [])])
        # A renamed persona keeps its desk; the next workbook adds only the new desk.
        renamed = {**made[1], 'name': 'Repo trading'}
        self.personas.write([made[0], renamed])
        self.save(extra_desk=True)
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['access']['message'], '3 desks, 7 requests; 1 new persona.')
        self.assertEqual(sorted(p['name'] for p in self.personas.all()), ['Corporate FX Sales', 'EM Sales', 'Repo trading'])
        self.assertEqual(self.watcher.check()['groups']['access']['result'], 'applied', 'The same file is not read twice')

    def test_an_unreadable_workbook_is_reported_and_keeps_the_last_requests(self):
        self.save()
        self.watcher.check()
        with patch('backend.deploy.persona_access.parse', side_effect=ValueError('Repo Trader lists 900 requests')):
            path = self.folder / 'ListOfRequests.xlsx'; stamp = time.time() - 100; os.utime(path, (stamp, stamp))
            summary = self.watcher.check()
        self.assertEqual(summary['groups']['access']['result'], 'error')
        self.assertIn('900 requests', summary['groups']['access']['message'])
        self.assertEqual(len(self.requests.read()['desks']), 2)


class Joiners(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / 'repo'
        for folder, script in (('Office', 'setup_i.ps1'), ('Teams', 'teams_install.ps1')):
            (self.repo / folder).mkdir(parents=True); (self.repo / folder / script).write_text('exit 0')
        self.db = base / 'atlas.db'
        with fixture_connect(main.MASTER_DB) as a, fixture_connect(self.db) as b:
            a.backup(b)
        self.service = JobService(lambda: base / 'operations.db'); self.addCleanup(self.service.pool.shutdown)
        self.started = []
        for target, value in (('HISTORY_DB', base / 'history.db'), ('MASTER_DB', self.db), ('REPO', self.repo), ('job_service', self.service),
                              ('jobs', self.service.jobs), ('queue_jobs', self.service.queues), ('lock', self.service.lock)):
            patcher = patch.object(main, target, value); patcher.start(); self.addCleanup(patcher.stop)
        submit = patch.object(self.service, 'submit', side_effect=lambda fn, queue_id, items: self.started.append(items))
        submit.start(); self.addCleanup(submit.stop)
        for store, name in ((main.persona_store, 'personas.json'), (main.persona_access_store, 'persona-access.json'), (main.joiner_store, 'joiners.json')):
            patcher = patch.object(store, 'path', base / 'data' / name); patcher.start(); self.addCleanup(patcher.stop)
        token = patch('backend.atlas_api.TOKEN', 'test-token'); token.start(); self.addCleanup(token.stop)
        self.client = TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)); self.addCleanup(self.client.close)
        parsed = persona_access.parse(requests_workbook(base / 'ListOfRequests.xlsx'))
        main.persona_access_store.replace(parsed, 'ListOfRequests.xlsx')
        main.persona_store.add_desks([d['name'] for d in parsed['desks']])
        self.repo_trader = next(p for p in main.persona_store.all() if p['desk'] == 'Repo Trader')

    def joiner(self, **body):
        response = self.client.post('/api/joiners', json={'name': ' Alex  Morgan ', 'persona': self.repo_trader['id'], **body}, headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_personas_show_their_desk_requests_and_can_add_software(self):
        listed = self.client.get('/api/personas').json()
        self.assertEqual([d['name'] for d in listed['desks']], ['Repo Trader', 'Corporate FX Sales'])
        self.assertEqual(listed['requests_source'], 'ListOfRequests.xlsx')
        persona = next(p for p in listed['personas'] if p['id'] == self.repo_trader['id'])
        self.assertEqual((persona['desk'], persona['items']), ('Repo Trader', []))
        refused = self.client.post(f'/api/personas/{persona["id"]}/install', json={'computer': 'NEWPC'}, headers=TOKEN)
        self.assertEqual(refused.status_code, 400)
        self.assertIn('no software yet', refused.json()['detail'])
        updated = self.client.put(f'/api/personas/{persona["id"]}', headers=TOKEN, json={
            'name': 'Repo Trader', 'desk': 'Repo Trader', 'revision': 1, 'items': [{'folder': 'Office', 'script': 'setup_i.ps1'}]})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual((updated.json()['desk'], len(updated.json()['items'])), ('Repo Trader', 1))

    def test_a_checklist_copies_the_desk_requests_and_tracks_each_ticket(self):
        joiner = self.joiner(email='alex@example.test', start='2026-11-02')
        self.assertEqual((joiner['name'], joiner['persona'], joiner['desk'], joiner['area']), ('Alex Morgan', 'Repo Trader', 'Repo Trader', 'Rates & Credit (3rd Floor)'))
        self.assertEqual([(r['catalog'], r['reference'], r['ticket'], r['raised']) for r in joiner['requests']][:3],
                         [('Application - Magics - EQFIN', 'REQ93752889-5', '', False), ('BARX FX', 'REQ93752954-2', '', False), ('+ bloomberg', '', '', False)])
        change = lambda body: self.client.put('/api/joiners/' + joiner['id'], json=body, headers=TOKEN)
        row = change({'request': {'index': 0, 'ticket': ' REQ99900001-1 '}}).json()['requests'][0]
        self.assertEqual((row['ticket'], row['raised']), ('REQ99900001-1', True), 'A new ticket number marks the request raised')
        self.assertFalse(change({'request': {'index': 0, 'raised': False}}).json()['requests'][0]['raised'])
        self.assertTrue(change({'request': {'index': 2, 'raised': True}}).json()['requests'][2]['raised'], 'Requests raised elsewhere are ticked by hand')
        self.assertEqual(change({'request': {'index': 99, 'raised': True}}).status_code, 409)
        self.assertEqual(self.client.put('/api/joiners/' + joiner['id'], json={'done': True}).status_code, 403)
        self.assertTrue(change({'done': True}).json()['done'])
        # A later workbook does not rewrite a checklist in progress.
        main.persona_access_store.replace({'desks': [{'name': 'Repo Trader', 'area': '', 'requests': [{'catalog': 'Only', 'ticket': '', 'notes': ''}]}]}, 'new.xlsx')
        kept = self.client.get('/api/joiners').json()['joiners'][0]
        self.assertEqual(len(kept['requests']), 4)
        self.assertEqual(self.client.delete('/api/joiners/' + joiner['id'], headers=TOKEN).status_code, 200)
        self.assertEqual(self.client.get('/api/joiners').json()['joiners'], [])

    def test_installing_the_software_starts_the_persona_queue_on_the_joiners_machine(self):
        main.persona_store.save(self.repo_trader['id'], personas.Persona(name='Repo Trader', desk='Repo Trader', revision=1, items=[
            {'folder': 'Office', 'script': 'setup_i.ps1'}, {'folder': 'Teams', 'script': 'teams_install.ps1'}]),
            [{'folder': 'Office', 'script': 'setup_i.ps1', 'action': 'Install'}, {'folder': 'Teams', 'script': 'teams_install.ps1', 'action': 'Install'}])
        joiner = self.joiner()
        install = lambda: self.client.post(f'/api/joiners/{joiner["id"]}/install', headers=TOKEN)
        self.assertEqual(install().status_code, 400, 'No machine yet')
        self.assertEqual(self.client.put('/api/joiners/' + joiner['id'], json={'computer': 'bad name!'}, headers=TOKEN).status_code, 400)
        self.assertEqual(self.client.put('/api/joiners/' + joiner['id'], json={'computer': 'newpc01'}, headers=TOKEN).json()['computer'], 'NEWPC01')
        started = install()
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual((started.json()['computer'], started.json()['count']), ('NEWPC01', 2))
        self.assertEqual([(i.computer, Path(i.folder).name) for i in self.started[0]], [('NEWPC01', 'Office'), ('NEWPC01', 'Teams')])
        listed = self.client.get('/api/joiners').json()['joiners'][0]
        self.assertEqual((listed['install']['queue'], listed['install']['state'], listed['install']['total'], listed['install']['finished']),
                         (started.json()['queue'], 'queued', 2, 0))
        self.assertEqual(install().status_code, 409, 'A second click while it installs is refused')

    def test_people_starting_soon_at_any_site_are_suggested_once(self):
        today = date.today()
        with fixture_connect(self.db) as c:  # closes it, so Windows can remove the folder
            uid = c.execute('select coalesce(max(id),0)+1 from users').fetchone()[0]
            for offset, (name, start, location) in enumerate([('Soon Starter', today + timedelta(days=5), 'Paris - 52 Avenue Hoche'),
                                                              ('Later Starter', today + timedelta(days=200), 'Paris - 52 Avenue Hoche'),
                                                              ('Tracked Starter', today + timedelta(days=3), 'London')]):
                c.execute('insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm,start_date,location,job_role,department) '
                          'values(?,?,?,?,?,?,?,?,?,?,?,?)', (uid + offset, f'uid:fixture{offset}', f'FIXTURE{offset}', f'fixture{offset}', name, name.lower(),
                                                              f'{name.split()[0].lower()}@example.test', f'{name.split()[0].lower()}@example.test',
                                                              start.isoformat() + ' 00:00:00', location, 'Repo Trader - VP', 'Rates'))
        self.joiner(name='Tracked Starter', user='uid:fixture2')
        result = self.client.get('/api/joiners/starting').json()
        names = [p['name'] for p in result['people']]
        self.assertIn('Soon Starter', names)
        self.assertNotIn('Later Starter', names)
        self.assertNotIn('Tracked Starter', names, 'Someone with a checklist is not suggested again')
        soon = next(p for p in result['people'] if p['name'] == 'Soon Starter')
        self.assertEqual((soon['user'], soon['email'], soon['location'], soon['title']), ('uid:fixture0', 'soon@example.test', 'Paris - 52 Avenue Hoche', 'Repo Trader - VP'))
        self.assertEqual(result['site'], 'Paris')

    def test_writes_need_the_admin_token_and_a_known_persona(self):
        self.assertEqual(self.client.post('/api/joiners', json={'name': 'X', 'persona': self.repo_trader['id']}).status_code, 403)
        self.assertEqual(self.client.post('/api/joiners', json={'name': 'X', 'persona': '0' * 12}, headers=TOKEN).status_code, 404)
        self.assertEqual(self.client.post('/api/joiners', json={'name': '  ', 'persona': self.repo_trader['id']}, headers=TOKEN).status_code, 400)
        self.assertEqual(self.client.put('/api/joiners/not-an-id', json={'done': True}, headers=TOKEN).status_code, 404)


if __name__ == '__main__':
    unittest.main()
