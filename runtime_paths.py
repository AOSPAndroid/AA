"""Source assets and mutable runtime data have separate lifetimes."""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE = 'office_atlas.db'
KNOWLEDGE = 'knowledge.sqlite3'
SCRIPTS = 'scripts.json'
PERSONAS = 'personas.json'
CLIPBOARD = 'clipboard-history.json'


def database_folder(root=None):
    """Folder named by "database_folder" in config.json (for example F:\\Atlas\\DB), or None."""
    try:
        config = json.loads(((root or ROOT) / 'config.json').read_text(encoding='utf-8'))
        folder = config.get('database_folder') if isinstance(config, dict) else None
    except (OSError, ValueError):
        return None
    return Path(folder).expanduser() if isinstance(folder, str) and folder.strip() else None


def database_path():
    configured = os.environ.get('ATLAS_DB_PATH')
    if configured:
        return Path(configured).expanduser().resolve()
    folder = database_folder()
    if folder:
        # No fallback to the seed: a missing drive must not open an empty-looking Atlas.
        return folder / DATABASE
    runtime = ROOT / 'data' / DATABASE
    return runtime if runtime.exists() else ROOT / DATABASE


def knowledge_path():
    folder = database_folder()
    return folder / KNOWLEDGE if folder else ROOT / 'data' / KNOWLEDGE


def scripts_path():
    folder = database_folder()
    return folder / SCRIPTS if folder else ROOT / 'data' / SCRIPTS


def personas_path():
    folder = database_folder()
    return folder / PERSONAS if folder else ROOT / 'data' / PERSONAS


def companion_state_path():
    return clipboard_path().with_name('companion-state.json')


def companion_inbox_path():
    return clipboard_path().with_name('companion-inbox')


def clipboard_path():
    folder = database_folder()
    return folder / CLIPBOARD if folder else ROOT / 'data' / CLIPBOARD


def prepare_runtime_database():
    """Copy the distributed seed once, using SQLite backup (including WAL data)."""
    if os.environ.get('ATLAS_DB_PATH'):
        path = database_path()
        if not path.is_file():
            raise ValueError('ATLAS_DB_PATH must point to an existing Atlas database.')
        return path
    folder = database_folder()
    if folder:
        path = folder / DATABASE
        if not path.is_file():
            raise ValueError(f'The Atlas database was not found in {folder}. Check that the drive is connected, '
                             'or remove "database_folder" from config.json to use the data folder.')
        return path
    target = ROOT / 'data' / 'office_atlas.db'
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    seed = ROOT / 'office_atlas.db'
    temporary = target.with_suffix('.migrating')
    try:
        source = sqlite3.connect(seed.resolve().as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            if destination.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Runtime database copy failed integrity verification.')
        finally:
            source.close()
            destination.close()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
