import unittest
from unittest.mock import patch
from backend.launch import edition_launcher as e

class EditionLauncherTests(unittest.TestCase):
    def test_start_all_opens_admin_demo_and_preview_once(self):
        with patch.object(e.launcher, "run", return_value=0) as start, patch.object(e.webbrowser, "open_new_tab") as browser:
            self.assertEqual(e.launch("both", "all"), 0)
            start.assert_called_once_with(open_browser=False)
            self.assertEqual([c.args[0] for c in browser.call_args_list], [e.edition_url(mode) for mode in ("admin", "demo", "preview")])

    def test_failure_does_not_open_tabs(self):
        with patch.object(e.launcher, "run", return_value=1), patch.object(e.webbrowser, "open_new_tab") as browser:
            self.assertEqual(e.launch("both", "all"), 1)
            browser.assert_not_called()

    def test_classic_and_no_browser(self):
        with patch.object(e.launcher, "run", return_value=0), patch.object(e.webbrowser, "open_new_tab") as browser:
            self.assertEqual(e.launch("classic", "all"), 0)
            self.assertEqual(browser.call_count, 2)
            browser.reset_mock()
            self.assertEqual(e.launch("both", "all", False), 0)
            browser.assert_not_called()

    def test_old_desktop_shortcuts_open_normal_atlas(self):
        with patch.object(e.launcher, "run", return_value=0), patch.object(e.webbrowser, "open_new_tab") as browser:
            self.assertEqual(e.launch("desktop", "admin"), 0)
            self.assertEqual([c.args[0] for c in browser.call_args_list], [e.edition_url("admin")])
            self.assertNotIn("desktop", e.edition_url("admin"))

    def test_preview_only_does_not_start_servers(self):
        with patch.object(e.launcher, "run") as start, patch.object(e.webbrowser, "open_new_tab") as browser:
            self.assertEqual(e.launch("both", "preview"), 0)
            start.assert_not_called()
            self.assertEqual([c.args[0] for c in browser.call_args_list], [e.PREVIEW + "/"])

if __name__ == "__main__":
    unittest.main()
