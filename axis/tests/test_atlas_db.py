"""Local synthetic Atlas inventory; no real people, machines or Atlas server."""
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas_db import AtlasDatabase


SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY,canonical_key TEXT UNIQUE,user_id TEXT,user_id_norm TEXT,
full_name TEXT,full_name_norm TEXT,email TEXT,email_norm TEXT,department TEXT,location TEXT,employee_number TEXT);
CREATE TABLE machines(id INTEGER PRIMARY KEY,machine_name TEXT,machine_name_norm TEXT UNIQUE,
model_id TEXT,operational_status TEXT,assigned_to TEXT,last_logon_user TEXT,serial_number TEXT,short_description TEXT);
CREATE TABLE assignments(user_id_ref INTEGER,machine_id INTEGER,relationship_type TEXT);
CREATE TABLE user_aliases(user_id_ref INTEGER,alias_type TEXT,alias_norm TEXT);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE INDEX ix_users_login ON users(user_id_norm);
CREATE INDEX ix_users_name ON users(full_name_norm);
CREATE INDEX ix_machines_name ON machines(machine_name_norm);
"""


def fixture(path):
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    for uid, key, account, name, email in (
            (1, "person-g", r"EXAMPLE\G001", "Marie Éclair", "marie@example.test"),
            (2, "person-x", r"EXAMPLE\x001", "Other Person", "other@example.test"),
            (3, "person-elsewhere", r"OTHER\x001", "Marie Éclair", "elsewhere@example.test"),
            (4, "person-literal", "literal", "Percent % Under_score", "literal@example.test")):
        con.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (uid, key, account, account.lower(), name, name.lower(), email, email.lower(), "Support", "Paris", str(uid)))
    con.executemany("INSERT INTO user_aliases VALUES(?,?,?)", [(1, "matching_account", "x001"),
                                                             (1, "matching_account", r"example\x001")])
    con.executemany("INSERT INTO machines VALUES(?,?,?,?,?,?,?,?,?)", [
        (1, "PC-001.example.test", "pc-001.example.test", "Test laptop", "Operational", "EXAMPLE\\G001", "EXAMPLE\\x001", "S-001", "Test PC"),
        (2, "PC-001.other.test", "pc-001.other.test", "Test desktop", "Retired", "OTHER\\x001", "", "S-002", ""),
        (3, "PC-002", "pc-002", "Test laptop", "Operational", "", "EXAMPLE\\G001", "S-003", ""),
    ])
    con.executemany("INSERT INTO assignments VALUES(?,?,?)", [(1, 1, "assigned_to"), (1, 3, "last_logon_user"), (2, 1, "last_logon_user"), (3, 2, "assigned_to")])
    con.executemany("INSERT INTO metadata VALUES(?,?)", [("created_at", "old-seed"), ("directory.created_at", "2026-10-22 10:00:00"), ("directory.generation", "current-generation")])
    con.commit()
    con.close()


class AtlasDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "office_atlas.db"
        fixture(self.path)
        self.db = AtlasDatabase(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def search(self, query, **kwargs):
        result = self.db.call("search_atlas", dict(query=query, **kwargs))
        self.assertNotIn("error", result)
        return result

    def test_discovery_uses_explicit_paths_and_refuses_ambiguous_defaults(self):
        other = self.root / "other.db"
        fixture(other)
        with patch.dict(os.environ, {"AGENT_ATLAS_DB": str(other), "ATLAS_DB_PATH": str(self.path)}, clear=True), patch("atlas_db.sqlite3.connect") as connect:
            self.assertEqual(AtlasDatabase().path, other)
            self.assertEqual(AtlasDatabase(self.path).path, self.path)
            connect.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(AtlasDatabase(directory=self.root).path, self.path)
            (self.root / "data").mkdir()
            fixture(self.root / "data" / "office_atlas.db")
            ambiguous = AtlasDatabase(directory=self.root)
            self.assertFalse(ambiguous.available)
            self.assertIn("multiple", ambiguous.status)
        missing = self.root / "absent.db"
        with patch.dict(os.environ, {"ATLAS_DB_PATH": str(self.path)}, clear=True):
            selected = AtlasDatabase(missing)
            self.assertEqual(selected.path, missing)
            self.assertFalse(selected.available)
            self.assertIn("error", selected.call("search_atlas", {"query": "Marie"}))
        self.assertFalse(missing.exists())

    def test_exact_aliases_preserve_separate_accounts_and_domain_boundaries(self):
        result = self.search("x001", kind="people")
        self.assertEqual({r["id"] for r in result["items"]}, {"person-g", "person-x", "person-elsewhere"})
        self.assertEqual(result["match"], "exact")
        self.assertEqual({r["id"] for r in self.search(r"EXAMPLE\x001", kind="people")["items"]}, {"person-g", "person-x"})
        self.assertEqual([r["id"] for r in self.search(r"OTHER\x001", kind="people")["items"]], ["person-elsewhere"])
        self.assertEqual(self.search(r"MISSING\x001", kind="people")["items"], [])

    def test_qualified_lookup_accepts_bare_accounts_when_domain_is_unknown(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE users SET user_id='G002',user_id_norm='g002' WHERE id=4")
        con.commit()
        con.close()
        result = self.search(r"EXAMPLE\x002", kind="people")
        self.assertEqual([r["id"] for r in result["items"]], ["person-literal"])

    def test_phone_mac_and_inventory_records_are_not_windows_targets(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE machines SET model_id='Apple iPhone',machine_name='INVENTORY-SERIAL:PHONE1',machine_name_norm='inventory-serial:phone1' WHERE id=1")
        con.execute("UPDATE machines SET model_id='MacBook Pro' WHERE id=2")
        con.commit()
        con.close()
        phone = self.search("S-001")["items"][0]
        self.assertEqual(phone["device_kind"], "iphone")
        self.assertFalse(phone["windows_remote_supported"])
        mac = self.search("S-002")["items"][0]
        self.assertEqual(mac["device_kind"], "mac")
        self.assertFalse(mac["windows_remote_supported"])
        person = self.db.call("read_atlas_record", {"kind": "people", "id": "person-g"})
        self.assertFalse(person["links"][0]["windows_remote_supported"])
        detail = self.db.call("read_atlas_record", {"kind": "computers", "id": "INVENTORY-SERIAL:PHONE1"})
        self.assertFalse(detail["record"]["windows_remote_supported"])

    def test_unicode_email_names_and_short_pc_names(self):
        self.assertEqual(self.search("MARIE@EXAMPLE.TEST")["items"][0]["id"], "person-g")
        self.assertEqual(len(self.search("Marie Éclair", kind="people")["items"]), 2)
        self.assertEqual(len(self.search("éclair", kind="people")["items"]), 2)
        self.assertEqual(len(self.search("PC-001", kind="computers")["items"]), 2)
        self.assertEqual(self.search("PC-001.example.test")["items"][0]["id"], "PC-001.example.test")

    def test_qualified_lookup_never_uses_a_foreign_or_unqualified_alias(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE users SET user_id='x001',user_id_norm='x001' WHERE id=3")
        con.executemany("INSERT INTO user_aliases VALUES(?,?,?)", [(3, "account", r"other\x001"), (3, "matching_account", "x001")])
        con.commit()
        con.close()
        self.assertEqual({r["id"] for r in self.search(r"EXAMPLE\x001", kind="people")["items"]}, {"person-g", "person-x"})
        self.assertEqual([r["id"] for r in self.search(r"OTHER\x001", kind="people")["items"]], ["person-elsewhere"])

    def test_literal_search_and_sql_injection_never_broaden_the_query(self):
        self.assertEqual(self.search("%")["items"][0]["id"], "person-literal")
        self.assertEqual(len(self.search("_")["items"]), 1)
        self.assertEqual(self.search("'; DROP TABLE users; --")["items"], [])
        self.assertIn("error", self.db.call("search_atlas", {"query": "Marie", "sql": "SELECT * FROM users"}))
        self.assertEqual(len(self.search("Marie")["items"]), 2)

    def test_pages_are_global_and_do_not_switch_from_exact_to_substring(self):
        first = self.search("001", limit=2)
        second = self.search("001", limit=2, offset=first["next_offset"])
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 2)
        self.assertFalse({(r["kind"], r["id"]) for r in first["items"]} & {(r["kind"], r["id"]) for r in second["items"]})
        exhausted = self.search("x001", kind="people", offset=10)
        self.assertEqual(exhausted["match"], "exact")
        self.assertEqual(exhausted["items"], [])
        self.assertIsNone(exhausted["next_offset"])

    def test_record_links_keep_assignment_and_inventory_logon_distinct(self):
        result = self.db.call("read_atlas_record", {"kind": "people", "id": "person-g", "limit": 1})
        self.assertEqual(result["record"]["name"], "Marie Éclair")
        self.assertEqual(result["links"][0]["relationship"], "Assigned")
        self.assertEqual(result["links"][0]["id"], "PC-001.example.test")
        self.assertEqual(result["next_offset"], 1)
        second = self.db.call("read_atlas_record", {"kind": "people", "id": "person-g", "offset": 1})
        self.assertEqual(second["links"][0]["relationship"], "Last logged on (inventory)")
        computer = self.db.call("read_atlas_record", {"kind": "computers", "id": "PC-001.example.test"})
        self.assertEqual({r["id"] for r in computer["links"]}, {"person-g", "person-x"})
        self.assertEqual(result["source"]["directory_imported_at"], "2026-10-22 10:00:00")
        self.assertIn("not live", result["warning"])

    def test_queries_are_read_only_and_missing_files_are_never_created(self):
        original = hashlib.sha256(self.path.read_bytes()).digest()
        with self.db._connect() as (con, tables, columns):
            self.assertEqual(con.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("UPDATE users SET full_name='changed'")
        self.search("Marie")
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), original)
        missing = AtlasDatabase(self.root / "missing.db")
        self.assertIn("error", missing.call("search_atlas", {"query": "Marie"}))
        self.assertFalse(missing.path.exists())

    def test_wal_commits_are_visible_and_change_the_cache_fingerprint(self):
        writer = sqlite3.connect(str(self.path))
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            before = self.db.fingerprint()
            writer.execute("UPDATE users SET department='New team' WHERE id=1")
            writer.commit()
            self.assertNotEqual(before, self.db.fingerprint())
            self.assertEqual(self.search("marie@example.test")["items"][0]["department"], "New team")
            writer.execute("UPDATE users SET department='Another team' WHERE id=1")
            writer.commit()
            self.assertEqual(self.search("marie@example.test")["items"][0]["department"], "Another team")
        finally:
            writer.close()

    def test_invalid_schema_missing_record_and_invalid_arguments_report_errors(self):
        broken = self.root / "wrong.db"
        sqlite3.connect(str(broken)).close()
        self.assertIn("compatible Atlas", AtlasDatabase(broken).call("search_atlas", {"query": "test"})["error"])
        self.assertIn("search again", self.db.call("read_atlas_record", {"kind": "people", "id": "missing"})["error"])
        for args in ({"query": ""}, {"query": "x" * 257}, {"query": "test", "limit": 26}, {"query": "test", "limit": True},
                     {"query": "test", "offset": 10001}, {"query": "test", "kind": "users;DROP TABLE users"}):
            self.assertIn("error", self.db.call("search_atlas", args))

    def test_oversized_fields_are_bounded_and_unknown_import_age_stays_unknown(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE machines SET short_description=? WHERE id=1", ("x" * 5000,))
        con.execute("DELETE FROM metadata WHERE key='directory.created_at'")
        con.commit()
        con.close()
        result = self.db.call("read_atlas_record", {"kind": "computers", "id": "PC-001.example.test"})
        self.assertEqual(len(result["record"]["description"]), 512)
        self.assertNotIn("directory_imported_at", result["source"])

    def test_duplicate_or_oversized_ids_are_never_silently_selected_or_truncated(self):
        con = sqlite3.connect(str(self.path))
        con.execute("UPDATE machines SET machine_name='PC-002' WHERE id=2")
        con.execute("UPDATE users SET canonical_key=? WHERE id=1", ("x" * 257,))
        con.commit()
        con.close()
        duplicate = self.db.call("read_atlas_record", {"kind": "computers", "id": "PC-002"})
        self.assertIn("ambiguous", duplicate["error"])
        oversized = self.db.call("search_atlas", {"query": "marie@example.test"})
        self.assertIn("oversized", oversized["error"])

    def test_uri_paths_with_spaces_and_punctuation_are_read_literally(self):
        path = self.root / "snapshot #1?.db" if os.name != "nt" else self.root / "snapshot #1.db"
        fixture(path)
        result = AtlasDatabase(path).call("search_atlas", {"query": "Marie"})
        self.assertNotIn("error", result)

    def test_query_budget_interrupts_large_scans(self):
        con = sqlite3.connect(str(self.path))
        con.executemany("INSERT INTO users(canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm) VALUES(?,?,?,?,?,?,?)",
                        [("p%d" % i, "u%d" % i, "u%d" % i, "Person %d" % i, "person %d" % i, "", "") for i in range(500)])
        con.commit()
        con.close()
        with patch("atlas_db.MAX_QUERY_SECONDS", -1):
            result = self.db.call("search_atlas", {"query": "Not found"})
        self.assertIn("time limit", result["error"])

    def test_busy_database_reports_retry_without_waiting_indefinitely(self):
        writer = sqlite3.connect(str(self.path))
        try:
            writer.execute("BEGIN EXCLUSIVE")
            result = self.db.call("search_atlas", {"query": "Marie"})
            self.assertIn("busy", result["error"])
        finally:
            writer.close()


if __name__ == "__main__":
    unittest.main()
