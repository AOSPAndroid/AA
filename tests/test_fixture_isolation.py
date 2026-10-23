"""Standalone backend tests must never initialize the distributed database."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackendFixtureIsolation(unittest.TestCase):
    def test_standalone_import_uses_disposable_database_and_preserves_seed(self):
        seed = ROOT / 'office_atlas.db'
        original = hashlib.sha256(seed.read_bytes()).digest()
        sidecars = {suffix: Path(str(seed) + suffix).exists() for suffix in ('-wal', '-shm')}
        env = dict(os.environ, PYTHONUTF8='1')
        env.pop('ATLAS_DB_PATH', None)
        script = r'''
import json, os, sys
sys.path.insert(0, 'tests')
from sqlite_fixture import isolate_backend_database
first = isolate_backend_database()
assert isolate_backend_database() == first
from backend import main
assert main.MASTER_DB.resolve() == first.resolve()
assert first.parent.name.startswith('atlas-backend-test-')
with main.job_service.connect() as db:
    assert db.execute("select name from sqlite_master where name='operation_guard'").fetchone()
print(json.dumps({'isolated': True, 'reused': True}))
main.job_service.pool.shutdown()
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                text=True, capture_output=True, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), {'isolated': True, 'reused': True})
        self.assertEqual(hashlib.sha256(seed.read_bytes()).digest(), original)
        for suffix, existed in sidecars.items():
            self.assertEqual(Path(str(seed) + suffix).exists(), existed)

    def test_explicit_database_is_respected(self):
        env = dict(os.environ, ATLAS_DB_PATH=str(ROOT / 'unused-fixture.db'))
        script = "import sys; sys.path.insert(0, 'tests'); from sqlite_fixture import isolate_backend_database; import os; assert str(isolate_backend_database()) == os.environ['ATLAS_DB_PATH']"
        subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                       capture_output=True, check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
