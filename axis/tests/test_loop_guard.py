"""Repeated lookup handling without caching live state or granting approval."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def call(identifier, name, args):
    return {"id": identifier, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}


def round_of(*calls):
    return {"role": "assistant", "content": "", "tool_calls": list(calls)}


class LoopGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ui = MagicMock()
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            self.agent = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.root), False, False,
                                     notes=str(self.root / "notes"), state_dir=str(self.root / "state"), ui=self.ui)

    def tearDown(self):
        self.temporary.cleanup()

    def script(self, calls):
        self.agent.chat = Mock(side_effect=[round_of(c) for c in calls] + [
            {"role": "assistant", "content": "Done."}])

    def test_case_only_note_search_repeat_reuses_result_with_guidance(self):
        self.agent.search_notes = Mock(return_value="Install the selected package.")
        self.script([call("first", "search_notes", {"query": " Package "}),
                     call("repeat", "search_notes", {"query": "PACKAGE"})])
        self.assertEqual(self.agent.run("Look up package notes"), "Done.")
        self.agent.search_notes.assert_called_once()
        replies = [m["content"] for m in self.agent.messages if m["role"] == "tool"]
        self.assertIn("Install the selected package.", replies[1])
        self.assertIn("was not repeated", replies[1])

    def test_persistent_lookup_loop_stops_before_pending_actions_and_preserves_pairs(self):
        self.agent.call_tool = Mock(return_value="No matching notes.")
        self.agent.chat = Mock(side_effect=[
            round_of(call("first", "search_notes", {"query": "package"})),
            round_of(call("repeat", "search_notes", {"query": "PACKAGE"})),
            round_of(call("again", "search_notes", {"query": "package"}),
                     call("not-run", "write_file", {"path": "change.txt", "content": "change"})),
        ])
        answer = self.agent.run("Look up a package")
        self.assertIn("kept repeating", answer)
        self.agent.call_tool.assert_called_once_with("search_notes", {"query": "package"})
        self.assertEqual(self.agent.chat.call_count, 3)
        replies = [m for m in self.agent.messages if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in replies], ["first", "repeat", "again", "not-run"])
        self.assertIn("Not run", replies[-1]["content"])
        self.assertEqual(self.agent.messages[-1], {"role": "assistant", "content": answer})
        self.agent.chat = Mock(return_value={"role": "assistant", "content": "Ready."})
        self.assertEqual(self.agent.run("Continue"), "Ready.")

    def test_package_pages_actions_and_selections_are_independent(self):
        self.agent.call_tool = Mock(return_value='{"packages": ["App 1", "App 2"]}')
        self.script([
            call("search", "find_packages", {"query": "app"}),
            call("repeat", "find_packages", {"query": "APP", "package": None, "offset": 0, "action": "Install"}),
            call("page", "find_packages", {"query": "app", "offset": 50}),
            call("install", "find_packages", {"package": "App 1"}),
            call("uninstall", "find_packages", {"package": "App 1", "action": "Uninstall"}),
            call("other", "find_packages", {"package": "App 2"}),
        ])
        self.assertEqual(self.agent.run("Inspect package choices"), "Done.")
        self.assertEqual(self.agent.call_tool.call_count, 5)
        self.assertEqual(self.agent.call_tool.call_args_list[1].args[1]["offset"], 50)

    def test_saved_output_pages_and_lengths_are_independent(self):
        self.agent.call_tool = Mock(return_value='{"content": "saved observation"}')
        output = "a" * 32
        self.script([
            call("first", "read_tool_output", {"output_id": output}),
            call("repeat", "read_tool_output", {"output_id": output, "offset": 0, "limit": 2000}),
            call("page", "read_tool_output", {"output_id": output, "offset": 2000}),
            call("length", "read_tool_output", {"output_id": output, "offset": 0, "limit": 1000}),
        ])
        self.assertEqual(self.agent.run("Read the saved result"), "Done.")
        self.assertEqual(self.agent.call_tool.call_count, 3)

    def test_note_results_are_fresh_in_a_new_user_request(self):
        self.agent.search_notes = Mock(side_effect=["Old notes", "Updated notes"])
        self.script([call("first", "search_notes", {"query": "package"})])
        self.agent.run("Read the notes")
        self.script([call("second", "search_notes", {"query": "package"})])
        self.agent.run("I changed the notes; read them again")
        self.assertEqual(self.agent.search_notes.call_count, 2)
        self.assertIn("Updated notes", [m["content"] for m in self.agent.messages if m["role"] == "tool"])

    def test_possible_changes_invalidate_reference_results(self):
        changes = [(name, {}) for name in ("run_command", "write_file", "deploy_package", "computer_action",
                                          "open_remote_tool", "unknown_tool")]
        changes.append(("it_job_status", {"acknowledge_unknown": True}))
        for name, args in changes:
            with self.subTest(name=name):
                self.agent.call_tool = Mock(return_value="Result")
                self.script([call("before", "search_notes", {"query": "package"}),
                             call("change", name, args),
                             call("after", "search_notes", {"query": "package"})])
                self.assertEqual(self.agent.run("Inspect after a change"), "Done.")
                self.assertEqual(self.agent.call_tool.call_count, 3)

    def test_live_reads_and_polling_run_each_time_without_invalidating_notes(self):
        for name in ("inspect_computer", "inspect_computers", "it_job_status", "directory_lookup", "web_search", "web_read", "read_file", "list_dir"):
            with self.subTest(name=name):
                self.agent.call_tool = Mock(return_value="Current observation")
                self.script([call("notes", "search_notes", {"query": "package"}),
                             call("check-1", name, {}), call("check-2", name, {}), call("check-3", name, {}),
                             call("reuse", "search_notes", {"query": "package"})])
                self.assertEqual(self.agent.run("Check current state"), "Done.")
                self.assertEqual(self.agent.call_tool.call_count, 4)
                self.assertEqual(sum(c.args[0] == name for c in self.agent.call_tool.call_args_list), 3)

    def test_transient_lookup_errors_can_be_retried(self):
        for error in ("Error: temporarily unavailable", '{"error":"temporarily unavailable"}'):
            with self.subTest(error=error):
                self.agent.call_tool = Mock(side_effect=[error, error, "Available now"])
                self.script([call(str(i), "find_packages", {"query": "app"}) for i in range(3)])
                self.assertEqual(self.agent.run("Find a package"), "Done.")
                self.assertEqual(self.agent.call_tool.call_count, 3)

    def test_declined_change_is_not_requested_again_until_a_new_user_request(self):
        self.ui.confirm.side_effect = [False, True]
        args = {"path": "example.txt", "content": "updated"}
        self.script([call("first", "write_file", args), call("repeat", "write_file", args)])
        self.agent.run("Write an example")
        self.ui.confirm.assert_called_once()
        self.assertFalse((self.root / "example.txt").exists())
        self.script([call("new-request", "write_file", args)])
        self.agent.run("I changed my mind; write the example")
        self.assertEqual(self.ui.confirm.call_count, 2)
        self.assertEqual((self.root / "example.txt").read_text(), "updated")

    def test_approval_is_never_reused_to_repeat_a_change_silently(self):
        self.ui.confirm.side_effect = [True, False]
        args = {"path": "example.txt", "content": "updated"}
        self.script([call("first", "write_file", args), call("repeat", "write_file", args)])
        self.agent.run("Write an example")
        self.assertEqual(self.ui.confirm.call_count, 2)
        replies = [m["content"] for m in self.agent.messages if m["role"] == "tool"]
        self.assertEqual(replies, ["Wrote example.txt", "User declined the write."])


if __name__ == "__main__":
    unittest.main()
