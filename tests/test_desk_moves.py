from sqlite_fixture import connect as fixture_connect
import unittest,tempfile,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.seating import desk_moves as dm
class DeskMoves(unittest.TestCase):
 def test_swap_roundtrip_conflicts_and_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);db=root/'test.db'
   with fixture_connect(Path(dm.__file__).parent/'office_atlas.db') as a,fixture_connect(db) as b:a.backup(b)
   p=root/'export.xlsx';p.write_bytes(dm.export_workbook(db));part=dict(dm.workbook_parts(p))['Desk moves'];it=dm.iter_rows(p,part);_,h=next(it);self.assertEqual(h,dm.HEADERS);rows=[r for _,r in it];self.assertEqual(len(rows),524)
   # Choose two occupied desks. Explicit links must travel while hostnames stay put.
   with fixture_connect(db) as c:
    records,_=dm.snapshot(c);ids=[id for id,r in records.items() if r['kind']=='desk' and r['occupancy']=='assigned'][:2];a,b=ids
    keys=[r[0] for r in c.execute('select canonical_key from users limit 2')]
    for id,key in zip(ids,keys):c.execute('insert or replace into desk_user_links values(?,?,?,?)',(id,key,'confirmed','test'))
   def move_rows():
    result=copy.deepcopy(rows)
    for r in result:
     r.extend(['']*(12-len(r)))
     if r[0]==a:r[11]=b
     if r[0]==b:r[11]=a
    return result
   with fixture_connect(db) as c:plan=dm.plan_moves(c,move_rows())
   backup=dm.apply_moves(db,plan,root/'backups');self.assertTrue((root/'backups'/backup).exists())
   with fixture_connect(db) as c:
    now,links=dm.snapshot(c);self.assertEqual(now[a]['name'],records[b]['name']);self.assertEqual(now[b]['name'],records[a]['name']);self.assertEqual(links[a],keys[1]);self.assertEqual(now[a]['hostname'],records[a]['hostname']);self.assertEqual(now[a]['x'],records[a]['x'])
    with self.assertRaises(ValueError):dm.plan_moves(c,move_rows())
   with self.assertRaises(ValueError):dm.apply_moves(db,plan,root/'backups')
   # Restore test baseline and ensure an occupied destination requires an explicit outgoing move.
   with fixture_connect(root/'backups'/backup) as src,fixture_connect(db) as dst:src.backup(dst)
   bad=move_rows()
   for r in bad:
    if r[0]==b:r[11]=''
   with fixture_connect(db) as c:
    with self.assertRaises(ValueError):dm.plan_moves(c,bad)
   # Transaction rollback if a later write fails.
   from unittest.mock import patch
   original=dm.store.save_record;calls=[]
   def fail(*args):
    calls.append(1)
    if len(calls)==2:raise RuntimeError('injected failure')
    return original(*args)
   with patch.object(dm.store,'save_record',fail):
    with self.assertRaises(RuntimeError):dm.apply_moves(db,plan,root/'backups')
   with fixture_connect(db) as c:
    now,_=dm.snapshot(c);self.assertEqual(now[a],records[a]);self.assertEqual(now[b],records[b])
if __name__=='__main__':unittest.main()
