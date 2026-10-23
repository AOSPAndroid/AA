"""Search everything: Knowledge Base articles and diagrams, Live Inbox requests and deployments.

A SQLite FTS5 index (search-index.sqlite3 beside the Knowledge Base) is brought up to date
before each search: new inbox messages are added by id, small sources are re-indexed only when
they change. It is a rebuildable cache; deleting the file is safe. Admin only.
"""
import json
import re
import sqlite3
import threading
from contextlib import closing

from fastapi import HTTPException, Query

KINDS = ('article', 'diagram', 'inbox', 'deployment')
STOP = set('''a an and are as at be been but by can could did do does for from had has have hello hi how i if in into is it its
me my no not of on or our please so thank thanks that the their them then there these they this to too was we were what when
where which who why will with would you your yes dear regards best kind team bonjour merci de des du la le les un une et est
pour sur dans avec pas que qui mon ma mes vous nous je il elle cordialement svp very also just need since still every after
before today morning time some more much there here have help''' .split())
INDEX_VERSION = '3'  # bump when the table layout or tokenizer changes; the cache is rebuilt
_lock = threading.Lock()


def fts_query(text, prefix=True, any_term=False):
    """User text -> safe FTS5 query: quoted terms, last one as a prefix ("outl" finds "outlook")."""
    terms = [t for t in re.findall(r'\w+', str(text or '').casefold()) if t][:12]
    if not terms:
        return ''
    quoted = ['"' + t.replace('"', '') + '"' for t in terms]
    if prefix and not any_term:
        quoted[-1] += '*'
    return (' OR ' if any_term else ' ').join(quoted)


def key_terms(text, limit=10):
    """Distinctive words of a message, for finding similar requests."""
    counts = {}
    # Words only: hostnames and ticket numbers (anything with a digit) are not topics.
    for word in re.findall(r'(?<![\w-])[^\W\d_]{4,}(?![\w-])', str(text or '').casefold()):
        if word not in STOP:
            counts[word] = counts.get(word, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


class SearchIndex:
    def __init__(self, path, sources):
        """sources: {kind: callable returning (signature, rows)} or, for 'inbox', callable(after_id)."""
        self.path, self.sources = path, sources

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE IF NOT EXISTS sources(kind TEXT PRIMARY KEY, signature TEXT NOT NULL)')
        version = c.execute("SELECT signature FROM sources WHERE kind='__version__'").fetchone()
        if not version or version['signature'] != INDEX_VERSION:
            c.execute('DROP TABLE IF EXISTS entries')
            c.execute('DELETE FROM sources')
            c.execute("INSERT INTO sources VALUES('__version__', ?)", (INDEX_VERSION,))
        # Porter stemming: "freezes" finds "freezing"; accents are ignored ("reseau" finds "réseau").
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(kind UNINDEXED, ref UNINDEXED, title, body,"
                  " at UNINDEXED, extra UNINDEXED, tokenize='porter unicode61 remove_diacritics 2')")
        c.commit()
        return c

    def sync(self):
        with _lock, closing(self.connect()) as c:
            for kind, load in self.sources.items():
                if kind == '__version__':
                    continue
                state = c.execute('SELECT signature FROM sources WHERE kind=?', (kind,)).fetchone()
                try:
                    if kind == 'inbox':
                        self._sync_inbox(c, load, state)
                    else:
                        signature, rows = load()
                        if state and state['signature'] == signature:
                            continue
                        c.execute('DELETE FROM entries WHERE kind=?', (kind,))
                        c.executemany('INSERT INTO entries(kind,ref,title,body,at,extra) VALUES(?,?,?,?,?,?)',
                                      [(kind, str(r['ref']), r['title'], r['body'], r.get('at') or '', json.dumps(r.get('extra') or {}))
                                       for r in rows])
                        c.execute('INSERT OR REPLACE INTO sources VALUES(?,?)', (kind, signature))
                except (OSError, sqlite3.Error, HTTPException):
                    continue  # one unavailable source never blocks searching the others
                c.commit()

    def _sync_inbox(self, c, load, state):
        last = int(state['signature']) if state else 0
        newest, rows = load(last)
        if newest < last:  # the mail queue was reset: index it again from the start
            c.execute("DELETE FROM entries WHERE kind='inbox'")
            last = 0
            newest, rows = load(0)
        c.executemany("INSERT INTO entries(kind,ref,title,body,at,extra) VALUES('inbox',?,?,?,?,?)",
                      [(str(r['ref']), r['title'], r['body'], r.get('at') or '', json.dumps(r.get('extra') or {})) for r in rows])
        indexed = max([int(r['ref']) for r in rows] + [last])
        c.execute("INSERT OR REPLACE INTO sources VALUES('inbox',?)", (str(indexed),))

    def search(self, query, kinds=KINDS, limit=30, exclude=None, require=None):
        """require=(terms, n): keep only results sharing at least n of the terms (for similar requests)."""
        if not query:
            return []
        self.sync()
        marks = ','.join('?' * len(kinds))
        with closing(self.connect()) as c:
            try:
                rows = c.execute(
                    "SELECT kind, ref, title, body, at, extra, snippet(entries, 3, char(2), char(3), ' … ', 14) AS snippet,"
                    " highlight(entries, 2, char(2), char(3)) AS marked_title, bm25(entries, 0, 0, 8.0, 1.0) AS rank"
                    f" FROM entries WHERE entries MATCH ? AND kind IN ({marks}) ORDER BY rank LIMIT ?",
                    (query, *kinds, (limit + 1) * (5 if require else 1))).fetchall()
            except sqlite3.OperationalError as error:
                raise HTTPException(400, 'Search could not understand that text. Use plain words.') from error
        if require:
            terms, needed = require
            stem = lambda word: word[:5]  # crude, matches the porter index closely enough for counting
            wanted = {stem(t) for t in terms}
            words = lambda r: {stem(w) for w in re.findall(r'\w+', f"{r['title']} {r['body']}".casefold())}
            rows = [r for r in rows if len(wanted & words(r)) >= needed]
        results = [{'kind': r['kind'], 'ref': r['ref'], 'title': r['marked_title'], 'snippet': r['snippet'], 'at': r['at'],
                    'extra': json.loads(r['extra'] or '{}')} for r in rows if (r['kind'], r['ref']) != exclude]
        return results[:limit]

    def common_terms(self, terms, kind='inbox', share=0.3):
        """Terms found in more than `share` of a kind's entries (signatures, disclaimers, boilerplate)."""
        with closing(self.connect()) as c:
            total = c.execute('SELECT count(*) FROM entries WHERE kind=?', (kind,)).fetchone()[0]
            if total < 20:  # too few messages to tell boilerplate from a shared topic
                return set()
            return {t for t in terms if c.execute("SELECT count(*) FROM entries WHERE entries MATCH ? AND kind=?",
                                                  ('"' + t + '"', kind)).fetchone()[0] > share * total}


def register(app, index, inbox_message):
    """inbox_message(message_id) -> {'subject','body'} for "similar requests"."""
    @app.get('/api/search-everything')
    def search(q: str = Query('', max_length=300), kinds: str = Query(','.join(KINDS), max_length=100),
               limit: int = Query(30, ge=1, le=100)):
        chosen = tuple(k for k in kinds.split(',') if k in KINDS) or KINDS
        return {'query': q, 'results': index.search(fts_query(q), chosen, limit)}

    @app.get('/api/search-everything/similar/{message_id}')
    def similar(message_id: int, limit: int = Query(4, ge=1, le=20)):
        message = inbox_message(message_id)
        index.sync()
        terms = key_terms(f"{message.get('subject', '')} {message.get('subject', '')} {str(message.get('body', ''))[:2000]}", limit=15)
        common = index.common_terms(terms)
        terms = [t for t in terms if t not in common][:10]
        query = fts_query(' '.join(terms), any_term=True)
        # Similar means sharing at least two distinctive words (one if the message has very few).
        need = (terms, 2 if len(terms) >= 3 else 1)
        return {'terms': terms,
                'requests': index.search(query, ('inbox',), limit, exclude=('inbox', str(message_id)), require=need) if query else [],
                'articles': index.search(query, ('article', 'diagram'), 3, require=need) if query else []}
