"""Update Windows Atlas in place, keeping runtime databases and configuration."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

REPOSITORY = 'https://github.com/AOSPAndroid/Atlas.git'
BRANCH = 'main'
BOOTSTRAP = {'Update-Atlas.bat', 'update_atlas.py'}
PROTECTED = {'data', 'backups', 'logs', 'config.json', '.git', '.env', '.venv', 'venv', 'models', 'node_modules'}


class UpdateError(RuntimeError):
    pass


def remove_created_git(path):
    def retry(function, filename, error):
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(filename, Path(filename).stat().st_mode | stat.S_IWRITE)
        function(filename)
    shutil.rmtree(path, onexc=retry)


def reparse(path):
    """Include Windows directory junctions, which are not always symlinks."""
    try:
        info = path.lstat()
        return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


class Updater:
    def __init__(self, root, *, repository=REPOSITORY, git='git', python=sys.executable,
                 environment=None, active=None, stop=None, start=None, install=None):
        self.root = Path(root).absolute()
        self.repository = repository
        self.git = git
        self.python = python
        self.environment = dict(os.environ if environment is None else environment)
        self.active = active or self._active
        self.stop = stop or (lambda: self._launch('stop'))
        self.start = start or (lambda: self._launch('run', '--no-browser'))
        self.install = install or self._install

    def run(self, command, *, cwd=None, capture=True):
        try:
            result = subprocess.run(command, cwd=cwd or self.root, env=self.environment,
                                    capture_output=capture, text=True, encoding='utf-8', errors='replace',
                                    timeout=600)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpdateError('Command could not finish: ' + str(error)) from error
        if result.returncode:
            detail = (result.stderr or result.stdout or '').strip() if capture else ''
            raise UpdateError(detail or 'Command failed with exit code ' + str(result.returncode))
        return result.stdout or ''

    def git_run(self, *args, cwd=None):
        return self.run([self.git, *args], cwd=cwd)

    def _launch(self, *args):
        self.run([self.python, str(self.root / 'launcher.py'), *args], capture=False)

    def _install(self, requirements):
        self.run([self.python, '-m', 'pip', 'install', '-r', str(requirements)], capture=False)

    def _path(self, relative):
        parts = PurePosixPath(relative).parts
        if not parts or PurePosixPath(relative).is_absolute() or any(p in ('..', '.') or ':' in p or '\\' in p for p in parts):
            raise UpdateError('Unsafe update path: ' + relative)
        first = parts[0].casefold()
        if first in PROTECTED or first.startswith('.env.'):
            raise UpdateError('Update would replace a protected runtime path: ' + relative)
        path = self.root.joinpath(*parts)
        for ancestor in [path, *path.parents]:
            if ancestor == self.root.parent:
                break
            if reparse(ancestor):
                raise UpdateError('Update path uses a symlink or junction: ' + relative)
        return path

    def _paths(self, ref, *, cwd=None):
        paths = self.git_run('ls-tree', '-rz', '--name-only', ref, cwd=cwd).rstrip('\0').split('\0')
        result = [p for p in paths if p]
        if len({p.casefold() for p in result}) != len(result):
            raise UpdateError('Update contains colliding Windows filenames.')
        for path in result:
            self._path(path)
        modes = self.git_run('ls-tree', '-rz', ref, cwd=cwd).split('\0')
        if any(row.startswith(('120000 ', '160000 ')) for row in modes):
            raise UpdateError('Update contains unsupported symlinks or submodules.')
        return result

    @staticmethod
    def _remote(value):
        remote = value.strip().replace('git@github.com:', 'https://github.com/').rstrip('/').removesuffix('.git').casefold()
        # GitHub renamed this repository. Accept existing installs, but fetch
        # the canonical repository explicitly rather than relying on redirects.
        if remote == 'https://github.com/aospandroid/batlas':
            return 'https://github.com/aospandroid/atlas'
        return remote

    def _database_folder(self):
        # Mirrors runtime_paths.database_folder; kept inline because an update replaces that file.
        try:
            folder = json.loads((self.root / 'config.json').read_text(encoding='utf-8')).get('database_folder')
        except (OSError, ValueError, AttributeError):
            return None
        return Path(folder).expanduser() if isinstance(folder, str) and folder.strip() else None

    def _database(self):
        configured = self.environment.get('ATLAS_DB_PATH')
        folder = None if configured else self._database_folder()
        if folder:
            return folder / 'office_atlas.db'
        path = Path(configured).expanduser() if configured else self.root / 'data' / 'office_atlas.db'
        if not path.is_absolute():
            path = self.root / path
        if configured and not path.is_file():
            raise UpdateError('ATLAS_DB_PATH must point to an existing database.')
        if not configured and not path.exists():
            path = self.root / 'office_atlas.db'
        return path

    @staticmethod
    def _sqlite_backup(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 60
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise UpdateError('Database backup timed out; application files were not changed.')
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)) as original:
            with closing(sqlite3.connect(target, timeout=20)) as snapshot:
                original.backup(snapshot, pages=1024, progress=progress)
                if snapshot.execute('pragma integrity_check').fetchone()[0] != 'ok':
                    raise UpdateError('Database backup failed its integrity check.')

    def _active(self):
        record_path = self.root / 'data' / 'server.json'
        try:
            for mode, filename in [('admin', 'server.json'), ('viewer', 'viewer-server.json')]:
                path = self.root / 'data' / filename
                if not path.exists():
                    continue
                record = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(record, dict) or not isinstance(record.get('root'), str) or Path(record['root']).resolve() != self.root.resolve():
                    raise UpdateError('Server record belongs to another Atlas folder. Stop that installation first.')
                port = int(record['port'])
                if not 1024 <= port <= 65535:
                    raise ValueError('Invalid server port')
                self.environment['ATLAS_ADMIN_PORT' if mode == 'admin' else 'ATLAS_VIEWER_PORT'] = str(port)
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise UpdateError('Could not verify server records. Run Stop-All-Atlas.bat, then retry.') from error
        # Without an owned Admin record there is no Admin started by this installation.
        if not record_path.exists():
            return False
        try:
            record = json.loads(record_path.read_text(encoding='utf-8'))
            if Path(record['root']).resolve() != self.root.resolve():
                raise UpdateError('Server record belongs to another Atlas folder. Stop that installation first.')
            port = int(record['port'])
            if not 1024 <= port <= 65535:
                raise ValueError('Invalid Admin port')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
                health = json.load(response)
            if not isinstance(health, dict) or health.get('mode') != 'admin' or health.get('instance_id') != record['instance_id'] or health.get('application') != 'Office Atlas':
                raise UpdateError('Admin identity changed; no server was stopped.')
            with opener.open(f'http://127.0.0.1:{port}/api/actions', timeout=3) as response:
                activity = json.load(response)
            if not isinstance(activity, dict) or type(activity.get('count')) is not int or activity['count'] < 0:
                raise ValueError('Invalid activity status')
            return activity['count'] > 0
        except UpdateError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise UpdateError('Could not verify Atlas activity. Finish jobs, run Stop-All-Atlas.bat, then retry.') from error

    @contextmanager
    def _lock(self):
        data = self.root / 'data'
        if reparse(data):
            raise UpdateError('Atlas data directory must not be a symlink or junction.')
        data.mkdir(exist_ok=True)
        lock = data / 'atlas-update.lock'
        try:
            handle = lock.open('x', encoding='utf-8')
        except FileExistsError as error:
            raise UpdateError('Another update is running. If it was interrupted, close it before removing data/atlas-update.lock.') from error
        try:
            with handle:
                handle.write(str(os.getpid()))
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _snapshot(self, paths):
        backup = self.root / 'data' / 'backups' / ('atlas-update-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        if reparse(backup.parent):
            raise UpdateError('Backup directory must not be a symlink or junction.')
        backup.mkdir(parents=True)
        manifest = {}
        for relative in paths:
            source = self._path(relative)
            manifest[relative] = source.is_file()
            if source.exists() and not source.is_file():
                raise UpdateError('Code path is occupied by a directory: ' + relative)
            if source.is_file():
                target = backup / 'code' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        database = self._database()
        if database.is_file():
            self._sqlite_backup(database, backup / 'database.sqlite3')
            # Legacy installs used the tracked root seed as their live database.
            if not self.environment.get('ATLAS_DB_PATH') and database == self.root / 'office_atlas.db':
                runtime = self.root / 'data' / 'office_atlas.db'
                if not runtime.exists():
                    shutil.copy2(backup / 'database.sqlite3', runtime)
        knowledge = (self._database_folder() or self.root / 'data') / 'knowledge.sqlite3'
        if knowledge.is_file():
            self._sqlite_backup(knowledge, backup / 'knowledge.sqlite3')
        config = self.root / 'config.json'
        if config.is_file():
            shutil.copy2(config, backup / 'config.json')
        (backup / 'manifest.json').write_text(json.dumps({'files': manifest, 'database': str(database)}, indent=2), encoding='utf-8')
        return backup, manifest

    @staticmethod
    def _copy_code(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _restore(self, backup, manifest):
        for relative, existed in manifest.items():
            destination = self._path(relative)
            if existed:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / 'code' / relative, destination)
            else:
                destination.unlink(missing_ok=True)

    def _bootstrap_collisions(self, before_paths, after_paths, after):
        bootstrap = []
        for relative in set(after_paths) - set(before_paths):
            path = self._path(relative)
            if not path.exists():
                continue
            if relative in BOOTSTRAP and path.is_file():
                expected = self.git_run('show', after + ':' + relative).replace('\r\n', '\n')
                if path.read_text(encoding='utf-8').replace('\r\n', '\n') == expected:
                    bootstrap.append(path)
                    continue
            raise UpdateError('An untracked file would be replaced: ' + relative + '. Keep it separately before retrying.')
        return bootstrap

    def update(self, *, check=False, no_start=False):
        if (self.root / 'Start AA.bat').is_file():
            raise UpdateError('This is AA. Use https://github.com/AOSPAndroid/AA/releases/download/aa-windows/aa-windows.zip '
                              'and the AA README update instructions. The Atlas updater cannot update AA.')
        if not (self.root / 'launcher.py').is_file():
            raise UpdateError('Run the updater from an Atlas installation folder.')
        if shutil.which(self.git) is None:
            raise UpdateError('Git for Windows is required. Install your approved Git client, then run Update-Atlas.bat again.')
        with self._lock():
            converted = not (self.root / '.git').exists()
            if converted:
                temp = tempfile.TemporaryDirectory(prefix='atlas-source-', dir=self.root / 'data')
                staged = Path(temp.name) / 'checkout'
            else:
                temp = None
                staged = None
            try:
                before = None
                if converted:
                    print('Preparing the first Git checkout in your existing Atlas folder…')
                    self.git_run('clone', '--quiet', '--branch', BRANCH, '--single-branch', self.repository, str(staged))
                    after = self.git_run('rev-parse', 'HEAD', cwd=staged).strip()
                    before_paths = []
                    after_paths = self._paths(after, cwd=staged)
                    bootstrap = []
                else:
                    if Path(self.git_run('rev-parse', '--show-toplevel').strip()).resolve() != self.root.resolve():
                        raise UpdateError('This folder belongs to another Git checkout.')
                    if self.git_run('branch', '--show-current').strip() != BRANCH:
                        raise UpdateError('Updates require the main branch. Keep your current branch unchanged and switch deliberately.')
                    if self._remote(self.git_run('remote', 'get-url', 'origin')) != self._remote(self.repository):
                        raise UpdateError('Git origin is not the Atlas repository; no update was applied.')
                    if self.git_run('status', '--porcelain', '--untracked-files=no').strip():
                        raise UpdateError('Local application files have changes. Commit or keep them separately before updating; imported data is kept.')
                    before = self.git_run('rev-parse', 'HEAD').strip()
                    self.git_run('fetch', '--quiet', self.repository, BRANCH)
                    after = self.git_run('rev-parse', 'FETCH_HEAD').strip()
                    before_paths = self._paths(before)
                    after_paths = self._paths(after)
                    if before == after:
                        print('Atlas is already up to date. Your imported data is unchanged.')
                        return dict(before=before, after=after, converted=False, updated=False, backup=None, started=False)
                    try:
                        self.git_run('merge-base', '--is-ancestor', before, after)
                    except UpdateError as error:
                        raise UpdateError('Local and upstream history diverged. No reset or overwrite was performed.') from error
                    bootstrap = self._bootstrap_collisions(before_paths, after_paths, after)
                print('Available version: ' + after[:12])
                database = self._database()
                legacy = not self.environment.get('ATLAS_DB_PATH') and database == self.root / 'office_atlas.db'
                for relative in set(before_paths) | set(after_paths):
                    deployed = self._path(relative)
                    shared = database.resolve() == deployed.resolve() or (database.exists() and deployed.exists() and database.samefile(deployed))
                    if shared and not (legacy and relative == 'office_atlas.db'):
                        raise UpdateError('The active Atlas database overlaps an application file that the update replaces. Move it to a separate runtime location and update ATLAS_DB_PATH if set before retrying.')
                if check:
                    return dict(before=before, after=after, converted=converted, updated=False, backup=None, started=False)
                if self.active():
                    raise UpdateError('Atlas has active jobs or scans. Finish them and close Atlas tabs before updating.')
                print('Stopping this installation. Do not start new jobs during the update.')
                self.stop()
                # Save all replaced files before Git or the ZIP conversion can write code.
                paths = sorted(set(before_paths) | set(after_paths))
                backup, manifest = self._snapshot(paths)
                print('Backup: ' + str(backup))
                requirements = self.root / 'requirements.txt'
                old_requirements = requirements.read_bytes() if requirements.is_file() else None
                installing = False
                applied_git = False
                try:
                    if converted:
                        for relative in after_paths:
                            self._copy_code(staged / relative, self._path(relative))
                        (staged / '.git' / 'atlas-update-owner').write_text(backup.name, encoding='utf-8')
                        applied_git = True
                        os.replace(staged / '.git', self.root / '.git')
                    else:
                        for path in bootstrap:
                            path.unlink()
                        self.git_run('merge', '--ff-only', after)
                    if self.git_run('rev-parse', 'HEAD').strip() != after:
                        raise UpdateError('Git revision verification failed.')
                    if self.git_run('status', '--porcelain', '--untracked-files=no').strip():
                        raise UpdateError('Updated code does not match the Git revision.')
                    if converted or requirements.read_bytes() != old_requirements:
                        installing = True
                        self.install(requirements)
                        installing = False
                except BaseException as error:
                    try:
                        self._restore(backup, manifest)
                        if converted:
                            if applied_git and (self.root / '.git').exists():
                                owner = self.root / '.git' / 'atlas-update-owner'
                                if not owner.is_file() or owner.read_text(encoding='utf-8') != backup.name:
                                    raise UpdateError('Git metadata changed during the update; it was not removed.')
                                remove_created_git(self.root / '.git')
                        else:
                            current = self.git_run('rev-parse', 'HEAD').strip()
                            self.git_run('read-tree', before)
                            if current != before:
                                self.git_run('update-ref', 'refs/heads/' + BRANCH, before, current)
                    except Exception as restore_error:
                        raise UpdateError('Update failed and code recovery needs review. Atlas remains stopped. Backup: ' + str(backup)) from restore_error
                    reason = 'Dependencies may be partially installed. Run Install_Dependencies.bat before starting Atlas.' if installing else 'Previous application code was restored.'
                    raise UpdateError(str(error) + '\n' + reason + '\nAtlas remains stopped; your runtime data is retained. Backup: ' + str(backup)) from error
                started = False
                if converted:
                    (self.root / '.git' / 'atlas-update-owner').unlink()
                if not no_start:
                    self.start()
                    started = True
                print('Atlas updated to ' + after[:12] + '. Imported users, devices, VDIs, packages and settings are retained.')
                return dict(before=before, after=after, converted=converted, updated=True, backup=str(backup), started=started)
            finally:
                if temp:
                    temp.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check for updates without stopping Atlas or replacing application files.')
    parser.add_argument('--no-start', action='store_true', help='Keep local services stopped after a successful update.')
    args = parser.parse_args()
    if os.name != 'nt':
        print('Run Update-Atlas.bat on Windows.', file=sys.stderr)
        return 1
    try:
        Updater(Path(__file__).resolve().parents[2]).update(check=args.check, no_start=args.no_start)
        return 0
    except (UpdateError, OSError, sqlite3.Error) as error:
        print('UPDATE STOPPED: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
