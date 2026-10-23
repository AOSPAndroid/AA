"""Atlas lookup registration, saved evidence and cache freshness without real records."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def tool_call(identifier, name, arguments):
    return {"id": identifier, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments)}}


class AtlasIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = Mock(available=True, status="Read-only Atlas fixture")
        self.backend.fingerprint.return_value = ("fixture.db", 1, 100, None)
        self.backend.call.return_value = {"items": [{"kind": "people", "id": "u1", "name": "Example Person"}]}
        self.ui = MagicMock()

    def tearDown(self):
        self.temporary.cleanup()

    def make_agent(self):
        with patch.object(agent, "system_facts", return_value=("Test PC", False)), \
                patch.object(agent, "AtlasDatabase", return_value=self.backend):
            return agent.Agent("http://127.0.0.1:8080/v1", "test", str(self.root), False, False,
                               notes=str(self.root / "notes"), state_dir=str(self.root / "state"),
                               ui=self.ui, web_enabled=False, atlas_db="fixture.db")

    def test_registration_uses_configured_database_without_reading_records_at_startup(self):
        instance = self.make_agent()
        names = {tool["function"]["name"] for tool in instance.tools}
        self.assertTrue({"search_atlas", "read_atlas_record"} <= names)
        self.assertIn("stored records, not live observations", instance.messages[0]["content"])
        self.backend.call.assert_not_called()
        self.backend.fingerprint.assert_not_called()
        self.backend.available = False
        self.backend.status = "Atlas database not configured"
        instance = self.make_agent()
        names = {tool["function"]["name"] for tool in instance.tools}
        self.assertTrue(names.isdisjoint({"search_atlas", "read_atlas_record"}))
        self.assertNotIn("Use search_atlas first", instance.messages[0]["content"])

    def test_lookup_saves_evidence_without_running_commands_or_asking_approval(self):
        instance = self.make_agent()
        instance.chat = Mock(side_effect=[
            {"content": "", "tool_calls": [tool_call("directory", "search_atlas", {"query": "Example"})]},
            {"content": "Found Example Person."},
        ])
        with patch.object(agent.subprocess, "Popen") as process:
            self.assertEqual(instance.run("Find Example in Atlas"), "Found Example Person.")
        process.assert_not_called()
        self.ui.confirm.assert_not_called()
        self.backend.call.assert_called_once_with("search_atlas", {"query": "Example"})
        replies = [message for message in instance.messages if message["role"] == "tool"]
        self.assertEqual(replies[0]["tool_call_id"], "directory")
        saved = self.root / "state" / "outputs" / (instance.last_output_id + ".txt")
        self.assertEqual(json.loads(saved.read_text()), self.backend.call.return_value)

    def test_repeated_reference_is_reused_but_a_changed_database_is_read_again(self):
        instance = self.make_agent()
        self.assertIsNone(instance.guarded_lookup("search_atlas", {"query": "Example"})[1])
        self.assertEqual(instance.guarded_lookup("search_atlas", {"query": " example "})[1], "reuse")
        self.assertEqual(self.backend.call.call_count, 1)
        self.backend.fingerprint.return_value = ("fixture.db", 1, 100, (2, 200))
        self.backend.call.return_value = {"items": [{"id": "new", "name": "Updated Person"}]}
        result, repeated = instance.guarded_lookup("search_atlas", {"query": "Example"})
        self.assertIsNone(repeated)
        self.assertIn("Updated Person", result)
        self.assertEqual(self.backend.call.call_count, 2)

    def test_kind_pages_and_record_ids_do_not_share_cached_results(self):
        instance = self.make_agent()
        calls = [("search_atlas", {"query": "Example"}),
                 ("search_atlas", {"query": "Example", "kind": "people"}),
                 ("search_atlas", {"query": "Example", "offset": 10}),
                 ("read_atlas_record", {"kind": "people", "id": "u1"}),
                 ("read_atlas_record", {"kind": "people", "id": "u1", "offset": 25}),
                 ("read_atlas_record", {"kind": "people", "id": "u2"})]
        for name, args in calls:
            self.assertIsNone(instance.guarded_lookup(name, args)[1])
        self.assertEqual(self.backend.call.call_count, len(calls))

    def test_database_errors_are_not_cached_and_next_request_gets_fresh_results(self):
        instance = self.make_agent()
        self.backend.call.side_effect = [{"error": "Database is locked"}, {"items": []}]
        for _ in range(2):
            self.assertIsNone(instance.guarded_lookup("search_atlas", {"query": "Example"})[1])
        self.backend.call.side_effect = None
        instance.chat = Mock(side_effect=[
            {"content": "", "tool_calls": [tool_call("fresh", "search_atlas", {"query": "Example"})]},
            {"content": "Done."},
        ])
        instance.run("Look up Example again")
        self.assertEqual(self.backend.call.call_count, 3)


if __name__ == "__main__":
    unittest.main()
