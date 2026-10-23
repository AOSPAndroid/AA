"""Check model assembly and launcher configuration using tiny local fixtures."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import start


class ModelPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.here, self.downloads = root / "agent", root / "downloads"
        self.here.mkdir()
        self.downloads.mkdir()
        self.stack.enter_context(patch.object(start, "HERE", str(self.here)))
        self.stack.enter_context(patch.object(start, "SEARCH_DIRS", [str(self.here), str(self.downloads)]))
        self.stack.enter_context(patch.object(start, "PART_SIZE", 4))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))

    def file(self, name, data):
        return {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "parts": [hashlib.sha256(data[i:i + 4]).hexdigest() for i in range(0, len(data), 4)]}

    def catalog(self, files, single=False):
        entry = {"key": "fixture", "name": "Fixture model", "tag": "fixture", "note": "Test"}
        entry.update(files[0] if single else {"files": files})
        (self.here / "models.json").write_text(json.dumps([entry]), encoding="utf-8")
        models = start.load_models()
        self.stack.enter_context(patch.object(start, "MODELS", models))
        return models["fixture"]

    def parts(self, file, data):
        paths = []
        for i in range(0, len(data), 4):
            path = self.downloads / (file["file"] + ".part%03d" % (i // 4 + 1))
            path.write_bytes(data[i:i + 4])
            paths.append(path)
        return paths

    def test_existing_single_file_catalog_remains_loadable(self):
        data = b"existing model"
        file = self.file("single.gguf", data)
        model = self.catalog([file], single=True)
        path = self.downloads / file["file"]
        path.write_bytes(data)
        self.assertEqual(len(model["files"]), 1)
        self.assertEqual(start.model_status(model), ("ready", str(path)))
        self.assertEqual(start.prepare_model(), ("fixture", str(path)))
        self.assertEqual(path.read_bytes(), data)

    def test_split_model_joins_remaining_file_and_keeps_both_together(self):
        first_data, second_data = b"first GGUF file", b"second GGUF file"
        first = self.file("model-00001-of-00002.gguf", first_data)
        second = self.file("model-00002-of-00002.gguf", second_data)
        model = self.catalog([first, second])
        first_path = self.downloads / first["file"]
        first_path.write_bytes(first_data)
        parts = self.parts(second, second_data)
        self.assertEqual(start.model_status(model), ("parts", None))
        self.assertEqual(start.prepare_model("fixture"), ("fixture", str(first_path)))
        self.assertEqual(first_path.read_bytes(), first_data)
        self.assertEqual((first_path.parent / second["file"]).read_bytes(), second_data)
        self.assertTrue(all(not path.exists() for path in parts))
        self.assertEqual(start.model_status(model), ("ready", str(first_path)))

    def test_missing_companion_part_is_reported_before_any_join(self):
        first = self.file("model-00001-of-00002.gguf", b"first file")
        second = self.file("model-00002-of-00002.gguf", b"second file")
        self.catalog([first, second])
        first_parts = self.parts(first, b"first file")
        second_parts = self.parts(second, b"second file")
        missing = second_parts.pop(1)
        missing.unlink()
        with patch.object(start, "join_parts") as join:
            with self.assertRaises(SystemExit):
                start.prepare_model("fixture")
        join.assert_not_called()
        self.assertIn(missing.name, self.output.getvalue())
        self.assertTrue(all(path.exists() for path in first_parts + second_parts))

    def test_interrupted_second_file_resumes_without_rejoining_the_first(self):
        first = self.file("model-00001-of-00002.gguf", b"first file")
        second = self.file("model-00002-of-00002.gguf", b"second file")
        self.catalog([first, second])
        first_path = self.here / first["file"]
        first_path.write_bytes(b"first file")
        parts = self.parts(second, b"second file")
        parts[0].unlink()
        target = self.downloads / (second["file"] + ".joining")
        # Part 1 was committed; an interrupted write left a partial part 2.
        target.write_bytes(b"second")
        state = target.with_name(target.name + ".json")
        state.write_text(json.dumps({"appended": 1, "size": 4}), encoding="utf-8")
        self.assertEqual(start.prepare_model("fixture"), ("fixture", str(first_path)))
        self.assertEqual(first_path.read_bytes(), b"first file")
        self.assertEqual((self.here / second["file"]).read_bytes(), b"second file")
        self.assertFalse(state.exists())
        self.assertFalse(target.exists())

    def test_damaged_companion_part_preserves_downloads_and_existing_file(self):
        first = self.file("model-00001-of-00002.gguf", b"first file")
        second = self.file("model-00002-of-00002.gguf", b"second file")
        self.catalog([first, second])
        first_path = self.here / first["file"]
        first_path.write_bytes(b"first file")
        parts = self.parts(second, b"second file")
        parts[1].write_bytes(b"bad!")
        with self.assertRaisesRegex(SystemExit, "damaged"):
            start.prepare_model("fixture")
        self.assertEqual(first_path.read_bytes(), b"first file")
        self.assertTrue(all(path.exists() for path in parts))
        self.assertFalse((self.downloads / (second["file"] + ".joining")).exists())

    def test_colocation_never_overwrites_an_existing_destination(self):
        first = self.here / "model-00001-of-00002.gguf"
        second = self.downloads / "model-00002-of-00002.gguf"
        duplicate = self.here / second.name
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        duplicate.write_bytes(b"keep me")
        with self.assertRaisesRegex(SystemExit, "already exists"):
            start.same_folder([str(first), str(second)])
        self.assertEqual(duplicate.read_bytes(), b"keep me")
        self.assertEqual(second.read_bytes(), b"second")


class ModelSettingsTests(unittest.TestCase):
    def test_model_settings_and_explicit_overrides_reach_server_and_agent(self):
        settings = {"name": "Split model", "ctx": 8192, "temperature": 1.0, "top_p": 0.95,
                    "server_args": ["--load-mode", "mmap", "--lazy-mode", "on"]}
        cases = [([], 8192, "1.0", "0.95"),
                 (["--ctx", "4096", "--temperature=0.4", "--top-p", "0.8"], 4096, "0.4", "0.8")]
        for args, ctx, temperature, top_p in cases:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
                process = MagicMock()
                stack.enter_context(patch.object(start, "MODELS", {"fixture": settings}))
                stack.enter_context(patch.object(start, "prepare_model", return_value=("fixture", "first.gguf")))
                stack.enter_context(patch.object(start, "server_ready", return_value=False))
                stack.enter_context(patch.object(start, "gpus", return_value=[]))
                stack.enter_context(patch.object(start, "find_server", return_value="llama-server.exe"))
                server = stack.enter_context(patch.object(start, "start_server", return_value=process))
                launch = stack.enter_context(patch.object(start, "wait_for_agent", return_value=0))
                stack.enter_context(patch.object(start, "log"))
                self.assertEqual(start.main(["--model", "fixture", "--workdir", folder] + args), 0)
                self.assertEqual(server.call_args.args[1:3], ("first.gguf", ctx))
                self.assertEqual(server.call_args.kwargs["extra"], settings["server_args"])
                command = launch.call_args.args[0]
                for flag, expected in (("--ctx", str(ctx)), ("--temperature", temperature),
                                       ("--top-p", top_p), ("--model", settings["name"])):
                    self.assertEqual(command.count(flag), 1)
                    self.assertEqual(command[command.index(flag) + 1], expected)
                self.assertIn("--think", command)
                process.terminate.assert_called_once()

    def test_flash_loading_options_are_passed_to_llama_server(self):
        with tempfile.TemporaryDirectory() as folder:
            process = MagicMock()
            process.poll.return_value = None
            extra = ["--load-mode", "mmap", "--lazy-mode", "on"]
            with patch.object(start, "HERE", folder), patch.object(start, "server_ready", return_value=True), \
                 patch.object(start.subprocess, "Popen", return_value=process) as popen, patch.object(start, "log"):
                self.assertIs(start.start_server(str(Path(folder) / "llama-server.exe"),
                                                "first.gguf", 8192, False, extra=extra), process)
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--load-mode"):], extra)


if __name__ == "__main__":
    unittest.main()
