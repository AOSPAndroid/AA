"""The data folder imports exports saved in one folder, on a disposable copy of the seed database."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import data_folder
import package_data
import package_data_api
import vdi_data
import vdi_data_api
from data_folder import DataFolder, Settings, classify
from sqlite_fixture import connect
from test_directory_exports import device_sheets
from test_directory_pair import csv_text

SEED = Path(__file__).resolve().parents[1] / 'office_atlas.db'
LATER = lambda: time.time() + 3600  # Every file in the folder has settled.
CITRIX = [['Name', 'Machine Catalog', 'User'], ['VDI-001', 'Catalog', 'u1']]


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
        # Columns specific to each export decide; a Name column alone is not enough.
        self.write('g.csv', [['user_name', 'name', 'department'], ['u3', 'Third Person', 'IT']])
        self.write('h.csv', [['Name', 'User'], ['Third Person', 'u3']])
        self.write('i.csv', [['Name', 'Description', 'sys_updated_on'], ['Some record', 'x', '']])
        self.write('j.csv', [['Name', 'User Name', 'Delivery Group'], ['VDI-002', 'u3', 'Group']])
        self.write('k.csv', [['name', 'serial_number'], ['PC-9', '123']])
        (self.folder / 'l.xlsx').write_bytes(b'PK\x03\x04 not really a workbook')
        kinds = {name: classify(self.folder / name)[0] for name in 'a b c d e f g h i j k l'.split() for name in [name + ('.xlsx' if name == 'l' else '.csv')]}
        self.assertEqual(kinds, {'a.csv': 'user', 'b.csv': 'machine', 'c.csv': 'package', 'd.csv': 'vdi', 'e.csv': 'user', 'f.csv': '',
                                 'g.csv': '', 'h.csv': '', 'i.csv': '', 'j.csv': 'vdi', 'k.csv': 'machine', 'l.xlsx': ''})
        self.assertIn('no email column', classify(self.folder / 'g.csv')[1])
        self.sync.check()
        self.assertEqual(self.count("select count(*) from vdi_devices where original_name='Third Person'"), 0, 'A list of people is not Citrix data')
        self.assertEqual(self.count('select count(*) from vdi_imports'), 1)
        self.assertIn('g.csv (looks like a users export but has no email column; export it with email)', self.sync.summary()['ignored'])
        with patch.object(data_folder, 'header', side_effect=PermissionError('open in Excel')):
            self.assertRaises(OSError, classify, self.folder / 'a.csv')

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
        self.write('SingleSessionMachines.csv', CITRIX)
        summary = self.sync.check()
        self.assertEqual(summary['status']['state'], 'waiting')
        self.assertIn('SingleSessionMachines.csv is still being saved or in use', summary['status']['message'])
        self.assertEqual(self.count('select count(*) from vdi_imports'), 0)
        self.assertTrue(self.sync.soon, 'Looked at again in a minute, not in 15')
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

    def settled(self, name, seconds=5):
        # Rewritten files get a distinct, settled modified time.
        later = time.time() + seconds
        os.utime(self.folder / name, (later, later))

    def test_a_newer_export_being_saved_holds_back_every_import(self):
        self.write('SingleSessionMachines.csv', CITRIX)
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        self.sync.state['review_large'] = False
        fresh = self.folder / 'SingleSessionMachines (2).csv'
        fresh.write_text(csv_text(CITRIX), encoding='utf-8', newline='')
        os.utime(fresh, (LATER(), LATER()))  # Saved just now, by the test clock.
        summary = self.sync.check()
        self.assertEqual(summary['status']['state'], 'waiting')
        self.assertTrue(self.sync.soon)
        self.assertEqual((self.count('select count(*) from vdi_imports'), self.count('select count(*) from directory_import_history')), (0, 0),
                         'Neither the older Citrix export nor the users and devices are imported meanwhile')
        os.utime(fresh, (time.time(), time.time()))
        self.assertEqual(self.kinds(self.sync.check())['vdi']['result'], 'applied')
        self.assertFalse(self.sync.soon)

    def test_an_export_open_elsewhere_is_looked_at_again_not_ignored(self):
        self.write('SingleSessionMachines.csv', CITRIX)
        with patch.object(data_folder, 'header', side_effect=PermissionError('locked')):
            summary = self.sync.check()
        self.assertIn('SingleSessionMachines.csv is still being saved or in use', summary['status']['message'])
        self.assertEqual(summary['ignored'], [])
        self.assertEqual(self.kinds(self.sync.check())['vdi']['result'], 'applied', 'Read once it is free')

    def test_a_busy_database_is_retried_while_a_bad_export_is_refused(self):
        self.write('SingleSessionMachines.csv', CITRIX)
        self.write('u_cmdb_software_package.csv', [['name', 'u_package_sub_state'], ['PKG_ONE', 'Live']])
        with patch.object(vdi_data_api, 'commit', side_effect=sqlite3.OperationalError('database is locked')), \
             patch.object(package_data_api, 'prepare', side_effect=TypeError('unexpected cell')):
            kinds = self.kinds(self.sync.check())
        self.assertEqual((kinds['vdi']['result'], kinds['packages']['result']), ('waiting', 'error'))
        self.assertIn('database is locked', kinds['vdi']['message'])
        self.assertIn('unexpected cell', kinds['packages']['message'])
        self.assertTrue(self.sync.soon)
        kinds = self.kinds(self.sync.check())
        self.assertEqual((kinds['vdi']['result'], kinds['packages']['result']), ('applied', 'error'),
                         'The database error was temporary; the refused export waits for a new version or Check now')
        self.assertEqual(self.kinds(self.sync.check(force=True))['packages']['result'], 'applied')

    def test_an_export_that_changes_while_it_is_copied_is_read_again(self):
        self.write('SingleSessionMachines.csv', CITRIX)
        real = data_folder.shutil.copy2
        def copy_changed(source, target):
            real(source, target)
            Path(target).write_text(csv_text([CITRIX[0], ['VDI-999', 'Other', 'u1']]), encoding='utf-8')
        with patch.object(data_folder.shutil, 'copy2', side_effect=copy_changed):
            vdi = self.kinds(self.sync.check())['vdi']
        self.assertEqual(vdi['result'], 'waiting')
        self.assertIn('changed while Atlas was reading it', vdi['message'])
        self.assertEqual(self.count("select count(*) from vdi_devices where original_name='VDI-999'"), 0)
        self.assertEqual(self.kinds(self.sync.check())['vdi']['result'], 'applied')

    def test_a_held_review_is_dropped_when_its_exports_change_or_go(self):
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        held = self.sync.check()['held']['id']
        users = self.count('select count(*) from users')
        self.write('sys_user.csv', self.sheets['users'] + [['u3', 'Third Person', 't@example.invalid'] + [''] * 8])
        self.settled('sys_user.csv')
        with self.assertRaises(HTTPException) as changed:
            self.sync.apply_held(held)
        self.assertIn('exports changed since this review', changed.exception.detail)
        self.assertEqual(self.count('select count(*) from users'), users, 'What was reviewed is not applied over a newer export')
        self.assertIsNone(self.sync.held)
        self.assertTrue(self.sync.soon)

        held = self.sync.check()['held']
        self.assertEqual(held['files'], ['sys_user.csv', 'alm_asset.csv'])
        (self.folder / 'alm_asset.csv').unlink()
        summary = self.sync.check()
        self.assertIsNone(summary['held'], 'A review of files that are gone is dropped')
        self.assertEqual(self.kinds(summary)['directory']['result'], 'waiting')
        with self.assertRaises(HTTPException):
            self.sync.apply_held(held['id'])
        self.assertEqual(self.count('select count(*) from users'), users)

    def test_background_imports_take_admins_change_gate_and_requests_do_not_take_it_twice(self):
        self.sync.state['review_large'] = False
        self.write('sys_user.csv', self.sheets['users'])
        self.write('alm_asset.csv', self.sheets['devices'])
        self.write('SingleSessionMachines.csv', CITRIX)
        self.write('u_cmdb_software_package.csv', [['name', 'u_package_sub_state'], ['PKG_ONE', 'Live']])
        held = []
        @contextmanager
        def gate():
            held.append(self.count('select count(*) from directory_import_history') + self.count('select count(*) from vdi_imports')
                        + self.count('select count(*) from package_data_imports'))
            yield
        kinds = self.kinds(self.sync.check(gate=gate))
        self.assertEqual({kind: kinds[kind]['result'] for kind in kinds}, {'directory': 'applied', 'vdi': 'applied', 'packages': 'applied'})
        self.assertEqual(held, [0, 1, 2], 'Held once around each change, not while reading the exports')

    def test_backups_made_by_the_folder_are_pruned_and_a_failed_merge_leaves_none(self):
        with patch.object(data_folder, 'KEEP_BACKUPS', 1):
            for number in (1, 2):
                self.write('SingleSessionMachines.csv', [CITRIX[0], [f'VDI-00{number}', 'Catalog', 'u1']])
                self.settled('SingleSessionMachines.csv', number)
                self.assertEqual(self.kinds(self.sync.check())['vdi']['result'], 'applied')
        backups = sorted(path.name for path in (self.db.parent / 'backups').iterdir())
        self.assertEqual(backups, self.sync.state['backups']['vdi'], 'Only the newest Citrix backup is kept')
        from refresh_directory import apply_refresh
        def fail(connection, backup):
            raise sqlite3.IntegrityError('simulated')
        with self.assertRaises(sqlite3.IntegrityError):
            apply_refresh(self.db, SEED, self.db.parent / 'backups', after_merge=fail)
        self.assertEqual(sorted(path.name for path in (self.db.parent / 'backups').iterdir()), backups, 'No backup of a merge that did not happen')

    def test_the_watcher_keeps_running_when_a_check_and_its_report_fail(self):
        calls = []
        def failing(**options):
            calls.append(options)
            raise RuntimeError('unexpected')
        self.sync.check = failing
        self.sync.set_status = lambda *args: (_ for _ in ()).throw(OSError('disk full'))
        self.sync.wake.set()
        thread = threading.Thread(target=self.sync.run)
        thread.start()
        for _ in range(100):
            if calls:
                break
            time.sleep(0.02)
        self.sync.wake.set()
        for _ in range(100):
            if len(calls) > 1:
                break
            time.sleep(0.02)
        self.sync.close()
        thread.join(5)
        self.assertEqual(len(calls), 2, 'A second check runs after the first one failed')
        self.assertFalse(thread.is_alive())

    def test_turning_it_off_stops_imports(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=False))
        self.write('SingleSessionMachines.csv', CITRIX)
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


class AdminGate(unittest.TestCase):
    def test_a_background_import_waits_while_a_request_holds_admins_change_gate(self):
        import asyncio
        from types import SimpleNamespace
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            db, exports = root / 'office_atlas.db', root / 'AtlasXL'
            exports.mkdir()
            with connect(db) as c:
                vdi_data.initialize(c)
            (exports / 'SingleSessionMachines.csv').write_text(csv_text(CITRIX), encoding='utf-8', newline='')
            app = FastAPI()
            sync = data_folder.register(app, SimpleNamespace(MASTER_DB=db, REPO=root), lambda request: None, lambda: False, root / 'data-folder.json')
            sync.start = lambda: None  # The test drives the checks.
            sync.settle, sync.clock = 0, LATER
            sync.configure(Settings(folder=str(exports), enabled=True))
            imported = lambda: connect(db).execute('select count(*) from vdi_imports').fetchone()[0]
            with TestClient(app) as client:
                async def make():
                    app.state.mutation_gate = asyncio.Lock()
                    await app.state.mutation_gate.acquire()  # A request is changing something.
                client.portal.call(make)
                thread = threading.Thread(target=sync.check, kwargs={'gate': sync.gate})
                thread.start()
                thread.join(1.5)
                self.assertTrue(thread.is_alive(), 'The import waits for the gate')
                self.assertEqual(imported(), 0)
                client.portal.call(app.state.mutation_gate.release)
                thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(imported(), 1)
                self.assertFalse(client.portal.call(app.state.mutation_gate.locked), 'The gate is released after the import')
            sync.close()


if __name__ == '__main__':
    unittest.main()
