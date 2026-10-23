"""Shared startup uses local fixtures; Windows CI also executes the BAT handoff."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch_atlas
import start


class SharedLauncherTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.here = self.root / "install" / "axis" / "local-agent"
        self.here.mkdir(parents=True)
        self.stack.enter_context(patch.dict(os.environ, {
            "LOCALAPPDATA": str(self.root / "profile"), "ATLAS_HOME": "", "WMI_PYTHON": "",
            "AXIS_TEST_INHERITED": "keep this value",
        }))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))
        # These tests run inside the AA checkout; standalone Axis is the default case here.
        self.stack.enter_context(patch.object(start, "AA_ROOT", str(self.root / "standalone")))
        self.identity = "EXAMPLE\\dsk-user"
        self.atlas = self.make_atlas(self.root / "atlas-install")
        self.database = self.atlas / "data" / "office_atlas.db"
        self.database.parent.mkdir()
        self.database.write_bytes(b"unchanged database fixture")
        self.health = {"application": "Office Atlas", "mode": "admin", "instance_id": "fixture-instance",
                       "instance_root": str(self.atlas), "identity": self.identity}
        self.record = {"root": str(self.atlas), "port": 18770, "instance_id": "fixture-instance"}
        self.write_record()
        self.status = {"available": True, "path": str(self.database)}

    def make_atlas(self, folder):
        folder.mkdir(parents=True)
        for name in ("Start-Office-Atlas.bat", "Python_Settings.bat", "launcher.py"):
            (folder / name).write_text("fixture", encoding="utf-8")
        return folder.resolve()

    def write_record(self):
        (self.atlas / "data" / "server.json").write_text(json.dumps(self.record), encoding="utf-8")

    def api(self, port, route):
        self.assertEqual(port, 18770)
        return self.health if route == "/api/health" else self.status

    def process(self, command, **kwargs):
        if command == ["whoami.exe"]:
            return subprocess.CompletedProcess(command, 0, self.identity + "\n")
        return subprocess.CompletedProcess(command, 0)

    def launch_mocks(self):
        self.stack.enter_context(patch.object(launch_atlas.sys, "platform", "win32"))
        api = self.stack.enter_context(patch.object(launch_atlas, "_get_json", side_effect=self.api))
        run = self.stack.enter_context(patch.object(launch_atlas.subprocess, "run", side_effect=self.process))
        return api, run

    def save(self, folder):
        path = launch_atlas._saved_folder()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(folder), encoding="utf-8")

    def test_explicit_folder_precedes_environment_and_saved_folder(self):
        other = self.make_atlas(self.root / "other")
        self.save(other)
        with patch.dict(os.environ, {"ATLAS_HOME": str(other)}):
            self.assertEqual(launch_atlas.find_atlas(self.here, '"%s"' % self.atlas), self.atlas)
            self.assertEqual(launch_atlas.find_atlas(self.here), other)
            with self.assertRaisesRegex(launch_atlas.AtlasLaunchError, "launcher files"):
                launch_atlas.find_atlas(self.here, self.root / "missing")
        with patch.dict(os.environ, {"ATLAS_HOME": str(self.root / "missing")}):
            with self.assertRaises(launch_atlas.AtlasLaunchError):
                launch_atlas.find_atlas(self.here)

    def test_saved_folder_precedes_sibling_and_stale_saved_path_is_recovered(self):
        sibling = self.make_atlas(self.here.parent / "Atlas")
        self.save(self.atlas)
        self.assertEqual(launch_atlas.find_atlas(self.here), self.atlas)
        self.save(self.root / "removed")
        self.assertEqual(launch_atlas.find_atlas(self.here), sibling)

    def test_literal_environment_tokens_survive_folder_save_and_instance_verification(self):
        folder = self.make_atlas(self.root / "Atlas $AXIS_TEST_TOKEN %AXIS_TEST_TOKEN% !ready!")
        (folder / "data").mkdir()
        record = dict(self.record, root=str(folder))
        (folder / "data" / "server.json").write_text(json.dumps(record), encoding="utf-8")
        health = dict(self.health, instance_root=str(folder))
        with patch.dict(os.environ, {"AXIS_TEST_TOKEN": "must-not-expand"}), \
             patch.object(launch_atlas, "_get_json", return_value=health):
            self.assertEqual(launch_atlas.find_atlas(self.here, folder), folder)
            self.save(folder)
            self.assertEqual(launch_atlas.find_atlas(self.here), folder)
            self.assertEqual(launch_atlas._active_port(folder, self.identity, required=True), 18770)

    def test_multiple_matches_prompt_once_instead_of_choosing_arbitrarily(self):
        self.make_atlas(self.here.parent / "Atlas")
        chosen = self.make_atlas(self.here.parent.parent / "Atlas")
        with patch("builtins.input", return_value=str(chosen)) as prompt:
            self.assertEqual(launch_atlas.find_atlas(self.here), chosen)
        prompt.assert_called_once()
        self.assertFalse(launch_atlas._saved_folder().exists())

    def test_missing_installation_without_interactive_input_has_actionable_error(self):
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesRegex(launch_atlas.AtlasLaunchError, "--atlas-dir"):
                launch_atlas.find_atlas(self.here)

    def test_active_runtime_database_wins_over_edited_config_and_relative_paths_resolve(self):
        self.launch_mocks()
        (self.atlas / "config.json").write_text(json.dumps({"database_folder": "changed-after-startup"}), encoding="utf-8")
        for path in (str(self.database), "data/office_atlas.db"):
            with self.subTest(path=path):
                self.status["path"] = path
                self.assertEqual(launch_atlas.start_atlas(self.here, self.atlas), str(self.database))
        self.assertEqual(launch_atlas._saved_folder().read_text(encoding="utf-8"), str(self.atlas))
        self.assertEqual(self.database.read_bytes(), b"unchanged database fixture")

    def test_inherited_environment_and_python_selection_need_no_account_switch(self):
        _, run = self.launch_mocks()
        for version, supplied, expected in (((3, 12), "", sys.executable),
                                             ((3, 8), "", ""),
                                             ((3, 12), r"C:\Atlas Python\python.exe", r"C:\Atlas Python\python.exe")):
            with self.subTest(version=version, supplied=supplied), \
                 patch.object(launch_atlas.sys, "version_info", version), \
                 patch.dict(os.environ, {"WMI_PYTHON": supplied}):
                launch_atlas.start_atlas(self.here, self.atlas)
                command, options = run.call_args.args[0], run.call_args.kwargs
                self.assertEqual(options["env"]["WMI_PYTHON"], expected)
                self.assertEqual(options["env"]["AXIS_TEST_INHERITED"], "keep this value")
                self.assertEqual(options["cwd"], str(self.atlas))
                self.assertEqual(options["env"]["AXIS_ATLAS_LAUNCHER"], str(self.atlas / "Start-Office-Atlas.bat"))
                self.assertNotIn(str(self.atlas), command)
                self.assertNotIn("runas", command.lower())
                self.assertNotIn("shell", options)
                self.assertNotIn("creationflags", options)
                self.assertEqual(os.environ["WMI_PYTHON"], supplied)

    def test_wrong_account_or_wrong_instance_cannot_start_collectors(self):
        api, run = self.launch_mocks()
        cases = (("identity", "EXAMPLE\\other-user"), ("instance_id", "other-instance"),
                 ("instance_root", str(self.root / "other-install")))
        for field, value in cases:
            with self.subTest(field=field), patch.dict(self.health, {field: value}):
                run.reset_mock()
                api.reset_mock()
                with self.assertRaises(launch_atlas.AtlasLaunchError):
                    launch_atlas.start_atlas(self.here, self.atlas)
                run.assert_called_once_with(["whoami.exe"], capture_output=True, text=True, check=True)
                self.assertFalse(launch_atlas._saved_folder().exists())
                self.assertNotIn("/api/master/status", [call.args[1] for call in api.call_args_list])

    def test_stale_health_is_left_to_existing_launcher_and_verified_after_start(self):
        api, run = self.launch_mocks()
        api.side_effect = [OSError("not running"), self.health, self.status]
        self.assertEqual(launch_atlas.start_atlas(self.here, self.atlas), str(self.database))
        self.assertEqual(run.call_count, 2)

    def test_failed_atlas_start_does_not_save_folder_or_query_database(self):
        api, run = self.launch_mocks()
        run.side_effect = [subprocess.CompletedProcess(["whoami.exe"], 0, self.identity),
                           subprocess.CompletedProcess("launcher", 7)]
        with self.assertRaisesRegex(launch_atlas.AtlasLaunchError, "exit 7"):
            launch_atlas.start_atlas(self.here, self.atlas)
        self.assertEqual(api.call_count, 1)
        self.assertFalse(launch_atlas._saved_folder().exists())

    def test_unavailable_active_database_never_falls_back_to_another_file(self):
        self.launch_mocks()
        for status in ({"available": False, "path": str(self.database)},
                       {"available": True, "path": str(self.atlas / "missing.db")},
                       {"available": True, "path": ""}):
            with self.subTest(status=status), patch.object(self, "status", status):
                with self.assertRaisesRegex(launch_atlas.AtlasLaunchError, "active database is unavailable"):
                    launch_atlas.start_atlas(self.here, self.atlas)
                self.assertFalse(launch_atlas._saved_folder().exists())

    def test_startup_failure_stops_before_model_preparation(self):
        with patch.object(launch_atlas, "start_atlas", side_effect=launch_atlas.AtlasLaunchError("fixture failed")), \
             patch.object(start, "prepare_model") as prepare, patch.object(start, "wait_for_agent") as agent:
            self.assertEqual(start.main(["--with-atlas"]), 1)
        prepare.assert_not_called()
        agent.assert_not_called()
        self.assertIn("fixture failed", self.output.getvalue())

    def test_common_launcher_passes_active_database_and_standalone_keeps_its_override(self):
        cases = ((["--with-atlas"], True), (["--atlas-dir", str(self.atlas)], True),
                 (["--atlas-db", str(self.database)], False))
        for options, shared in cases:
            with self.subTest(options=options), \
                 patch.object(launch_atlas, "start_atlas", return_value=str(self.database)) as atlas, \
                 patch.object(start, "prepare_model", return_value=("35b", "model.gguf")), \
                 patch.object(start, "server_ready", return_value=True), \
                 patch.object(start, "server_model", return_value="fixture-model"), \
                 patch.object(start, "TerminalUI"), \
                 patch.object(start, "wait_for_agent", return_value=0) as agent:
                self.assertEqual(start.main(["--workdir", str(self.here), "--plain"] + options), 0)
                command = agent.call_args.args[0]
                self.assertEqual(command[command.index("--atlas-db") + 1], str(self.database))
                self.assertNotIn("--with-atlas", command)
                self.assertNotIn("--atlas-dir", command)
                self.assertEqual(atlas.call_count, int(shared))

    def test_terminal_inside_aa_uses_the_browser_chat_state_database_and_packages(self):
        aa = self.root / "AA"
        (aa / "axis" / "state" / "jobs").mkdir(parents=True)
        source = Path(start.__file__).resolve().parents[1]
        for name in ("runtime_paths.py", "package_paths.py"):
            shutil.copyfile(source / name, aa / name)
        (aa / "config.json").write_text(json.dumps({"database_folder": str(self.root / "DB"),
                                                    "package_repository": "pkgs"}), encoding="utf-8")
        (aa / "axis" / "state" / "jobs" / "old.json").write_text(json.dumps({"id": "old", "state": "unknown"}))
        expected = {"--state-dir": str(aa / "data" / "axis" / "state"),
                    "--atlas-db": str(self.root / "DB" / "office_atlas.db"), "--package-repo": str(aa / "pkgs")}
        cases = (([], True, expected), (["--state-dir", "mine"], True, dict(expected, **{"--state-dir": "mine"})),
                 ([], False, {}))
        for options, inside, wanted in cases:
            with self.subTest(options=options, inside=inside), \
                 patch.dict(os.environ, {"ATLAS_DB_PATH": "", "WMI_PACKAGE_REPO": "", "AGENT_PACKAGE_REPO": ""}), \
                 patch.object(start, "HERE", str(aa / "axis")), patch.object(start, "AA_ROOT", str(aa)), \
                 patch.object(start, "prepare_model", return_value=("35b", "model.gguf")), \
                 patch.object(start, "server_ready", return_value=True), \
                 patch.object(start, "server_model", return_value="fixture-model"), \
                 patch.object(start, "TerminalUI"), \
                 patch.object(start, "wait_for_agent", return_value=0) as agent:
                launcher = aa / "aa_launcher.py"
                launcher.write_text("") if inside else launcher.unlink(missing_ok=True)
                self.output.truncate(0)
                self.assertEqual(start.main(["--workdir", str(self.here), "--plain"] + options), 0)
                command = agent.call_args.args[0]
                for option in ("--state-dir", "--atlas-db", "--package-repo"):
                    self.assertEqual(command.count(option), int(option in wanted), option)
                    if option in wanted:
                        self.assertEqual(command[command.index(option) + 1], wanted[option])
                self.assertEqual("Earlier terminal jobs" in self.output.getvalue(), inside and not options)

    def test_aa_terminal_refuses_to_start_a_second_atlas(self):
        aa = self.root / "AA"
        (aa / "axis").mkdir(parents=True)
        (aa / "aa_launcher.py").write_text("")
        with patch.object(start, "AA_ROOT", str(aa)), patch.object(launch_atlas, "start_atlas") as atlas, \
             redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit):
                start.main(["--with-atlas"])
        atlas.assert_not_called()
        self.assertIn("AA already includes Atlas", errors.getvalue())

    def test_conflicting_database_override_is_rejected_before_starting_anything(self):
        with patch.object(launch_atlas, "start_atlas") as atlas, patch.object(start, "prepare_model") as prepare, \
             redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as stopped:
                start.main(["--with-atlas", "--atlas-db", str(self.database)])
        self.assertEqual(stopped.exception.code, 2)
        atlas.assert_not_called()
        prepare.assert_not_called()
        self.assertIn("active database automatically", errors.getvalue())

    @unittest.skipUnless(os.name == "nt", "Executes Windows cmd.exe")
    def test_real_atlas_bat_handles_shell_characters_in_installation_path(self):
        folder = self.make_atlas(self.root / "Atlas & (team) %AXIS_TEST_TOKEN% !ready!")
        (folder / "data").mkdir()
        database = folder / "data" / "office_atlas.db"
        database.write_bytes(b"fixture")
        (folder / "Start-Office-Atlas.bat").write_bytes(
            b'@echo off\r\n"%AXIS_TEST_PYTHON%" fixture.py\r\nexit /b %errorlevel%\r\n')
        (folder / "fixture.py").write_text(
            "from pathlib import Path\nPath('launched.txt').write_text('started', encoding='utf-8')\n", encoding="utf-8")
        status = {"available": True, "path": str(database)}
        with patch.dict(os.environ, {"AXIS_TEST_PYTHON": sys.executable, "AXIS_TEST_TOKEN": "must-not-expand"}), \
             patch.object(launch_atlas, "_active_port", return_value=18770), \
             patch.object(launch_atlas, "_get_json", return_value=status):
            self.assertEqual(launch_atlas.start_atlas(self.here, folder), str(database))
        self.assertEqual((folder / "launched.txt").read_text(encoding="utf-8"), "started")

if __name__ == "__main__":
    unittest.main()
