"""Copy a validated Windows build into the repository's distributable package.

Run Build-Notification-Listener.ps1 with -MakeAppxPath first. Copies only the
known package payload, never mail queues, accounts, settings or logs.
"""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ('AppxManifest.xml', 'Atlas.NotificationListener.exe', 'Atlas.NotificationListener.exe.config',
           'Assets/Square150x150Logo.png', 'Assets/Square44x44Logo.png', 'Assets/StoreLogo.png')
SOURCES = ('notification-listener/Program.cs', 'notification-listener/Store.cs',
           'notification-listener/AppxManifest.xml', 'notification-listener/app.manifest',
           'inbox_schema.sql', 'Build-Notification-Listener.ps1')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path):
    # Git's Windows CRLF checkout must not invalidate an otherwise identical build.
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    source = ROOT / 'output' / 'Atlas-Notification-Listener'
    msix = ROOT / 'output' / 'Atlas-Notification-Listener-unsigned.msix'
    with zipfile.ZipFile(msix) as archive:
        for name in PAYLOAD:
            if archive.read(name) != (source / name).read_bytes():
                raise ValueError('MSIX and loose package differ: ' + name)
    destination = ROOT / 'notification-listener'
    for name in PAYLOAD:
        target = destination / 'package' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    shutil.copyfile(msix, destination / msix.name)
    manifest = {'format': 1, 'unsigned': True, 'source_line_endings': 'LF',
                'source_sha256': {name: source_digest(ROOT / name) for name in SOURCES},
                'package_sha256': {name: digest(destination / name) for name in
                                   (*('package/' + name for name in PAYLOAD), msix.name)}}
    (destination / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Packaged 6 known payload files and unsigned MSIX; source and payload SHA-256 recorded. No runtime data included.')


if __name__ == '__main__':
    main()
