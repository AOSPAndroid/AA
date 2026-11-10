"""Stopped workspace snapshots preserve SQLite WAL data and reject unsafe restores."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from runtime_workspace import export,restore
from runtime_paths import paths


class Workspace(unittest.TestCase):
    def test_paths_and_export_restore_cover_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'runtime';root.mkdir()
            with patch.dict(os.environ,{'AA_DATA_HOME':str(root)},clear=True):
                self.assertEqual(paths().database,root/'office_atlas.db')
                self.assertEqual(paths().axis,root/'axis')
            database=sqlite3.connect(root/'office_atlas.db')
            try:
                database.execute('pragma journal_mode=wal');database.execute('create table evidence(value text)')
                database.execute("insert into evidence values('retained')");database.commit()
                (root/'axis/chats').mkdir(parents=True);(root/'axis/chats/example.json').write_text('{"messages":[]}')
                archive=base/'workspace.zip';export(root,archive);restore(archive,base/'restored')
                with sqlite3.connect(base/'restored/office_atlas.db') as copy:
                    self.assertEqual(copy.execute('select value from evidence').fetchone()[0],'retained')
                self.assertTrue((base/'restored/axis/chats/example.json').is_file())
            finally:database.close()

    def test_external_database_override_is_included_as_the_main_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);runtime=base/'runtime';runtime.mkdir();external=base/'external.db'
            with sqlite3.connect(external) as con:con.execute('create table retained(value text)')
            archive=base/'backup.zip';export(runtime,archive,external);restore(archive,base/'restored')
            with sqlite3.connect(base/'restored/office_atlas.db') as con:
                self.assertIsNotNone(con.execute("select name from sqlite_master where name='retained'").fetchone())

    def test_source_seed_cannot_be_selected_as_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('runtime_paths.ROOT',root),patch.dict(os.environ,{'ATLAS_DB_PATH':str(root/'office_atlas.db')},clear=True):
                with self.assertRaisesRegex(ValueError,'seed is read-only'):paths()

    def test_viewer_sharing_requires_explicit_opt_in(self):
        import launcher
        with tempfile.TemporaryDirectory() as tmp,patch.object(launcher,'ROOT',Path(tmp)),patch.dict(os.environ,{},clear=True):
            self.assertEqual(launcher.servers()[1]['host'],'127.0.0.1')
            (Path(tmp)/'config.json').write_text('{"share_viewer":true}')
            self.assertEqual(launcher.servers()[1]['host'],'0.0.0.0')
            with patch.dict(os.environ,{'AA_SHARE_VIEWER':'0'}):
                self.assertEqual(launcher.servers()[1]['host'],'127.0.0.1')

    def test_active_records_and_unsafe_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime';root.mkdir();(root/'server.json').write_text('{}')
            with self.assertRaises(ValueError):export(root,Path(tmp)/'backup.zip')
            for name in ('../escape','/absolute','C:/outside','x\\outside'):
                archive=Path(tmp)/'bad.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('AA-WORKSPACE.json',json.dumps({'format':1}));z.writestr(name,'bad')
                with self.assertRaises(ValueError):restore(archive,Path(tmp)/'target')
                self.assertFalse((Path(tmp)/'target').exists())
