"""Recovery and read-only boundaries, using fictional inboxes."""
import argparse
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import outlook_watcher as watcher

UTC = timezone.utc
START = datetime(2026, 10, 15, 10, 0, 30, tzinfo=UTC)
IDENTITY = {'profile': 'Test profile', 'store_id': 'store', 'folder_id': 'inbox'}


def message(entry_id, received=START):
    return {'entry_id': entry_id, 'received_at': watcher.stamp(received), 'conversation_id': 'thread',
            'sender_name': 'Test User', 'sender_address': 'user@example.invalid', 'subject': 'Application issue',
            'body': 'A fictional application stopped responding.', 'body_truncated': 0}


class Inbox:
    def __init__(self, messages, fail=None, identity=None):
        self.messages = messages
        self.fail = fail
        self.identity = dict(identity or IDENTITY)
        self.reads = []
        self.lower = None

    def entries(self, lower):
        self.lower = lower
        for item in self.messages:
            if datetime.fromisoformat(item['received_at']) >= lower.replace(second=0, microsecond=0):
                yield item['entry_id']

    def read(self, entry_id):
        self.reads.append(entry_id)
        if self.fail == entry_id:
            raise RuntimeError('Simulated unavailable item')
        return next(item for item in self.messages if item['entry_id'] == entry_id)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.queue = watcher.MailQueue(self.directory, START)

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def test_first_run_ignores_older_messages_within_filter_minute(self):
        inbox = Inbox([message('old', START - timedelta(seconds=1)), message('new')])
        self.assertEqual(watcher.scan(self.queue, inbox, START + timedelta(seconds=15)), 1)
        self.assertEqual(self.queue.db.execute('SELECT entry_id FROM messages').fetchone()[0], 'new')

    def test_repeated_scan_and_restart_do_not_duplicate_or_read_bodies_again(self):
        inbox = Inbox([message('one')])
        watcher.scan(self.queue, inbox, START)
        self.queue.close()
        self.queue = watcher.MailQueue(self.directory, START + timedelta(hours=2))
        self.assertEqual(self.queue.get('since'), watcher.stamp(START))
        self.assertEqual(watcher.scan(self.queue, inbox, START + timedelta(hours=2)), 0)
        self.assertEqual(inbox.reads, ['one'])
        self.assertEqual(self.queue.count(), 1)

    def test_partial_read_failure_preserves_checkpoint_and_retries_only_missing_items(self):
        inbox = Inbox([message('one'), message('two')], fail='two')
        with self.assertRaises(RuntimeError):
            watcher.scan(self.queue, inbox, START + timedelta(minutes=1))
        self.assertEqual(self.queue.get('cursor'), watcher.stamp(START))
        self.assertIsNone(self.queue.get('reconciled'))
        self.assertEqual(self.queue.count(), 1)
        inbox.fail = None
        self.assertEqual(watcher.scan(self.queue, inbox, START + timedelta(minutes=2)), 1)
        self.assertEqual(inbox.reads, ['one', 'two', 'two'])
        self.assertEqual(self.queue.count(), 2)

    def test_stop_mid_pass_does_not_checkpoint_unprocessed_mail(self):
        inbox = Inbox([message('one'), message('two')])
        with self.assertRaises(watcher.StopRequested):
            watcher.scan(self.queue, inbox, START + timedelta(minutes=1), lambda: bool(inbox.reads))
        self.assertEqual(self.queue.count(), 1)
        self.assertEqual(self.queue.get('cursor'), watcher.stamp(START))
        self.assertEqual(watcher.scan(self.queue, inbox, START + timedelta(minutes=2)), 1)

    def test_inaccessible_message_does_not_starve_other_new_mail(self):
        inbox = Inbox([message('blocked'), message('readable')], fail='blocked')
        with self.assertRaises(RuntimeError):
            watcher.scan(self.queue, inbox, START + timedelta(minutes=1))
        self.assertEqual(inbox.reads, ['blocked', 'readable'])
        self.assertEqual(self.queue.count(), 1)
        self.assertEqual(self.queue.get('cursor'), watcher.stamp(START))

    def test_periodic_reconciliation_finds_delayed_sync_outside_overlap(self):
        watcher.scan(self.queue, Inbox([]), START + timedelta(minutes=20))
        delayed = Inbox([message('delayed', START + timedelta(minutes=1))])
        self.assertEqual(watcher.scan(self.queue, delayed, START + timedelta(minutes=21)), 0)
        self.assertEqual(watcher.scan(self.queue, delayed, START + timedelta(minutes=35)), 1)
        self.assertEqual(delayed.lower, START)

    def test_pin_prevents_silently_following_a_different_profile_or_folder(self):
        watcher.scan(self.queue, Inbox([]), START)
        for key in IDENTITY:
            with self.assertRaises(watcher.OutlookUnavailable):
                watcher.scan(self.queue, Inbox([message('wrong')], identity={**IDENTITY, key: 'different'}), START)
        self.assertEqual(self.queue.count(), 0)

    def test_mail_received_while_stopped_is_caught_up(self):
        watcher.scan(self.queue, Inbox([]), START)
        self.queue.close()
        self.queue = watcher.MailQueue(self.directory, START + timedelta(days=2))
        self.assertEqual(watcher.scan(self.queue, Inbox([message('offline', START + timedelta(days=1))]),
                                      START + timedelta(days=2)), 1)

    def test_mailbox_configuration_cannot_silently_change(self):
        with self.assertRaisesRegex(ValueError, 'different inbox'):
            watcher.MailQueue(self.directory, START, mailbox='Another mailbox')
        self.assertEqual(self.queue.get('config'), {'mailbox': '', 'subfolder': ''})


class ReadOnlyItem:
    Class = 43
    SenderEmailAddress = 'user@example.invalid'
    SenderEmailType = 'SMTP'
    SenderName = 'Test User'
    Subject = 'Test issue'
    ConversationID = 'thread'
    ReceivedTime = START.astimezone(timezone(timedelta(hours=2)))
    Body = 'x' * (watcher.BODY_LIMIT + 10)
    UnRead = True

    def __setattr__(self, key, value):
        raise AssertionError('Watcher must not modify an Outlook item')

    def Save(self):
        raise AssertionError('Watcher must not save Outlook items')

    def Send(self):
        raise AssertionError('Watcher must not send email')


class AdapterTests(unittest.TestCase):
    def test_read_preserves_unread_state_and_bounds_body(self):
        item = ReadOnlyItem()
        inbox = watcher.OutlookInbox.__new__(watcher.OutlookInbox)
        inbox.identity = IDENTITY
        inbox.namespace = SimpleNamespace(GetItemFromID=lambda entry, store: item)
        result = inbox.read('entry')
        self.assertTrue(item.UnRead)
        self.assertEqual(len(result['body']), watcher.BODY_LIMIT)
        self.assertEqual(result['body_truncated'], 1)
        self.assertEqual(result['received_at'], watcher.stamp(START))
        self.assertEqual(result['sender_address'], 'user@example.invalid')

    def test_non_mail_is_ignored(self):
        inbox = watcher.OutlookInbox.__new__(watcher.OutlookInbox)
        inbox.identity = IDENTITY
        inbox.namespace = SimpleNamespace(GetItemFromID=lambda entry, store: SimpleNamespace(Class=26))
        self.assertIsNone(inbox.read('meeting'))

    def test_table_filter_uses_utc_regional_format_without_seconds_and_batches_ids(self):
        calls = []
        class Table:
            EndOfTable = False
            Columns = SimpleNamespace(RemoveAll=lambda: None, Add=lambda name: None)
            def GetArray(self, size):
                self.EndOfTable = True
                self.size = size
                return [('mail', 'IPM.Note'), ('custom', 'IPM.Note.Custom'), ('meeting', 'IPM.Schedule.Meeting')]
        table = Table()
        inbox = watcher.OutlookInbox.__new__(watcher.OutlookInbox)
        def date_format(locale, flags, value, fmt):
            self.assertEqual(value, START.replace(second=0))
            self.assertEqual(value.tzinfo, UTC)
            return '15/10/2026'
        def time_format(locale, flags, value, fmt):
            self.assertEqual(flags, 2)
            return '10:00'
        inbox.win32api = SimpleNamespace(GetDateFormat=date_format, GetTimeFormat=time_format)
        inbox.folder = SimpleNamespace(GetTable=lambda query: (calls.append(query), table)[1])
        self.assertEqual(list(inbox.entries(START.astimezone(timezone(timedelta(hours=2))))), ['mail', 'custom'])
        self.assertIn("'15/10/2026 10:00'", calls[0])
        self.assertEqual(table.size, 100)

    def test_attach_never_launches_outlook(self):
        class ComError(Exception):
            hresult = -2147221021
        client = SimpleNamespace(GetActiveObject=lambda name: (_ for _ in ()).throw(ComError()))
        with patch.object(watcher, 'windows_dependencies', return_value=(SimpleNamespace(com_error=ComError), None, client)):
            with self.assertRaises(watcher.OutlookUnavailable):
                watcher.OutlookInbox({'mailbox': '', 'subfolder': ''})


class ProcessTests(unittest.TestCase):
    def test_reader_probes_status_without_opening_any_file_for_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            watcher.write_json(directory / 'status.json', {'state': 'watching'})
            original = Path.open
            modes = []
            def read_only(path, mode='r', *args, **kwargs):
                modes.append(mode)
                self.assertFalse(any(flag in mode for flag in ('w', 'a', '+')))
                return original(path, mode, *args, **kwargs)
            with watcher.process_lock(directory):
                with patch.object(Path, 'open', read_only):
                    self.assertTrue(watcher.status(directory)['running'])
            with patch.object(Path, 'open', read_only):
                self.assertFalse(watcher.status(directory)['running'])
            self.assertIn('rb', modes)

    def test_read_only_lock_file_does_not_look_like_a_running_watcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            lock = directory / 'watcher.lock'
            lock.write_bytes(b'0')
            lock.chmod(stat.S_IREAD)
            try:
                self.assertFalse(watcher.is_running(directory))
            finally:
                lock.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_denied_open_is_not_mistaken_for_a_running_watcher(self):
        with patch.object(Path, 'open', side_effect=PermissionError('Reader cannot access this folder')):
            with self.assertRaises(PermissionError):
                watcher.is_running(Path('not-accessible'))

    def test_os_lock_prevents_two_watchers_and_is_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertFalse(watcher.is_running(directory))
            with watcher.process_lock(directory):
                self.assertTrue(watcher.is_running(directory))
                with self.assertRaises(watcher.AlreadyRunning):
                    with watcher.process_lock(directory):
                        self.fail('Duplicate lock acquired')
            self.assertFalse(watcher.is_running(directory))

    def test_stale_status_is_not_reported_as_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            watcher.write_json(directory / 'status.json', {'pid': 123, 'state': 'watching'})
            self.assertEqual(watcher.status(directory)['state'], 'stopped')
            self.assertFalse(watcher.status(directory)['running'])

    def test_once_without_outlook_returns_retry_status_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args = argparse.Namespace(data_dir=directory, lookback_hours=0, mailbox=None, subfolder=None, interval=5, once=True)
            com = SimpleNamespace(COINIT_APARTMENTTHREADED=2, CoInitializeEx=lambda mode: None, CoUninitialize=lambda: None)
            with patch.object(watcher, 'windows_dependencies', return_value=(com, None, None)), \
                 patch.object(watcher, 'OutlookInbox', side_effect=watcher.OutlookUnavailable('Waiting for Outlook')):
                self.assertEqual(watcher.run(args), 2)
            record = watcher.read_json(directory / 'status.json')
            self.assertEqual(record['state'], 'waiting_for_outlook')
            self.assertTrue(record['exited'])
            self.assertFalse(watcher.is_running(directory))
            self.assertEqual(record['messages_saved'], 0)


if __name__ == '__main__':
    unittest.main()
