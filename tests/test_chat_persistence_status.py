"""A chat can finish while making a failed save visible, without leaking its text to logs."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from backend.axis_api import Chat,Sessions


class PersistenceStatus(unittest.TestCase):
    def test_failed_save_emits_notice_and_preserves_a_retryable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions=Sessions(SimpleNamespace(ROOT=Path(tmp),MASTER_DB=Path(tmp)/'example.db',REPO=Path(tmp)))
            with patch('backend.axis_api.write_json',side_effect=OSError('simulated disk full')):
                session,turn=sessions.begin(Chat(message='/help'))
                self.assertTrue(turn.finished.wait(5))
            self.assertIsNotNone(session.persistence_error)
            events=[]
            while not turn.events.empty():events.append(turn.events.get_nowait())
            self.assertTrue(any(e['type']=='notice' and 'could not be saved' in e['text'] for e in events))
            self.assertIsNone(session.current)
            sessions.save(session)
            self.assertIsNone(session.persistence_error)
            self.assertTrue((sessions.chats/(session.id+'.json')).is_file())
