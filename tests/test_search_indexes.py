"""An admin upgrade changes derived matching state, preserving source data."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from backend import atlas_store
from backend.directory.directory_lookup import exact_users, prepare_views
from backend.directory.identity_links import MATCHING_VERSION


class IndexTests(unittest.TestCase):
 def test_upgrade_preserves_source_rows_and_is_idempotent(self):
  original=atlas_store.DB
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'test.db'
   source=sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True);c=sqlite3.connect(target)
   source.backup(c);source.close()
   # Force the actual one-time matching migration, even if the test runtime has
   # already been initialized by another module. Only this disposable DB changes.
   c.execute("delete from metadata where key='directory.matching_version'");c.commit()
   tables=[r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
   def snapshot(names):return {t:hashlib.sha256(repr(c.execute('select * from "'+t+'"').fetchall()).encode()).hexdigest() for t in names}
   raw_tables=[t for t in tables if t not in ('metadata','assignments','user_aliases')]
   raw_aliases=c.execute("select * from user_aliases where alias_type not like 'matching_%' order by id").fetchall()
   before=snapshot(raw_tables)
   people=c.execute('select canonical_key,id from users order by id limit 30').fetchall()
   query="select distinct * from users where user_id_norm=? or lower(email)=? or lower(employee_number)=? or full_name_norm=? or id in (select user_id_ref from user_aliases where alias_norm=?) order by full_name,id limit 100"
   try:
    atlas_store.DB=target;atlas_store.initialize()
    self.assertEqual(before,snapshot(raw_tables))
    self.assertEqual(raw_aliases,c.execute("select * from user_aliases where alias_type not like 'matching_%' order by id").fetchall())
    self.assertEqual(c.execute("select value from metadata where key='directory.matching_version'").fetchone()[0],MATCHING_VERSION)
    self.assertIsNotNone(c.execute("select value from metadata where key='matching_diagnostics'").fetchone())
    repaired=snapshot(tables);atlas_store.initialize()
    self.assertEqual(repaired,snapshot(tables),'No repeat changes to aliases, links, generation or source data')
    c.row_factory=sqlite3.Row;prepare_views(c)
    for canonical,uid in people:
     self.assertEqual([row['id'] for row in exact_users(c,canonical)],[uid])
    plan=str([tuple(row) for row in c.execute('explain query plan '+query,('missing',)*5)])
    self.assertIn('MULTI-INDEX OR',plan);self.assertNotIn('SCAN users',plan)
   finally:atlas_store.DB=original;c.close()

if __name__=='__main__':unittest.main()
