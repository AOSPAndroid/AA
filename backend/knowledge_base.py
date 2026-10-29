"""Local Admin knowledge documents. Never registered on the public/LAN viewer."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

class Document(BaseModel):
    title: str = Field(default='Untitled diagram', min_length=1, max_length=180)
    notes: str = Field(default='', max_length=100000)
    xml: str = Field(max_length=5000000)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def diagram_xml(self):
        import re
        from xml.etree import ElementTree
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)',self.xml,re.I):
            raise ValueError('XML document types and entities are not supported')
        try:root=ElementTree.fromstring(self.xml)
        except ElementTree.ParseError:raise ValueError('Invalid Draw.io XML')
        if root.tag not in ('mxfile','mxGraphModel'):raise ValueError('Expected a Draw.io diagram')
        return self


def register(app, path):
    def db():
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,updated TEXT NOT NULL)')
        c.commit()
        return c

    def valid_id(doc_id):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',doc_id):
            raise HTTPException(400,'Invalid document ID')

    @app.get('/api/knowledge')
    def listing():
        with closing(db()) as c:
            return {'documents':[dict(r) for r in c.execute('SELECT id,title,revision,updated FROM documents ORDER BY updated DESC')]}

    @app.get('/api/knowledge/{doc_id}')
    def get(doc_id:str):
        valid_id(doc_id)
        with closing(db()) as c:
            row=c.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
        if not row:raise HTTPException(404,'Document not found')
        return {**json.loads(row['body']),'id':doc_id,'revision':row['revision'],'updated':row['updated']}

    @app.put('/api/knowledge/{doc_id}')
    def save(doc_id:str, document:Document):
        valid_id(doc_id)
        body=document.model_dump(exclude={'revision'})
        if len(json.dumps(body).encode('utf-8'))>6500000:raise HTTPException(413,'Document too large')
        now=datetime.now(timezone.utc).isoformat()
        with closing(db()) as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT revision FROM documents WHERE id=?',(doc_id,)).fetchone()
            if (old['revision'] if old else 0)!=document.revision:
                raise HTTPException(409,'This document changed in another window. Export your draft, then reopen it or save a copy.')
            revision=document.revision+1
            c.execute('INSERT INTO documents VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,body=excluded.body,revision=excluded.revision,updated=excluded.updated',(doc_id,document.title,json.dumps(body),revision,now))
            c.commit()
        return {'id':doc_id,'revision':revision,'updated':now}

    @app.delete('/api/knowledge/{doc_id}')
    def delete(doc_id:str, revision:int):
        valid_id(doc_id)
        with closing(db()) as c:
            row=c.execute('DELETE FROM documents WHERE id=? AND revision=?',(doc_id,revision))
            if not row.rowcount:raise HTTPException(409,'Document changed or was deleted. Refresh the library.')
            c.commit()
        return {'deleted':True}
