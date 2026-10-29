"""New joiner access: the requests each desk raises, read from the requests workbook.

The workbook (ListOfRequests.xlsx) has one sheet per desk with the columns Catalog Name, Request
Ticket Number and Notes: one row per request ticket, where the ticket is an earlier joiner's
request to copy. A Main sheet lists each desk sheet with its Area. Saved in C:\\AtlasXL, the import
folder reads it like the other exports and replaces the copy kept in persona-access.json.
Atlas never raises requests itself; the New joiners page lists them to raise and tick off.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

MAX_DESKS = 200
MAX_REQUESTS = 500
MAX_TEXT = 300


def key(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').casefold()).strip()


def text(value):
    return ' '.join(str(value or '').split())[:MAX_TEXT]


def columns(row):
    """Column numbers of Catalog Name, Request Ticket Number and Notes, or None for another row."""
    names = [key(cell) for cell in row]
    catalog = next((i for i, name in enumerate(names) if name in ('catalog name', 'catalogue name', 'catalog item', 'catalogue item')), None)
    ticket = next((i for i, name in enumerate(names) if 'ticket' in name or name in ('request', 'request number', 'req')), None)
    if catalog is None or ticket is None:
        return None
    return catalog, ticket, next((i for i, name in enumerate(names) if name in ('notes', 'note', 'comments')), None)


def parse(path):
    """{'desks': [{'name', 'area', 'requests': [{'catalog', 'ticket', 'notes'}]}]} from the workbook."""
    from backend.directory.directory_workbook import iter_rows, workbook_parts, workbook_scope

    @workbook_scope
    def read():
        desks, areas = [], {}
        for sheet, part in workbook_parts(path):
            header, rows = None, []
            for number, row in iter_rows(path, part):
                if header is None:
                    if number > 20:
                        break
                    header = columns(row)
                    if header is None and {'desk sheet', 'area'} <= {key(cell) for cell in row}:
                        names = [key(cell) for cell in row]
                        header = ('main', names.index('desk sheet'), names.index('area'))
                    continue
                if header[0] == 'main':
                    cells = row + [''] * 3
                    if text(cells[header[1]]):
                        areas[key(cells[header[1]])] = text(cells[header[2]])
                    continue
                catalog, ticket, notes = header
                cells = row + [''] * (max(i for i in header if i is not None) + 1)
                if not text(cells[catalog]):
                    continue
                rows.append({'catalog': text(cells[catalog]), 'ticket': text(cells[ticket]),
                             'notes': text(cells[notes]) if notes is not None else ''})
            if header and header[0] != 'main' and rows:
                if len(rows) > MAX_REQUESTS:
                    raise ValueError(f'{sheet} lists {len(rows)} requests; Atlas reads up to {MAX_REQUESTS} per desk.')
                desks.append({'name': text(sheet), 'requests': rows})
        if not desks:
            raise ValueError('No desk sheets with Catalog Name and Request Ticket Number columns were found.')
        if len(desks) > MAX_DESKS:
            raise ValueError(f'The workbook has {len(desks)} desk sheets; Atlas reads up to {MAX_DESKS}.')
        for desk in desks:
            desk['area'] = areas.get(key(desk['name']), '')
        return {'desks': desks}
    return read()


def recognise(path):
    """'access' for a requests workbook: an .xlsx with at least one desk sheet."""
    from backend.directory.directory_workbook import iter_rows, workbook_parts, workbook_scope

    @workbook_scope
    def check():
        for _, part in workbook_parts(path):
            for number, row in iter_rows(path, part):
                if number > 20:
                    break
                if columns(row):
                    return 'access'
        return ''
    return check()


class Store:
    """The desks and requests from the latest workbook, in one JSON file written atomically."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'desks': [], 'source': '', 'imported': ''}
        except (OSError, ValueError) as error:
            raise HTTPException(503, f'Cannot read the new joiner requests in {self.path}.') from error
        if not isinstance(data, dict) or not isinstance(data.get('desks'), list):
            raise HTTPException(503, f'Cannot read the new joiner requests in {self.path}.')
        return data

    def desk(self, name):
        wanted = key(name)
        return next((desk for desk in self.read()['desks'] if key(desk.get('name')) == wanted), None) if wanted else None

    def replace(self, parsed, source):
        data = {'version': 1, 'source': source, 'imported': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'desks': parsed['desks']}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
        return data
