"""Two ServiceNow exports (users, devices) as one directory workbook.

The import reads one workbook with "users" and "devices" sheets. Rather than asking for that
by hand, this writes it: each export may be .xlsx or .csv, in either order, and is copied cell
for cell (dates stay as exported) into a streamed workbook the existing import then validates.
"""
import codecs
import csv
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from backend.directory.directory_workbook import directory_columns, iter_rows, workbook_parts, workbook_scope

ILLEGAL_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')
REQUIRED = {'user': {'user_id', 'full_name', 'email'}, 'machine': {'machine_name'}}
LABEL = {'user': 'users', 'machine': 'devices'}


def rows(path):
    """Rows of the first non-empty sheet of an .xlsx, or of a CSV (UTF-8 or Windows-1252)."""
    path = Path(path)
    with path.open('rb') as handle:
        is_zip = handle.read(4) == b'PK\x03\x04'
    if is_zip:
        for _, part in workbook_parts(path):
            found = False
            for _, row in iter_rows(path, part, raw=True):
                found = True
                yield row
            if found:
                return
        return
    encoding = 'utf-8-sig'
    with path.open('rb') as handle:
        try:
            decoder = codecs.getincrementaldecoder('utf-8-sig')()
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                decoder.decode(chunk)
        except UnicodeDecodeError:
            encoding = 'cp1252'
    with path.open(encoding=encoding, newline='') as text:
        sample = text.read(65536)
        text.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        yield from csv.reader(text, dialect)


def kind_of(headers):
    """'user' when the export has the user identity columns, else 'machine' for a hostname column."""
    for kind in ('user', 'machine'):
        if REQUIRED[kind] <= {field for _, _, field in directory_columns(kind, headers)}:
            return kind
    return ''


def column(index):
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def sheet_xml(source_rows):
    yield b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    yield b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    for number, row in enumerate(source_rows, start=1):
        cells = ''.join(
            f'<c r="{column(i)}{number}" t="inlineStr"><is><t xml:space="preserve">{escape(ILLEGAL_XML.sub("", str(value)))}</t></is></c>'
            for i, value in enumerate(row) if str(value) != '')
        yield f'<row r="{number}">{cells}</row>'.encode('utf-8')
    yield b'</sheetData></worksheet>'


@workbook_scope
def combine(first, second, out):
    """Write out.xlsx with users and devices sheets; returns which input was which and row counts."""
    sources = {}
    for path in (first, second):
        header = next(iter(rows(path)), None)
        if not header:
            raise ValueError(f'{Path(path).name}: the file is empty.')
        kind = kind_of([str(value).strip() for value in header])
        if not kind:
            raise ValueError(f'{Path(path).name}: not a users or devices export. Users need user_name, name and email '
                             'columns; devices need a ci or name column.')
        if kind in sources:
            raise ValueError(f'Both files look like {LABEL[kind]} exports. Choose one users file and one devices file.')
        sources[kind] = Path(path)
    if 'user' not in sources:
        raise ValueError('Neither file looks like a users export (user_name, name and email columns).')
    counts = {}
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as book:
        book.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>')
        book.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
        book.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="users" sheetId="1" r:id="rId1"/><sheet name="devices" sheetId="2" r:id="rId2"/></sheets></workbook>')
        book.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '</Relationships>')
        # Two files with different kinds, one of them users: the other is the devices export.
        for number, kind in ((1, 'user'), (2, 'machine')):
            count, pending, size = 0, [], 0
            with book.open(f'xl/worksheets/sheet{number}.xml', 'w', force_zip64=True) as sheet:
                for piece in sheet_xml(rows(sources[kind])):
                    count += piece.startswith(b'<row ')
                    pending.append(piece)
                    size += len(piece)
                    if size >= 1 << 20:
                        sheet.write(b''.join(pending))
                        pending, size = [], 0
                sheet.write(b''.join(pending))
            counts[LABEL[kind]] = max(0, count - 1)
    return {'users_file': sources['user'].name, 'devices_file': sources['machine'].name, 'rows': counts}
