"""No operational seating assignments may be reapplied from distributed assets."""
import json
import unittest
from pathlib import Path
from sqlite_fixture import connect
import tempfile
from unittest.mock import patch
import atlas_store as store
from official_atlas import apply_visual_matches


class VisualMatches(unittest.TestCase):
    def test_distribution_contains_no_automatic_person_mappings(self):
        data=json.loads((store.ROOT/'visual-seating-matches.json').read_text())
        self.assertEqual(data['matches'],[])

    def test_reviewed_mapping_is_idempotent_and_preserves_later_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            match=dict(source='L2-001',target='02R010070',sourceRevision=1,sourceName='Demo Arden',sourceX=.2,sourceY=.4,evidence='Fictional test')
            (root/'visual-seating-matches.json').write_text(json.dumps({'matches':[match]}))
            with connect(root/'fixture.db') as c:
                c.executescript('create table records(id text primary key,body text);create table official_records(id text primary key,body text);create table official_seating_mappings(legacy_id text primary key,official_id text unique,at text);create table desk_user_links(desk_id text,user_key text,method text,at text);create table history(seq integer primary key,desk_id text,at text,action text,before_json text,after_json text);')
                base=dict(floor=2,x=.2,y=.4,angle=0,kind='desk',occupancy='assigned',name='Demo Arden',team='',revision=1)
                c.execute('insert into records values(?,?)',('L2-001',json.dumps(dict(base,id='L2-001'))))
                c.execute('insert into official_records values(?,?)',('02R010070',json.dumps(dict(base,id='02R010070',name='Unconfirmed desk',occupancy='unconfirmed'))))
                with patch.object(store,'ROOT',root):
                    self.assertEqual(apply_visual_matches(c),1)
                    self.assertEqual(apply_visual_matches(c),0)
                    c.execute('delete from official_seating_mappings')
                    r=store.get_record(c,'02R010070');r['name']='Later edit'
                    c.execute('update official_records set body=?',(json.dumps(r),))
                    self.assertEqual(apply_visual_matches(c),0)
                    self.assertEqual(store.get_record(c,r['id'])['name'],'Later edit')
