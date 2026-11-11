"""Reject operational data, stale manifests and retired editor files before release."""
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]


def main():
    manifest=json.loads((ROOT/'resources/runtime-manifest.json').read_text())['files']
    missing=[name for name in manifest if not (ROOT/name).is_file()]
    if missing:raise ValueError('Missing runtime entries: '+', '.join(missing))
    if (ROOT/'frontend/drawio').exists() or (ROOT/'templates/database040926.xlsx').exists():
        raise ValueError('Retired operational/editor assets must not be distributed')
    with sqlite3.connect((ROOT/'office_atlas.db').as_uri()+'?mode=ro',uri=True) as c:
        if c.execute("select value from metadata where key='distribution'").fetchone()!=('fictional-example-data-only',):
            raise ValueError('The distributed seed must be fictional')
        if c.execute("select count(*) from users where email not like '%@example.test' or canonical_key not like 'example:%'").fetchone()[0]:
            raise ValueError('Non-fictional directory records found')
        if c.execute("select count(*) from machines where machine_name not like 'EXAMPLE-PC-%' or serial_number not like 'EXAMPLE-SERIAL-%'").fetchone()[0]:
            raise ValueError('Non-fictional machine records found')
        for table in ('history','deployments','directory_export_rows','desk_link_history','official_seating_mappings'):
            if c.execute('select count(*) from '+table).fetchone()[0]:raise ValueError('Operational history found in seed: '+table)
    for name in ('data.json','official-data.json'):
        data=json.loads((ROOT/'atlas'/name).read_text())
        for row in data['records']:
            if any(row.get(k) for k in ('hostname','asset','notes','outlet')):raise ValueError('Operational seating fields in '+name)
            if row['occupancy']=='assigned' and not row['name'].startswith(('Example Person ','Demo ')):
                raise ValueError('Non-fictional seating name in '+name)
    import sys
    sys.path.insert(0,str(ROOT))
    from directory_workbook import workbook_parts,iter_rows
    template=ROOT/'templates/desk_moves_template.xlsx'
    part=dict(workbook_parts(template))['Desk moves']
    for number,row in iter_rows(template,part):
        if number>1 and row[2] not in ('Vacant desk','Unconfirmed desk') and not row[2].startswith(('Example Person ','Demo ')):
            raise ValueError('Non-fictional name in desk-move template')
    print('PASS: fictional seed, seating assets and explicit runtime manifest')


if __name__=='__main__':main()
