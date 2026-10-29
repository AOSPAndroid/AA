import contextlib, io, json, os, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from backend.directory import move_databases
from backend import runtime_paths
from backend.launch import update_atlas


def make_db(path, rows, wal=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    if wal:
        db.execute('pragma journal_mode=wal')
    db.execute('create table items(id integer primary key, name text)')
    db.executemany('insert into items(name) values(?)', [(f'row {n}',) for n in range(rows)])
    db.commit()
    return db


class MoveDatabases(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'Atlas'; self.dest = Path(tmp.name) / 'F' / 'Atlas' / 'DB'
        (self.root / 'office_atlas.db').parent.mkdir(parents=True)
        make_db(self.root / 'office_atlas.db', 1).close()  # tracked seed
        self.main = make_db(self.root / 'data' / 'office_atlas.db', 25, wal=True)
        self.addCleanup(self.main.close)
        make_db(self.root / 'data' / 'knowledge.sqlite3', 3).close()
        for target, value in ((runtime_paths, 'ROOT'), (move_databases.runtime_paths, 'ROOT')):
            p = patch.object(target, value, self.root); p.start(); self.addCleanup(p.stop)
        env = patch.dict(os.environ, {}, clear=False); env.start(); self.addCleanup(env.stop)
        os.environ.pop('ATLAS_DB_PATH', None)
        stopped = patch.object(move_databases, 'atlas_running', return_value=[]); stopped.start(); self.addCleanup(stopped.stop)

    def run_move(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = move_databases.move(self.dest, self.root)
        return result, out.getvalue()

    def count(self, path):
        with contextlib.closing(sqlite3.connect(path)) as db:
            return db.execute('select count(*) from items').fetchone()[0]

    def test_moves_both_databases_and_switches_atlas(self):
        self.assertTrue(Path(str(self.root / 'data' / 'office_atlas.db') + '-wal').exists())
        self.main.close()  # as after Stop-All-Atlas.bat
        copied, output = self.run_move()
        self.assertEqual(sorted(p.name for p in copied), ['knowledge.sqlite3', 'office_atlas.db'])
        self.assertEqual(self.count(self.dest / 'office_atlas.db'), 25)
        self.assertEqual(self.count(self.dest / 'knowledge.sqlite3'), 3)
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['database_folder'], str(self.dest))
        self.assertEqual(runtime_paths.database_path(), self.dest / 'office_atlas.db')
        self.assertEqual(runtime_paths.knowledge_path(), self.dest / 'knowledge.sqlite3')
        self.assertEqual(runtime_paths.prepare_runtime_database(), self.dest / 'office_atlas.db')
        self.assertFalse((self.root / 'data' / 'office_atlas.db').exists())
        archived = list((self.root / 'data' / 'backups').glob('before-database-move-*/office_atlas.db'))
        self.assertEqual(len(archived), 1)
        self.assertTrue((self.root / 'office_atlas.db').exists(), 'The tracked seed stays in place')
        self.assertIn('Start Atlas again', output)
        # A second run is a no-op.
        self.assertEqual(self.run_move()[0], [])

    def test_keeps_other_settings(self):
        (self.root / 'config.json').write_text(json.dumps({'package_repository': r'\\share\pkgs', 'deployment_timeout_seconds': 900}))
        self.main.close(); self.run_move()
        config = json.loads((self.root / 'config.json').read_text())
        self.assertEqual(config['package_repository'], r'\\share\pkgs'); self.assertEqual(config['deployment_timeout_seconds'], 900)

    def test_refuses_while_atlas_runs_and_never_overwrites(self):
        with patch.object(move_databases, 'atlas_running', return_value=['admin']):
            with self.assertRaisesRegex(move_databases.MoveError, 'Stop-All-Atlas'):
                move_databases.move(self.dest, self.root)
        self.dest.mkdir(parents=True); (self.dest / 'office_atlas.db').write_text('keep me')
        with self.assertRaisesRegex(move_databases.MoveError, 'not overwritten'):
            move_databases.move(self.dest, self.root)
        self.assertEqual((self.dest / 'office_atlas.db').read_text(), 'keep me')
        self.assertFalse((self.root / 'config.json').exists())
        self.assertTrue((self.root / 'data' / 'office_atlas.db').exists())

    def test_failed_copy_changes_nothing(self):
        self.main.close()
        with patch.object(move_databases, 'row_counts', side_effect=[{'items': 25}, {'items': 24}]):
            with self.assertRaisesRegex(move_databases.MoveError, 'does not match'), contextlib.redirect_stdout(io.StringIO()):
                move_databases.move(self.dest, self.root)
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertFalse((self.root / 'config.json').exists())
        self.assertTrue((self.root / 'data' / 'office_atlas.db').exists())

    def test_missing_folder_is_reported_instead_of_opening_the_seed(self):
        (self.root / 'config.json').write_text(json.dumps({'database_folder': str(self.dest)}))
        self.assertEqual(runtime_paths.database_path(), self.dest / 'office_atlas.db')
        with self.assertRaisesRegex(ValueError, 'drive is connected'):
            runtime_paths.prepare_runtime_database()

    def test_updater_backs_up_from_the_configured_folder(self):
        self.main.close(); self.run_move()
        updater = update_atlas.Updater.__new__(update_atlas.Updater)
        updater.root, updater.environment = self.root, {}
        self.assertEqual(updater._database(), self.dest / 'office_atlas.db')
        self.assertEqual(updater._database_folder(), self.dest)

    def test_config_failure_keeps_sources_and_removes_copies(self):
        self.main.close()
        with patch.object(move_databases, 'save_folder', side_effect=OSError('write failed')):
            with self.assertRaises(OSError): self.run_move()
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertTrue((self.root / 'data' / 'office_atlas.db').exists())

    def test_missing_primary_cannot_rename_knowledge_database(self):
        with patch.object(runtime_paths, 'database_path', return_value=self.root / 'missing.db'):
            with self.assertRaisesRegex(move_databases.MoveError, 'main Atlas database'): self.run_move()
        self.assertFalse(self.dest.exists())

    def test_unreadable_server_record_fails_closed(self):
        # Bypass the fixture's stopped-server stub to exercise the real check.
        with patch.object(move_databases.launcher, 'read_record', side_effect=ValueError('invalid')):
            with self.assertRaisesRegex(move_databases.MoveError, 'server records'):
                ORIGINAL_RUNNING_CHECK()

ORIGINAL_RUNNING_CHECK = move_databases.atlas_running


if __name__ == '__main__':
    unittest.main()
