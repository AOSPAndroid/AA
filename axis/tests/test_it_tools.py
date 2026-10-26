"""No live Windows targets: exercise approvals, job outcomes and context retention."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import it_tools as it
import setup_local


class ITTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "packages"
        self.package = self.repo / "Example 1.0"
        self.package.mkdir(parents=True)
        (self.package / "app_i.ps1").write_text("exit 0\n")
        (self.package / "app_u.vbs").write_text("WScript.Quit 0\n")
        self.confirm = Mock(return_value=True)
        self.backend = it.ITTools(self.root / "state", str(self.repo), self.confirm)

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, mode="full"):
        return {"id": "a" * 32, "kind": "deploy", "computers": ["PC-1"], "repository": str(self.repo),
                "package": self.package.name, "script": "app_i.ps1", "script_sha256": it.digest(self.package / "app_i.ps1"),
                "action": "Install", "mode": mode, "timeout": 60}

    def job_file(self, job):
        job = dict(job, state=job.get("state", "queued"), created=it.now(), created_epoch=time.time() - 30,
                   worker_pid=None, results=[], events=[])
        path = self.backend.state / "jobs" / (job["id"] + ".json")
        it.write_json(path, job)
        return path

    def test_hostname_cannot_inject_a_command_or_path(self):
        for value in ("pc;whoami", "pc\\C$", "-PC", "pc..example", "pc\n", "*", "PC.", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                it.computer(value)
        self.assertEqual(it.computer("pc-1.example.org"), "PC-1.EXAMPLE.ORG")

    def test_package_discovery_and_action_matching(self):
        self.assertEqual(self.backend.find_packages(query="example")["packages"], ["Example 1.0"])
        self.assertEqual(self.backend.find_packages(package="example 1.0")["scripts"], ["app_i.ps1"])
        with self.assertRaises(ValueError):
            self.backend.selection(self.package.name, "app_u.vbs", "Install")
        for package in ("../packages", "C:\\Temp", "..", "Example 1.0/other"):
            with self.subTest(package=package), self.assertRaises(ValueError):
                self.backend.package(package)
        for script in ("../app_i.ps1", "C:\\app_i.ps1", "sub\\..\\app_i.ps1"):
            with self.subTest(script=script), self.assertRaises(ValueError):
                self.backend.selection(self.package.name, script, "Install")

    def test_unique_package_search_returns_action_scripts_ready_for_selection(self):
        (self.package / "app_r.ps1").write_text("exit 0\n")
        for action, script in (("Install", "app_i.ps1"), ("Uninstall", "app_u.vbs"), ("Repair", "app_r.ps1")):
            with self.subTest(action=action):
                result = self.backend.find_packages(query="EXAMPLE", action=action)
                self.assertEqual(result["packages"], [self.package.name])
                self.assertEqual(result["total"], 1)
                self.assertIsNone(result["next_offset"])
                self.assertEqual(result["package"], self.package.name)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["scripts"], [script])
                self.assertEqual(result["script_total"], 1)
                self.assertIsNone(result["script_next_offset"])
                # The combined result is sufficient for the existing deployment validator.
                folder, selected, checksum = self.backend.selection(result["package"], result["scripts"][0], result["action"])
                self.assertEqual(folder, self.package.resolve())
                self.assertEqual(selected, script)
                self.assertEqual(checksum, it.digest(self.package / script))

    def test_ambiguous_package_pages_do_not_scan_or_choose_a_package(self):
        for index in range(51):
            (self.repo / ("Example extra %02d" % index)).mkdir()
        with patch.object(self.backend, "scripts") as scripts:
            first = self.backend.find_packages(query="Example")
            second = self.backend.find_packages(query="Example", offset=first["next_offset"])
        scripts.assert_not_called()
        self.assertEqual(first["total"], 52)
        self.assertEqual(len(first["packages"]), 50)
        self.assertEqual(len(second["packages"]), 2)
        self.assertEqual(len(set(first["packages"] + second["packages"])), 52)
        self.assertIsNone(second["next_offset"])
        for result in (first, second):
            self.assertNotIn("package", result)
            self.assertNotIn("scripts", result)

    def test_unique_package_script_pagination_is_separate_from_package_pagination(self):
        for index in range(55):
            (self.package / ("extra_%02d_i.ps1" % index)).write_text("exit 0\n")
        result = self.backend.find_packages(query="Example")
        self.assertEqual(result["total"], 1)
        self.assertIsNone(result["next_offset"])
        self.assertEqual(result["script_total"], 56)
        self.assertEqual(len(result["scripts"]), 50)
        self.assertEqual(result["script_next_offset"], 50)
        rest = self.backend.find_packages(package=result["package"], action=result["action"], offset=result["script_next_offset"])
        self.assertEqual(rest["total"], 56)
        self.assertIsNone(rest["next_offset"])
        self.assertEqual(result["scripts"] + rest["scripts"], self.backend.scripts(self.package.resolve(), "Install"))

    def test_no_match_or_past_last_package_page_has_no_phantom_selection(self):
        with patch.object(self.backend, "scripts") as scripts:
            missing = self.backend.find_packages(query="missing")
            beyond = self.backend.find_packages(query="Example", offset=1)
        scripts.assert_not_called()
        self.assertEqual(missing["total"], 0)
        self.assertEqual(beyond["total"], 1)
        for result in (missing, beyond):
            self.assertEqual(result["packages"], [])
            self.assertNotIn("package", result)
            self.assertNotIn("scripts", result)

    def test_unique_package_lookup_retains_existing_validation(self):
        with self.assertRaisesRegex(ValueError, "Choose Install"):
            self.backend.find_packages(query="Example", action="Delete")
        with self.assertRaisesRegex(ValueError, "missing"):
            self.backend.find_packages(package="Missing")
        original = it.linked
        with patch.object(it, "linked", side_effect=lambda path: path.name == "app_i.ps1" or original(path)):
            with self.assertRaisesRegex(ValueError, "symlink/junction"):
                self.backend.find_packages(query="Example")
        # Revalidate after discovery: the selected folder may have disappeared.
        with patch.object(self.backend, "package", side_effect=ValueError("Package missing")):
            with self.assertRaisesRegex(ValueError, "Package missing"):
                self.backend.find_packages(query="Example")

    def test_linked_package_content_is_rejected(self):
        outside = self.root / "outside.ps1"
        outside.write_text("exit 0")
        try:
            (self.package / "linked_i.ps1").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(ValueError):
            self.backend.selection(self.package.name, "app_i.ps1", "Install")

    def test_declining_does_not_start_a_worker(self):
        self.confirm.return_value = False
        with patch.object(self.backend, "spawn") as spawn:
            result = self.backend.deploy_package(["PC-1"], self.package.name, "app_i.ps1", "Install")
        self.assertEqual(result["state"], "declined")
        spawn.assert_not_called()
        self.assertEqual(self.backend.jobs(), [])

    def test_approved_script_cannot_change_during_confirmation(self):
        def changed(_):
            (self.package / "app_i.ps1").write_text("Write-Output changed")
            return True
        self.backend.confirm = changed
        with patch.object(self.backend, "spawn") as spawn, self.assertRaisesRegex(RuntimeError, "changed during approval"):
            self.backend.deploy_package(["PC-1"], self.package.name, "app_i.ps1", "Install")
        spawn.assert_not_called()

    def test_bulk_targets_are_deduplicated_and_named_in_approval(self):
        with patch.object(self.backend, "spawn", return_value={"job_id": "j"}) as spawn:
            self.backend.deploy_package(["pc-1", "PC-1", "pc-2"], self.package.name, "app_i.ps1", "Install")
        self.assertEqual(spawn.call_args.args[0]["computers"], ["PC-1", "PC-2"])
        self.assertIn("PC-1, PC-2", self.confirm.call_args.args[0])
        self.assertIn("SHA256=", self.confirm.call_args.args[0])

    def test_queued_deployment_returns_a_saved_job_link_without_waiting_or_claiming_success(self):
        with patch.object(it.subprocess, "Popen") as worker, \
             patch.object(self.backend, "ps") as ps, \
             patch.object(self.backend, "it_job_status") as status:
            result = self.backend.deploy_package(["PC-1"], self.package.name, "app_i.ps1", "Install")
        worker.assert_called_once()
        ps.assert_not_called()
        status.assert_not_called()
        self.confirm.assert_called_once()
        job = it.read_json(self.backend.state / "jobs" / (result["job_id"] + ".json"))
        self.assertEqual(result["state"], "queued")
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["results"], [])
        self.assertEqual(job["script_sha256"], it.digest(self.package / "app_i.ps1"))
        self.assertEqual(result["computers"], ["PC-1"])
        self.assertIn("/jobs " + job["id"], result["message"])
        self.assertIn("not yet verified", result["message"])
        self.assertNotIn("verified", result)
        self.assertNotIn("application_verified", result)

    def test_snapshot_is_bound_to_target_view_and_lifetime(self):
        self.backend.ps = Mock(return_value={"ok": True, "computer": "PC-1", "items": [{"Name": "Spooler"}]})
        snap = self.backend.inspect_computer("pc-1", "services")["snapshot"]
        with self.assertRaises(ValueError):
            self.backend.expected(snap, "PC-2", "services", name="Spooler")
        with self.assertRaises(ValueError):
            self.backend.expected(snap, "PC-1", "processes", pid=45)
        self.assertEqual(self.backend.expected(snap, "PC-1", "services", name="spooler")["Name"], "Spooler")
        path = self.backend.state / "snapshots" / (snap + ".json")
        saved = it.read_json(path); saved["created"] -= 901; it.write_json(path, saved)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.backend.expected(snap, "PC-1", "services", name="Spooler")

    def test_service_decline_does_not_mutate(self):
        self.backend.ps = Mock(return_value={"ok": True, "computer": "PC-1", "items": [{"Name": "Spooler"}]})
        snap = self.backend.inspect_computer("PC-1", "services")["snapshot"]
        self.backend.ps.reset_mock(); self.confirm.return_value = False
        self.assertEqual(self.backend.computer_action("PC-1", "service_stop", name="Spooler", snapshot=snap)["state"], "declined")
        self.backend.ps.assert_not_called()

    def test_target_lock_excludes_another_operation_and_releases(self):
        with it.target_lock(self.backend.state, "PC-1"):
            with self.assertRaises(RuntimeError):
                with it.target_lock(self.backend.state, "PC-1"):
                    self.fail("Second lock acquired")
        with it.target_lock(self.backend.state, "PC-1"):
            pass

    def test_job_write_waits_for_a_concurrent_reader_on_windows(self):
        path = self.root / "state" / "jobs" / "job.json"
        replace = os.replace
        calls = []
        def busy_once(source, target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError("file is open in another process")
            replace(source, target)
        with patch.object(it.os, "replace", side_effect=busy_once), patch.object(it.time, "sleep"):
            it.write_json(path, {"state": "running"})
        self.assertEqual(it.read_json(path), {"state": "running"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_prune_keeps_recent_active_and_unresolved_state(self):
        def job(index, state, **extra):
            key = "%032x" % index
            path = self.job_file(dict(self.plan(), id=key, state=state, **extra))
            data = it.read_json(path)
            data["created"] = "2026-01-01T00:00:%02d.%06d+00:00" % (index // 1000000, index)
            it.write_json(path, data)
            path.with_suffix(".worker.log").write_text("log")
            return path
        oldest = [job(i, "complete") for i in range(1, 6)]
        unresolved = job(6, "unknown")
        acknowledged = job(7, "unknown", acknowledged=it.now())
        running = job(8, "running")
        kept = [job(i, "failed") for i in range(100, 100 + it.RETAINED_JOBS - 1)]
        old = time.time() - it.OUTPUT_SECONDS - 60
        for folder, name, age in (("snapshots", "old.json", time.time() - it.SNAPSHOT_SECONDS - 60),
                                  ("snapshots", "new.json", time.time()), ("outputs", "old.txt", old),
                                  ("outputs", "new.txt", time.time())):
            path = self.backend.state / folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("x")
            os.utime(path, (age, age))
        self.backend.prune()
        for path in oldest:
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix(".worker.log").exists())
        for path in [unresolved, running, acknowledged] + kept:
            self.assertTrue(path.exists(), path.name)
        self.assertEqual(sorted(p.name for p in (self.backend.state / "snapshots").iterdir()), ["new.json"])
        self.assertEqual(sorted(p.name for p in (self.backend.state / "outputs").iterdir()), ["new.txt"])
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.backend.ensure_available("PC-1")

    def test_short_and_qualified_names_share_one_target(self):
        self.assertEqual(it.target_key("pc-1.corp.example."), "PC-1")
        self.assertEqual(it.target_key("10.0.0.5"), "10.0.0.5")
        with it.target_lock(self.backend.state, "PC-1.CORP.EXAMPLE"):
            with self.assertRaises(RuntimeError):
                with it.target_lock(self.backend.state, "pc-1"):
                    self.fail("Second lock acquired")
        self.job_file(dict(self.plan(), state="running", computers=["PC-1.CORP.EXAMPLE"]))
        with self.assertRaisesRegex(RuntimeError, "a{32}"):
            self.backend.ensure_available("PC-1")

    def atlas_guard(self, *targets):
        import sqlite3
        database = self.root / "atlas.db"
        con = sqlite3.connect(database)
        con.execute("create table if not exists operation_guard(target text primary key)")
        con.executemany("insert into operation_guard values(?)", ((t,) for t in targets))
        con.commit(); con.close()
        return database

    def test_atlas_unresolved_target_blocks_axis_until_acknowledged_in_atlas(self):
        database = self.atlas_guard("PC-1.CORP.EXAMPLE")
        guarded = it.ITTools(self.root / "state", str(self.repo), self.confirm, atlas_db=database)
        with self.assertRaisesRegex(RuntimeError, "unresolved Atlas operation"):
            guarded.ensure_available("PC-1")
        with self.assertRaisesRegex(RuntimeError, "unresolved Atlas operation"):
            guarded.deploy_package(["PC-1"], self.package.name, "app_i.ps1", "Install")
        self.confirm.assert_not_called()
        guarded.ensure_available("PC-2")
        import sqlite3
        con = sqlite3.connect(database); con.execute("delete from operation_guard"); con.commit(); con.close()
        guarded.ensure_available("PC-1")

    def test_unreadable_atlas_guard_never_reads_as_clear(self):
        guarded = it.ITTools(self.root / "state", str(self.repo), self.confirm, atlas_db=self.root / "missing.db")
        with self.assertRaisesRegex(RuntimeError, "Cannot read Atlas's operation records"):
            guarded.ensure_available("PC-1")

    def test_an_atlas_job_running_or_left_running_by_a_stopped_atlas_blocks_axis(self):
        import sqlite3
        database = self.atlas_guard()
        con = sqlite3.connect(database)
        con.execute("create table operation_state(id text primary key,kind text,body text,updated real)")
        rows = [("a", "job", json.dumps({"state": "running", "target": "PC-1.CORP.EXAMPLE"})),
                ("b", "job", json.dumps({"state": "complete", "target": "PC-2"})),
                ("c", "job", json.dumps({"state": "running", "results": [{"machine": "PC-3"}]})),
                ("d", "queue", json.dumps({"state": "paused", "items": [{"target": "PC-4", "state": "waiting"}]}))]
        con.executemany("insert into operation_state values(?,?,?,0)", rows)
        con.commit(); con.close()
        guarded = it.ITTools(self.root / "state", str(self.repo), self.confirm, atlas_db=database)
        for pc in ("PC-1", "PC-3"):
            with self.assertRaisesRegex(RuntimeError, "was running when Atlas stopped"):
                guarded.ensure_available(pc)
        guarded.ensure_available("PC-2")
        guarded.ensure_available("PC-4")  # A waiting queue item becomes its own job when it starts.
        con = sqlite3.connect(database)
        con.execute("insert into operation_state values('e','job','not json',0)")
        con.commit(); con.close()
        with self.assertRaisesRegex(RuntimeError, "Cannot read Atlas's operation records"):
            guarded.ensure_available("PC-2")

    def test_detached_worker_rechecks_the_atlas_guard(self):
        database = self.atlas_guard()
        guarded = it.ITTools(self.root / "state", str(self.repo), self.confirm, atlas_db=database)
        with patch.object(it.subprocess, "Popen"):
            job_id = guarded.deploy_package(["PC-1"], self.package.name, "app_i.ps1", "Install")["job_id"]
        path = self.backend.state / "jobs" / (job_id + ".json")
        self.assertEqual(it.read_json(path)["atlas_db"], str(database))
        self.atlas_guard("PC-1")  # Atlas loses track of PC-1 after approval.
        with patch.object(it.ITTools, "ps") as ps:
            it.run_worker(path)
        result = it.read_json(path)["results"][0]
        self.assertEqual(result["state"], "failed")
        self.assertIn("unresolved Atlas operation", result["message"])
        ps.assert_not_called()

    def deploy_simulated(self, exit_code=0, mode="full", robocopy=1, mutate=False, launch_error=False):
        plan = self.plan(mode)
        if mutate:
            (self.package / "app_i.ps1").write_text("changed")
        remote = self.root / "remote"
        destination = remote / "Temp" / "LocalAgent" / "Packages" / self.package.name
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "app_i.ps1").write_text("exit 0\n")
        def local_share(pc, path):
            self.assertEqual(pc, "PC-1")
            return remote.joinpath(*it.PureWindowsPath(path).parts[1:])
        def ps(request, **kw):
            if request["op"] == "inspect":
                return {"data": {"wmi": True, "admin_share": True, "ping": False}}
            if launch_error:
                raise RuntimeError("Transport disconnected after Create")
            jobfolder = local_share("PC-1", it.REMOTE_ROOT + "\\Jobs\\" + plan["id"])
            if exit_code is not None:
                (jobfolder / "exitcode.txt").write_text(str(exit_code))
                (jobfolder / "output.log").write_text("Installer output\n")
            return {"pid": 123}
        self.backend.ps = Mock(side_effect=ps)
        clock = iter((0, 100, 101, 102))
        with patch.object(it, "share", side_effect=local_share), patch.object(it.subprocess, "run", return_value=subprocess.CompletedProcess([], robocopy, b"copy", b"")) as run, patch.object(it.time, "monotonic", side_effect=lambda: next(clock)):
            result = self.backend.deploy_one(plan, "PC-1", Mock())
        return result, run

    def test_copy_accepts_robocopy_success_codes_without_launch(self):
        for code in (0, 1, 3, 7):
            with self.subTest(code=code):
                result, run = self.deploy_simulated(mode="copy", robocopy=code)
                self.assertEqual(result["state"], "copied")
                self.assertTrue(result["verified"])
                self.assertEqual(self.backend.ps.call_count, 1)
        result, _ = self.deploy_simulated(mode="copy", robocopy=8)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("pid", result)

    def test_script_exit_codes_never_claim_application_verification(self):
        for code, expected in ((0, "script_succeeded"), (1603, "failed"), (3010, "reboot_required")):
            with self.subTest(code=code):
                # Each run owns its own remote job folder.
                jobdir = self.root / "remote" / "Temp" / "LocalAgent" / "Jobs"
                if jobdir.exists():
                    import shutil
                    shutil.rmtree(jobdir)
                result, _ = self.deploy_simulated(exit_code=code)
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["application_verified"])
                self.assertEqual(result["exit_code"], code)

    def test_missing_exit_record_and_launch_disconnect_are_unknown(self):
        for disconnected in (False, True):
            with self.subTest(disconnected=disconnected):
                jobdir = self.root / "remote" / "Temp" / "LocalAgent" / "Jobs"
                if jobdir.exists():
                    import shutil
                    shutil.rmtree(jobdir)
                result, _ = self.deploy_simulated(exit_code=None, launch_error=disconnected)
                self.assertEqual(result["state"], "unknown")
                self.assertTrue(result["inspect_before_retry"])

    def test_execute_mode_never_copies_and_worker_rechecks_approved_bytes(self):
        result, run = self.deploy_simulated(mode="execute")
        self.assertEqual(result["state"], "script_succeeded")
        run.assert_not_called()
        result, run = self.deploy_simulated(mutate=True)
        self.assertEqual(result["state"], "failed")
        self.assertIn("changed after approval", result["message"])
        run.assert_not_called()

    def test_dead_worker_is_unknown_and_blocks_retry_until_acknowledged(self):
        path = self.job_file(self.plan())
        result = self.backend.it_job_status("a" * 32)
        self.assertEqual(result["state"], "unknown")
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.backend.ensure_available("PC-1")
        self.confirm.return_value = False
        self.backend.it_job_status("a" * 32, acknowledge_unknown=True)
        self.assertNotIn("acknowledged", it.read_json(path))
        self.confirm.return_value = True
        self.backend.it_job_status("a" * 32, acknowledge_unknown=True)
        self.backend.ensure_available("PC-1")

    def test_worker_persists_all_bulk_outcomes(self):
        plan = self.plan(); plan["computers"] = ["PC-1", "PC-2"]
        path = self.job_file(plan)
        with patch.object(it.ITTools, "deploy_one", side_effect=[{"computer": "PC-1", "state": "script_succeeded"}, {"computer": "PC-2", "state": "failed"}]) as deploy:
            it.run_worker(path)
        saved = it.read_json(path)
        self.assertEqual(saved["state"], "failed")
        self.assertEqual(len(saved["results"]), 2)
        self.assertEqual(deploy.call_count, 2)

    def test_reboot_is_verified_only_after_a_changed_boot_timestamp(self):
        plan = {"id": "b" * 32, "kind": "reboot", "computers": ["PC-1"], "before_boot": "old", "timeout": 60}
        path = self.job_file(plan)
        with patch.object(it.ITTools, "ps", side_effect=[{"accepted": True}, {"data": {"LastBootUpTime": "old"}}, {"data": {"LastBootUpTime": "new"}}]), patch.object(it.time, "sleep"):
            it.run_worker(path)
        result = it.read_json(path)["results"][0]
        self.assertEqual(result["state"], "reboot_verified")
        self.assertTrue(result["verified"])


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            self.agent = agent.Agent("http://127.0.0.1:8080/v1", "local", str(root), False, False,
                                     notes=str(root / "notes"), state_dir=str(root / "state"))

    def tearDown(self):
        self.temp.cleanup()

    def test_full_output_can_be_recovered_in_pages(self):
        original = "prefix\n" + "0123456789" * 1000 + "\nlast line"
        summary = self.agent.save_output(original)
        output_id = summary.split("output_id=", 1)[1].split(",", 1)[0]
        recovered, offset = "", 0
        while offset is not None:
            result = json.loads(self.agent.call_tool("read_tool_output", {"output_id": output_id, "offset": offset}))
            recovered += result["content"]; offset = result["next_offset"]
        self.assertEqual(original, recovered)
        self.assertIn("Error", self.agent.call_tool("read_tool_output", {"output_id": "../outside"}))

    def test_history_drops_complete_turns_and_keeps_tool_pairs(self):
        a = self.agent
        a.messages += [{"role": "user", "content": "old"},
                       {"role": "assistant", "tool_calls": [{"id": "x"}], "content": ""},
                       {"role": "tool", "tool_call_id": "x", "content": "old output" * 100},
                       {"role": "assistant", "content": "done"},
                       {"role": "user", "content": "new"}]
        a.history_budget = len(json.dumps(a.messages[0])) + 300
        a.trim_history()
        self.assertEqual([m["role"] for m in a.messages], ["system", "user"])
        self.assertEqual(a.messages[-1]["content"], "new")

    def test_it_dispatch_returns_structured_errors_and_preserves_declines(self):
        with patch.object(self.agent.it, "call", return_value={"state": "declined"}) as call:
            result = json.loads(self.agent.call_tool("deploy_package", {"computers": ["PC-1"]}))
            self.assertEqual(result["state"], "declined")
            call.assert_called_once()
        with patch.object(self.agent.it, "call", side_effect=it.UnknownOutcome("Inspect before retrying")):
            self.assertIn("Inspect before retrying", self.agent.call_tool("computer_action", {}))

    def test_setup_includes_windows_runtime_files(self):
        with tempfile.TemporaryDirectory() as destination:
            setup_local.setup_agent(destination)
            self.assertEqual({p.name for p in Path(destination).iterdir()}, {"agent.py", "it_tools.py", "it_windows.ps1", "terminal_ui.py", "web_tools.py", "atlas_db.py", "skill_library.py", "skills"})
            from skill_library import SkillLibrary
            skills, errors = SkillLibrary(bundled=Path(destination) / "skills").scan()
            self.assertEqual(len(skills), 10)
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
