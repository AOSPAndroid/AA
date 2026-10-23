"""SQLite fixtures must close handles before Windows can remove their files."""
import sqlite3
import os
from pathlib import Path
import tempfile

_runtime_fixture = None


def isolate_backend_database():
    """Keep standalone backend-test imports away from shipped/runtime databases."""
    global _runtime_fixture
    # The Companion connection file never goes to the shared ProgramData or the checkout in tests.
    os.environ.setdefault('ATLAS_COMPANION_DIR', tempfile.mkdtemp(prefix='atlas-companion-test-'))
    if os.environ.get('ATLAS_DB_PATH'):
        return Path(os.environ['ATLAS_DB_PATH'])
    _runtime_fixture = tempfile.TemporaryDirectory(prefix='atlas-backend-test-', ignore_cleanup_errors=True)
    destination = Path(_runtime_fixture.name) / 'fixture.db'
    seed = Path(__file__).resolve().parents[1] / 'office_atlas.db'
    source = sqlite3.connect(seed.as_uri() + '?mode=ro&immutable=1', uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    os.environ['ATLAS_DB_PATH'] = str(destination)
    return destination


class FixtureConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()
def connect(*args,**kwargs):
    kwargs.setdefault('factory',FixtureConnection)
    return sqlite3.connect(*args,**kwargs)
