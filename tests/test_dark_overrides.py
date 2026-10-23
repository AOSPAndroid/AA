"""Hard-coded light colours in the stylesheets have generated dark counterparts that are up to date."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('tinycss2'), 'tinycss2 is a development dependency')
class DarkOverrides(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        self.addCleanup(sys.path.remove, str(ROOT / 'tools'))
        import build_dark_overrides
        self.tool = build_dark_overrides

    def test_generated_block_matches_the_stylesheets(self):
        self.assertTrue(self.tool.main(check=True), 'Run python tools/build_dark_overrides.py after changing stylesheet colours')

    def test_colours_map_by_hue_without_extra_specificity(self):
        css = (ROOT / 'frontend/assets/design-system.css').read_text(encoding='utf-8')
        block = css.split(self.tool.START)[1].split(self.tool.END)[0]
        self.assertIn(':where(html[data-theme="dark"]) body.atlas-console .selection-health-grid .warning{background:var(--atlas-warning-bg)', block)
        self.assertIn(':where(html[data-theme="dark"]) body :is(.atlas-header-menu,.atlas-ad-context,.atlas-context-menu){background:var(--atlas-surface)', block)
        self.assertNotIn('map-name', block, 'Map labels keep their own colours')
        self.assertTrue(css.rstrip().endswith(self.tool.END), 'The generated block is the last layer')


if __name__ == '__main__':
    unittest.main()
