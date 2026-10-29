from sqlite_fixture import connect as fixture_connect
import unittest,tempfile,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import atlas_store as store
from backend.seating.official_atlas import apply_visual_matches
class VisualMatches(unittest.TestCase):
 def test_migration_and_guards(self):
  with tempfile.TemporaryDirectory() as tmp:
   with fixture_connect(store.DB) as a,fixture_connect(Path(tmp)/'test.db') as c:
    a.backup(c)
    c.execute('delete from official_seating_mappings');c.execute('delete from desk_user_links where desk_id not like "L%"')
    c.execute('delete from official_records')
    for r in json.loads((store.ROOT/'official-data.json').read_text())['records']:c.execute('insert into official_records values(?,?)',(r['id'],json.dumps(r)))
    before=list(c.execute('select id,body from records order by id'))
    self.assertEqual(apply_visual_matches(c),300);self.assertEqual(apply_visual_matches(c),0)
    self.assertEqual(list(c.execute('select id,body from records order by id')),before)
    for target,name in [('03R030090','Lina HOMOR'),('03B043086','Ayoub Asseli'),('03B044090','Baptiste Flais'),('03R031059','Sabri El Jailani')]:
     r=store.get_record(c,target);self.assertEqual(r['name'],name);self.assertFalse(r['verified'])
    for source,target in c.execute('select legacy_id,official_id from official_seating_mappings').fetchall():
     a=c.execute('select user_key from desk_user_links where desk_id=?',(source,)).fetchone()
     if a:self.assertEqual(a,c.execute('select user_key from desk_user_links where desk_id=?',(target,)).fetchone())
    c.execute('delete from official_seating_mappings where legacy_id="L3-030"')
    r=store.get_record(c,'03R030090');r['name']='Later edit';c.execute('update official_records set body=? where id=?',(json.dumps(r),r['id']))
    self.assertEqual(apply_visual_matches(c),0);self.assertEqual(store.get_record(c,r['id'])['name'],'Later edit')
if __name__=='__main__':unittest.main()
