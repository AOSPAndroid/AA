"""Knowledge Base articles: Markdown runbooks with tags and links to Live Inbox issue categories.

Stored beside the Draw.io diagrams in knowledge.sqlite3 (table "articles"). Admin only; never
registered on the LAN viewer. Saving uses the same revision check as diagrams, so two windows
cannot overwrite each other.
"""
import json
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator

SCHEMA = '''CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, title TEXT NOT NULL, markdown TEXT NOT NULL,
            tags TEXT NOT NULL, categories TEXT NOT NULL, revision INTEGER NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL)'''


class Article(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    markdown: str = Field('', max_length=200000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    categories: list[str] = Field(default_factory=list, max_length=12)
    revision: int = Field(0, ge=0)

    @field_validator('tags')
    @classmethod
    def clean_tags(cls, tags):
        result = []
        for tag in tags:
            tag = ' '.join(str(tag).split())[:40]
            if tag and tag.casefold() not in {t.casefold() for t in result}:
                result.append(tag)
        return result

    @field_validator('categories')
    @classmethod
    def known_categories(cls, categories):
        from backend.inbox.inbox_analysis import CATEGORIES
        known = {key for key, *_ in CATEGORIES}
        unknown = [c for c in categories if c not in known]
        if unknown:
            raise ValueError('Unknown issue category: ' + ', '.join(unknown))
        return list(dict.fromkeys(categories))


def plain_text(markdown, code=True):
    """Markdown -> readable words for search snippets and list excerpts (code kept unless code=False)."""
    text = str(markdown or '')
    text = re.sub(r'```[^\n]*\n(.*?)```', (lambda m: ' ' + m.group(1) + ' ') if code else ' ', text, flags=re.S)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)          # links and images keep their text
    text = re.sub(r'^\s*(?:[-*+]\s+\[[ xX]\]|[-*+]|\d+[.)]|#{1,6}|>)\s*', '', text, flags=re.M)  # list, heading, quote markers
    text = re.sub(r'^\s*\|?\s*:?-{3,}.*$', '', text, flags=re.M)      # table divider rows
    text = re.sub(r'[*_`|]+', ' ', text)
    return ' '.join(text.split())


def excerpt(markdown, length=160):
    text = plain_text(markdown, code=False)
    return text[:length] + ('…' if len(text) > length else '')


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def row_dict(row, full=True):
    data = {'id': row['id'], 'title': row['title'], 'tags': json.loads(row['tags']), 'categories': json.loads(row['categories']),
            'revision': row['revision'], 'created': row['created'], 'updated': row['updated']}
    if full:
        data['markdown'] = row['markdown']
    else:
        data['excerpt'] = excerpt(row['markdown'])
    return data


def all_articles(path):
    """Every article with its Markdown, for search indexing and Live Inbox suggestions."""
    if not path.is_file():
        return []
    with closing(connect(path)) as c:
        return [row_dict(r) for r in c.execute('SELECT * FROM articles')]


def register(app, path):
    def check_token(request):
        from backend.atlas_api import TOKEN
        if not secrets.compare_digest(request.headers.get('x-atlas-token', ''), TOKEN):
            raise HTTPException(403, 'Refresh Atlas before changing Knowledge Base articles')

    def valid_id(article_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', article_id):
            raise HTTPException(400, 'Invalid article ID')

    @app.get('/api/knowledge/article-categories')
    def categories():
        from backend.inbox.inbox_analysis import CATEGORIES
        return {'categories': [{'id': key, 'label': label} for key, label, *_ in CATEGORIES]}

    @app.get('/api/knowledge/articles')
    def listing():
        with closing(connect(path)) as c:
            return {'articles': [row_dict(r, full=False) for r in c.execute('SELECT * FROM articles ORDER BY updated DESC')]}

    @app.get('/api/knowledge/articles/{article_id}')
    def get(article_id: str):
        valid_id(article_id)
        with closing(connect(path)) as c:
            row = c.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Article not found')
        return row_dict(row)

    @app.put('/api/knowledge/articles/{article_id}')
    def save(article_id: str, article: Article, request: Request):
        check_token(request)
        valid_id(article_id)
        now = datetime.now(timezone.utc).isoformat()
        with closing(connect(path)) as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT revision, created FROM articles WHERE id=?', (article_id,)).fetchone()
            if (old['revision'] if old else 0) != article.revision:
                raise HTTPException(409, 'This article changed in another window. Copy your text, then reopen the article.')
            revision = article.revision + 1
            c.execute('INSERT INTO articles VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,'
                      'markdown=excluded.markdown,tags=excluded.tags,categories=excluded.categories,revision=excluded.revision,'
                      'updated=excluded.updated',
                      (article_id, article.title.strip(), article.markdown, json.dumps(article.tags), json.dumps(article.categories),
                       revision, old['created'] if old else now, now))
            c.commit()
        return {'id': article_id, 'revision': revision, 'updated': now}

    @app.delete('/api/knowledge/articles/{article_id}')
    def delete(article_id: str, revision: int, request: Request):
        check_token(request)
        valid_id(article_id)
        with closing(connect(path)) as c:
            if not c.execute('DELETE FROM articles WHERE id=? AND revision=?', (article_id, revision)).rowcount:
                raise HTTPException(409, 'Article changed or was deleted. Refresh the list.')
            c.commit()
        return {'deleted': True}
