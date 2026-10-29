"""Import folder against a copy of the Atlas database; every export is synthetic."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.deploy import package_data
from backend.directory import vdi_data
from backend.atlas_store import ClosingConnection
from backend.directory.import_folder import ImportFolder, Settings, headers, kind_of, register
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import device_sheets, workbook
from test_directory_pair import csv_text
from test_package_data import extract as package_csv
from test_vdi_data import HEADERS as CITRIX_HEADERS, csv_bytes as citrix_csv, device as citrix_device

SEED = Path(__file__).resolve().parents[1] / 'office_atlas.db'


@unittest.skipUnless(SEED.is_file(), 'Seed database not available')
class ImportFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = root / 'office_atlas.db'
        with fixture_connect(SEED) as a, fixture_connect(self.db) as b:
            a.backup(b)
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            package_data.initialize(c)
            vdi_data.initialize(c)
        self.folder = root / 'AtlasXL'
        self.folder.mkdir()
        self.busy = False
        self.watcher = ImportFolder(self.db, root / 'import-folder.json', busy=lambda: self.busy)
        self.watcher.state['folder'] = str(self.folder)
        self.sheets = device_sheets()

    def write(self, name, content, age=120):
        path = self.folder / name
        if isinstance(content, str):
            path.write_text(content, encoding='utf-8-sig', newline='')
        elif isinstance(content, dict):
            workbook(path, content)
        else:
            path.write_bytes(content)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def directory(self, users=None):
        self.write('sys_user.csv', csv_text(users or self.sheets['users']))
        self.write('alm_asset.csv', csv_text(self.sheets['devices']))

    def count(self, sql):
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            return c.execute(sql).fetchone()[0]

    def test_exports_are_recognised_by_their_headers_not_their_names(self):
        self.assertEqual(kind_of(self.sheets['users'][0]), 'users')
        self.assertEqual(kind_of(self.sheets['devices'][0]), 'devices')
        # Citrix and package exports also have a Name column a devices export would accept.
        self.assertEqual(kind_of(['Name', 'Machine Catalog', 'Delivery Group', 'User', 'User Display Name', 'Power State']), 'vdi')
        self.assertEqual(kind_of(['u_display_name', 'name', 'u_package_sub_state', 'assigned_to']), 'packages')
        self.assertEqual(kind_of(['Name', 'Requested for', 'Opened']), '', 'An unrelated list must not become device inventory')
        self.assertEqual(kind_of(['Ticket', 'Opened', 'Short description']), '')
        # A Citrix CSV saved as UTF-16 with Excel's sep= line.
        self.assertEqual(headers(self.write('a.csv', citrix_csv([citrix_device()], sep=True, encoding='utf-16'))), CITRIX_HEADERS)
        self.assertEqual(kind_of(headers(self.write('SingleSessionMachines.csv.xlsx', {'Sheet1': [['Name', 'User', 'Delivery Group'], ['VDI-1', 'x1', 'EMEA']]}))), 'vdi')
        self.assertEqual(kind_of(headers(self.write('u_cmdb_software_package.csv', package_csv([('App', 'Live')])))), 'packages')

    def test_a_locked_header_is_retried_without_resaving_the_export(self):
        self.write('citrix.csv', citrix_csv([citrix_device()]))
        with patch('backend.directory.import_folder.headers', side_effect=[PermissionError('locked'), CITRIX_HEADERS]) as read:
            first = self.watcher.check()
            second = self.watcher.check()
        self.assertEqual(first['status']['state'], 'waiting')
        self.assertEqual(second['groups']['vdi']['result'], 'applied')
        self.assertEqual(read.call_count, 2)

    def test_an_unfinished_new_export_prevents_importing_an_older_snapshot(self):
        self.directory()
        self.watcher.state['review_large'] = False
        before = self.count('select count(*) from users')
        self.write('new-users.xlsx', b'incomplete workbook', age=1)
        summary = self.watcher.check()
        self.assertEqual(summary['status']['state'], 'waiting')
        self.assertEqual(self.count('select count(*) from users'), before)
        self.assertIsNone(summary['held'])

    def test_an_old_review_is_withdrawn_while_a_new_export_is_being_saved(self):
        self.directory()
        first = self.watcher.check()
        self.assertIsNotNone(first['held'])
        before = self.count('select count(*) from users')
        self.write('new-users.xlsx', b'incomplete workbook', age=1)
        summary = self.watcher.check()
        self.assertIsNone(summary['held'])
        self.assertEqual(summary['groups']['directory']['result'], 'waiting')
        self.assertEqual(self.count('select count(*) from users'), before)

    def test_an_export_changed_during_copy_does_not_reach_the_database(self):
        import shutil
        self.directory()
        self.watcher.state['review_large'] = False
        before = self.count('select count(*) from users')
        copy = shutil.copy2
        changed = False
        def changing_copy(source, destination, *args, **kwargs):
            nonlocal changed
            if Path(source).name == 'sys_user.csv' and not changed:
                changed = True
                self.write('sys_user.csv', csv_text(self.sheets['users']) + '\n')
            return copy(source, destination, *args, **kwargs)
        with patch('backend.directory.import_folder.shutil.copy2', side_effect=changing_copy):
            summary = self.watcher.check()
        self.assertTrue(changed)
        self.assertEqual(summary['groups']['directory']['result'], 'waiting')
        self.assertEqual(self.count('select count(*) from users'), before)

    def test_oversized_packages_are_reported_without_aborting_other_imports(self):
        self.write('citrix.csv', citrix_csv([citrix_device()]))
        self.write('packages.csv', package_csv([('App', 'Live')]) + b' ' * (10 * 1024 * 1024))
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['vdi']['result'], 'applied')
        self.assertEqual(summary['groups']['packages']['result'], 'error')
        self.assertIn('larger than 10 MB', summary['groups']['packages']['message'])

    def test_changing_folders_discards_cached_export_classifications(self):
        data = package_csv([('App', 'Live')])
        citrix = citrix_csv([citrix_device()])
        size = max(len(data), len(citrix)) + 10
        first = self.write('snapshot.csv', citrix + b' ' * (size - len(citrix)))
        self.assertIn('vdi', self.watcher.scan(self.folder))
        other = self.folder.parent / 'other-exports'
        other.mkdir()
        second = other / first.name
        second.write_bytes(data + b' ' * (size - len(data)))
        os.utime(second, ns=(first.stat().st_atime_ns, first.stat().st_mtime_ns))
        self.watcher.configure(Settings(folder=str(other)))
        found = self.watcher.scan(other)
        self.assertIn('packages', found)
        self.assertNotIn('vdi', found)

    def test_a_large_snapshot_waits_for_review_then_later_saves_apply_by_themselves(self):
        before = self.count('select count(*) from users')
        self.directory()
        summary = self.watcher.check()
        self.assertEqual(summary['status']['state'], 'held')
        held = summary['held']
        self.assertEqual(held['files'], ['sys_user.csv', 'alm_asset.csv'])
        self.assertIn('removes', held['reason'])
        self.assertEqual(self.count('select count(*) from users'), before, 'Nothing changes before the review')
        self.assertEqual(self.watcher.check()['held']['id'], held['id'], 'The same files keep the same review')
        with self.assertRaises(HTTPException):
            self.watcher.apply_held('stale')
        self.busy = True
        with self.assertRaises(HTTPException):
            self.watcher.apply_held(held['id'])
        self.busy = False
        # A job that starts between the check and the write still stops the import.
        from backend.database_manager import apply_directory as real_apply
        from backend import database_manager
        def starts_job(*args, **kwargs):
            self.busy = True
            try:
                return real_apply(*args, **kwargs)
            finally:
                self.busy = False
        database_manager.apply_directory = starts_job
        try:
            with self.assertRaises(HTTPException):
                self.watcher.apply_held(held['id'])
        finally:
            database_manager.apply_directory = real_apply
        self.assertEqual(self.count('select count(*) from users'), before)
        held = self.watcher.check()['held']
        summary = self.watcher.apply_held(held['id'])
        self.assertEqual(summary['groups']['directory']['result'], 'applied')
        self.assertEqual(self.count('select count(*) from users'), 2)
        self.assertEqual(self.count('select count(*) from directory_import_history'), 1)
        backup = summary['groups']['directory']['backup']
        self.assertTrue((self.db.parent / 'backups' / backup).is_file(), 'A full backup comes first')
        self.assertEqual(self.watcher.check()['status']['state'], 'synced')
        self.assertEqual(self.count('select count(*) from directory_import_history'), 1, 'Unchanged exports are not imported again')
        # A normal save of the users export (one more person) is applied straight away.
        users = [row[:] for row in self.sheets['users']] + [['u3', 'Third Person', 'third@example.invalid', 'IT', 'Technology', '', '', 'Paris', '', '', 'E003']]
        self.directory(users)
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['directory']['result'], 'applied')
        self.assertIsNone(summary['held'])
        self.assertEqual(self.count('select count(*) from users'), 3)
        self.assertEqual(summary['history'][0]['kind'], 'Users & devices')

    def test_review_can_be_skipped_or_switched_off(self):
        self.directory()
        held = self.watcher.check()['held']
        summary = self.watcher.skip_held(held['id'])
        self.assertIsNone(summary['held'])
        self.assertEqual(summary['groups']['directory']['result'], 'skipped')
        self.assertIsNone(self.watcher.check()['held'], 'A skipped snapshot is not offered again until it is saved again')
        self.watcher.state['review_large'] = False
        self.directory()
        self.assertEqual(self.watcher.check()['groups']['directory']['result'], 'applied')
        self.assertEqual(self.count('select count(*) from users'), 2)

    def test_citrix_and_package_exports_apply_directly_and_bad_files_are_reported_once(self):
        self.write('SingleSessionMachines (1).csv', citrix_csv([citrix_device(), citrix_device('INTRANET\\VDI-002')]))
        self.write('u_cmdb_software_package.csv', package_csv([('App One', 'Live'), ('App Two', 'Work in Progress')]))
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['vdi']['result'], 'applied', summary['groups'])
        self.assertEqual(summary['groups']['packages']['result'], 'applied', summary['groups'])
        self.assertEqual(summary['status']['state'], 'synced')
        self.assertEqual(self.count('select count(*) from vdi_devices'), 2)
        self.assertEqual(self.count('select count(*) from package_data'), 2)
        self.assertEqual(self.count('select count(*) from vdi_imports'), 1)
        self.assertEqual(self.count('select count(*) from package_data_imports'), 1)
        # The newest export of a kind is used; older copies are listed but ignored.
        self.write('SingleSessionMachines.csv', citrix_csv([citrix_device('INTRANET\\VDI-OLD')]), age=600)
        files = {f['name']: f for f in self.watcher.check()['files']}
        self.assertFalse(files['SingleSessionMachines.csv']['used'])
        self.assertTrue(files['SingleSessionMachines (1).csv']['used'])
        self.assertEqual(self.count('select count(*) from vdi_imports'), 1)
        broken = 'name,u_package_sub_state,u_package_sub_state\r\nApp,Live,Live\r\n'
        self.write('u_cmdb_software_package.csv', broken)
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['packages']['result'], 'error')
        self.assertEqual(summary['status']['state'], 'error')
        self.assertEqual(self.count('select count(*) from package_data'), 2, 'A bad file changes nothing')
        self.watcher.check()
        self.assertEqual(sum(h['result'] == 'error' for h in self.watcher.summary()['history']), 1, 'Reported once until saved again')

    def test_waits_for_just_saved_files_running_jobs_and_the_other_directory_export(self):
        self.write('sys_user.csv', csv_text(self.sheets['users']))
        summary = self.watcher.check()
        self.assertEqual(summary['groups']['directory']['result'], 'waiting')
        self.assertIn('devices export', summary['groups']['directory']['message'])
        self.write('alm_asset.csv', csv_text(self.sheets['devices']), age=1)
        self.assertIn('just saved', self.watcher.check()['groups']['directory']['message'])
        self.write('alm_asset.csv', csv_text(self.sheets['devices']))
        self.busy = True
        self.assertIn('Deployments', self.watcher.check()['groups']['directory']['message'])
        self.busy = False
        self.assertEqual(self.watcher.check()['status']['state'], 'held')
        self.write('Notes.xlsx', {'Sheet1': [['Ticket', 'Opened'], ['INC1', 'today']]})
        files = {f['name']: f for f in self.watcher.check()['files']}
        self.assertEqual(files['Notes.xlsx']['kind'], '', 'Other files are listed and left alone')

    def test_missing_folder_settings_and_api(self):
        app = FastAPI()
        tokens = []
        def check_token(request):
            tokens.append(request.headers.get('x-atlas-token'))
            if request.headers.get('x-atlas-token') != 'test':
                raise HTTPException(403, 'Refresh Atlas')
        wmi = SimpleNamespace(MASTER_DB=self.db, REPO=None)
        watcher = register(app, wmi, check_token, lambda: False, Path(self.temp.name) / 'api-state.json')
        client = TestClient(app)
        self.assertEqual(client.post('/api/import-folder/check').status_code, 403)
        missing = str(Path(self.temp.name) / 'nowhere')
        summary = client.post('/api/import-folder/settings', json={'folder': '"' + missing + '"', 'enabled': True, 'review_large': True}, headers={'X-Atlas-Token': 'test'}).json()
        self.assertEqual(summary['folder'], missing)
        self.assertEqual(summary['status']['state'], 'empty')
        self.assertIn('Create', summary['status']['message'])
        summary = client.post('/api/import-folder/settings', json={'folder': str(self.folder), 'enabled': False, 'review_large': True}, headers={'X-Atlas-Token': 'test'}).json()
        self.assertEqual(summary['status']['state'], 'off')
        self.directory()
        self.assertEqual(client.post('/api/import-folder/check', headers={'X-Atlas-Token': 'test'}).json()['held'], None, 'Off reads nothing')
        summary = client.post('/api/import-folder/settings', json={'folder': str(self.folder), 'enabled': True, 'review_large': True}, headers={'X-Atlas-Token': 'test'}).json()
        held = summary['held']
        self.assertTrue(held)
        self.assertEqual(client.post('/api/import-folder/apply', json={'id': held['id']}, headers={'X-Atlas-Token': 'test'}).json()['groups']['directory']['result'], 'applied')
        self.assertEqual(client.get('/api/import-folder').json()['status']['state'], 'synced')
        self.assertEqual(ImportFolder(self.db, Path(self.temp.name) / 'api-state.json').state['folder'], str(self.folder), 'Settings survive a restart')
        watcher.close()


if __name__ == '__main__':
    unittest.main()
