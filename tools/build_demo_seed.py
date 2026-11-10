"""Rebuild the distributable fixture solely from schema and fictional inputs."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build(target):
    if target.exists():
        raise FileExistsError(target)
    con = sqlite3.connect(target)
    try:
        con.executescript((ROOT / 'resources/seed-schema.sql').read_text())
        def insert(table, values):
            columns = list(values)
            con.execute('insert into '+table+'('+','.join(columns)+') values('+','.join('?' for _ in columns)+')', tuple(values.values()))
        names=['Demo Arden','Demo Birch','Demo Cedar','Demo Dale','Demo Elm','Demo Fern','Demo Glen','Demo Heath']
        for i in range(1,129):
            account=f'X9000{i:04}';name=names[i-1] if i<=len(names) else f'Example Person {i:03}';email=f'person{i:03}@example.test'
            insert('users',dict(id=i,canonical_key=f'example:{i}',user_id=account,user_id_norm=account.lower(),
                full_name=name,full_name_norm=name.lower(),email=email,email_norm=email,
                employee_number=f'DEMO{i:04}',department='Example support',location='Paris'))
        for i in range(1,257):
            name=f'EXAMPLE-PC-{i:03}';account=f'X9000{(i-1)%128+1:04}'
            insert('machines',dict(id=i,machine_name=name,machine_name_norm=name.lower(),serial_number=f'EXAMPLE-SERIAL-{i:03}',
                model_id='Example Windows workstation',operational_status='Operational',assigned_to=account,last_logon_user=account))
        from identity_links import rebuild_links,MATCHING_VERSION
        rebuild_links(con)
        for name,table in [('data.json','records'),('official-data.json','official_records')]:
            for row in json.loads((ROOT/'atlas'/name).read_text())['records']:
                from atlas_store import validate
                row=validate(row)|{'revision':1}
                con.execute(f'insert into {table} values(?,?)',(row['id'],json.dumps(row)))
        con.executemany('insert into metadata values(?,?)',[
            ('atlas.seeded','1'),('directory.matching_version',MATCHING_VERSION),
            ('directory.generation','fictional-demo-v1'),('distribution','fictional-example-data-only')])
        con.execute("insert into desk_user_links values('04R024065','example:1','confirmed','2026-01-01')")
        for desk in ['04R024065']:
            row=json.loads(con.execute('select body from official_records where id=?',(desk,)).fetchone()[0])
            row.update(name=names[0],occupancy='assigned')
            con.execute('update official_records set body=? where id=?',(json.dumps(row),desk))
        con.commit()
        if con.execute('pragma integrity_check').fetchone()[0]!='ok':
            raise ValueError('Invalid demo seed')
        con.execute('vacuum')
    finally:
        con.close()


if __name__=='__main__':
    build(Path(sys.argv[1]))
