"""Lifecycle tests; no remote computers, model weights or Atlas services needed."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.launch import aa_launcher as aa


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(aa, "ROOT", self.root))
        self.stack.enter_context(patch.object(aa, "STATE", self.root / "data" / "axis"))
        self.args = argparse.Namespace(model=None, ctx=None, cpu=True, gpu=False,
                                       plain=True, no_browser=False)

    def patch(self, target, **kwargs):
        return self.stack.enter_context(patch(target, **kwargs))

    def record(self, **changes):
        record = dict(root=str(self.root), pid=4321, created="987654321",
                      executable=str(self.root / "llama-server.exe"), model="test-model")
        record.update(changes)
        aa._write(aa.STATE / "model-process.json", record)
        return record

    def process(self, metadata):
        handle = Mock()
        handle.metadata.return_value = metadata
        factory = self.patch("backend.launch.aa_launcher._WindowsProcess")
        factory.return_value.__enter__.return_value = handle
        return factory, handle

    def prepare_start(self, catalog=None):
        self.patch("backend.launch.aa_launcher.axis.server_ready", return_value=False)
        self.patch("backend.launch.aa_launcher._port_busy", return_value=False)
        self.patch("backend.launch.aa_launcher.axis.prepare_model", return_value=("test", "model.gguf"))
        self.patch("backend.launch.aa_launcher.axis.find_server", return_value=str(self.root / "llama-server.exe"))
        self.patch("backend.launch.aa_launcher.axis.MODELS", new={"test": catalog or {"name": "test-model"}})
        self.patch("backend.launch.aa_launcher.axis.TerminalUI")

    def test_reused_external_model_is_not_owned_or_stopped(self):
        self.patch("backend.launch.aa_launcher.axis.server_ready", return_value=True)
        self.patch("backend.launch.aa_launcher.axis.server_model", return_value="external-model")
        self.patch("backend.launch.aa_launcher._running_context", return_value=8192)
        factory = self.patch("backend.launch.aa_launcher._WindowsProcess")
        prepare = self.patch("backend.launch.aa_launcher.axis.prepare_model")
        aa._start_model(self.args)
        aa._stop_model()
        self.assertFalse((aa.STATE / "model-process.json").exists())
        self.assertEqual(aa._read(aa.STATE / "model-settings.json"), {
            "model": "external-model", "ctx": 8192, "think": True,
            "managed": False, "sampling": {}})
        prepare.assert_not_called()
        factory.assert_not_called()

    def test_reuse_does_not_overwrite_existing_ownership_record(self):
        original = self.record()
        self.patch("backend.launch.aa_launcher.axis.server_ready", return_value=True)
        self.patch("backend.launch.aa_launcher.axis.server_model", return_value="external-model")
        self.patch("backend.launch.aa_launcher._running_context", return_value=4096)
        aa._start_model(self.args)
        self.assertEqual(aa._read(aa.STATE / "model-process.json"), original)

    def test_stop_verifies_metadata_then_terminates_same_handle(self):
        record = self.record()
        factory, handle = self.process(record)
        aa._stop_model()
        factory.assert_called_once_with(4321, terminate=True)
        handle.stop.assert_called_once_with()
        self.assertFalse((aa.STATE / "model-process.json").exists())

    def test_recycled_pid_or_different_executable_is_not_stopped(self):
        for changes in ({"created": "999999999"}, {"executable": str(self.root / "other.exe")}):
            with self.subTest(changes=changes):
                record = self.record()
                _, handle = self.process(dict(record, **changes))
                with self.assertRaisesRegex(RuntimeError, "another process"):
                    aa._stop_model()
                handle.stop.assert_not_called()
                self.assertEqual(aa._read(aa.STATE / "model-process.json"), record)

    def test_unavailable_metadata_retains_record_and_process(self):
        record = self.record()
        _, handle = self.process(record)
        handle.metadata.side_effect = PermissionError("Access denied")
        with self.assertRaises(PermissionError):
            aa._stop_model()
        handle.stop.assert_not_called()
        self.assertEqual(aa._read(aa.STATE / "model-process.json"), record)

    def test_gone_process_removes_only_stale_record(self):
        self.record()
        self.patch("backend.launch.aa_launcher._WindowsProcess", side_effect=ProcessLookupError(4321))
        aa._stop_model()
        self.assertFalse((aa.STATE / "model-process.json").exists())

    def test_foreign_record_cannot_stop_process(self):
        self.record(root=str(self.root / "other-aa"))
        factory = self.patch("backend.launch.aa_launcher._WindowsProcess")
        with self.assertRaisesRegex(RuntimeError, "Invalid model ownership"):
            aa._stop_model()
        factory.assert_not_called()

    def test_missing_or_failed_model_leaves_no_owner_record(self):
        self.prepare_start()
        self.patch("backend.launch.aa_launcher.axis.start_server", return_value=None)
        with self.assertRaisesRegex(RuntimeError, "Model startup failed"):
            aa._start_model(self.args)
        self.assertFalse((aa.STATE / "model-process.json").exists())

    def test_new_model_uses_catalog_and_persists_settings(self):
        catalog = {"name": "test-model", "ctx": 8192, "temperature": 1.0,
                   "top_p": 0.9, "server_args": ["--lazy-mode", "on"]}
        self.prepare_start(catalog)
        child = Mock(pid=4321)
        child.poll.return_value = None
        start = self.patch("backend.launch.aa_launcher.axis.start_server", return_value=child)
        record = dict(root=str(self.root), pid=4321, created="987654321",
                      executable=str(self.root / "llama-server.exe"), model="test-model")
        self.patch("backend.launch.aa_launcher._owned_record", return_value=record)
        aa._start_model(self.args)
        self.assertEqual(start.call_args.args[2:4], (8192, False))
        self.assertTrue(start.call_args.kwargs["think"])
        self.assertEqual(start.call_args.kwargs["extra"], ["--lazy-mode", "on"])
        self.assertEqual(aa._read(aa.STATE / "model-settings.json"), {
            "model": "test-model", "ctx": 8192, "think": True, "managed": True,
            "sampling": {"temperature": 1.0, "top_p": 0.9}})
        self.assertEqual(aa._read(aa.STATE / "model-process.json"), record)
        child.terminate.assert_not_called()

    def test_unverified_new_child_is_cleaned_up_and_not_owned(self):
        self.prepare_start()
        child = Mock(pid=4321)
        child.poll.return_value = None
        self.patch("backend.launch.aa_launcher.axis.start_server", return_value=child)
        self.patch("backend.launch.aa_launcher._owned_record", side_effect=RuntimeError("listener belongs to another process"))
        with self.assertRaisesRegex(RuntimeError, "listener"):
            aa._start_model(self.args)
        child.terminate.assert_called_once_with()
        self.assertFalse((aa.STATE / "model-process.json").exists())

    def test_owned_record_requires_child_listener(self):
        record = self.record()
        self.process(record)
        child = Mock(pid=4321)
        child.poll.return_value = None
        self.patch("backend.launch.aa_launcher._listener_pid", return_value=7777)
        self.patch("backend.launch.aa_launcher.axis.server_model", return_value="test-model")
        with self.assertRaisesRegex(RuntimeError, "Cannot verify ownership"):
            aa._owned_record(child, record["executable"], "test-model")

    def test_busy_model_port_never_starts_another_server(self):
        self.patch("backend.launch.aa_launcher.axis.server_ready", return_value=False)
        self.patch("backend.launch.aa_launcher._port_busy", return_value=True)
        prepare = self.patch("backend.launch.aa_launcher.axis.prepare_model")
        with self.assertRaisesRegex(RuntimeError, "Port 8080 is busy"):
            aa._start_model(self.args)
        prepare.assert_not_called()

    def test_other_atlas_account_is_rejected_before_collectors_start(self):
        self.patch("backend.launch.aa_launcher._identity", return_value="DOMAIN\\dsk-user")
        self.patch("backend.launch.aa_launcher._active_port", side_effect=RuntimeError("different Windows account"))
        run = self.patch("backend.launch.aa_launcher.atlas.run")
        with self.assertRaisesRegex(RuntimeError, "different Windows account"):
            aa.start(self.args)
        run.assert_not_called()

    def test_model_missing_still_opens_only_the_ready_admin_map(self):
        self.patch("backend.launch.aa_launcher._identity", return_value="DOMAIN\\dsk-user")
        self.patch("backend.launch.aa_launcher._active_port", return_value=8770)
        run = self.patch("backend.launch.aa_launcher.atlas.run", return_value=0)
        self.patch("backend.launch.aa_launcher._start_model", side_effect=RuntimeError("Model files are not ready"))
        browser = self.patch("backend.launch.aa_launcher.webbrowser.open")
        self.assertEqual(aa.start(self.args), 0)
        run.assert_called_once_with(open_browser=False)
        browser.assert_called_once_with("http://127.0.0.1:8770/")

    def test_foreign_atlas_root_is_not_stopped(self):
        self.patch("backend.launch.aa_launcher.atlas.read_record", return_value={"root": str(self.root / "other")})
        stop = self.patch("backend.launch.aa_launcher.atlas.stop")
        model = self.patch("backend.launch.aa_launcher._stop_model")
        with self.assertRaisesRegex(RuntimeError, "another installation"):
            aa.stop()
        stop.assert_not_called()
        model.assert_not_called()

    def test_startup_lock_excludes_concurrent_launcher(self):
        with aa.target_lock(aa.STATE, "AA-LAUNCHER"):
            with self.assertRaises(RuntimeError):
                with aa.target_lock(aa.STATE, "AA-LAUNCHER"):
                    self.fail("Second launcher acquired a live startup lock")

    @unittest.skipUnless(sys.platform == "win32", "Windows kernel process handles")
    def test_real_windows_process_handle_stop(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            with aa._WindowsProcess(child.pid) as process:
                record = dict(process.metadata(), root=str(self.root), model="test-model")
            aa._write(aa.STATE / "model-process.json", record)
            aa._stop_model()
            child.wait(timeout=10)
            self.assertFalse((aa.STATE / "model-process.json").exists())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)

    @unittest.skipUnless(sys.platform == "win32", "Windows BAT smoke test")
    def test_bat_preserves_python_override_and_launches_from_its_folder(self):
        source = Path(aa.__file__).resolve().parents[2]
        folder = self.root / "AA spaces & ! percent%folder"
        (folder / "windows").mkdir(parents=True)
        (folder / "backend" / "launch").mkdir(parents=True)
        for name in ("Start AA.bat", "Stop AA.bat", "windows/Python_Settings.bat"):
            shutil.copyfile(source / name, folder / name)
        for package in ("backend", "backend/launch"):
            (folder / package / "__init__.py").write_text("", encoding="utf-8")
        (folder / "backend" / "launch" / "aa_launcher.py").write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path('called.json').write_text(json.dumps([sys.argv[1:], sys.executable, os.getcwd()]))\n",
            encoding="utf-8")
        for bat, action in (("Start AA.bat", "start"), ("Stop AA.bat", "stop")):
            env = dict(os.environ, WMI_PYTHON=sys.executable, AA_TEST_BAT=str(folder / bat))
            command = '"%s" /d /v:off /s /c ""%%AA_TEST_BAT%%" --no-browser"' % os.environ["ComSpec"]
            result = subprocess.run(command, env=env, cwd=self.root, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            arguments, executable, working = json.loads((folder / "called.json").read_text())
            self.assertEqual(arguments, [action, "--no-browser"])
            self.assertTrue(aa._same_path(executable, sys.executable))
            self.assertTrue(aa._same_path(working, folder))


if __name__ == "__main__":
    unittest.main()
