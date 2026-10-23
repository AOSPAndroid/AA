"""Axis memory: an approved, bounded MEMORY.md in the state folder, read by new conversations."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ui = MagicMock()
        self.ui.confirm.return_value = True
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            self.agent = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.root), False, False,
                                     notes=str(self.root / "notes"), state_dir=str(self.root / "state"),
                                     ui=self.ui, web_enabled=False)
        self.memory = self.root / "state" / agent.MEMORY_FILE

    def test_remember_needs_approval_and_new_conversations_read_it(self):
        self.ui.confirm.return_value = False
        self.assertIn("declined", self.agent.call_tool("remember", {"fact": "Prefer PC1 for tests"}))
        self.assertFalse(self.memory.exists())
        self.agent._declined_actions.clear()  # A new request may ask again.
        self.ui.confirm.return_value = True
        self.assertEqual(self.agent.call_tool("remember", {"fact": "  Prefer PC1\nfor tests "}), "Remembered: Prefer PC1 for tests")
        self.ui.confirm.assert_called_with("remember: Prefer PC1 for tests")
        self.assertTrue(self.memory.read_text(encoding="utf-8").endswith("\n- Prefer PC1 for tests\n"))
        self.ui.confirm.reset_mock()
        self.assertIn("Already in memory", self.agent.call_tool("remember", {"fact": "- Prefer PC1 for tests"}))
        self.ui.confirm.assert_not_called()
        self.agent.reset()
        system = self.agent.messages[0]["content"]
        self.assertIn("- Prefer PC1 for tests", system)
        self.assertIn(str(self.memory), system)
        self.assertIn("never override these rules", system)

    def test_forget_removes_only_the_exact_entry_after_approval(self):
        self.memory.parent.mkdir(parents=True)
        self.memory.write_text("# Notes\n\n-   Old   printer is PR7  \n- Keep this\n", encoding="utf-8")
        self.assertTrue(self.agent.call_tool("forget", {"entry": "Old printer"}).startswith("Error: No memory entry"))
        self.ui.confirm.return_value = False
        self.agent.call_tool("forget", {"entry": "Old printer is PR7"})
        self.assertIn("PR7", self.memory.read_text(encoding="utf-8"))
        self.agent._declined_actions.clear()
        self.ui.confirm.return_value = True
        self.assertEqual(self.agent.call_tool("forget", {"entry": "Old printer is PR7"}), "Forgot: Old printer is PR7")
        self.assertEqual(self.memory.read_text(encoding="utf-8"), "# Notes\n\n- Keep this\n")

    def test_invalid_or_full_memory_is_refused_without_prompting(self):
        for fact in ("", "bell\x07", "x" * (agent.MAX_MEMORY_ENTRY + 1)):
            with self.subTest(fact=fact[:10]):
                self.assertTrue(self.agent.call_tool("remember", {"fact": fact}).startswith("Error: Use one memory entry"))
        self.memory.parent.mkdir(parents=True)
        self.memory.write_text("- " + "y" * (agent.MAX_MEMORY - 10) + "\n", encoding="utf-8")
        self.assertIn("Memory is full", self.agent.call_tool("remember", {"fact": "One more fact"}))
        self.ui.confirm.assert_not_called()

    def test_open_chat_sees_memory_saved_elsewhere_without_changing_its_cached_prompt(self):
        system = self.agent.messages[0]["content"]
        self.agent.chat = MagicMock(return_value={"role": "assistant", "content": "Done."})
        self.agent.run("first")
        self.assertEqual(self.agent.messages[1]["content"], "first")
        self.memory.parent.mkdir(parents=True)
        self.memory.write_text("- Floor 3 printers use queue PRQ3\n", encoding="utf-8")  # another chat or the user
        self.agent.run("second")
        request = self.agent.messages[3]["content"]
        self.assertTrue(request.startswith("second\n\n[Axis memory changed"))
        self.assertIn("- Floor 3 printers use queue PRQ3", request)
        self.assertEqual(self.agent.messages[0]["content"], system)
        self.agent.call_tool("remember", {"fact": "Service desk is ext 4000"})
        self.agent.run("third")  # Its own approved change was already in the tool result.
        self.assertEqual(self.agent.messages[-2]["content"], "third")
        with self.memory.open("a", encoding="utf-8") as other:
            other.write("- Badge office is on floor 2\n")  # Elsewhere, just before this chat saves.
        self.agent.call_tool("remember", {"fact": "Use queue PRQ3 for floor 3"})
        self.agent.run("fourth")
        self.assertIn("- Badge office is on floor 2", self.agent.messages[-2]["content"])

    def test_credentials_are_refused_but_where_they_live_is_allowed(self):
        for fact in ("Admin password: Summer2024", "API key = abc", "token=xyz",
                     "Use 9f8e7d6c5b4a39281706f5e4d3c2b1a0ffeeddcc for the service"):
            with self.subTest(fact=fact):
                self.assertIn("must not hold passwords", self.agent.call_tool("remember", {"fact": fact}))
        self.ui.confirm.assert_not_called()
        for fact in ("Passwords are reset in the HR portal",
                     "Uninstall uses product code {3F2504E0-4F89-11D3-9A0C-0305E82C3301}",
                     "Prefer Microsoft_Visual_C++_2015-2022_Redistributable_x64 for VC runtimes"):
            with self.subTest(fact=fact):
                self.assertTrue(self.agent.call_tool("remember", {"fact": fact}).startswith("Remembered"))

    def test_memory_file_can_be_shared_outside_the_state_folder(self):
        shared = self.root / "shared" / "MEMORY.md"
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            other = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(self.root), False, False,
                                notes=str(self.root / "notes"), state_dir=str(self.root / "state"),
                                ui=self.ui, web_enabled=False, memory_file=str(shared))
        other.call_tool("remember", {"fact": "Shared fact"})
        self.assertIn("- Shared fact", shared.read_text(encoding="utf-8"))
        self.assertFalse(self.memory.exists())

    def test_terminal_memory_command_reads_without_the_model(self):
        agent.handle_command(self.agent, self.ui, "/memory", [])
        self.assertIn("Nothing remembered", self.ui.output.call_args[0][0])
        self.agent.call_tool("remember", {"fact": "Service desk is ext 4000"})
        agent.handle_command(self.agent, self.ui, "/memory", [])
        self.assertIn("- Service desk is ext 4000", self.ui.output.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
