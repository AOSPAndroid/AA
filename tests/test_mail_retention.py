"""Retention and reconciliation remain bounded without connecting to a mailbox."""
from datetime import timedelta
from contextlib import closing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from outlook_watcher import MailQueue,scan,stamp,utcnow
from search_index import SearchIndex,fts_query


class Retention(unittest.TestCase):
    def message(self,key,at):
        return dict(entry_id=str(key),received_at=stamp(at),conversation_id='',sender_name='Example',sender_address='example@example.test',subject='Fictional printer',body='Fictional retained message',body_truncated=0)

    def test_age_count_limits_and_recent_reconciliation(self):
        now=utcnow()
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AA_MAIL_MAX_MESSAGES':'100','AA_MAIL_RETENTION_DAYS':'90','AA_MAIL_RECONCILE_DAYS':'7'}),closing(MailQueue(Path(tmp),now-timedelta(days=180))) as queue:
            queue.insert('example',self.message('old',now-timedelta(days=100)))
            for i in range(120):queue.insert('example',self.message(i,now))
            queue.prune(now);self.assertEqual(queue.count(),100)
            self.assertFalse(queue.contains('example','old'))
            class Inbox:
                identity={'profile':'fictional','store_id':'example','folder_id':'inbox'}
                def entries(self,since):self.since=since;return []
            inbox=Inbox();scan(queue,inbox,now)
            self.assertEqual(inbox.since,now-timedelta(days=7))
            queue.set('repair_requested',True);queue.db.commit();scan(queue,inbox,now+timedelta(minutes=1))
            self.assertEqual(inbox.since,now+timedelta(minutes=1)-timedelta(days=90))
            self.assertFalse(queue.get('repair_requested'))

    def test_search_drops_removed_mail_and_retired_diagram_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            alive=[1,2]
            index=SearchIndex(Path(tmp)/'search.sqlite3',{'inbox':lambda after:(2,[{'ref':i,'title':'Fictional printer','body':'Example'} for i in alive if i>after],list(alive))})
            self.assertEqual(len(index.search(fts_query('printer'))),2)
            alive.remove(1)
            self.assertEqual([x['ref'] for x in index.search(fts_query('printer'))],['2'])
