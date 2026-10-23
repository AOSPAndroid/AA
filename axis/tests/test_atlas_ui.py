"""Atlas presentation uses synthetic records and no database or network."""
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_ui import TerminalUI, _width


WARNING = "Stored inventory, not live status or current sessions."


class AtlasUITests(unittest.TestCase):
    def test_search_shows_record_ids_source_and_next_page(self):
        output = io.StringIO()
        ui = TerminalUI(stream=output, plain=True, width=110)
        ui.tool_start("search_atlas", {"query": "Marie", "kind": "people"})
        ui.tool_result("search_atlas", json.dumps({
            "items": [{"kind": "people", "id": "account:example\\mdupont", "name": "Marie Dupont", "account": "mdupont"},
                      {"kind": "computers", "id": "PC-042", "name": "PC-042", "model": "Laptop"}],
            "source": {"path": r"F:\Atlas\DB\office_atlas.db", "directory_imported_at": "2026-10-20T08:00:00Z"},
            "warning": WARNING, "offset": 0, "next_offset": 2}), 0.1, "sample-output")
        text = output.getvalue()
        for wanted in ("[Search Atlas]", "kind: people", "Database (read-only)", r"F:\Atlas\DB\office_atlas.db",
                       "Directory imported", "2026-10-20T08:00:00Z", WARNING, "account:example\\mdupont",
                       "Marie Dupont", "PC-042", "search_atlas with offset 2", "/output sample-output"):
            self.assertIn(wanted, text)
        self.assertNotIn('"items"', text)
        self.assertNotIn("State verified", text)

    def test_record_distinguishes_assignment_inventory_logon_and_status(self):
        output = io.StringIO()
        ui = TerminalUI(stream=output, plain=True, width=110, verbose=True)
        ui.tool_start("read_atlas_record", {"kind": "computers", "id": "PC-042"})
        ui.tool_result("read_atlas_record", json.dumps({
            "kind": "computers", "record": {"id": "PC-042", "name": "PC-042", "status": "Operational", "last_logon_user": "jdoe"},
            "links": [{"kind": "people", "id": "account:mdupont", "name": "Marie", "account": "mdupont", "relationship": "Assigned"},
                      {"kind": "people", "id": "account:jdoe", "name": "Jane", "account": "jdoe", "relationship": "Last logged on (inventory)"}],
            "warning": WARNING, "offset": 0, "next_offset": None}), 0)
        text = output.getvalue()
        for wanted in ("[Read Atlas record]", "id: PC-042", "Record ID  PC-042", "Inventory status  Operational",
                       "Last logged on (inventory)", "Assigned", "account:mdupont", "account:jdoe", WARNING):
            self.assertIn(wanted, text)
        self.assertNotIn("next offset", text)
        self.assertNotIn("online", text.lower())

    def test_narrow_output_preserves_long_ids_and_sanitizes_source_and_fields(self):
        record_id = "account:" + "long-account-" * 6
        output = io.StringIO()
        ui = TerminalUI(stream=output, plain=True, width=30)
        ui.tool_result("search_atlas", json.dumps({
            "source": {"path": "database\x1b[2J.db"}, "warning": WARNING,
            "items": [{"kind": "people", "id": record_id, "name": "Marie\x1b]0;hidden\x07", "account": "mdupont"}]}), 0)
        ui.tool_result("search_atlas", json.dumps({"items": [], "warning": WARNING}), 0)
        ui.tool_result("read_atlas_record", json.dumps({"error": "Database is locked", "warning": WARNING}), 0)
        text = output.getvalue()
        self.assertIn(record_id, "".join(line.strip() for line in text.splitlines()))
        self.assertIn("database.db", text)
        self.assertIn("No matching Atlas records.", text)
        self.assertIn("Database is locked", text)
        self.assertIn("[!] Request failed", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("hidden", text)
        self.assertTrue(all(_width(line) <= 30 for line in text.splitlines()))

    def test_verbose_displays_all_returned_rows_and_banner_is_optional(self):
        for verbose in (False, True):
            output = io.StringIO()
            ui = TerminalUI(stream=output, plain=True, verbose=verbose)
            ui.banner("Qwen", "workspace", 16384, True, False)
            self.assertNotIn("ATLAS", output.getvalue())
            ui.banner("Qwen", "workspace", 16384, True, False, atlas="read-only database.db")
            ui.tool_result("search_atlas", json.dumps({
                "items": [{"kind": "computers", "id": "PC-%02d" % i, "name": "PC-%02d" % i} for i in range(12)],
                "warning": WARNING}), 0)
            self.assertIn("ATLAS  read-only database.db", output.getvalue())
            self.assertEqual("PC-11" in output.getvalue(), verbose)
            self.assertEqual("Showing 10 of 12" in output.getvalue(), not verbose)

    def test_non_windows_devices_and_inventory_ids_are_not_presented_as_targets(self):
        phone = {"kind": "computers", "id": "INVENTORY-123", "name": "Phone", "device_kind": "phone", "windows_remote_supported": False}
        pc = {"kind": "computers", "id": "PC-042", "name": "PC-042", "device_kind": "computer", "windows_remote_supported": True}
        output = io.StringIO()
        ui = TerminalUI(stream=output, plain=True, verbose=True, width=110)
        ui.tool_result("search_atlas", json.dumps({"items": [phone, pc], "warning": WARNING}), 0)
        ui.tool_result("read_atlas_record", json.dumps({"record": phone, "links": [], "warning": WARNING}), 0)
        ui.tool_result("read_atlas_record", json.dumps({"record": {"id": "person:1", "name": "Marie"}, "links": [phone], "warning": WARNING}), 0)
        text = output.getvalue()
        self.assertIn("Device type", text)
        self.assertIn("Device type  phone", text)
        self.assertEqual(text.count("Windows actions unsupported for INVENTORY-123"), 3)
        self.assertNotIn("Windows actions unsupported for PC-042", text)
        self.assertNotIn("Windows remote supported", text)
        self.assertNotIn("verified", text.lower())
        self.assertIn("device type or inventory-only ID", text)


if __name__ == "__main__":
    unittest.main()
