import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_paths as paths


class PackagePathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'admin-profile'
        for context in [patch.dict(os.environ, {}, clear=True),
                        patch.object(Path, 'home', return_value=self.home)]:
            context.start()
            self.addCleanup(context.stop)
        registry_patch = patch.object(paths, '_registered_onedrive_roots', return_value=[])
        self.registry = registry_patch.start()
        self.addCleanup(registry_patch.stop)

    def folder(self, root, shortcut=True):
        path = root / 'Shortcuts' / paths.PACKAGE_FOLDER if shortcut else root / paths.PACKAGE_FOLDER
        path.mkdir(parents=True)
        return path

    def test_clean_install_uses_standard_sharepoint_default(self):
        expected = self.home / paths.BUSINESS_ONEDRIVE / 'Shortcuts' / paths.PACKAGE_FOLDER
        self.assertEqual(paths.package_repository({}, self.root), expected)
        self.assertEqual(paths.package_repository({'package_repository': '  '}, self.root), expected)

    def test_business_environment_finds_relocated_onedrive(self):
        business = self.root / 'relocated-onedrive'
        os.environ['OneDriveCommercial'] = str(business)
        expected = self.folder(business)
        self.assertEqual(paths.package_repository({}, self.root), expected)

    def test_the_team_plan_folder_is_found_like_the_package_repository(self):
        business = self.root / 'business'
        os.environ['OneDriveCommercial'] = str(business)
        self.assertEqual(paths.default_plan_folder(), business / 'Shortcuts' / 'PA-IT_shared' / '02_Current_plan')
        direct = business / 'PA-IT_shared' / '02_Current_plan'
        direct.mkdir(parents=True)
        self.assertEqual(paths.default_plan_folder(), direct, 'A folder added directly to OneDrive is found too')
        loaded = self.root / 'signed-in-user-onedrive'
        os.environ.pop('OneDriveCommercial')
        expected = loaded / 'Shortcuts' / 'PA-IT_shared' / '02_Current_plan'
        expected.mkdir(parents=True)
        self.registry.side_effect = lambda other_profiles=False: [loaded] if other_profiles else []
        self.assertEqual(paths.default_plan_folder(), expected, 'Admin under the DSK account finds the signed-in user\'s plan folder')

    def test_root_level_sharepoint_shortcut_is_supported(self):
        business = self.root / 'business'
        os.environ['OneDriveCommercial'] = str(business)
        expected = self.folder(business, False)
        self.assertEqual(paths.default_package_repository(), expected)

    def test_current_account_registration_precedes_other_profiles(self):
        current, other = self.root / 'current', self.root / 'other'
        expected = self.folder(current)
        self.folder(other)
        self.registry.side_effect = lambda other_profiles=False: [other] if other_profiles else [current]
        self.assertEqual(paths.default_package_repository(), expected)

    def test_separate_admin_account_finds_single_loaded_sharepoint_folder(self):
        business = self.root / 'signed-in-user-onedrive'
        expected = self.folder(business)
        self.registry.side_effect = lambda other_profiles=False: [business, business] if other_profiles else []
        self.assertEqual(paths.default_package_repository(), expected)

    def test_ambiguous_loaded_profiles_are_not_chosen(self):
        roots = [self.root / 'first', self.root / 'second']
        for root in roots:
            self.folder(root)
        self.registry.side_effect = lambda other_profiles=False: roots if other_profiles else []
        self.assertEqual(paths.default_package_repository(),
                         self.home / paths.BUSINESS_ONEDRIVE / 'Shortcuts' / paths.PACKAGE_FOLDER)

    def test_explicit_setting_and_environment_override_remain_authoritative(self):
        configured = self.root / 'custom-packages'
        self.assertEqual(paths.package_repository({'package_repository': str(configured)}, self.root), configured)
        override = self.root / 'environment-packages'
        os.environ['WMI_PACKAGE_REPO'] = str(override)
        self.assertEqual(paths.package_repository({'package_repository': str(configured)}, self.root), override)
        self.registry.assert_not_called()

    def test_relative_override_resolves_against_project(self):
        self.assertEqual(paths.package_repository({'package_repository': 'packages'}, self.root), self.root / 'packages')

    def test_missing_sync_still_returns_business_default(self):
        business = self.root / 'not-yet-synced'
        os.environ['OneDriveCommercial'] = str(business)
        self.assertEqual(paths.default_package_repository(), business / 'Shortcuts' / paths.PACKAGE_FOLDER)


if __name__ == '__main__':
    unittest.main()
