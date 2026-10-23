"""Package cleanup clears Atlas's and Axis's staging folders on simulated admin shares. No remote calls."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import os, sys, tempfile, unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from backend import main


class PackageCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.share = Path(self.tmp.name) / 'PC1'
        def unc(pc, path='C:'):
            return str(self.share.joinpath(*PureWindowsPath(path).parts[1:]))
        for name, value in (('unc', unc), ('validate_pc', lambda pc: pc), ('identity', lambda: 'TEST OPERATOR')):
            patcher = patch.object(main, name, value); patcher.start(); self.addCleanup(patcher.stop)
        self.atlas = self.share / 'Temp' / 'Packages'
        self.axis = self.share / 'Temp' / 'LocalAgent' / 'Packages'
        self.logs = self.share / 'Temp' / 'LocalAgent' / 'Jobs' / 'job'
        for folder, name in ((self.atlas / 'Atlas App', 'setup_i.ps1'), (self.axis / 'Axis App', 'app_i.ps1'), (self.logs, 'output.log')):
            folder.mkdir(parents=True); (folder / name).write_text('x' * 10)

    def test_one_cleanup_clears_both_staging_folders_but_keeps_axis_job_logs(self):
        info = main.package_folder_info('PC1')
        self.assertEqual((info['exists'], info['files'], info['bytes']), (True, 2, 20))
        self.assertEqual(info['locations'], list(main.STAGING_ROOTS))
        result = main._cleanup_package_folder('PC1')
        self.assertEqual((result['deleted'], result['failed']), (2, 0))
        self.assertEqual(sorted(result['items']), ['Atlas App', 'Axis: Axis App'])
        self.assertEqual(list(self.atlas.iterdir()) + list(self.axis.iterdir()), [])
        self.assertTrue((self.logs / 'output.log').is_file())

    def test_a_staging_folder_that_is_a_link_is_never_followed(self):
        elsewhere = Path(self.tmp.name) / 'elsewhere'
        (elsewhere / 'Important').mkdir(parents=True)
        for item in self.axis.iterdir():
            import shutil; shutil.rmtree(item)
        self.axis.rmdir()
        try:
            os.symlink(elsewhere, self.axis, target_is_directory=True)
        except OSError:
            self.skipTest('Creating a directory link needs extra rights on this machine')
        result = main._cleanup_package_folder('PC1')
        self.assertEqual(result['errors'], [{'item': main.STAGING_ROOTS[1], 'error': 'Staging folder is a link; not followed'}])
        self.assertTrue((elsewhere / 'Important').is_dir())
        self.assertEqual(list(self.atlas.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
