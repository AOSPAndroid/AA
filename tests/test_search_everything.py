import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import search_index
from backend.search_index import SearchIndex, fts_query, key_terms, register
from sqlite_fixture import connect as fixture_connect

BOILERPLATE = 'This message is confidential and intended for the addressee only.'


class Sources:
    def __init__(self):
        self.articles = [{'ref': 'outlook', 'title': 'Outlook keeps freezing', 'body': 'Start Outlook in safe mode and disable add-ins',
                          'at': '2026-10-01', 'extra': {'tags': ['outlook']}}]
        self.inbox = {1: ('Outlook freezes every morning', 'Hi IT, Outlook freezes when I open attachments on LT-PAR-0042.'),
                      2: ('VPN will not connect', 'My laptop cannot connect to VPN since the update.'),
                      3: ('Printer jammed', 'The printer on floor 3 is jammed again.'),
                      4: ('New starter', 'Please create an account for the new starter.'),
                      5: ('Outlook freezing again', 'Outlook is freezing when opening attachments.')}
        # Unrelated mail, so the disclaimer every message carries is recognised as boilerplate.
        self.inbox.update({i: (f'Request {i}', f'Please reset my password number {i}.') for i in range(6, 26)})
        self.calls = []

    def article(self):
        return str(len(self.articles)) + self.articles[-1]['title'], self.articles

    def mailbox(self, after):
        self.calls.append(after)
        rows = [{'ref': i, 'title': s, 'body': b + ' ' + BOILERPLATE, 'at': f'2026-10-0{i}'} for i, (s, b) in self.inbox.items() if i > after]
        return max(self.inbox, default=0), rows


class SearchEverything(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'search-index.sqlite3'
        self.src = Sources()
        self.index = SearchIndex(self.path, {'article': self.src.article, 'inbox': self.src.mailbox})
        self.app = FastAPI()

        def message(message_id):
            if message_id not in self.src.inbox:
                raise HTTPException(404, 'Message not found')
            subject, body = self.src.inbox[message_id]
            return {'subject': subject, 'body': body + ' ' + BOILERPLATE}
        register(self.app, self.index, message)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def search(self, text, **params):
        return self.client.get('/api/search-everything', params={'q': text, **params}).json()['results']

    def test_query_text_is_made_safe(self):
        self.assertEqual(fts_query('Outlook "freez'), '"outlook" "freez"*')
        self.assertEqual(fts_query('a OR b', any_term=True), '"a" OR "or" OR "b"')
        self.assertEqual(fts_query('  ;; '), '')
        self.assertEqual(self.search('NEAR( "x" AND'), [], 'FTS5 syntax in user text is treated as words')

    def test_searches_every_kind_with_stems_prefixes_and_marks(self):
        results = self.search('freezes')
        self.assertEqual({(r['kind'], r['ref']) for r in results}, {('article', 'outlook'), ('inbox', '1'), ('inbox', '5')})
        article = next(r for r in results if r['kind'] == 'article')
        self.assertEqual(article['title'], 'Outlook keeps \x02freezing\x03', 'Porter stemming: freezes finds freezing')
        self.assertEqual(article['extra'], {'tags': ['outlook']})
        self.assertEqual([r['ref'] for r in self.search('vp')], ['2'], 'The last word is a prefix while typing')
        self.assertEqual([r['kind'] for r in self.search('outlook', kinds='article')], ['article'])
        self.assertEqual(len(self.search('outlook', kinds='nonsense')), 3, 'Unknown kinds fall back to everything')
        self.assertEqual(self.search(''), [])

    def test_sources_are_reindexed_only_when_they_change(self):
        self.search('outlook')
        self.search('outlook')
        self.assertEqual(self.src.calls, [0, 25], 'New mail is read by id, from the last one indexed')
        self.src.articles = [{'ref': 'printer', 'title': 'Printer jams', 'body': 'Open tray 2'}]
        self.assertEqual([(r['kind'], r['ref']) for r in self.search('tray')], [('article', 'printer')])
        self.assertEqual([r['kind'] for r in self.search('safe mode')], [], 'The old article is gone')

    def test_new_mail_is_added_and_a_reset_queue_is_reindexed(self):
        self.search('outlook')
        self.src.inbox[26] = ('Teams camera', 'Camera is black in Teams.')
        self.assertEqual([r['ref'] for r in self.search('camera')], ['26'])
        self.src.inbox = {1: ('Disk full', 'C drive is full.')}
        self.assertEqual([r['ref'] for r in self.search('drive')], ['1'])
        self.assertEqual(self.search('camera'), [], 'Messages from the old queue are dropped')

    def test_one_broken_source_does_not_block_the_others(self):
        def broken():
            raise sqlite3.OperationalError('locked')
        self.index.sources['deployment'] = broken
        self.assertEqual(len(self.search('outlook')), 3)

    def test_old_index_layout_is_rebuilt(self):
        self.search('outlook')
        with fixture_connect(self.path) as c:
            c.execute("UPDATE sources SET signature='0' WHERE kind='__version__'")
        self.src.calls.clear()
        self.assertEqual(len(self.search('outlook')), 3)
        self.assertEqual(self.src.calls, [0], 'Everything is indexed again from scratch')

    def test_similar_requests_share_distinctive_words(self):
        similar = self.client.get('/api/search-everything/similar/1').json()
        self.assertIn('outlook', similar['terms'])
        self.assertNotIn('confidential', similar['terms'], 'Text found in most messages (disclaimers) is ignored')
        self.assertFalse(any(any(ch.isdigit() for ch in term) for term in similar['terms']), 'Hostnames are not topics')
        self.assertEqual([r['ref'] for r in similar['requests']], ['5'], 'Not itself, and not unrelated mail')
        self.assertEqual([r['ref'] for r in similar['articles']], ['outlook'])
        self.assertEqual(self.client.get('/api/search-everything/similar/3').json()['requests'], [])
        self.assertEqual(len(self.search('confidential', limit=100)), 25, 'Boilerplate is still searchable on purpose')
        self.assertEqual(self.client.get('/api/search-everything/similar/99').status_code, 404)

    def test_key_terms(self):
        self.assertEqual(key_terms('Hello, Outlook outlook freezes on LT-PAR-0042 and PC123. Thanks'), ['outlook', 'freezes'])
        self.assertEqual(key_terms('Bonjour merci cordialement'), [])
        self.assertTrue(search_index.INDEX_VERSION)


if __name__ == '__main__':
    unittest.main()
