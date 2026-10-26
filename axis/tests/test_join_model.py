"""The join tool, on tiny fixture models in temporary folders. Nothing is downloaded or started."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import join_model
import start


def entry(key, name, data):
    return {"key": key, "name": name.title(), "tag": key, "note": "Test", "file": name + ".gguf", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "parts": [hashlib.sha256(data[i:i + 4]).hexdigest() for i in range(0, len(data), 4)]}


class JoinModelTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.here, self.downloads, self.other = root / "local-agent", root / "Downloads", root / "elsewhere"
        for folder in (self.here, self.downloads, self.other):
            folder.mkdir()
        self.data = {"alpha": b"alpha model!", "beta": b"beta weights"}
        (self.here / "models.json").write_text(json.dumps([entry(k, k, d) for k, d in self.data.items()]), encoding="utf-8")
        stack.enter_context(patch.object(start, "HERE", str(self.here)))
        stack.enter_context(patch.object(start, "PART_SIZE", 4))
        stack.enter_context(patch.object(start, "MODELS", start.load_models()))
        stack.enter_context(patch.object(start, "SEARCH_DIRS", [str(self.here), str(self.downloads)]))
        self.output = stack.enter_context(redirect_stdout(io.StringIO()))

    def parts(self, key, folder=None, skip=()):
        data = self.data[key]
        for index in range(0, len(data), 4):
            number = index // 4 + 1
            if number not in skip:
                ((folder or self.downloads) / ("%s.gguf.part%03d" % (key, number))).write_bytes(data[index:index + 4])

    def test_joins_verified_parts_next_to_the_tool_and_removes_them(self):
        self.parts("alpha")
        self.assertEqual(join_model.main([]), 0)
        self.assertEqual((self.here / "alpha.gguf").read_bytes(), self.data["alpha"])
        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assertIn("Model ready: " + str(self.here / "alpha.gguf"), self.output.getvalue())
        self.assertEqual(join_model.main(["--model", "alpha"]), 0)
        self.assertIn("already joined", self.output.getvalue())

    def test_parts_in_another_folder_are_found_with_folder(self):
        self.parts("beta", self.other)
        self.assertEqual(join_model.main([]), 1)
        self.assertEqual(join_model.main(["--folder", str(self.other)]), 0)
        self.assertEqual((self.here / "beta.gguf").read_bytes(), self.data["beta"])

    def test_asks_which_model_when_several_can_be_joined(self):
        self.parts("alpha")
        self.parts("beta")
        with patch("builtins.input", return_value="2"):
            self.assertEqual(join_model.main([]), 0)
        self.assertTrue((self.here / "beta.gguf").exists())
        self.assertFalse((self.here / "alpha.gguf").exists())

    def test_explains_unfinished_renamed_and_wrong_size_parts(self):
        self.parts("alpha", skip=(1, 2, 3))
        (self.downloads / "alpha.gguf.part001.crdownload").write_bytes(b"al")
        (self.downloads / "alpha.gguf (1).part002").write_bytes(b"a mo")
        (self.downloads / "alpha.gguf.part003").write_bytes(b"del!!")
        self.assertEqual(join_model.main([]), 1)
        report = self.output.getvalue()
        self.assertIn("alpha.gguf.part001.crdownload has not finished downloading", report)
        self.assertIn("was renamed by the browser (it was downloaded twice): rename it to alpha.gguf.part002", report)
        self.assertIn("alpha.gguf.part003 is 5 bytes, not 4: delete it and download it again", report)
        self.assertFalse((self.here / "alpha.gguf").exists())

    def test_a_damaged_part_stops_the_join_and_says_which(self):
        self.parts("alpha")
        (self.downloads / "alpha.gguf.part002").write_bytes(b"XXXX")
        self.assertEqual(join_model.main(["--model", "alpha"]), 1)
        self.assertIn("alpha.gguf.part002 is damaged", self.output.getvalue())
        self.assertFalse((self.here / "alpha.gguf").exists())

    def test_a_shared_file_points_at_the_release_that_has_its_parts(self):
        def part(name, data):
            return {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "parts": [hashlib.sha256(data[i:i + 4]).hexdigest() for i in range(0, len(data), 4)]}
        shared = part("base-00002-of-00002.gguf", b"shared table")
        catalog = [{"key": "base", "name": "Base", "tag": "base", "note": "Test", "files": [part("base-00001-of-00002.gguf", b"base")]
                    + [shared]},
                   {"key": "variant", "name": "Variant", "tag": "variant", "note": "Test",
                    "files": [part("variant-00001-of-00002.gguf", b"vari"), {"file": "variant-00002-of-00002.gguf", "same_as": shared["file"]}]}]
        (self.here / "models.json").write_text(json.dumps(catalog), encoding="utf-8")
        (self.downloads / "variant-00001-of-00002.gguf.part001").write_bytes(b"vari")
        with patch.object(start, "MODELS", start.load_models()):
            self.assertEqual(join_model.main(["--model", "variant"]), 1)
        report = self.output.getvalue()
        self.assertIn("base-00002-of-00002.gguf.part001 to part003", report)
        self.assertIn("Download them from " + start.RELEASES + "base\n", report)

    def test_nothing_to_join(self):
        self.assertEqual(join_model.main([]), 1)
        self.assertIn("No model parts found", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
