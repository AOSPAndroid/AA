"""Build resources/winget_aliases.json.gz from the public winget source index.

The Windows Package Manager community repository (github.com/microsoft/winget-pkgs, MIT licence)
publishes an index of package names and monikers. Atlas uses it offline as a dictionary of product
names, e.g. "acrobatreader" and "Adobe Acrobat Reader DC" are the same product, to recognise software
requests. Nothing is installed from winget.

Usage: python tools/build_winget_aliases.py [path-or-url-of-source.msix]
"""
import gzip
import io
import json
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE = 'https://cdn.winget.microsoft.com/cache/source.msix'
TARGET = Path(__file__).resolve().parents[1] / 'resources' / 'winget_aliases.json.gz'


def read_index(location):
    data = Path(location).read_bytes() if Path(location).is_file() else urllib.request.urlopen(location, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as package, tempfile.TemporaryDirectory() as tmp:
        package.extract('Public/index.db', tmp)
        db = sqlite3.connect(Path(tmp, 'Public', 'index.db'))
        rows = db.execute('''SELECT DISTINCT i.id, n.name, m.moniker FROM manifest x
                             JOIN ids i ON i.rowid=x.id JOIN names n ON n.rowid=x.name
                             JOIN monikers m ON m.rowid=x.moniker''').fetchall()
        db.close()
    return rows


def build(rows):
    packages = {}
    for package_id, name, moniker in rows:
        entry = packages.setdefault(package_id, ({}, set()))
        name = ' '.join(str(name or '').split())
        if any(c.isalpha() for c in name):
            entry[0][name.casefold()] = name
        if moniker and any(c.isalpha() for c in moniker):
            entry[1].add(moniker.casefold())
    result = []
    for package_id in sorted(packages, key=str.casefold):
        names, monikers = packages[package_id]
        # A few distinct names per package keep the file small; shorter names are the useful aliases.
        kept = sorted(names.values(), key=lambda n: (len(n), n.casefold()))[:4]
        if kept:
            result.append([package_id, kept, sorted(monikers)])
    return result


def main():
    rows = read_index(sys.argv[1] if len(sys.argv) > 1 else SOURCE)
    packages = build(rows)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    document = {'source': 'Windows Package Manager community repository index (github.com/microsoft/winget-pkgs)',
                'licence': 'MIT', 'generated': datetime.now(timezone.utc).date().isoformat(), 'packages': packages}
    TARGET.write_bytes(gzip.compress(json.dumps(document, separators=(',', ':'), ensure_ascii=False).encode('utf-8'), 9))
    print(f'{len(packages)} packages -> {TARGET} ({TARGET.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
