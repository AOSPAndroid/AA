"""The desk-plan reader on drawn layouts: same cell, stacked cells, merged boxes; synthetic data."""
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from atlas_store import ClosingConnection
from seating_grid import name_key, read_plan

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def sheet_xml(cells, merges=()):
    rows = {}
    for ref, text in cells.items():
        number = int(''.join(ch for ch in ref if ch.isdigit()))
        rows.setdefault(number, []).append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
    body = ''.join(f'<row r="{n}">{"".join(cells)}</row>' for n, cells in sorted(rows.items()))
    merged = f'<mergeCells count="{len(merges)}">' + ''.join(f'<mergeCell ref="{m}"/>' for m in merges) + '</mergeCells>' if merges else ''
    return f'<worksheet xmlns="{NS}"><sheetData>{body}</sheetData>{merged}</worksheet>'


def plan(path, sheets, hidden=()):
    with zipfile.ZipFile(path, 'w') as z:
        tabs = ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="r{i}"{' state="hidden"' if name in hidden else ''}/>' for i, name in enumerate(sheets, 1))
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{tabs}</sheets></workbook>')
        rels = ''.join(f'<Relationship Id="r{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, (cells, merges) in enumerate(sheets.values(), 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', sheet_xml(cells, merges))


class DeskPlanReader(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = sqlite3.connect(':memory:', factory=ClosingConnection)
        self.addCleanup(self.c.close)
        self.c.execute('create table users(canonical_key,user_id,email,full_name,department,location)')
        self.c.executemany('insert into users values(?,?,?,?,?,?)', [
            ('k1', 'durc', 'c@x.test', 'DURIEZ Christophe', 'Sales', 'Paris - 52 Avenue Hoche'),
            ('k2', 'konesand', 's@x.test', 'Sandrine Kone Penali', 'Market Risk - Europe', 'Paris - 52 Avenue Hoche'),
            ('k3', 'a1', 'a1@x.test', 'Alex Smith', '', ''), ('k4', 'a2', 'a2@x.test', 'Alex Smith', '', ''),
            ('k5', 'tdl', 't1@x.test', 'Thomas Dubois Lefevre', '', 'London'), ('k6', 'tdm', 't2@x.test', 'Thomas Dubois Martin', '', 'Paris'),
            ('k7', 'mr1', 'm1@x.test', 'Marie Roux Blanc', '', 'Paris'), ('k8', 'mr2', 'm2@x.test', 'Marie Roux Noir', '', 'Paris'),
            ('k9', 'ons', 'o@x.test', 'Ons Belkecir', '', 'Paris - 52 Avenue Hoche'),
            ('k10', 'rp1', 'r1@x.test', 'Rishi Patel', '', 'London'), ('k11', 'rp2', 'r2@x.test', 'Rishi Patel', '', 'Paris')])

    def test_layouts_people_labels_and_problems(self):
        path = Path(self.temp.name) / 'plan.xlsx'
        plan(path, {
            '+2 (FINAL)': ({'B2': 'Christophe Duriez', 'B3': '02R015079',             # stacked cells
                            'D2': 'Sandrine Kone', 'D4': '2R019073',                     # merged box D2:D3 above the code
                            'F2': 'Open 02R016079', 'G2': 'Credit Sales\n02R016081', 'H2': 'Credit Sales\n02R017071',
                            'B6': 'Alex Smith\n02R011079', 'C6': 'Oren Ruban (intern)\n02R010086', 'D6': 'Ghost\n02R999999',
                            'B8': 'Thomas Dubois\n02R011081', 'C8': 'Marie Roux\n02R011086',
                            'B10': 'Ons Belkicir\n02R020088', 'C10': 'Rishi Patel\n03R011081', 'D10': 'Alessandro Pelleriti\n02R015081'},
                           ['D2:D3']),
            'Desk Mapping (FINAL)': ({'A1': 'Pierre Haberer 02R015079', 'A2': 'Notes only'}, []),
            'Headcount': ({'A1': 'Team', 'B1': '12'}, []),
        })
        known = {d: {'team': 'Credit'} for d in ('02R015079', '02R019073', '02R016079', '02R016081', '02R017071', '02R011079', '02R010086', '02R011081', '02R011086', '02R020088', '03R011081', '02R015081')}
        result = read_plan(path, self.c, known)
        rows = {row['desk']: row for row in result['rows']}
        self.assertEqual((rows['02R015079']['kind'], rows['02R015079']['account']), ('person', 'durc'), 'Name in the cell above; order-free match')
        self.assertEqual((rows['02R019073']['name'], rows['02R019073']['account']), ('Sandrine Kone', 'konesand'), 'Merged box; shorter plan name, plan wording kept')
        self.assertEqual(rows['02R011081']['account'], 'tdm', 'Two fuller names: the one in Paris')
        self.assertEqual(rows['02R011086']['kind'], 'label', 'Two fuller names in Paris: not guessed')
        self.assertEqual([(m['name'], m['directory'], m['how']) for m in result['matched_partly']],
                         [('Sandrine Kone', 'Sandrine Kone Penali', 'fuller'), ('Thomas Dubois', 'Thomas Dubois Martin', 'fuller'),
                          ('Ons Belkicir', 'Ons Belkecir', 'spelling'), ('Rishi Patel', 'Rishi Patel', 'paris')])
        self.assertEqual(rows['02R015081']['kind'], 'label', 'A spelling far from anyone in Paris is not guessed')
        self.assertEqual(rows['02R016079']['status'], 'vacant')
        self.assertEqual([rows[d]['kind'] for d in ('02R016081', '02R017071')], ['label', 'label'])
        self.assertEqual(rows['02R011079']['kind'], 'label', 'Two directory people share the name: not guessed')
        self.assertEqual(rows['02R010086']['name'], 'Oren Ruban (intern)')
        self.assertEqual(result['fixes'], [{'cell': '+2 (FINAL)!D4', 'written': '2R019073', 'desk': '02R019073'}])
        self.assertEqual(result['unknown_desks'], [{'cell': '+2 (FINAL)!D6', 'desk': '02R999999', 'label': 'Ghost'}])
        self.assertEqual(result['conflicts'], [], 'The floor tab wins over a tab naming no floor')
        self.assertEqual(result['sheets'], {'+2 (FINAL)': 13, 'Desk Mapping (FINAL)': 1})
        flagged = {item['name']: item['ambiguous'] for item in result['not_in_directory']}
        self.assertEqual(flagged, {'Alex Smith': True, 'Oren Ruban (intern)': False, 'Marie Roux': False, 'Alessandro Pelleriti': False}, 'Repeated team labels are not flagged as people')
        self.assertEqual(name_key('Duriez,  CHRISTOPHE (intern)'), 'christophe duriez')

    def test_floor_tabs_win_over_hidden_old_and_list_tabs(self):
        path = Path(self.temp.name) / 'plan.xlsx'
        plan(path, {
            # An older copy hidden to the left of the FINAL tabs: never read.
            'R+4 (OLD)': ({'A1': 'Open\n04R019086', 'B1': '04R014086'}, []),
            'R+4 (DRAFT)': ({'A1': 'Open\n04R015088'}, []),
            'R+4 (FINAL)': ({'A1': 'Christophe Duriez\n04R019086', 'B1': 'Equities\n04R014086', 'C1': '04R015090',
                             'A3': 'Sandrine Kone\n04R015088'}, []),
            # A list tab: desk and name columns, read row by row; a floor tab still wins.
            'Desk Mapping (FINAL)': ({'A1': 'Desk number', 'B1': 'Team name', 'C1': 'Person assigned', 'A2': '04R019086', 'C2': 'Someone Else',
                                      'A3': '04R009086', 'C3': 'Ons Belkicir', 'A4': '04R009088', 'B4': 'Equities',
                                      'A5': '04R009090'}, []),
            'R+4 (FINAL) (2)': ({'A1': 'Marie Roux\n04R015088', 'A3': 'Alex Smith\n02R011079'}, []),
            # A list with no header row: the person is in the cell beside the code.
            'Moves': ({'A1': '04R011090', 'B1': 'Christophe Duriez'}, []),
        }, hidden={'R+4 (OLD)'})
        known = {d: {'team': 'Equities'} for d in ('04R019086', '04R014086', '04R015088', '04R015090', '04R009086', '04R009088', '04R009090', '04R011090', '04R011088', '02R011079')}
        result = read_plan(path, self.c, known)
        rows = {row['desk']: row for row in result['rows']}
        self.assertEqual(result['hidden_sheets'], ['R+4 (OLD)'])
        self.assertNotIn('R+4 (OLD)', result['sheets'])
        self.assertEqual((rows['04R019086']['account'], rows['04R019086']['_cell']), ('durc', 'R+4 (FINAL)!A1'))
        self.assertEqual(rows['04R014086']['name'], 'Equities', 'A team desk on the floor tab stays a team desk')
        self.assertEqual(rows['04R015088']['account'], 'konesand', 'The FINAL tab beats a draft of the same floor')
        self.assertEqual((rows['04R009086']['account'], rows['04R009088']['name']), ('ons', 'Equities'), 'List rows: name column, else team')
        self.assertNotIn('04R015090', rows, 'A bare code says nothing, so the desk is left alone')
        self.assertEqual(rows['04R011090']['account'], 'durc')
        self.assertEqual(result['other_floor'], [{'cell': 'R+4 (FINAL) (2)!A3', 'desk': '02R011079', 'label': 'Alex Smith'}])
        self.assertNotIn('04R009090', rows)
        self.assertEqual([item['desk'] for item in result['blank']], ['04R015090', '04R009090'])
        self.assertEqual(result['conflicts'], [{'desk': '04R015088', 'cells': ['R+4 (FINAL)!A3', 'R+4 (FINAL) (2)!A1'], 'labels': ['Sandrine Kone', 'Marie Roux']}],
                         'Two FINAL tabs for the same floor that disagree still need a person')

    def test_no_desk_codes(self):
        path = Path(self.temp.name) / 'joiners.xlsx'
        plan(path, {'Sheet1': ({'A1': 'Name', 'B1': 'Start date'}, [])})
        with self.assertRaisesRegex(ValueError, 'No desk codes'):
            read_plan(path, self.c)


if __name__ == '__main__':
    unittest.main()
