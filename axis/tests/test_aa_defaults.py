"""Inside AA, every way of starting Axis shares AA's jobs, database and packages. Disposable folders only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import it_tools as it


class AADefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()  # Windows temp folders can be 8.3 short names.
        self.aa = self.base / "AA"
        (self.aa / "axis").mkdir(parents=True)
        source = Path(agent.__file__).resolve().parents[1]
        for name in ("runtime_paths.py", "package_paths.py"):
            shutil.copyfile(source / name, self.aa / name)
        seed = sqlite3.connect(self.aa / "office_atlas.db")
        seed.execute("create table metadata(key text primary key, value text)")
        seed.commit(); seed.close()
        self.seed_bytes = (self.aa / "office_atlas.db").read_bytes()
        for patcher in (patch.object(agent, "AA_ROOT", str(self.aa)), patch.object(agent, "IN_AA", True),
                        patch.dict(os.environ, {"ATLAS_DB_PATH": "", "WMI_PACKAGE_REPO": "", "AGENT_PACKAGE_REPO": "",
                                                "AGENT_ATLAS_DB": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def args(self, **given):
        return argparse.Namespace(**dict(dict(state_dir=None, atlas_db=None, package_repo=None), **given))

    def config(self, **values):
        (self.aa / "config.json").write_text(json.dumps(values), encoding="utf-8")

    def test_fresh_aa_uses_its_runtime_copy_never_the_seed(self):
        self.config(package_repository="pkgs")
        a = self.args()
        self.assertIsNone(agent.apply_aa_defaults(a))
        self.assertEqual(a.state_dir, str(self.aa / "data" / "axis" / "state"))
        self.assertEqual(Path(a.atlas_db), self.aa / "data" / "office_atlas.db")
        self.assertTrue(Path(a.atlas_db).is_file())
        self.assertEqual(a.package_repo, str(self.aa / "pkgs"))
        self.assertEqual((self.aa / "office_atlas.db").read_bytes(), self.seed_bytes)

    def test_history_is_never_written_into_the_seed(self):
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            axis = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.aa), False, False,
                               state_dir=str(self.aa / "state"), ui=MagicMock(), web_enabled=False,
                               atlas_db=str(self.aa / "office_atlas.db"))
        self.assertFalse(axis.it.atlas_history)

    def test_a_missing_configured_database_keeps_refusing_changes(self):
        self.config(database_folder=str(self.base / "offline-drive"))
        a = self.args()
        self.assertIsNone(agent.apply_aa_defaults(a))
        self.assertEqual(Path(a.atlas_db), self.base / "offline-drive" / "office_atlas.db")
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            axis = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.aa), False, False,
                               state_dir=a.state_dir, ui=MagicMock(), web_enabled=False, atlas_db=a.atlas_db)
        with self.assertRaisesRegex(RuntimeError, "Cannot read Atlas's operation records"):
            axis.it.ensure_available("PC-1")

    def test_unresolved_jobs_in_the_old_terminal_folder_stop_startup(self):
        jobs = self.aa / "axis" / "state" / "jobs"
        jobs.mkdir(parents=True)
        it.write_json(jobs / ("a" * 32 + ".json"), {"id": "a" * 32, "state": "unknown", "computers": ["PC9"]})
        it.write_json(jobs / ("b" * 32 + ".json"), {"id": "b" * 32, "state": "complete", "computers": ["PC8"]})
        problem = agent.apply_aa_defaults(self.args())
        self.assertIn("a" * 32, problem)
        self.assertNotIn("b" * 32, problem)
        self.assertIn("--state-dir state", problem)
        explicit = self.args(state_dir="state")
        self.assertIsNone(agent.apply_aa_defaults(explicit))
        self.assertEqual(explicit.state_dir, "state")
        it.write_json(jobs / ("a" * 32 + ".json"), {"id": "a" * 32, "state": "unknown", "acknowledged": "now"})
        self.assertIsNone(agent.apply_aa_defaults(self.args()))

    def test_explicit_choices_and_environment_win(self):
        a = self.args(atlas_db="mine.db", package_repo="repo")
        self.assertIsNone(agent.apply_aa_defaults(a))
        self.assertEqual((a.atlas_db, a.package_repo), ("mine.db", "repo"))
        with patch.dict(os.environ, {"AGENT_PACKAGE_REPO": "from-env", "AGENT_ATLAS_DB": "env.db"}):
            b = self.args()
            self.assertIsNone(agent.apply_aa_defaults(b))
        self.assertEqual((b.atlas_db, b.package_repo), (None, None))


if __name__ == "__main__":
    unittest.main()
