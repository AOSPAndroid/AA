"""Windows native writer contract; build with -IncludeTests before this test."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from outlook_watcher import MailQueue, utcnow

WRITER = Path(__file__).resolve().parents[1] / 'output' / 'NotificationWriter.Tests.exe'


@unittest.skipUnless(os.name == 'nt' and WRITER.exists(), 'Build-Notification-Listener.ps1 -IncludeTests requires Windows')
class WindowsNotificationWriterTests(unittest.TestCase):
    def test_native_writer_interoperates_with_python_and_preserves_old_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            # Model a prior release's queue, including an existing message ID.
            queue = MailQueue(path, utcnow())
            queue.db.execute("INSERT INTO messages VALUES(1,'outlook-store','mail-1','2026-01-01','2026-01-01','','Mail User','mail@example.test','Saved mail','Original body',0,'outlook','mail','')")
            for column in ('channel', 'content_kind', 'app_name'):
                queue.db.execute(f'ALTER TABLE messages DROP COLUMN {column}')
            queue.db.commit()
            checkpoint = queue.get('cursor')
            # Keep Python's connection open while the native collector writes.
            result = subprocess.run([str(WRITER), temp], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS:', result.stdout)
            self.assertEqual(queue.get('cursor'), checkpoint)
            queue.close()
            with closing(sqlite3.connect(path / 'inbox.sqlite3')) as db:
                rows = db.execute('SELECT id,channel,content_kind,sender_address,body FROM messages ORDER BY id').fetchall()
                self.assertEqual(len(rows), 6)
                self.assertEqual(rows[0], (1, 'outlook', 'mail', 'mail@example.test', 'Original body'))
                self.assertEqual(rows[1][1:4], ('teams', 'notification', ''))
                self.assertIn('café 中文', rows[1][4])
                self.assertEqual(rows[4][1], 'outlook')
                self.assertTrue((path / 'notifications-status.json').is_file())


if __name__ == '__main__': unittest.main()
