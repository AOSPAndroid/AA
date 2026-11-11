"""Read-only directory access; callers own one connection/snapshot per request."""
import sqlite3
from pathlib import Path
from directory_lookup import prepare_views


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class DirectoryRepository:
    def __init__(self, database):
        self.database = database

    def connect(self, views=True):
        path = Path(self.database())
        if not path.is_file():
            raise RuntimeError(f'Directory database missing: {path}')
        connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=20,factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        try:
            if views:
                prepare_views(connection)
            return connection
        except BaseException:
            connection.close()
            raise
