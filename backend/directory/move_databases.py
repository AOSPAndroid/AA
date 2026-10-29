"""Move Atlas databases to another folder (default F:\\Atlas\\DB) and point Atlas at it.

Each database is copied with SQLite's backup API, so changes still held in -wal
files are included. A copy is used only after its integrity check passes and its
table row counts match the original. config.json then records the new folder,
and the originals are moved into data/backups instead of being deleted.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from backend.launch import launcher
from backend import runtime_paths

DEFAULT_DESTINATION = r'F:\Atlas\DB'


class MoveError(Exception):
    pass


def atlas_running():
    try:
        # A stale/unresponsive record is not proof that the process stopped.
        # The launcher removes owned records only after stopping the process.
        return [mode for mode in ('admin', 'viewer') if launcher.read_record(mode)]
    except (OSError, ValueError):
        raise MoveError('Cannot verify Atlas server records. Run windows\\Stop-All-Atlas.bat and retry.')


def row_counts(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)) as db:
        tables = [r[0] for r in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        return {t: db.execute('select count(*) from "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}


def copy_database(source, target):
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex[:8] + '.copying')
    try:
        original = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)
        copy = sqlite3.connect(temporary)
        try:
            original.backup(copy)
            if copy.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise MoveError(f'The copy of {source.name} failed its integrity check. Nothing was changed.')
        finally:
            original.close()
            copy.close()
        if row_counts(source) != row_counts(temporary):
            raise MoveError(f'The copy of {source.name} does not match the original. Nothing was changed.')
        os.replace(temporary, target)
    finally:
        for part in (temporary, Path(str(temporary) + '-wal'), Path(str(temporary) + '-shm')):
            part.unlink(missing_ok=True)


def save_folder(root, folder):
    path = root / 'config.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    if not isinstance(config, dict):
        raise MoveError('config.json is not a settings object; fix it before moving the databases.')
    config['database_folder'] = str(folder)
    temporary = root / ('config.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def move(destination, root=None):
    root = root or runtime_paths.ROOT
    if os.environ.get('ATLAS_DB_PATH'):
        raise MoveError('ATLAS_DB_PATH is set for this window, so Atlas ignores the database folder. Clear it and retry.')
    if running := atlas_running():
        raise MoveError(f'Atlas is running ({", ".join(running)}). Finish active jobs, run windows\\Stop-All-Atlas.bat, then retry.')
    destination = Path(destination).expanduser()
    if not destination.is_absolute():
        raise MoveError('Give the destination as a full path, for example F:\\Atlas\\DB.')
    if not Path(destination.anchor).exists():
        raise MoveError(f'Drive {destination.anchor} is not available. Connect it and retry.')
    primary = runtime_paths.database_path()
    if not primary.is_file():
        raise MoveError('The main Atlas database was not found. Restore its configured location before moving it.')
    sources = [primary, *([runtime_paths.knowledge_path()] if runtime_paths.knowledge_path().is_file() else [])]
    current = runtime_paths.database_folder(root)
    if current and destination.resolve() == current.resolve():
        print(f'The databases are already in {destination}. Nothing to do.')
        return []
    destination.mkdir(parents=True, exist_ok=True)
    names = {runtime_paths.DATABASE: sources[0]} | {p.name: p for p in sources[1:]}
    clashes = [destination / name for name in names if (destination / name).exists()]
    if clashes:
        raise MoveError('These files already exist and were not overwritten: ' + ', '.join(map(str, clashes))
                        + '. Move or rename them, then retry.')

    copied = []
    try:
        for name, source in names.items():
            print(f'Copying {source} ...')
            copy_database(source, destination / name)
            copied.append(destination / name)
        save_folder(root, destination)
    except BaseException:
        for path in copied:
            path.unlink(missing_ok=True)
        raise

    # Keep the originals as a rollback copy. The tracked seed in the application folder stays.
    archive = root / 'data' / 'backups' / ('before-database-move-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    for source in names.values():
        if source.resolve() == (root / runtime_paths.DATABASE).resolve():
            continue
        archive.mkdir(parents=True, exist_ok=True)
        for part in (source, *(Path(str(source) + s) for s in ('-wal', '-shm'))):
            if part.exists():
                shutil.move(str(part), str(archive / part.name))
    print(f'\nDone. Atlas now uses {destination}:')
    for path in copied:
        print(f'  {path}')
    if archive.exists():
        print(f'The previous files were kept in {archive}. Delete them once Atlas works from the new folder.')
    print('Start Atlas again with windows\\Start-All-Atlas.bat.')
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('destination', nargs='?', default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    try:
        move(args.destination)
    except (MoveError, OSError, sqlite3.Error, ValueError) as error:
        print('Database move error: ' + str(error))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
