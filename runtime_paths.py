"""Resolve installation inputs separately from one configurable runtime workspace."""
from dataclasses import dataclass
import json
import os
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE = 'office_atlas.db'
KNOWLEDGE = 'knowledge.sqlite3'
SCRIPTS = 'scripts.json'
CLIPBOARD = 'clipboard-history.json'


def configuration(root=None):
    path = (root or ROOT) / 'config.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('config.json must contain an object.')
    return data


def database_folder(root=None):
    folder = configuration(root).get('database_folder')
    return Path(folder).expanduser() if isinstance(folder, str) and folder.strip() else None


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    database: Path

    @property
    def axis(self):
        return self.root / 'axis'

    @property
    def logs(self):
        return self.root / 'logs'

    def diagnostics(self):
        return {key: str(value) for key, value in {
            'runtime': self.root, 'database': self.database, 'axis': self.axis,
            'knowledge': self.root / KNOWLEDGE, 'logs': self.logs}.items()}


def paths(root=None):
    install = root or ROOT
    config = configuration(install)
    explicit = os.environ.get('AA_DATA_HOME') or config.get('runtime_folder')
    folder = explicit or config.get('database_folder')
    database = os.environ.get('ATLAS_DB_PATH') if root is None or install.resolve() == ROOT.resolve() else None
    runtime = Path(folder).expanduser() if folder else Path(database).expanduser().parent if database else install / 'data'
    target=Path(database).expanduser().resolve() if database else (runtime/DATABASE).resolve()
    if target==(install/DATABASE).resolve():
        raise ValueError('The distributed seed is read-only. Choose a separate runtime folder/database.')
    return RuntimePaths(runtime.resolve(),target)


def database_path():
    # Never return the source seed as a writable database.
    return paths().database


def knowledge_path():
    return paths().root / KNOWLEDGE


def scripts_path():
    return paths().root / SCRIPTS


def companion_state_path():
    return paths().root / 'companion-state.json'


def companion_inbox_path():
    return paths().root / 'companion-inbox'


def clipboard_path():
    return paths().root / CLIPBOARD


def prepare_runtime_database():
    resolved = paths()
    target = resolved.database
    if target.exists():
        return target
    if os.environ.get('ATLAS_DB_PATH') or database_folder():
        raise ValueError('The configured Atlas database must exist. Check that the drive is connected and the configuration is correct.')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.migrating')
    try:
        source = sqlite3.connect((ROOT / DATABASE).resolve().as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            if destination.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Runtime database copy failed integrity verification.')
        finally:
            source.close()
            destination.close()
        # Publish without replacing a runtime created by a concurrent launcher.
        try:
            if os.name == 'nt':
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return target
