"""Updater regressions use local Git repositories and fictional SQLite data only."""
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import contextmanager


@contextmanager
def database_connection(path):
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


def git(root, *arguments):
    return subprocess.run([shutil.which('git'), '-C', str(root), *arguments],
                          check=True, capture_output=True, text=True).stdout.strip()


def fictional_database(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript('''
            create table metadata(key text primary key,value text);
            create table users(id integer primary key,canonical_key text,user_id text,full_name text);
            create table machines(id integer primary key,machine_name text);
            create table operation_state(id text primary key,kind text,body text,updated real);
            create table operation_guard(target text primary key);
            create table directory_import_history(id text primary key,at text,source text,backup text,report text);
            create table fictional_data(value text not null);
        ''')
        con.execute('insert into metadata values(?,?)', ('generation', marker))
        con.execute('insert into users values(1,?,?,?)', ('uid:fictional', 'FICT001', 'Fictional User'))
        con.execute('insert into machines values(1,?)', ('FICTIONAL-PC',))
        con.execute('insert into fictional_data values(?)', (marker,))
        con.commit()
    finally:
        con.close()


def values(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return [row[0] for row in con.execute('select value from fictional_data order by rowid')]
    finally:
        con.close()


def integrity(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return con.execute('pragma integrity_check').fetchone()[0]
    finally:
        con.close()


class LocalGitFixture(unittest.TestCase):
    """Real local Git operations; no GitHub, package installs or real stop commands."""
    def setUp(self):
        if not shutil.which('git'):
            self.skipTest('git is required for local updater fixtures')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.author = self.parent / 'author'; self.author.mkdir()
        self.upstream = self.parent / 'upstream.git'
        subprocess.run([shutil.which('git'), 'init', '--bare', '--initial-branch=main', str(self.upstream)],
                       check=True, capture_output=True)
        git(self.author, 'init', '--initial-branch=main')
        git(self.author, 'config', 'user.name', 'Fictional Fixture')
        git(self.author, 'config', 'user.email', 'fixture@example.invalid')
        self.write_author('launcher.py', 'import sys\nprint("Fictional launcher", sys.argv[1:])\n')
        self.write_author('backend/main.py', 'VERSION = "old"\n')
        self.write_author('frontend/app.js', 'const release = "old";\n')
        self.write_author('runtime_paths.py', '# fictional runtime marker\n')
        self.write_author('requirements.txt', '# no fixture dependencies\n')
        self.write_author('README.md', 'Fictional Atlas release old\n')
        self.write_author('.gitignore', 'data/\nlogs/\nbackups/\nconfig.json\n.env\n')
        fictional_database(self.author / 'office_atlas.db', 'upstream-old')
        git(self.author, 'add', '.')
        git(self.author, 'commit', '-m', 'Old fictional release')
        self.old_head = git(self.author, 'rev-parse', 'HEAD')
        git(self.author, 'remote', 'add', 'origin', str(self.upstream))
        git(self.author, 'push', '-u', 'origin', 'main')
        self.root = self.parent / 'Atlas'

    def write_author(self, relative, text):
        path = self.author / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def release(self, *, extra=None):
        self.write_author('backend/main.py', 'VERSION = "new"\n')
        self.write_author('frontend/app.js', 'const release = "new";\n')
        self.write_author('README.md', 'Fictional Atlas release new\n')
        if extra:
            for name, text in extra.items():
                self.write_author(name, text)
        git(self.author, 'add', '.')
        git(self.author, 'commit', '-m', 'New fictional release')
        git(self.author, 'push', 'origin', 'main')
        return git(self.author, 'rev-parse', 'HEAD')

    def clone(self):
        subprocess.run([shutil.which('git'), 'clone', str(self.upstream), str(self.root)],
                       check=True, capture_output=True)
        git(self.root, 'config', 'user.name', 'Fictional Fixture')
        git(self.root, 'config', 'user.email', 'fixture@example.invalid')

    def raw_zip(self):
        self.root.mkdir()
        archive = subprocess.run([shutil.which('git'), '-C', str(self.author), 'archive', self.old_head],
                                 check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as members:
            members.extractall(self.root, filter='data')

    def persistent(self, *, database=True):
        (self.root / 'data').mkdir(exist_ok=True)
        (self.root / 'config.json').write_text(json.dumps({'fixture_setting': 'keep me'}), encoding='utf-8')
        (self.root / '.env').write_text('FICTIONAL_SETTING=keep\n', encoding='utf-8')
        (self.root / 'data' / 'selection.json').write_text('{"pc":"FICTIONAL-PC"}', encoding='utf-8')
        if database:
            fictional_database(self.root / 'data' / 'office_atlas.db', 'local-user-data')
        return self.root / 'data' / 'office_atlas.db'

    def manager(self, **overrides):
        from update_atlas import Updater
        quiet = patch('update_atlas.print', create=True)
        quiet.start(); self.addCleanup(quiet.stop)
        self.events = []
        hooks = dict(root=self.root, repository=str(self.upstream), git=shutil.which('git'),
                     python=sys.executable, environment=dict(os.environ, ATLAS_DB_PATH=''),
                     active=lambda: False, stop=lambda: self.events.append('stop'),
                     start=lambda: self.events.append('start'),
                     install=lambda requirements: self.events.append('install'))
        hooks.update(overrides)
        return Updater(**hooks)

    def backup_databases(self, result):
        backup = Path(result['backup'])
        self.assertTrue(backup.is_dir(), str(backup))
        databases = []
        for path in backup.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream:
                    if stream.read(16) == b'SQLite format 3\x00':
                        databases.append(path)
        self.assertTrue(databases, 'update backup must include a consistent SQLite snapshot')
        for path in databases:
            self.assertEqual(integrity(path), 'ok')
        return databases

    def assert_refused(self, manager):
        from update_atlas import UpdateError
        with self.assertRaises(UpdateError):
            manager.update(no_start=True)
        self.assertNotIn('stop', self.events)
        self.assertNotIn('start', self.events)


class UpdateSuccess(LocalGitFixture):
    def test_existing_clone_fast_forwards_and_keeps_local_runtime_configuration(self):
        self.clone(); database = self.persistent(); new_head = self.release()
        (self.root / 'operator-notes.txt').write_text('Untracked operator note', encoding='utf-8')
        result = self.manager().update(no_start=True)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), new_head)
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "new"\n')
        self.assertEqual(values(database), ['local-user-data'])
        self.assertEqual(json.loads((self.root / 'config.json').read_text()), {'fixture_setting': 'keep me'})
        self.assertEqual((self.root / '.env').read_text(), 'FICTIONAL_SETTING=keep\n')
        self.assertEqual((self.root / 'operator-notes.txt').read_text(), 'Untracked operator note')
        self.assertEqual(result['before'], self.old_head)
        self.assertEqual(result['after'], new_head)
        self.assertTrue(result['updated']); self.assertFalse(result['converted']); self.assertFalse(result['started'])
        self.assertEqual(self.events.count('stop'), 1); self.assertNotIn('start', self.events)
        self.assertTrue(any(values(path) == ['local-user-data'] for path in self.backup_databases(result)))

    def test_zip_conversion_keeps_same_root_and_absolute_import_backup_paths(self):
        self.raw_zip(); database = self.persistent(); root_before = self.root.resolve()
        old_backup = self.root / 'backups' / 'absolute-before-import.db'
        fictional_database(old_backup, 'historical-directory-data')
        with database_connection(database) as con:
            con.execute('insert into directory_import_history values(?,?,?,?,?)',
                        ('fictional-import', '2026-10-01', 'fictional.xlsx', str(old_backup.resolve()), '{}'))
        new_head = self.release()
        result = self.manager().update(no_start=True)
        self.assertTrue(result['converted']); self.assertEqual(self.root.resolve(), root_before)
        self.assertTrue((self.root / '.git').is_dir())
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), new_head)
        self.assertEqual(git(self.root, 'remote', 'get-url', 'origin'), str(self.upstream))
        self.assertEqual(values(database), ['local-user-data'])
        with database_connection(database) as con:
            path = Path(con.execute('select backup from directory_import_history').fetchone()[0])
        self.assertEqual(path, old_backup.resolve()); self.assertTrue(path.is_file())
        self.assertEqual(values(path), ['historical-directory-data'])
        self.assertEqual((self.root / 'data/selection.json').read_text(), '{"pc":"FICTIONAL-PC"}')
        self.assertEqual((self.root / '.env').read_text(), 'FICTIONAL_SETTING=keep\n')
        self.backup_databases(result)

    def test_runtime_backup_includes_committed_wal_frames(self):
        self.clone(); database = self.persistent(); self.release()
        writer = sqlite3.connect(database); self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal'); writer.execute('pragma wal_autocheckpoint=0')
        writer.execute('insert into fictional_data values(?)', ('committed-wal-only',)); writer.commit()
        self.assertTrue(Path(str(database) + '-wal').is_file())
        result = self.manager().update(no_start=True)
        expected = ['local-user-data', 'committed-wal-only']
        self.assertEqual(values(database), expected)
        self.assertTrue(any(values(path) == expected for path in self.backup_databases(result)))

    def test_external_database_is_backed_up_without_relocation_or_runtime_replacement(self):
        self.raw_zip(); local = self.persistent(); self.release()
        external = self.parent / 'persistent-external' / 'atlas.db'
        fictional_database(external, 'external-users')
        writer = sqlite3.connect(external); self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal'); writer.execute('pragma wal_autocheckpoint=0')
        writer.execute('insert into fictional_data values(?)', ('external-wal-only',)); writer.commit()
        result = self.manager(environment=dict(os.environ, ATLAS_DB_PATH=str(external))).update(no_start=True)
        expected = ['external-users', 'external-wal-only']
        self.assertEqual(values(external), expected)
        self.assertEqual(values(local), ['local-user-data'])
        self.assertTrue(any(values(path) == expected for path in self.backup_databases(result)))

    def test_edited_legacy_root_seed_migrates_before_incoming_seed_replacement(self):
        self.raw_zip(); self.persistent(database=False)
        with database_connection(self.root / 'office_atlas.db') as con:
            con.execute('insert into fictional_data values(?)', ('operator-imported-users',))
        (self.author / 'office_atlas.db').unlink()
        fictional_database(self.author / 'office_atlas.db', 'new-upstream-seed')
        self.release()
        self.manager().update(no_start=True)
        self.assertEqual(values(self.root / 'data/office_atlas.db'), ['upstream-old', 'operator-imported-users'])
        self.assertEqual(values(self.root / 'office_atlas.db'), ['new-upstream-seed'])

    def test_check_only_finds_new_version_without_stopping_or_changing_clone(self):
        self.clone(); database = self.persistent(); new_head = self.release()
        result = self.manager().update(check=True, no_start=True)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual(values(database), ['local-user-data']); self.assertEqual(self.events, [])
        self.assertEqual(result['before'], self.old_head); self.assertEqual(result['after'], new_head)
        self.assertFalse(result['started'])

    def test_check_only_zip_does_not_install_git_or_move_persistent_data(self):
        self.raw_zip(); database = self.persistent(); self.release()
        self.manager().update(check=True, no_start=True)
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual(values(database), ['local-user-data']); self.assertEqual(self.events, [])

    def test_success_restarts_only_when_requested(self):
        self.clone(); self.persistent(); self.release()
        result = self.manager().update(no_start=False)
        self.assertTrue(result['started'])
        self.assertEqual([event for event in self.events if event in ('stop', 'start')], ['stop', 'start'])

    def test_up_to_date_does_not_stop_install_backup_or_restart(self):
        self.clone(); database = self.persistent()
        result = self.manager().update(no_start=False)
        self.assertFalse(result['updated']); self.assertFalse(result['started']); self.assertIsNone(result['backup'])
        self.assertEqual(self.events, []); self.assertEqual(values(database), ['local-user-data'])

    def test_knowledge_wal_backup_and_runtime_database_are_both_consistent(self):
        self.clone(); database = self.persistent(); self.release()
        knowledge = self.root / 'data/knowledge.sqlite3'; fictional_database(knowledge, 'local-knowledge')
        writer = sqlite3.connect(knowledge); self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal'); writer.execute('pragma wal_autocheckpoint=0')
        writer.execute('insert into fictional_data values(?)', ('knowledge-wal-only',)); writer.commit()
        result = self.manager().update(no_start=True)
        snapshots = self.backup_databases(result)
        self.assertTrue(any(values(path) == ['local-user-data'] for path in snapshots))
        self.assertTrue(any(values(path) == ['local-knowledge', 'knowledge-wal-only'] for path in snapshots))
        self.assertEqual(values(knowledge), ['local-knowledge', 'knowledge-wal-only'])
        self.assertEqual(values(database), ['local-user-data'])


class UpdateRefusals(LocalGitFixture):
    def refuse_default_runtime_alias(self, link):
        self.raw_zip(); runtime = self.persistent(database=False)
        seed = self.root / 'office_atlas.db'
        with database_connection(seed) as con:
            con.execute('insert into fictional_data values(?)', ('operator-root-data',))
        try:
            link(seed, runtime)
        except OSError as error:
            self.skipTest('This platform does not allow the fixture link: ' + str(error))
        (self.author / 'office_atlas.db').unlink()
        fictional_database(self.author / 'office_atlas.db', 'incoming-replacement-seed')
        self.release()
        self.assert_refused(self.manager())
        self.assertEqual(values(seed), ['upstream-old', 'operator-root-data'])
        self.assertEqual(values(runtime), ['upstream-old', 'operator-root-data'])
        self.assertFalse((self.root / '.git').exists())

    def test_default_runtime_symlink_to_tracked_seed_is_refused_before_overwrite(self):
        self.refuse_default_runtime_alias(os.symlink)

    def test_default_runtime_hardlink_to_tracked_seed_is_refused_before_overwrite(self):
        self.refuse_default_runtime_alias(os.link)

    def server_record(self, *, mode='admin', root=None, port=23300):
        filename = 'server.json' if mode == 'admin' else 'viewer-server.json'
        path = self.root / 'data' / filename
        path.write_text(json.dumps({'root': str(root or self.root), 'port': port,
                                    'instance_id': 'fictional-instance', 'pid': 1234}), encoding='utf-8')
        return path

    def fake_http(self, actions, *, health=None):
        calls = []
        def open_response(url, **kwargs):
            calls.append(url)
            payload = (health if health is not None else {'application': 'Office Atlas', 'mode': 'admin',
                                                         'instance_id': 'fictional-instance'}) if url.endswith('/api/health') else actions
            return io.BytesIO(json.dumps(payload).encode())
        return SimpleNamespace(open=open_response), calls

    def test_configured_database_overlapping_seed_or_code_is_refused_before_stop(self):
        self.raw_zip(); database = self.persistent(); self.release()
        for relative in ('office_atlas.db', 'frontend/app.js'):
            with self.subTest(relative=relative):
                overlap = self.root / relative; before = overlap.read_bytes()
                self.assert_refused(self.manager(environment=dict(os.environ, ATLAS_DB_PATH=str(overlap))))
                self.assertEqual(overlap.read_bytes(), before)
                self.assertEqual(values(database), ['local-user-data'])
                self.assertFalse((self.root / '.git').exists())

    def test_owned_admin_activity_aggregate_blocks_update_without_real_http(self):
        self.clone(); self.persistent(); self.release(); record = self.server_record()
        opener, calls = self.fake_http({'count': 1})
        with patch('update_atlas.urllib.request.build_opener', return_value=opener):
            self.assert_refused(self.manager(active=None))
        self.assertEqual(calls, ['http://127.0.0.1:23300/api/health', 'http://127.0.0.1:23300/api/actions'])
        self.assertTrue(record.exists()); self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_boolean_or_malformed_activity_counts_cannot_claim_no_active_jobs(self):
        self.clone(); self.persistent(); self.release(); self.server_record()
        for actions in ({'count': False}, {'count': True}, {'count': -1}, {'count': '0'}, []):
            with self.subTest(actions=actions):
                opener, _ = self.fake_http(actions)
                with patch('update_atlas.urllib.request.build_opener', return_value=opener):
                    self.assert_refused(self.manager(active=None))
                self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_changed_admin_identity_is_not_stopped(self):
        self.clone(); self.persistent(); self.release(); record = self.server_record()
        opener, calls = self.fake_http({'count': 0}, health={'application': 'Office Atlas', 'mode': 'admin', 'instance_id': 'stale-instance'})
        with patch('update_atlas.urllib.request.build_opener', return_value=opener):
            self.assert_refused(self.manager(active=None))
        self.assertEqual(calls, ['http://127.0.0.1:23300/api/health']); self.assertTrue(record.exists())

    def test_foreign_viewer_record_blocks_before_admin_http_or_stop(self):
        self.clone(); self.persistent(); self.release()
        foreign = self.server_record(mode='viewer', root=self.parent / 'another-installation')
        with patch('update_atlas.urllib.request.build_opener', side_effect=AssertionError('No real or foreign HTTP request allowed')):
            self.assert_refused(self.manager(active=None))
        self.assertTrue(foreign.exists()); self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_success_preserves_owned_custom_ports_after_stop_deletes_server_records(self):
        self.clone(); self.persistent(); self.release()
        admin = self.server_record(port=23300); viewer = self.server_record(mode='viewer', port=23301)
        opener, _ = self.fake_http({'count': 0})
        def stop():
            self.events.append('stop'); admin.unlink(); viewer.unlink()
        def start():
            self.events.append('start')
            self.assertEqual(manager.environment['ATLAS_ADMIN_PORT'], '23300')
            self.assertEqual(manager.environment['ATLAS_VIEWER_PORT'], '23301')
        manager = self.manager(active=None, stop=stop, start=start)
        with patch('update_atlas.urllib.request.build_opener', return_value=opener):
            result = manager.update(no_start=False)
        self.assertTrue(result['started']); self.assertEqual(self.events, ['stop', 'start'])

    def test_dirty_tracked_source_is_not_overwritten_or_stopped(self):
        self.clone(); database = self.persistent(); self.release()
        path = self.root / 'frontend/app.js'; path.write_text('local operator change\n')
        self.assert_refused(self.manager())
        self.assertEqual(path.read_text(), 'local operator change\n')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual(values(database), ['local-user-data'])

    def test_diverged_clone_is_not_reset_or_stopped(self):
        self.clone(); self.persistent()
        (self.root / 'frontend/app.js').write_text('locally committed feature\n')
        git(self.root, 'add', 'frontend/app.js'); git(self.root, 'commit', '-m', 'Local feature')
        local_head = git(self.root, 'rev-parse', 'HEAD'); self.release()
        self.assert_refused(self.manager())
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), local_head)
        self.assertEqual((self.root / 'frontend/app.js').read_text(), 'locally committed feature\n')

    def test_untracked_file_collision_is_not_deleted_or_stopped(self):
        self.clone(); self.persistent()
        collision = self.root / 'backend/new-tool.py'; collision.write_text('operator script\n')
        self.release(extra={'backend/new-tool.py': 'upstream script\n'})
        self.assert_refused(self.manager())
        self.assertEqual(collision.read_text(), 'operator script\n')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_non_main_branch_is_not_switched_or_stopped(self):
        self.clone(); self.persistent(); git(self.root, 'checkout', '-b', 'operator-work'); self.release()
        self.assert_refused(self.manager())
        self.assertEqual(git(self.root, 'branch', '--show-current'), 'operator-work')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_changed_remote_is_not_trusted_or_stopped(self):
        self.clone(); self.persistent(); self.release()
        other = self.parent / 'other-upstream.git'
        subprocess.run([shutil.which('git'), 'init', '--bare', str(other)], check=True, capture_output=True)
        git(self.root, 'remote', 'set-url', 'origin', str(other))
        self.assert_refused(self.manager())
        self.assertEqual(git(self.root, 'remote', 'get-url', 'origin'), str(other))
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)

    def test_active_jobs_block_before_stop_and_leave_data_usable(self):
        self.raw_zip(); database = self.persistent(); self.release()
        with database_connection(database) as con:
            con.execute('insert into operation_state values(?,?,?,?)', ('fictional-job', 'job', '{"state":"running"}', 1))
        def active():
            with database_connection(database) as con:
                return any(json.loads(body).get('state') == 'running' for body, in con.execute('select body from operation_state'))
        self.assert_refused(self.manager(active=active))
        self.assertFalse((self.root / '.git').exists()); self.assertEqual(values(database), ['local-user-data'])
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')

    def test_existing_update_lock_is_not_removed_by_refused_second_updater(self):
        self.clone(); self.persistent(); self.release()
        lock = self.root / 'data/atlas-update.lock'; lock.write_text('existing fictional updater\n')
        self.assert_refused(self.manager())
        self.assertEqual(lock.read_text(), 'existing fictional updater\n')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)


class UpdateFailures(LocalGitFixture):
    def test_completed_git_move_followed_by_interrupt_removes_created_metadata_and_restores_code(self):
        from update_atlas import UpdateError
        self.raw_zip(); database = self.persistent(); self.release()
        manager = self.manager(); original = os.replace; interrupted = []
        def move_then_cancel(source, destination):
            result = original(source, destination)
            if Path(destination) == self.root / '.git' and not interrupted:
                interrupted.append(True)
                self.assertTrue((self.root / '.git').is_dir())
                self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "new"\n')
                raise KeyboardInterrupt('Fictional cancellation just after Git move')
            return result
        with patch('update_atlas.os.replace', side_effect=move_then_cancel):
            with self.assertRaises(UpdateError):
                manager.update(no_start=True)
        self.assertTrue(interrupted); self.assertFalse((self.root / '.git').exists())
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual((self.root / 'frontend/app.js').read_text(), 'const release = "old";\n')
        self.assertEqual(values(database), ['local-user-data']); self.assertNotIn('start', self.events)

    def test_git_metadata_install_failure_restores_copied_code_and_runtime_data(self):
        from update_atlas import UpdateError
        self.raw_zip(); database = self.persistent(); self.release()
        manager = self.manager(); original = os.replace; attempts = []
        def deny_git_move(source, destination):
            if Path(destination) == self.root / '.git':
                attempts.append(str(source))
                self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "new"\n')
                raise OSError('Fictional Git metadata move refusal')
            return original(source, destination)
        with patch('update_atlas.os.replace', side_effect=deny_git_move):
            with self.assertRaises(UpdateError):
                manager.update(no_start=True)
        self.assertEqual(len(attempts), 1)
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual((self.root / 'frontend/app.js').read_text(), 'const release = "old";\n')
        self.assertEqual(values(database), ['local-user-data']); self.assertNotIn('start', self.events)

    def test_keyboard_interrupt_after_partial_apply_restores_old_code(self):
        from update_atlas import UpdateError
        self.raw_zip(); database = self.persistent(); self.release()
        manager = self.manager(); original = manager._copy_code; interrupted = []
        def cancel(source, destination):
            result = original(source, destination)
            if Path(destination) == self.root / 'backend/main.py' and not interrupted:
                interrupted.append(True)
                raise KeyboardInterrupt('Fictional operator cancellation')
            return result
        with patch.object(manager, '_copy_code', side_effect=cancel):
            with self.assertRaises(UpdateError):
                manager.update(no_start=True)
        self.assertTrue(interrupted)
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual(values(database), ['local-user-data']); self.assertNotIn('start', self.events)

    def test_fetch_failure_keeps_code_data_and_configuration_without_stopping(self):
        from update_atlas import UpdateError
        self.clone(); database = self.persistent(); self.release(); manager = self.manager()
        original = manager.git_run
        def offline(*arguments, **kwargs):
            if arguments and arguments[0] == 'fetch':
                raise UpdateError('Fictional local fetch failure')
            return original(*arguments, **kwargs)
        with patch.object(manager, 'git_run', offline):
            self.assert_refused(manager)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual(values(database), ['local-user-data'])
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['fixture_setting'], 'keep me')

    def test_zip_clone_failure_keeps_installation_and_has_no_git_metadata(self):
        self.raw_zip(); database = self.persistent()
        self.assert_refused(self.manager(repository=str(self.parent / 'missing-local-upstream.git')))
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual(values(database), ['local-user-data'])

    def test_partial_stop_failure_blocks_code_changes_and_does_not_restart(self):
        from update_atlas import UpdateError
        self.clone(); database = self.persistent(); self.release()
        viewer = self.root / 'data/viewer-server.json'; viewer.write_text('{"fixture":true}')
        admin = self.root / 'data/server.json'; admin.write_text('{"fixture":true}')
        def failed_stop():
            self.events.append('stop'); viewer.unlink()
            raise UpdateError('Fictional administrator stop refusal')
        manager = self.manager(stop=failed_stop)
        with self.assertRaises(UpdateError):
            manager.update(no_start=True)
        self.assertFalse(viewer.exists()); self.assertTrue(admin.exists())
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual(values(database), ['local-user-data']); self.assertNotIn('start', self.events)

    def test_partial_zip_code_copy_failure_rolls_back_code_and_keeps_stopped_records_absent(self):
        from update_atlas import UpdateError
        self.raw_zip(); database = self.persistent(); self.release(extra={'a-new.py': '# new fictional tool\n'})
        server = self.root / 'data/server.json'; server.write_text('{"fixture":true}')
        old_code = {name: (self.root / name).read_bytes() for name in ('backend/main.py', 'frontend/app.js', 'README.md')}
        def stop():
            self.events.append('stop'); server.unlink()
        manager = self.manager(stop=stop); original = manager._copy_code; failures = []
        def fault(source, destination):
            result = original(source, destination)
            if Path(destination) == self.root / 'backend/main.py' and not failures:
                failures.append(str(destination))
                self.assertEqual(Path(destination).read_text(), 'VERSION = "new"\n')
                raise OSError('Fictional partial code copy failure')
            return result
        with patch.object(manager, '_copy_code', fault):
            with self.assertRaises(UpdateError):
                manager.update(no_start=True)
        self.assertTrue(failures, 'fixture must reach the source-apply boundary')
        for name, before in old_code.items():
            self.assertEqual((self.root / name).read_bytes(), before, name)
        self.assertFalse((self.root / '.git').exists()); self.assertFalse(server.exists())
        self.assertFalse((self.root / 'a-new.py').exists(), 'rollback must remove newly copied upstream files')
        self.assertEqual(values(database), ['local-user-data'])
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['fixture_setting'], 'keep me')
        self.assertNotIn('start', self.events)

    def test_dependency_failure_restores_clone_head_and_source_but_leaves_servers_stopped(self):
        from update_atlas import UpdateError
        self.clone(); database = self.persistent()
        self.release(extra={'requirements.txt': '# changed fictional dependencies\n'})
        server = self.root / 'data/server.json'; server.write_text('{"fixture":true}')
        def stop():
            self.events.append('stop'); server.unlink()
        def install(requirements):
            self.events.append('install')
            raise UpdateError('Fictional dependency installation failure')
        manager = self.manager(stop=stop, install=install)
        with self.assertRaises(UpdateError):
            manager.update(no_start=False)
        self.assertIn('install', self.events)
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual((self.root / 'backend/main.py').read_text(), 'VERSION = "old"\n')
        self.assertEqual(values(database), ['local-user-data']); self.assertFalse(server.exists())
        self.assertNotIn('start', self.events)


class OwnedGitCleanup(unittest.TestCase):
    def test_readonly_owned_git_cleanup_makes_file_writable_then_retries_failed_operation(self):
        from update_atlas import remove_created_git
        with tempfile.TemporaryDirectory() as temporary:
            owned = Path(temporary) / '.git'; owned.mkdir()
            object_file = owned / 'fictional-object'; object_file.write_bytes(b'fictional Git object')
            attempts = []
            def failed_operation(filename):
                attempts.append(filename)
            def failed_rmtree(path, *, onexc):
                self.assertEqual(Path(path), owned)
                onexc(failed_operation, str(object_file), PermissionError('Fictional read-only Git object'))
            expected_mode = object_file.stat().st_mode | stat.S_IWRITE
            with patch('update_atlas.shutil.rmtree', side_effect=failed_rmtree), patch('update_atlas.os.chmod') as chmod:
                remove_created_git(owned)
            chmod.assert_called_once_with(str(object_file), expected_mode)
            self.assertEqual(attempts, [str(object_file)])
            self.assertEqual(object_file.read_bytes(), b'fictional Git object')


class AAUpdateBoundary(unittest.TestCase):
    def test_atlas_updater_refuses_aa_before_any_external_action(self):
        from update_atlas import Updater, UpdateError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'aa_launcher.py').write_text('# AA', encoding='utf-8')
            manager = Updater(root)
            with patch.object(manager, 'run', side_effect=AssertionError('No commands allowed')):
                for check in (True, False):
                    with self.assertRaisesRegex(UpdateError, 'AOSPAndroid/AA'):
                        manager.update(check=check)
            self.assertEqual([p.name for p in root.iterdir()], ['aa_launcher.py'])


if __name__ == '__main__':
    unittest.main()
