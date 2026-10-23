import hashlib
import json
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InboxPackageTests(unittest.TestCase):
    def test_distributed_listener_matches_sources_and_msix(self):
        base = ROOT / 'notification-listener'
        manifest = json.loads((base / 'package-manifest.json').read_text())
        self.assertTrue(manifest['unsigned'], 'Production installation requires approved signing')
        for prefix, files in ((ROOT, manifest['source_sha256']), (base, manifest['package_sha256'])):
            for name, expected in files.items():
                with self.subTest(file=name):
                    contents = (prefix / name).read_bytes()
                    if prefix == ROOT:
                        contents = contents.replace(b'\r\n', b'\n')
                    self.assertEqual(hashlib.sha256(contents).hexdigest(), expected,
                                     'Rebuild and package the listener after changing its source')
        with zipfile.ZipFile(base / 'Atlas-Notification-Listener-unsigned.msix') as archive:
            for path in (base / 'package').rglob('*'):
                if path.is_file():
                    self.assertEqual(archive.read(path.relative_to(base / 'package').as_posix()), path.read_bytes())
            self.assertFalse(any(name.endswith(('.sqlite3', '.db')) for name in archive.namelist()))


if __name__ == '__main__':
    unittest.main()
