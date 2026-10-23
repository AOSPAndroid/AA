"""Exercise browser registration, dispatch and saved evidence without network access."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def call(identifier, name, arguments):
    return {"id": identifier, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


class WebIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def make_agent(self, enabled=True):
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            return agent.Agent("http://127.0.0.1:8080/v1", "test-model", str(self.root), False, False,
                               notes=str(self.root / "notes"), state_dir=str(self.root / "state"),
                               ui=MagicMock(), web_enabled=enabled)

    def test_search_then_read_retains_sources_and_tool_call_pairs(self):
        instance = self.make_agent()
        search = {"query": "vendor troubleshooting", "results": [
            {"title": "Vendor guide", "url": "https://example.com/guide", "snippet": "A source to read."}]}
        page = {"url": "https://example.com/guide", "title": "Vendor guide", "text": "Check the documented setting.",
                "links": [], "offset": 0, "next_offset": None, "untrusted_content": True}
        instance.web.call = Mock(side_effect=[json.dumps(search), json.dumps(page)])
        instance.chat = Mock(side_effect=[
            {"content": "", "tool_calls": [call("search", "web_search", {"query": "vendor troubleshooting"})]},
            {"content": "", "tool_calls": [call("read", "web_read", {"url": "https://example.com/guide"})]},
            {"content": "See the vendor guide: https://example.com/guide"},
        ])

        answer = instance.run("Find the vendor's troubleshooting guide and read it")

        self.assertIn("https://example.com/guide", answer)
        self.assertEqual(instance.web.call.call_count, 2)
        replies = [message for message in instance.messages if message["role"] == "tool"]
        self.assertEqual([message["tool_call_id"] for message in replies], ["search", "read"])
        self.assertEqual(json.loads(replies[1]["content"])["url"], page["url"])
        output = self.root / "state" / "outputs" / (instance.last_output_id + ".txt")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), page)
        instance.ui.confirm.assert_not_called()

    def test_disabled_web_hides_schemas_and_rejects_calls_without_a_browser(self):
        with patch.object(agent, "WebTools") as browser:
            instance = self.make_agent(enabled=False)
            names = {entry["function"]["name"] for entry in instance.tools}
            self.assertNotIn("web_search", names)
            self.assertNotIn("web_read", names)
            self.assertIn("read_file", names)
            for name, args in (("web_search", {"query": "anything"}),
                               ("web_read", {"url": "https://example.com"})):
                self.assertIn("disabled", instance.call_tool(name, args))
            browser.assert_not_called()

    def test_web_available_without_network_during_startup(self):
        with patch.object(agent, "WebTools") as browser:
            instance = self.make_agent()
            names = {entry["function"]["name"] for entry in instance.tools}
            self.assertTrue({"web_search", "web_read"}.issubset(names))
            browser.return_value.call.assert_not_called()

    def test_saved_web_page_can_be_read_after_conversation_reset(self):
        instance = self.make_agent()
        text = json.dumps({"url": "https://example.com/guide", "text": "Reference " * 1000})
        instance.web.call = Mock(return_value=text)
        instance.save_output(instance.call_tool("web_read", {"url": "https://example.com/guide"}))
        output_id = instance.last_output_id
        instance.reset()
        result = json.loads(instance.call_tool("read_tool_output", {"output_id": output_id, "offset": 0, "limit": 2000}))
        self.assertEqual(result["content"], text[:2000])
        self.assertEqual(result["next_offset"], 2000)


if __name__ == "__main__":
    unittest.main()
