"""Read from screen: text from the operator's own window, screen or clipboard, analysed like an email.

Admin only (never registered on the LAN viewer). Capture uses scripts/screen_reader.ps1 with Windows
OCR; screenshots are temporary and deleted by the script. Text is analysed in memory and not stored.
"""
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from directory_lookup import exact_users, linked_machines

SCRIPT = Path(__file__).parent / 'scripts' / 'screen_reader.ps1'
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
# Window-title pieces that are application names, not people.
APP_WORDS = re.compile(r'\b(microsoft|teams|outlook|chat|message|inbox|mail|calendar|servicenow|edge|chrome|google|'
                       r'atlas|notepad|excel|word|powerpoint|onenote|meeting|call|activity|ticket|incident)\b', re.I)
BROWSERS = {'msedge', 'chrome', 'firefox', 'openfin', 'iexplore'}
LIMIT = 20000
IMAGE_LIMIT = 15 * 1024 * 1024
# A screenshot pasted or read from the clipboard in the browser: only these formats are accepted.
IMAGE_TYPES = {b'\x89PNG\r\n\x1a\n': '.png', b'\xff\xd8\xff': '.jpg', b'BM': '.bmp', b'GIF8': '.gif'}


def ocr_image(ps, data):
    """Windows OCR of a PNG/JPEG/BMP/GIF image: {'text', 'language'}. Shared with the Atlas Companion."""
    if not windows():
        raise HTTPException(501, 'Reading screenshots needs Windows.')
    if len(data) > IMAGE_LIMIT:
        raise HTTPException(413, 'The image is larger than 15 MB.')
    suffix = next((ext for magic, ext in IMAGE_TYPES.items() if data.startswith(magic)), None)
    if not suffix:
        raise HTTPException(415, 'Paste a PNG, JPEG, BMP or GIF screenshot.')
    with tempfile.TemporaryDirectory(prefix='atlas-image-') as folder:
        path = Path(folder) / ('clipboard' + suffix)
        path.write_bytes(data)
        # The path is Atlas's own temporary file, quoted as a PowerShell literal.
        literal = "'" + str(path).replace("'", "''") + "'"
        script = f"$Mode='image'; $Delay=0; $ImagePath={literal}\n" + SCRIPT.read_text(encoding='utf-8')
        try:
            captured = json.loads(ps(script, timeout=60))
        except (RuntimeError, ValueError) as error:
            raise HTTPException(502, f'Could not read the screenshot: {error}') from error
    text = str(captured.get('text') or '')
    if not text.strip():
        raise HTTPException(422, 'No text was found in the screenshot. Copy a larger or sharper area and retry.')
    return {'text': text, 'language': captured.get('language') or ''}


def remember(text, source):
    # Everything read from the clipboard also lands in the clipboard history, with its enrichment.
    from clipboard_history import record
    record(text, source)


def windows():
    return os.name == 'nt'


class Capture(BaseModel):
    source: str = Field('window', pattern='^(window|screen|clipboard)$')
    delay: int = Field(3, ge=0, le=10)


class Text(BaseModel):
    title: str = Field('', max_length=1000)
    text: str = Field('', max_length=LIMIT)
    user_id: int | None = Field(None, ge=1)


def title_names(title):
    """Person-like segments of a window title, e.g. "Chat | Alex Morgan | Microsoft Teams"."""
    names = []
    for part in re.split(r'\s+[|\-–—·:]\s+|\s*\|\s*', title or ''):
        part = re.sub(r'\(.*?\)|\[.*?\]', '', part).strip(' ,.')
        words = part.split()
        looks_like_name = all(re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['\u2019.-])*", w) for w in words) and sum(w[0].isupper() for w in words) >= 2
        if 2 <= len(words) <= 4 and looks_like_name and not APP_WORDS.search(part):
            names.append(part)
    return names


def match_people(connection, title, text, chosen=None):
    from mail_inbox import person
    emails = list(dict.fromkeys(e.casefold() for e in EMAIL.findall(f'{title}\n{text}')))[:10]
    people, basis = {}, None
    for email in emails:
        for row in exact_users(connection, email, field='email'):
            people.setdefault(row['id'], person(row))
    if people:
        basis = 'email'
    else:
        for name in title_names(title):
            for row in exact_users(connection, name, field='name'):
                people.setdefault(row['id'], person(row))
        basis = 'name' if people else None
    candidates = list(people.values())
    user = candidates[0] if len(candidates) == 1 else None
    if chosen is not None:
        user = people.get(chosen)
        if user is None:
            raise HTTPException(409, 'This person is no longer a candidate for the captured text. Read the screen again.')
    kind = basis if len(candidates) == 1 else 'ambiguous' if candidates else 'unmatched'
    return {'kind': kind, 'basis': basis, 'user': user, 'candidates': candidates, 'chosen': chosen is not None}


def register(app, wmi, check_token):
    def analysed(title, text, chosen=None):
        from inbox_analysis import analyse
        from mail_inbox import mentioned_machines, safely
        text = str(text or '')[:LIMIT]
        warnings = []
        catalogue = safely(getattr(wmi, 'inbox_packages', lambda: []), 'Package catalogue', warnings)
        knowledge = safely(getattr(wmi, 'inbox_documents', lambda: []), 'Knowledge Base', warnings)
        try:
            with wmi.db() as connection:
                match = match_people(connection, title, text, chosen)
                machines = linked_machines(connection, match['user']['id']) if match['user'] else []
                analysis = analyse(title, text, packages=catalogue, documents=knowledge,
                                   find_machines=lambda names: mentioned_machines(connection, names),
                                   linked=[m.get('name') for m in machines])
        except sqlite3.Error as error:
            raise HTTPException(503, 'Atlas directory lookup is unavailable. Retry after the database is ready.') from error
        return {'match': match, 'machines': machines, 'analysis': {**analysis, 'warnings': warnings}}

    @app.post('/api/screen/read')
    def read(body: Capture, request: Request):
        check_token(request)
        if not windows():
            raise HTTPException(501, 'Read from screen needs Windows.')
        # Only validated values reach the script: a mode name and a whole number of seconds.
        script = f"$Mode='{body.source}'; $Delay={body.delay}\n" + SCRIPT.read_text(encoding='utf-8')
        try:
            captured = json.loads(wmi.ps(script, timeout=60 + body.delay))
        except (RuntimeError, ValueError) as error:
            raise HTTPException(502, f'Could not read the {body.source}: {error}') from error
        title, process = str(captured.get('title') or ''), str(captured.get('process') or '').lower()
        if body.source != 'clipboard' and process in BROWSERS and 'atlas' in title.lower():
            raise HTTPException(409, 'Atlas was still in front. Click Read, then switch to the ticket or chat before the countdown ends.')
        text = str(captured.get('text') or '')
        if not text.strip():
            raise HTTPException(422, 'No text was found. Make the text larger or select the window, then retry.'
                                if body.source != 'clipboard' else 'The clipboard has no text.')
        result = {'source': body.source, 'title': title, 'process': captured.get('process') or '',
                  'text': text[:LIMIT], 'truncated': len(text) > LIMIT, 'language': captured.get('language') or ''}
        if body.source == 'clipboard':
            remember(text, 'inbox')
        return {**result, **analysed(title, text)}

    @app.post('/api/screen/image')
    async def read_image(request: Request):
        """Text from a screenshot the browser read from the clipboard or got from Ctrl+V, via Windows OCR."""
        check_token(request)
        if not windows():
            raise HTTPException(501, 'Reading screenshots needs Windows.')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > IMAGE_LIMIT:
                raise HTTPException(413, 'The image is larger than 15 MB.')
        captured = ocr_image(wmi.ps, bytes(data))
        text = str(captured.get('text') or '')
        title = 'Pasted screenshot'
        remember(text, 'screenshot')
        result = {'source': 'image', 'title': title, 'process': '', 'text': text[:LIMIT], 'truncated': len(text) > LIMIT,
                  'language': captured.get('language') or ''}
        return {**result, **analysed(title, text)}

    @app.post('/api/screen/analyse')
    def analyse_text(body: Text, request: Request):
        # Re-run after the operator corrects recognised text or chooses one of several people.
        check_token(request)
        if body.title == 'Clipboard' and body.user_id is None:
            remember(body.text, 'inbox')
        return {'title': body.title, 'text': body.text, **analysed(body.title, body.text, body.user_id)}
