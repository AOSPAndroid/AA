"""AA's Axis records deployments in Atlas's history and every approval decision. No live targets."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import it_tools as it


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "atlas.db"
        sqlite3.connect(self.database).close()

    def worker(self, results, history=True, computers=("PC-1", "PC-2"), database=None):
        job = {"id": "c" * 32, "kind": "deploy", "computers": list(computers), "repository": str(self.root / "repo"),
               "package": "Example 1.0", "script": "app_i.ps1", "script_sha256": "0" * 64, "action": "Install",
               "mode": "full", "timeout": 60, "state": "queued", "created": it.now(), "created_epoch": time.time(),
               "results": [], "events": [], "worker_pid": None,
               "atlas_db": str(database or self.database), "atlas_history": history}
        path = self.root / "state" / "jobs" / (job["id"] + ".json")
        it.write_json(path, job)
        with patch.object(it.ITTools, "deploy_one", side_effect=results):
            it.run_worker(path)
        return it.read_json(path)

    def rows(self):
        con = sqlite3.connect(self.database)
        con.row_factory = sqlite3.Row
        try:
            return {row["id"]: dict(row) for row in con.execute("select * from deployments")}
        finally:
            con.close()

    def test_each_pc_becomes_an_atlas_history_row_with_a_retryable_request(self):
        self.worker([{"computer": "PC-1", "state": "script_succeeded", "exit_code": 0, "pid": 42, "robocopy_code": 1,
                      "message": "Installer script returned 0", "log_tail": "done"},
                     {"computer": "PC-2", "state": "failed", "message": "WMI unavailable"}])
        rows = self.rows()
        first, second = rows["axis-" + "c" * 32 + "-0"], rows["axis-" + "c" * 32 + "-1"]
        self.assertEqual((first["state"], first["exit_code"], first["pid"], first["target"]), ("launched", "0", "42", "PC-1"))
        self.assertIn("done", first["details"])
        self.assertTrue(first["operator"].endswith("(Axis)"))
        self.assertTrue(first["finished"])
        self.assertEqual((second["state"], second["exit_code"]), ("failed", ""))
        self.assertEqual(json.loads(first["payload"]), {"computer": "PC-1", "folder": str(self.root / "repo" / "Example 1.0"),
                                                        "script": "app_i.ps1", "action": "Install", "mode": "full"})

    def test_history_problems_never_change_the_deployment(self):
        job = self.worker([{"computer": "PC-1", "state": "script_succeeded", "exit_code": 0}],
                          computers=("PC-1",), database=self.root / "missing" / "atlas.db")
        self.assertEqual(job["state"], "complete")
        self.assertEqual(sum("history was not updated" in e["message"] for e in job["events"]), 1)
        self.worker([{"computer": "PC-1", "state": "copied"}], history=False, computers=("PC-1",))
        con = sqlite3.connect(self.database)
        self.assertIsNone(con.execute("select 1 from sqlite_master where name='deployments'").fetchone())
        con.close()

    def test_older_history_table_gains_the_request_column_and_a_crash_closes_the_row(self):
        con = sqlite3.connect(self.database)
        con.execute("create table deployments(id text primary key,started text,finished text,operator text,target text,"
                    "package text,action text,script text,mode text,state text,robocopy_code text,pid text,exit_code text,details text)")
        con.commit(); con.close()
        self.worker(KeyboardInterrupt(), computers=("PC-1",))
        row = self.rows()["axis-" + "c" * 32 + "-0"]
        self.assertEqual(row["state"], "unknown")
        self.assertIn("inspect target state", row["details"])
        self.assertIn("PC-1", row["payload"])


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ui = MagicMock()

    def make(self, auto=False):
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            return agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.root), auto, False,
                               notes=str(self.root / "notes"), state_dir=str(self.root / "state"),
                               ui=self.ui, web_enabled=False)

    def entries(self):
        with (self.root / "state" / agent.AUDIT_FILE).open(encoding="utf-8") as log:
            return [json.loads(line) for line in log]

    def test_every_decision_is_recorded_before_the_change(self):
        axis = self.make()
        self.ui.confirm.return_value = False
        self.assertFalse(axis.confirm("restart PC-1"))
        self.assertFalse(axis.confirm("restart PC-1"))  # Not asked again in this request; nothing new to record.
        self.ui.confirm.return_value = True
        self.ui.interface = "browser"
        self.assertTrue(axis.confirm("remember: Floor 3 uses PRQ3"))
        self.assertTrue(self.make(auto=True).confirm("run: Get-Service"))
        entries = self.entries()
        self.assertEqual([(e["decision"], e["action"]) for e in entries],
                         [("declined", "restart PC-1"), ("approved", "remember: Floor 3 uses PRQ3"),
                          ("approved automatically (--yes)", "run: Get-Service")])
        self.assertEqual(entries[1]["interface"], "browser")
        self.assertEqual(entries[0]["account"], it.windows_account())

    def test_an_unwritable_audit_is_reported(self):
        axis = self.make()
        (self.root / "state").mkdir(exist_ok=True)
        (self.root / "state" / agent.AUDIT_FILE).mkdir()
        self.ui.confirm.return_value = True
        self.assertTrue(axis.confirm("restart PC-1"))
        self.assertIn("audit log", self.ui.error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
