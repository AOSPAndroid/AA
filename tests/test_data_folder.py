"""The data folder imports exports saved in one folder, on a disposable copy of the seed database."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import data_folder
import package_data
import package_data_api
import vdi_data
from data_folder import DataFolder, Settings, classify
from sqlite_fixture import connect
from test_directory_exports import device_sheets
from test_directory_pair import csv_text

SEED = Path(__file__).resolve().parents[1] / 'office_atlas.db'
LATER = lambda: time.time() + 3600  # Every file in the folder has settled.


class DataFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db, self.folder = root / 'data' / 'office_atlas.db', root / 'AtlasXL'
        self.db.parent.mkdir()
        self.folder.mkdir()
        source = sqlite3.connect(SEED.as_uri() + '?mode=ro&immutable=1', uri=True)
        with connect(self.db) as target:
            source.backup(target)
        source.close()
        with connect(self.db) as c:
            package_data.initialize(c)
            vdi_data.initialize(c)
            c.execute('create table if not exists directory_import_history(id text primary key,at text,source text,backup text,report text)')
        self.jobs = []
        self.sync = DataFolder(self.db, root / 'repo', root / 'data-folder.json', busy=lambda: bool(self.jobs), clock=LATER, settle=0)
        self.addCleanup(self.sync.close)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        self.sheets = device_sheets()

    def write(self, name, rows):
        (self.folder / name).write_text(csv_text(rows), encoding='utf-8', newline='')

    def kinds(self, summary):
        return {entry['kind']: entry for entry in summary['kinds']}

    def count(self, sql):
        with connect(self.db) as c:
            return c.execute(sql).fetchone()[0]

    def test_exports_are_recognised_by_their_columns_whatever_their_names(self):
        self.write('a.csv', self.sheets['users'])
        self.write('b.csv', self.sheets['devices'])
        self.write('c.csv', [['name', 'u_package_sub_state', 'u_display_name'], ['PKG_ONE', 'Live', 'Package one']])
        self.write('d.csv', [['Name', 'Machine Catalog', 'User'], ['VDI-001', 'Catalog', 'u1']])
        # A users export has a state (address) column too; it stays a users export.
        self.write('e.csv', [['user_name', 'name', 'email', 'state'], ['u3', 'Third Person', 't@example.invalid', 'Paris']])
        self.write('f.csv', [['Column A', 'Column B'], ['1', '2']])
        self.assertEqual({name: classify(self.folder / name) for name in 'a.csv b.csv c.csv d.csv e.csv f.csv'.split()},
                         {'a.csv': 'user', 'b.csv': 'machine', 'c.csv': 'package', 'd.csv': 'vdi', 'e.csv': 'user', 'f.csv': ''})

    def test_a_snapshot_that_removes_many_records_waits_then_later_updates_apply_on_their_own(self):
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        summary = self.sync.check()
        directory = self.kinds(summary)['directory']
        self.assertEqual((summary['status']['state'], directory['result']), ('held', 'held'))
        self.assertIn('existing records disappear', summary['held']['reason'])
        before = self.count('select count(*) from users')
        self.assertGreater(before, 2, 'Nothing is applied before the review')
        self.sync.check()
        self.assertEqual(self.count('select count(*) from users'), before, 'A held snapshot is not applied by the next check')

        summary = self.sync.apply_held(summary['held']['id'])
        self.assertEqual(self.count('select count(*) from users'), 2)
        self.assertEqual(self.kinds(summary)['directory']['result'], 'applied')
        history = self.count("select count(*) from directory_import_history where source='Data folder · sys_user.csv + alm_asset.csv'")
        self.assertEqual(history, 1)
        backup = self.kinds(summary)['directory']['backup']
        self.assertTrue((self.db.parent / 'backups' / backup).is_file())

        self.sync.check()
        self.assertEqual(self.count('select count(*) from directory_import_history'), 1, 'The same files are not imported again')

        devices = [row[:] for row in self.sheets['devices']]
        devices.append(['', 'ASSET-4', 'Computer', 'TESTPC-4', 'Dell Example', '', 'In Stock', '000126', '', 'ASSET-4 - Dell Example', 'Paris'])
        self.write('alm_asset.csv', devices)
        os.utime(self.folder / 'alm_asset.csv', (time.time() + 5, time.time() + 5))
        summary = self.sync.check()
        self.assertEqual(self.kinds(summary)['directory']['result'], 'applied', summary)
        self.assertEqual(self.count("select count(*) from machines where machine_name_norm='testpc-4'"), 1)
        self.assertEqual([entry['kind'] for entry in summary['history']], ['directory', 'directory'])

    def test_citrix_and_package_exports_are_applied_and_link_to_the_new_users(self):
        self.sync.state['review_large'] = False  # Replace the seed directory with the two fixture users.
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        self.write('SingleSessionMachines.csv', [['Name', 'Machine Catalog', 'User'], ['VDI-001', 'Catalog', 'u1']])
        self.write('u_cmdb_software_package.csv', [['name', 'u_package_sub_state'], ['PKG_ONE', 'Live']])
        summary = self.sync.check()
        kinds = self.kinds(summary)
        self.assertEqual({kind: kinds[kind]['result'] for kind in kinds}, {'directory': 'applied', 'vdi': 'applied', 'packages': 'applied'}, summary)
        self.assertEqual(summary['status']['state'], 'synced')
        self.assertEqual(self.count("select count(*) from vdi_devices where original_name='VDI-001'"), 1)
        self.assertEqual(self.count('select count(*) from vdi_links'), 1, 'Citrix is imported after users, so the link resolves')
        self.assertEqual(self.count("select count(*) from package_data where source='Data folder · u_cmdb_software_package.csv'"), 1)
        self.assertEqual(self.count('select count(*) from vdi_imports'), 1)
        self.sync.check()
        self.assertEqual((self.count('select count(*) from vdi_imports'), self.count('select count(*) from package_data_imports')), (1, 1))

    def test_users_and_devices_wait_for_running_jobs_and_for_both_files(self):
        self.write('sys_user.csv', self.sheets['users'])
        directory = self.kinds(self.sync.check())['directory']
        self.assertEqual(directory['result'], 'waiting')
        self.assertIn('add the devices export', directory['message'])
        self.write('alm_asset.csv', self.sheets['devices'])
        self.jobs.append('deployment')
        directory = self.kinds(self.sync.check())['directory']
        self.assertEqual(directory['result'], 'waiting')
        self.assertIn('Deployments or queue jobs are running', directory['message'])
        self.jobs.clear()
        self.assertEqual(self.kinds(self.sync.check())['directory']['result'], 'held')

    def test_a_file_still_being_saved_is_left_until_it_settles(self):
        self.sync.clock = time.time
        self.write('SingleSessionMachines.csv', [['Name', 'User'], ['VDI-001', 'u1']])
        summary = self.sync.check()
        self.assertEqual(summary['status']['state'], 'waiting')
        self.assertIn('SingleSessionMachines.csv still being saved', summary['status']['message'])
        self.assertEqual(self.count('select count(*) from vdi_imports'), 0)
        self.sync.clock = LATER
        self.assertEqual(self.kinds(self.sync.check())['vdi']['result'], 'applied')

    def test_a_refused_export_is_not_retried_until_it_changes(self):
        self.write('u_cmdb_software_package.csv', [['name', 'u_package_sub_state'], ['PKG_ONE', 'Live', 'extra cell']])
        packages = self.kinds(self.sync.check())['packages']
        self.assertEqual(packages['result'], 'error')
        self.assertIn('u_cmdb_software_package.csv', packages['message'])
        with patch.object(package_data_api, 'prepare', side_effect=AssertionError('The same file is not parsed again')):
            self.assertEqual(self.kinds(self.sync.check())['packages']['result'], 'error')
        self.write('u_cmdb_software_package.csv', [['name', 'u_package_sub_state'], ['PKG_ONE', 'Live']])
        os.utime(self.folder / 'u_cmdb_software_package.csv', (time.time() + 5, time.time() + 5))
        self.assertEqual(self.kinds(self.sync.check())['packages']['result'], 'applied')

    def test_a_held_review_that_is_out_of_date_is_refused(self):
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        self.sync.check()
        with self.assertRaises(HTTPException) as refused:
            self.sync.apply_held('not-the-review')
        self.assertEqual(refused.exception.status_code, 409)
        held = self.sync.held['id']
        self.jobs.append('deployment')
        with self.assertRaises(HTTPException) as busy:
            self.sync.apply_held(held)
        self.assertIn('Finish active jobs', busy.exception.detail)
        self.assertGreater(self.count('select count(*) from users'), 2)

    def test_turning_it_off_stops_imports(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=False))
        self.write('SingleSessionMachines.csv', [['Name', 'User'], ['VDI-001', 'u1']])
        self.assertEqual(self.sync.check()['status']['state'], 'off')
        self.assertEqual(self.count('select count(*) from vdi_imports'), 0)


class BuiltInFolder(unittest.TestCase):
    def test_the_built_in_folder_is_on_without_setup_until_a_person_saves_settings(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            atlas, axis = root / 'AtlasXL', root / 'AxisXL'
            with patch.object(data_folder, 'FOLDERS', (str(atlas), str(axis))):
                self.assertEqual(data_folder.default_exports_folder(), str(atlas), 'Neither exists: the first is shown')
                axis.mkdir()
                self.assertEqual(data_folder.default_exports_folder(), str(axis), 'Only the second exists: it is used')
                atlas.mkdir()
                self.assertEqual(data_folder.default_exports_folder(), str(atlas))
                sync = DataFolder(root / 'db', root, root / 'data-folder.json', default_folder=data_folder.default_exports_folder, settle=0)
                summary = sync.check()
                self.assertEqual((summary['folder'], summary['enabled']), (str(atlas), True))
                self.assertEqual(summary['status']['state'], 'synced', 'An empty built-in folder is simply up to date')
                sync.configure(Settings(folder=str(atlas), enabled=False))
                again = DataFolder(root / 'db', root, root / 'data-folder.json', default_folder=data_folder.default_exports_folder, settle=0)
                self.assertFalse(again.summary()['enabled'], 'Turning it off is remembered after a restart')
                self.assertEqual(data_folder.CHECK_SECONDS, 900)
                self.assertEqual(sync.interval, 900, 'Checked every 15 minutes, not every minute')


class Routes(unittest.TestCase):
    def test_changes_need_the_admin_token_and_reading_the_state_does_not(self):
        from types import SimpleNamespace
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            app = FastAPI()
            def token(request):
                if request.headers.get('x-atlas-token') != 'test':
                    raise HTTPException(403, 'token')
            sync = data_folder.register(app, SimpleNamespace(MASTER_DB=root / 'office_atlas.db', REPO=root), token, lambda: False, root / 'data-folder.json')
            sync.settle = 0
            client = TestClient(app)
            self.assertEqual(client.get('/api/data-folder').json()['folder'], data_folder.DEFAULT_FOLDER)
            body = {'folder': str(root / 'AtlasXL'), 'enabled': True}
            for url, payload in (('/api/data-folder/settings', body), ('/api/data-folder/check', {}), ('/api/data-folder/apply', {'id': 'x'})):
                self.assertEqual(client.post(url, json=payload).status_code, 403, url)
            response = client.post('/api/data-folder/settings', json=body, headers={'x-atlas-token': 'test'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status']['state'], 'error', 'A folder that does not exist is reported')
            self.assertIn('Folder not reachable', response.json()['status']['message'])
            self.assertEqual(client.post('/api/data-folder/settings', json={**body, 'extra': 1}, headers={'x-atlas-token': 'test'}).status_code, 422)
            sync.close()


if __name__ == '__main__':
    unittest.main()
