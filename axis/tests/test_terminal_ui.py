"""Presentation tests use in-memory streams; no Windows targets or model needed."""
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_ui import TerminalUI, clean_text, _width


class TTYStream(io.StringIO):
    def isatty(self):
        return True


class UTF8TTYStream(TTYStream):
    @property
    def encoding(self):
        return "utf-8"


class LegacyTTYStream(TTYStream):
    @property
    def encoding(self):
        return "cp1252"


class AsciiStream(io.StringIO):
    @property
    def encoding(self):
        return "ascii"


class TerminalUITests(unittest.TestCase):
    def test_package_results_keep_script_and_package_pagination_distinct(self):
        cases = [
            ({"packages": ["App 1"], "total": 1, "next_offset": None,
              "package": "App 1", "action": "Uninstall", "scripts": ["app_u.ps1"],
              "script_total": 51, "script_next_offset": 50}, "More scripts", "More packages"),
            ({"package": "App 1", "action": "Uninstall", "scripts": ["app_u.ps1"],
              "total": 51, "next_offset": 50}, "More scripts", "More packages"),
            ({"packages": ["App 1", "App 2"], "total": 51, "next_offset": 50},
             "More packages", "More scripts"),
        ]
        for data, expected, absent in cases:
            with self.subTest(data=data):
                stream = io.StringIO()
                ui = TerminalUI(stream=stream, plain=True, width=120)
                ui.tool_result("find_packages", json.dumps(data), 0)
                text = stream.getvalue()
                self.assertIn(expected, text)
                self.assertNotIn(absent, text)
                self.assertIn("offset 50", text)
                if "scripts" in data:
                    self.assertIn("app_u.ps1", text)
                    self.assertIn("Uninstall scripts for App 1", text)

    def test_roles_have_distinct_body_colours_and_readable_icon_headings(self):
        stream = UTF8TTYStream()
        with patch.dict(os.environ, {"WT_SESSION": "test"}, clear=True), patch("terminal_ui._enable_vt", return_value=True):
            ui = TerminalUI(stream=stream, width=36)
        ui.user("Check PC-1\x1b[2J")
        ui.write_thinking("Checking the target.")
        for piece in ("Target ", "**ready", "**", "*"):
            ui.write_response(piece)
        ui.end_response()
        ui.tool_start("inspect_computer", {"computer": "PC-1"})
        text = stream.getvalue()
        for role, body in (("user", "Check PC-1"), ("dim", "Checking the target."), ("assistant", "Target ")):
            self.assertIn("\x1b[" + ui._tones[role] + "m" + body, text)
        self.assertEqual(len({ui._tones[r] for r in ("user", "assistant", "dim")}), 3)
        self.assertIn("\x1b[1;" + ui._tones["assistant"] + "mready", text)
        self.assertIn("\x1b[" + ui._tones["assistant"] + "m*", text)
        shown = clean_text(text)
        for label in ("\U0001f4ac You", "\U0001f916 AXIS", "\U0001f4ad Thinking", "\U0001f527 Inspect computer"):
            self.assertIn(label, shown)
        self.assertTrue(all(_width(line) <= 36 for line in shown.splitlines()))
        self.assertNotIn("\x1b[2J", text)
        self.assertIsNone(ui._activity)

    def test_role_icons_fall_back_to_text_without_terminal_support(self):
        cases = ((UTF8TTYStream, True, {}, True),
                 (UTF8TTYStream, False, {"NO_COLOR": "1"}, True),
                 (UTF8TTYStream, False, {"TERM": "dumb"}, True),
                 (UTF8TTYStream, False, {}, False),
                 (LegacyTTYStream, False, {}, True),
                 (io.StringIO, False, {}, True))
        for stream_type, plain, environment, vt in cases:
            with self.subTest(stream=stream_type.__name__, plain=plain, environment=environment, vt=vt):
                stream = stream_type()
                with patch.dict(os.environ, environment, clear=True), patch("terminal_ui._enable_vt", return_value=vt):
                    ui = TerminalUI(stream=stream, plain=plain)
                ui.user("Check PC-1")
                ui.write_thinking("Checking.")
                ui.assistant("Ready.")
                ui.tool_start("inspect_computer", {})
                self.assertFalse(ui.icons)
                self.assertTrue(stream.getvalue().isascii())
                for label in ("You", "AXIS", "Thinking", "Inspect computer"):
                    self.assertIn(label, stream.getvalue())
                if not ui.color:
                    self.assertNotIn("\x1b", stream.getvalue())

    def test_input_colour_resets_after_success_interrupt_and_eof(self):
        for failure in (None, KeyboardInterrupt, EOFError):
            with self.subTest(failure=failure):
                stream = TTYStream()
                with patch.dict(os.environ, {}, clear=True), patch("terminal_ui._enable_vt", return_value=True):
                    ui = TerminalUI(stream=stream)

                def read(prompt):
                    self.assertEqual(prompt, "")
                    self.assertTrue(stream.getvalue().endswith("\x1b[" + ui._tones["user"] + "m"))
                    self.assertIsNone(ui._activity)
                    self.assertFalse(ui._thinking_open)
                    if failure:
                        raise failure()
                    return "Check PC-1"

                ui._input_fn = read
                ui.write_thinking("Ready for input.")
                if failure:
                    with self.assertRaises(failure):
                        ui.prompt()
                else:
                    self.assertEqual(ui.prompt(), "Check PC-1")
                self.assertIn("You > ", clean_text(stream.getvalue()))
                self.assertTrue(stream.getvalue().endswith("\x1b[0m"))
                self.assertIsNone(ui._activity)

    def test_plain_paste_input_uses_supplied_reader_without_escape_sequences(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, input_fn=lambda _: self.fail("wrong reader"))
        self.assertEqual(ui.read_input(input_fn=lambda prompt: "a pasted line"), "a pasted line")
        self.assertEqual(stream.getvalue(), "")

    def test_plain_and_no_color_output_contains_no_ansi(self):
        for plain, environment in ((True, {}), (False, {"NO_COLOR": "1"})):
            stream = TTYStream()
            with patch.dict(os.environ, environment, clear=True), patch("terminal_ui._enable_vt", return_value=True):
                ui = TerminalUI(stream=stream, plain=plain, width=72)
                ui.banner("Qwen", r"C:\Work", 16384, False, False)
                ui.assistant("Hello **world**.")
                ui.notice("Ready")
            self.assertNotIn("\x1b", stream.getvalue())
            self.assertIn("Qwen", stream.getvalue())

    def test_controls_and_bidi_cannot_change_the_terminal(self):
        dirty = "first\x1b[2J\x1b]0;hidden title\x07last\r\b\u202eevil"
        self.assertEqual(clean_text(dirty), "firstlastevil")
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, input_fn=lambda _: "n", plain=True, width=50)
        ui.confirm("run " + dirty)
        shown = stream.getvalue()
        self.assertNotIn("\x1b", shown)
        self.assertNotIn("\r", shown)
        self.assertNotIn("\u202e", shown)
        self.assertIn(r"\x1b[2J", shown)
        self.assertIn(r"\u202e", shown)

    def test_approval_is_complete_wrapped_and_defaults_to_no(self):
        action = "deploy " + "long-package-name-" * 12 + " on PC-123 final-evidence"
        for answer, expected in (("", False), ("no", False), ("yes", True), ("Y", True)):
            stream = io.StringIO()
            ui = TerminalUI(stream=stream, plain=True, width=36, input_fn=lambda _, a=answer: a)
            self.assertEqual(ui.confirm(action), expected)
            self.assertIn("final-evidence", stream.getvalue())
            self.assertTrue(all(len(line) <= 36 for line in stream.getvalue().splitlines()))
            self.assertIn("[y/N]", stream.getvalue())

    def test_streamed_bold_markers_split_between_chunks(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True)
        for piece in ("Hello *", "*world", "*", "* and *", "single"):
            ui.write_response(piece)
        ui.end_response()
        self.assertIn("Hello world and *single", stream.getvalue())
        self.assertEqual(stream.getvalue().count("[AXIS]"), 1)
        self.assertNotIn("**", stream.getvalue())

    def test_logo_has_no_tagline(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, width=90)
        ui.banner("Qwen", r"C:\Work", 16384, True, False)
        self.assertIn("AXIS", stream.getvalue())
        self.assertNotIn("LOCAL INTELLIGENCE", stream.getvalue())
        self.assertNotIn("REAL ACTIONS", stream.getvalue())

    def test_thinking_is_visible_in_normal_verbose_and_plain_output(self):
        for plain, verbose in ((False, False), (False, True), (True, False)):
            with self.subTest(plain=plain, verbose=verbose):
                stream = io.StringIO()
                ui = TerminalUI(stream=stream, plain=plain, verbose=verbose)
                ui.write_thinking("The package and target are known. ")
                ui.write_thinking("Proceed to the requested action.")
                ui.assistant("Ready to deploy.")
                output = stream.getvalue()
                self.assertIn("The package and target are known. Proceed to the requested action.", output)
                self.assertIn("Ready to deploy.", output)
                self.assertLess(output.index("Proceed to"), output.index("Ready to deploy"))
                self.assertEqual(output.count("Thinking"), 1)
                self.assertFalse(ui._thinking_open)
                self.assertIsNone(ui._activity)

    def test_job_state_never_implies_verified_installation(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, width=90)
        ui.tool_result("deploy_package", json.dumps({"job_id": "a" * 32, "state": "queued", "message": "Accepted; check job status"}), 0.2)
        ui.jobs({"id": "a" * 32, "kind": "deploy", "state": "complete", "results": [
            {"computer": "PC-1", "state": "script_succeeded", "exit_code": 0, "application_verified": False},
            {"computer": "PC-2", "state": "reboot_required", "exit_code": 3010, "application_verified": False},
            {"computer": "PC-3", "state": "unknown", "message": "Monitoring lost"}]})
        text = stream.getvalue()
        for required in ("QUEUED", "FINISHED", "SCRIPT EXIT 0", "REBOOT REQUIRED", "UNKNOWN", "PC-1", "PC-2", "PC-3", "Application health is not verified"):
            self.assertIn(required, text)
        self.assertNotIn("installation verified", text.lower())

    def test_narrow_and_ascii_only_terminals(self):
        stream = AsciiStream()
        ui = TerminalUI(stream=stream, width=30)
        ui.banner("A model", r"C:\very\long\workspace\folder", 16384, True, True, r"C:\long\package\repository")
        ui.jobs({"jobs": [{"id": "a" * 32, "computers": ["PC-123", "PC-456"], "kind": "deploy", "state": "unknown"}]})
        self.assertTrue(stream.getvalue().isascii())
        self.assertTrue(all(len(line) <= 30 for line in stream.getvalue().splitlines()))
        self.assertIn("UNKNOWN", stream.getvalue())

    def test_noninteractive_status_is_silent(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream)
        with ui.status("Waiting"):
            pass
        self.assertEqual(stream.getvalue(), "")

    def test_spinner_does_not_run_without_terminal_support(self):
        stream = TTYStream()
        with patch("terminal_ui._enable_vt", return_value=False):
            ui = TerminalUI(stream=stream)
        with ui.status("Waiting"):
            self.assertIsNone(ui._activity)
        self.assertEqual(stream.getvalue(), "")

    def test_semantic_result_colors_and_failure_log_locations(self):
        stream = TTYStream()
        with patch.dict(os.environ, {}, clear=True), patch("terminal_ui._enable_vt", return_value=True):
            ui = TerminalUI(stream=stream, width=100)
        ui.jobs({"id": "a" * 32, "kind": "deploy", "state": "unknown", "results": [
            {"computer": "PC-1", "state": "failed", "remote_log": r"C:\Temp\LocalAgent\Jobs\abc\output.log"},
            {"computer": "PC-2", "state": "unknown"}, {"computer": "PC-3", "state": "copied"},
            {"computer": "PC-4", "state": "script_succeeded", "application_verified": False}]})
        text = stream.getvalue()
        self.assertIn("\x1b[31mFAILED", text)
        self.assertIn("\x1b[33mUNKNOWN", text)
        self.assertIn("\x1b[32mCOPIED", text)
        self.assertIn("\x1b[36mSCRIPT EXIT 0", text)
        self.assertIn("PC-1 installer log", text)
        self.assertIn(r"C:\Temp\LocalAgent\Jobs\abc\output.log", text)

    def test_empty_item_record_is_rendered_gracefully(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True)
        ui.tool_result("inspect_computer", '{"items":[{}]}', 0.1)
        self.assertIn("No displayable fields", stream.getvalue())

    def test_web_search_shows_titles_snippets_and_source_urls(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, width=90)
        ui.tool_start("web_search", {"query": "installer exit code 3010", "max_results": 5})
        ui.tool_result("web_search", json.dumps({
            "query": "installer exit code 3010", "provider": "DuckDuckGo",
            "results": [{"title": "Windows Installer error codes", "url": "https://learn.microsoft.com/example",
                         "snippet": "A restart is required to complete the install."}],
            "untrusted_content": True, "fetched_at": "2026-10-22T12:00:00Z"}), 0.2, output_id="a" * 32)
        text = stream.getvalue()
        for required in ("[Search web]", "installer exit code 3010", "DuckDuckGo",
                         "1. Windows Installer error codes", "https://learn.microsoft.com/example",
                         "A restart is required", "/output " + "a" * 32):
            self.assertIn(required, text)
        self.assertNotIn('"results":', text)
        self.assertNotIn("verified", text.lower())

    def test_web_page_excerpt_links_and_pagination(self):
        data = {"url": "https://example.com/guide", "title": "Install guide",
                "text": "\n".join("Page line %d" % i for i in range(18)),
                "links": [{"id": i, "text": "Reference %d" % i, "url": "https://example.com/ref%d" % i}
                          for i in range(1, 9)], "offset": 0, "next_offset": 6000,
                "link_offset": 0, "total_links": 40, "next_link_offset": 8,
                "total_characters": 9000, "cached": False, "content_type": "text/html",
                "fetched_at": "2026-10-22T12:00:00Z", "untrusted_content": True}
        for verbose in (False, True):
            stream = io.StringIO()
            ui = TerminalUI(stream=stream, plain=True, width=90, verbose=verbose)
            ui.tool_start("web_read", {"url": data["url"], "offset": 0})
            ui.tool_result("web_read", json.dumps(data), 0.3, output_id="b" * 32)
            text = stream.getvalue()
            for required in ("[Read web page]", "Install guide", "Source  https://example.com/guide",
                             "Fetched  2026-10-22T12:00:00Z", "Page line 0", "Text offset 0",
                             "9000 total characters", "next offset 6000", "Page links (8 returned / 40 total)",
                             "next link offset 8", "1. Reference 1", "https://example.com/ref1",
                             "8. Reference 8", "/output " + "b" * 32):
                self.assertIn(required, text)
            self.assertEqual("Page line 17" in text, verbose)
            self.assertEqual("additional returned text" in text, not verbose)
            self.assertNotIn("verified", text.lower())

    def test_web_errors_empty_results_and_untrusted_terminal_controls(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, width=30)
        ui.tool_result("web_search", json.dumps({"query": "no matches", "provider": "Example",
                                               "results": [], "untrusted_content": True}), 0.1)
        ui.tool_result("web_read", json.dumps({"error": "Unsupported page type", "kind": "web_error"}), 0.1)
        ui.tool_result("web_read", json.dumps({
            "url": "https://example.com/a-long-document", "title": "Title\x1b[2Jafter",
            "text": "Page\x1b]0;hidden\x07 text\r\u202e", "offset": 6000, "next_offset": None,
            "total_characters": 6010, "links": [{"id": 1, "text": "Read\x1b[31m more",
                                                "url": "https://example.com/another-page"}]}), 0.1)
        text = stream.getvalue()
        for required in ("No search results returned.", "Unsupported page type", "Titleafter", "Page text", "Read more"):
            self.assertIn(required, text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\r", text)
        self.assertNotIn("\u202e", text)
        self.assertNotIn("next offset", text)
        self.assertTrue(all(len(line) <= 30 for line in text.splitlines()))

    def test_minimum_width_approval_and_queued_job_remain_readable(self):
        stream = io.StringIO()
        ui = TerminalUI(stream=stream, plain=True, width=20, input_fn=lambda _: "")
        self.assertFalse(ui.confirm("restart PC-123"))
        ui.jobs({"id": "a" * 32, "state": "queued", "computers": ["PC-123"], "results": []})
        self.assertTrue(all(len(line) <= 20 for line in stream.getvalue().splitlines()))
        self.assertIn("PC-123", stream.getvalue())
        self.assertIn("Waiting for per-PC", stream.getvalue())

    def test_spinner_joins_before_approval_and_on_exception(self):
        stream = TTYStream()
        seen = []
        with patch("terminal_ui._enable_vt", return_value=True):
            ui = TerminalUI(stream=stream, input_fn=lambda _: seen.append(ui._activity) or "n")
        with ui.status("Working"):
            time.sleep(0.12)
            ui.confirm("restart PC-1")
        self.assertEqual(seen, [None])
        self.assertIsNone(ui._activity)
        try:
            with ui.status("More work"):
                raise ValueError("test")
        except ValueError:
            pass
        self.assertIsNone(ui._activity)
        self.assertFalse(any(t.name == "local-agent-status" for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
