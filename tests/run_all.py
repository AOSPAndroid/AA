"""Run regressions against disposable databases and local simulated operations."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(*args, env):
    subprocess.run(args, cwd=ROOT, env=env, check=True, timeout=180)


def main():
    with tempfile.TemporaryDirectory(prefix='atlas-tests-') as tmp:
        db = Path(tmp) / 'fixture.db'
        source = sqlite3.connect((ROOT / 'office_atlas.db').as_uri() + '?mode=ro&immutable=1', uri=True)
        dest = sqlite3.connect(db)
        source.backup(dest)
        source.close()
        dest.close()
        env = dict(os.environ, ATLAS_DB_PATH=str(db), PYTHON=sys.executable, PYTHONUTF8='1')
        run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v', env=env)
        children = []
        try:
            for script, port in [('serve_ui_fixture.py', 8892), ('serve_seating_fixture.py', 8893)]:
                child = subprocess.Popen([sys.executable, str(ROOT / 'tests' / script)], cwd=ROOT, env=env)
                children.append(child)
                for _ in range(100):
                    if child.poll() is not None:
                        raise RuntimeError(f'{script} failed to start')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/session', timeout=1):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError(f'{script} startup timed out')
            scripts = sorted({path.stem for path in (ROOT/'tests').glob('*_dom.cjs')} |
                             {'installer_frontend_regression','render_cache','map_motion','map_labels','map_furniture','plan_details'})
            failures = []
            for script in scripts:
                try:
                    run('node', '--experimental-vm-modules', f'tests/{script}.cjs', env=env)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    failures.append(script)
            if failures:
                raise RuntimeError('Frontend regressions failed: '+', '.join(failures))
        finally:
            for child in children:
                child.terminate()
                child.wait(timeout=10)
    print('PASS: Python and all frontend regression suites.')


if __name__ == '__main__':
    main()
