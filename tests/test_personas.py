"""Personas: saved software bundles installed on one machine as a queue. No remote command runs."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from job_service import JobService

TOKEN = {'X-Atlas-Token': 'test-token'}


class Personas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / 'repo'
        for folder, script in (('Office', 'setup_i.ps1'), ('Teams', 'teams_install.ps1'), ('Zoom', 'zoom_i.ps1'), ('Zoom', 'zoom_u.ps1')):
            (self.repo / folder).mkdir(parents=True, exist_ok=True); (self.repo / folder / script).write_text('exit 0')
        self.service = JobService(lambda: base / 'operations.db'); self.addCleanup(self.service.pool.shutdown)
        self.started = []
        for target, value in (('HISTORY_DB', base / 'history.db'), ('REPO', self.repo), ('job_service', self.service),
                              ('jobs', self.service.jobs), ('queue_jobs', self.service.queues), ('lock', self.service.lock)):
            patcher = patch.object(main, target, value); patcher.start(); self.addCleanup(patcher.stop)
        # Record the queue instead of running it: nothing is copied or launched.
        submit = patch.object(self.service, 'submit', side_effect=lambda fn, queue_id, items: self.started.append((fn, queue_id, items)))
        submit.start(); self.addCleanup(submit.stop)
        store = patch.object(main.persona_store, 'path', base / 'data' / 'personas.json'); store.start(); self.addCleanup(store.stop)
        token = patch('atlas_api.TOKEN', 'test-token'); token.start(); self.addCleanup(token.stop)
        self.client = TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345)); self.addCleanup(self.client.close)

    def create(self, name='New starter', items=None, **extra):
        items = items or [{'folder': 'Office', 'script': 'setup_i.ps1'}, {'folder': 'Teams', 'script': 'teams_install.ps1'}]
        return self.client.post('/api/personas', json={'name': name, 'items': items, **extra}, headers=TOKEN)

    def test_a_persona_is_saved_by_package_name_and_listed_in_order(self):
        response = self.create('  New   starter ', [{'folder': str(self.repo / 'Office'), 'script': 'setup_i.ps1'},
                                                   {'folder': 'Teams', 'script': 'teams_install.ps1', 'action': 'Install'}],
                               description=' First day ', fresh=True, threads=16)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual((saved['name'], saved['description'], saved['revision'], saved['fresh'], saved['threads']),
                         ('New starter', 'First day', 1, True, 16))
        self.assertEqual(saved['items'], [{'folder': 'Office', 'script': 'setup_i.ps1', 'action': 'Install'},
                                          {'folder': 'Teams', 'script': 'teams_install.ps1', 'action': 'Install'}],
                         'Folder names only, so a persona survives a repository move')
        self.assertEqual(self.create('Analyst', [{'folder': 'Zoom', 'script': 'zoom_i.ps1'}]).status_code, 200)
        listed = self.client.get('/api/personas').json()
        self.assertEqual([p['name'] for p in listed['personas']], ['Analyst', 'New starter'])
        self.assertTrue(listed['repository'])
        self.assertEqual([i['problem'] for i in listed['personas'][1]['items']], [None, None])
        stored = json.loads(main.persona_store.path.read_text(encoding='utf-8'))
        self.assertEqual(len(stored['personas']), 2)
        self.assertNotIn('problem', stored['personas'][1]['items'][0], 'Checks are worked out when listed, never saved')

    def test_only_available_packages_with_a_matching_script_are_saved(self):
        (self.repo.parent / 'outside').mkdir(); (self.repo.parent / 'outside' / 'setup_i.ps1').write_text('exit 0')
        cases = {
            'Missing': ([{'folder': 'Missing', 'script': 'setup_i.ps1'}], 'Missing: Not in the package repository'),
            'Outside': ([{'folder': '../outside', 'script': 'setup_i.ps1'}], 'Not in the package repository'),
            'Wrong action': ([{'folder': 'Office', 'script': 'setup_i.ps1', 'action': 'Uninstall'}], 'No uninstall script named setup_i.ps1'),
            'Escape': ([{'folder': 'Office', 'script': '..\\Teams\\teams_install.ps1'}], 'No install script'),
            'Twice': ([{'folder': 'Office', 'script': 'setup_i.ps1'}, {'folder': 'Office', 'script': 'setup_i.ps1'}], 'Office is listed twice'),
        }
        for name, (items, detail) in cases.items():
            with self.subTest(name):
                response = self.create(name, items)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(detail, response.json()['detail'])
        self.assertEqual(self.create('   ').status_code, 400)
        self.assertEqual(self.client.post('/api/personas', json={'name': 'Empty', 'items': []}, headers=TOKEN).status_code, 422)
        # The same package may be removed and installed again in one persona.
        self.assertEqual(self.create('Reinstall Zoom', [{'folder': 'Zoom', 'script': 'zoom_u.ps1', 'action': 'Uninstall'},
                                                        {'folder': 'Zoom', 'script': 'zoom_i.ps1'}]).status_code, 200)
        self.assertEqual(self.create('reinstall ZOOM').status_code, 409, 'Names are unique, ignoring case and spacing')
        self.assertEqual(self.client.post('/api/personas', json={'name': 'No token', 'items': [{'folder': 'Office', 'script': 'setup_i.ps1'}]}).status_code, 403)
        self.assertEqual([p['name'] for p in self.client.get('/api/personas').json()['personas']], ['Reinstall Zoom'])

    def test_edits_and_deletes_need_the_current_revision(self):
        saved = self.create().json()
        body = {'name': 'New starter', 'items': saved['items'][:1], 'revision': 1}
        updated = self.client.put('/api/personas/' + saved['id'], json=body, headers=TOKEN)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual((updated.json()['revision'], len(updated.json()['items']), updated.json()['id']), (2, 1, saved['id']))
        self.assertEqual(self.client.put('/api/personas/' + saved['id'], json=body, headers=TOKEN).status_code, 409, 'Changed in another window')
        self.assertEqual(self.client.delete(f'/api/personas/{saved["id"]}?revision=1', headers=TOKEN).status_code, 409)
        self.assertEqual(self.client.delete(f'/api/personas/{saved["id"]}?revision=2').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/personas/{saved["id"]}?revision=2', headers=TOKEN).status_code, 200)
        self.assertEqual(self.client.put('/api/personas/' + saved['id'], json={**body, 'revision': 2}, headers=TOKEN).status_code, 404)
        self.assertEqual(self.client.get('/api/personas').json()['personas'], [])
        self.assertEqual(self.client.put('/api/personas/not-an-id', json=body, headers=TOKEN).status_code, 404)

    def test_the_list_flags_packages_removed_since_saving(self):
        saved = self.create().json()
        (self.repo / 'Teams' / 'teams_install.ps1').unlink()
        items = self.client.get('/api/personas').json()['personas'][0]['items']
        self.assertEqual([i['problem'] for i in items], [None, 'No install script named teams_install.ps1'])
        (self.repo / 'Office' / 'setup_i.ps1').unlink(); (self.repo / 'Office').rmdir()
        self.assertEqual(self.client.get('/api/personas').json()['personas'][0]['items'][0]['problem'], 'Not in the package repository')
        with patch.object(main, 'REPO', self.repo / 'offline'):
            offline = self.client.get('/api/personas').json()
        self.assertFalse(offline['repository'])
        self.assertNotIn('problem', offline['personas'][0]['items'][0], 'An unavailable share is reported once, not per package')
        self.assertEqual(saved['revision'], 1)

    def test_install_starts_one_queue_for_the_machine_in_persona_order(self):
        saved = self.create(fresh=True, threads=4).json()
        response = self.client.post(f'/api/personas/{saved["id"]}/install', json={'computer': 'testpc', 'revision': 1}, headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual((result['persona'], result['computer'], result['count']), ('New starter', 'TESTPC', 2))
        self.assertEqual(result['items'], [{'package': 'Office', 'action': 'Install'}, {'package': 'Teams', 'action': 'Install'}])
        self.assertEqual(len(self.started), 1, 'One queue, started once')
        fn, queue_id, items = self.started[0]
        self.assertIs(fn, main._queue_worker)
        self.assertEqual(queue_id, result['queue'])
        self.assertEqual([(i.computer, Path(i.folder).name, i.script, i.action, i.fresh, i.threads, i.mode) for i in items],
                         [('TESTPC', 'Office', 'setup_i.ps1', 'Install', True, 4, 'full'),
                          ('TESTPC', 'Teams', 'teams_install.ps1', 'Install', True, 4, 'full')])
        queue = self.service.queues[queue_id]
        self.assertEqual((queue['persona'], [row['package'] for row in queue['items']]), ('New starter', ['Office', 'Teams']))
        active = self.client.get('/api/deployments/active').json()['deployments']
        self.assertEqual((active[0]['kind'], active[0]['persona'], len(active[0]['items'])), ('queue', 'New starter', 2))

    def test_install_starts_nothing_unless_every_package_and_the_machine_are_ready(self):
        saved = self.create().json()
        install = lambda **body: self.client.post(f'/api/personas/{saved["id"]}/install', json={'computer': 'TESTPC', **body}, headers=TOKEN)
        self.assertEqual(install(revision=7).status_code, 409, 'Edited since it was opened')
        self.assertEqual(self.client.post(f'/api/personas/{saved["id"]}/install', json={'computer': 'TESTPC'}).status_code, 403)
        self.assertEqual(install(computer='bad name!').status_code, 400)
        self.assertEqual(self.client.post('/api/personas/0123456789ab/install', json={'computer': 'TESTPC'}, headers=TOKEN).status_code, 404)
        self.service.unresolved.add('TESTPC')
        self.assertEqual(install().status_code, 409, 'An unknown earlier outcome holds the machine')
        self.service.unresolved.clear()
        self.service.jobs['running'] = {'state': 'running', 'target': 'TESTPC', 'events': []}
        refused = install()
        self.assertEqual(refused.status_code, 409)
        self.assertIn('already has a deployment running', refused.json()['detail'])
        self.service.jobs['running']['state'] = 'launched'
        self.service.queues['paused'] = {'state': 'paused', 'items': [{'target': 'TESTPC', 'state': 'waiting'}]}
        (self.repo / 'Teams' / 'teams_install.ps1').unlink()
        missing = install()
        self.assertEqual(missing.status_code, 400, 'One unavailable package stops the whole install')
        self.assertEqual(self.started, [])
        self.assertEqual(set(self.service.queues), {'paused'})
        (self.repo / 'Teams' / 'teams_install.ps1').write_text('exit 0')
        self.assertEqual(install().status_code, 200, 'Finished jobs and paused queues do not hold the machine')
        self.assertEqual(install().status_code, 409, 'A second click while the first install runs is refused')
        self.assertEqual(len(self.started), 1)

    def test_an_unreadable_file_is_reported_not_replaced(self):
        main.persona_store.path.parent.mkdir(parents=True, exist_ok=True)
        main.persona_store.path.write_text('{"personas": ', encoding='utf-8')
        self.assertEqual(self.client.get('/api/personas').status_code, 503)
        self.assertEqual(self.create().status_code, 503)
        self.assertEqual(main.persona_store.path.read_text(encoding='utf-8'), '{"personas": ')


if __name__ == '__main__':
    unittest.main()
