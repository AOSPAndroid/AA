"""Large-import behavior and bounded previews, using fictional records only."""
import random
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.database_manager import compare, compare_rows
from backend.directory.directory_workbook import NS, iter_rows, schema, workbook_scope
from backend.directory.merge_data import atlas_schema


class AuditOptimizations(unittest.TestCase):
    def test_streamed_diff_matches_full_comparison_and_bounds_examples(self):
        rng = random.Random(42)
        for _ in range(30):
            old = {f'key-{i:03}': rng.randrange(5) for i in rng.sample(range(200), 100)}
            new = {f'key-{i:03}': rng.randrange(5) for i in rng.sample(range(200), 100)}
            result = compare_rows(iter(sorted(old.items())), iter(sorted(new.items())), key=lambda row: row[0])
            self.assertEqual(result, {
                'before':len(old), 'after':len(new), 'added':len(new.keys()-old.keys()),
                'removed':len(old.keys()-new.keys()),
                'changed':sum(old[k]!=new[k] for k in old.keys() & new.keys()),
                'added_examples':sorted(new.keys()-old.keys())[:20],
                'removed_examples':sorted(old.keys()-new.keys())[:20],
            })
        self.assertEqual(compare_rows(iter([]), iter([]))['changed'], 0)

    def test_preview_ignores_row_ids_and_preserves_links_and_missing_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = [Path(tmp)/name for name in ('old.db','new.db')]
            for db, offset in ((before,0),(after,100)):
                c=sqlite3.connect(db)
                try:
                    schema(c);atlas_schema(c)
                    c.execute('insert into users(id,canonical_key,user_id,full_name) values(?,?,?,?)', (1+offset,'uid:sample','sample','Sample Person'))
                    c.execute('insert into machines(id,machine_name,machine_name_norm) values(?,?,?)', (2+offset,'PC01','pc01'))
                    c.execute('insert into assignments(user_id_ref,machine_id,relationship_type) values(?,?,?)', (1+offset,2+offset,'assigned_to'))
                    c.execute('insert into desk_user_links values(?,?,?,?)', ('desk','uid:missing','confirmed','fixture'))
                    c.commit()
                finally:c.close()
            result=compare(before,after)
            self.assertEqual(result['users']['changed'],0)
            self.assertEqual(result['machines']['changed'],0)
            self.assertEqual(result['relationships'],dict(before=1,after=1,added=0,removed=0))
            self.assertEqual(result['missing_desk_accounts'],[dict(desk='desk',account='uid:missing')])

    def test_streamed_xml_keeps_rich_strings_sparse_cells_and_raw_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.xlsx'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{NS[1:-1]}"><si><r><t>Shared </t></r><r><t>value</t></r></si><si><t> Other </t></si></sst>')
                sheet=f'<worksheet xmlns="{NS[1:-1]}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t> raw </t></is></c></row><row r="2"/><row r="3"><c r="B3" t="s"><v>1</v></c><c r="C3"><v>0</v></c></row></sheetData></worksheet>'
                for tab in ('one','two'):archive.writestr('xl/'+tab+'.xml',sheet)
            @workbook_scope
            def read():
                self.assertEqual(list(iter_rows(path,'xl/one.xml',raw=True)),[(1,['Shared value','',' raw ']),(3,['',' Other ','0'])])
                self.assertEqual(list(iter_rows(path,'xl/two.xml')),[(1,['Shared value','','raw']),(3,['','Other','0'])])
            read()
