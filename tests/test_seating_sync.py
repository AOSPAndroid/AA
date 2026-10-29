"""Live floor plan against a copy of the Atlas database; plans are synthetic workbooks."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from backend import atlas_store as store
from backend.atlas_store import ClosingConnection
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.seating.desk_moves import snapshot
from backend.seating.seating_sync import SeatingSync, Settings, large, register, seating_version
from sqlite_fixture import connect as fixture_connect
from test_directory_exports import workbook

SEED = Path(__file__).resolve().parents[1] / 'office_atlas.db'


def official(db, desk):
    with sqlite3.connect(db, factory=ClosingConnection) as c:
        row = c.execute('select body from official_records where id=?', (desk,)).fetchone()
        link = c.execute('select user_key from desk_user_links where desk_id=?', (desk,)).fetchone()
    return json.loads(row[0]), link and link[0]


@unittest.skipUnless(SEED.is_file(), 'Seed database not available')
class LiveFloorPlan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = root / 'office_atlas.db'
        with fixture_connect(SEED) as a, fixture_connect(self.db) as b:
            a.backup(b)
        self.folder = root / '02_Current_plan'
        self.folder.mkdir()
        self.busy = False
        self.sync = SeatingSync(self.db, root / 'seating-sync.json', root / 'backups', busy=lambda: self.busy)
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            records, _ = snapshot(c)
        self.desks = sorted(d for d, r in records.items() if r.get('layout') == 'official' and d.startswith('02R'))
        # Fourteen boxes like the assistants' sheet: two people, team desks, an office, Open.
        self.layout = [
            ['Private Office (209)\n16m2\nGCAS (Baptiste Flais + Manon Desmazes)\n02R010070', 'Credit Sales\n2R017069', 'Compliance\n2R019069'],
            ['Jennifer Aidaoui\n02R011079', 'Credit Sales\n02R017071', 'Market Risk\n2R019071'],
            ['Christophe Duriez\n02R015079', 'Credit Sales\n02R016079', 'Credit Sales\n02R016081'],
            ['Cedric Authier\n02R011081', 'Pierre Haberer\n02R015081', 'TFS Credit\n02R017073'],
            ['Oren Ruban (intern)\n02R010086', 'Sandrine Kone\n2R019073', ''],
        ]

    def write(self, name, rows, age=120):
        path = self.folder / name
        workbook(path, {'+2 (FINAL)': rows, 'Headcount': [['Team', 'Count'], ['Credit', '12']]})
        past = time.time() - age
        os.utime(path, (past, past))
        return path

    def test_plan_changes_reach_the_map_with_a_backup(self):
        self.write('Hoche Project_20261002.xlsx', self.layout)
        self.write('New Joiners 2026.xlsx', [['Name', 'Start'], ['Someone', '01/11/2026']], age=60)
        self.assertEqual(self.sync.summary()['status']['state'], 'off')
        result = self.sync.configure(Settings(folder=f'"{self.folder}"', enabled=True))
        self.assertTrue(result['enabled'], 'Pasted paths in quotes are fine')
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            before = seating_version(c)['version']
        first = self.sync.check()
        self.assertEqual(first['status']['state'], 'synced', first['status'])
        self.assertEqual(first['last']['file'], 'Hoche Project_20261002.xlsx', 'A newer non-plan workbook is skipped')
        self.assertEqual([fix['desk'] for fix in first['last']['reader']['fixes']], ['02R017069', '02R019069', '02R019071', '02R019073'])
        record, link = official(self.db, '02R010070')
        self.assertEqual(record['name'], 'Private Office (209) 16m2 GCAS (Baptiste Flais + Manon Desmazes)')
        self.assertEqual(record['occupancy'], 'unconfirmed')
        # Christophe moves to a team desk; his old desk opens.
        moved = [row[:] for row in self.layout]
        moved[2] = ['Open\n02R015079', 'Christophe Duriez\n02R016079', 'Credit Sales\n02R016081']
        self.write('Hoche Project_20261020.xlsx', moved, age=60)
        second = self.sync.check()
        self.assertEqual(second['status']['state'], 'synced', second['status'])
        self.assertEqual(second['last']['counts'].get('moved'), 1, second['last'])
        self.assertEqual(official(self.db, '02R016079')[0]['name'], 'Christophe Duriez')
        self.assertEqual(official(self.db, '02R015079')[0]['occupancy'], 'vacant')
        self.assertTrue(official(self.db, '02R016079')[1], 'The person is linked to their directory account')
        self.assertTrue((self.db.parent / 'backups' / second['history'][0]['backup']).is_file())
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            after = seating_version(c)
        self.assertNotEqual(after['version'], before, 'Open maps see a new version')
        self.assertEqual(after['live_plan']['source'], 'Hoche Project_20261020.xlsx')
        self.assertEqual(self.sync.check()['history'], second['history'], 'An unchanged file is not applied twice')

    def test_undo_puts_desks_back_and_a_reader_update_reads_again(self):
        self.write('plan.xlsx', self.layout)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        self.assertEqual(self.sync.check()['status']['state'], 'synced')
        seats = lambda: [(r['name'], r['team'], r['occupancy'], link) for r, link in (official(self.db, d) for d in ('02R015079', '02R016079'))]
        before = seats()
        moved = [row[:] for row in self.layout]
        moved[2] = ['Open\n02R015079', 'Christophe Duriez\n02R016079', 'Credit Sales\n02R016081']
        self.write('plan.xlsx', moved, age=60)
        update = self.sync.check()['history'][0]
        self.assertEqual(update['desks'], ['02R015079', '02R016079'])
        # Updates made before desk lists were kept still undo, from the import log.
        del self.sync.state['history'][0]['desks']
        undone = self.sync.undo(update['backup'])
        self.assertEqual(seats(), before)
        self.assertEqual(undone['history'][0]['counts'], {'restored': 2})
        self.assertTrue(undone['history'][1]['undone'])
        self.assertEqual(self.sync.check()['history'], undone['history'], 'The same file is not applied again after an undo')
        with self.assertRaises(HTTPException):
            self.sync.undo(update['backup'])
        # A newer reader reads the unchanged file again.
        self.sync.state['last']['signature'] = self.sync.state['last']['signature'][:3]
        self.assertEqual(self.sync.check()['history'][0]['file'], 'plan.xlsx')
        self.assertEqual(official(self.db, '02R016079')[0]['name'], 'Christophe Duriez')

    def test_a_workbook_with_floor_tabs_beats_a_newer_list(self):
        self.write('Hoche Project_20261002.xlsx', self.layout)
        path = self.folder / 'New Joiners 2026.xlsx'
        workbook(path, {'Joiners': [['Name', 'Desk']] + [[f'Joiner {i}', desk] for i, desk in enumerate(self.desks[:12])]})
        past = time.time() - 60
        os.utime(path, (past, past))
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        self.assertEqual(self.sync.check()['last']['file'], 'Hoche Project_20261002.xlsx')

    def moved_update(self):
        self.write('plan.xlsx', self.layout)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        self.sync.check()
        moved = [row[:] for row in self.layout]
        moved[2] = ['Open\n02R015079', 'Christophe Duriez\n02R016079', 'Credit Sales\n02R016081']
        self.write('plan.xlsx', moved, age=60)
        return self.sync.check()['history'][0]

    def test_undo_preserves_newer_desk_details_and_clears_verification(self):
        update = self.moved_update()
        desk = '02R016079'
        original, _ = official(self.db, desk)
        details = {'notes': 'Later manual note', 'asset': 'ASSET-NEW', 'hostname': 'PC-NEW',
                   'outlet': 'NEW-OUTLET', 'status': 'Reviewed hardware', 'x': 0.123456, 'y': 0.654321, 'angle': 90}
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            store.save_record(c, dict(original, **details, verified=True), original, 'fixture later desk edit')
        history = json.dumps(self.sync.state['history'], sort_keys=True)
        with patch('backend.seating.seating_sync.apply_sheet', side_effect=store.Conflict('fixture concurrent edit')):
            with self.assertRaises(HTTPException) as caught:
                self.sync.undo(update['backup'])
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(json.dumps(self.sync.state['history'], sort_keys=True), history)
        self.sync.undo(update['backup'])
        restored, _ = official(self.db, desk)
        self.assertEqual({field: restored[field] for field in details}, details)
        self.assertFalse(restored['verified'], 'Restored seating must be checked again')
        self.assertEqual((restored['name'], restored['occupancy']), ('Credit Sales', 'unconfirmed'),
                         'Repeated unconfirmed team labels remain valid')

    def test_undo_older_update_refuses_later_move_without_writes(self):
        update = self.moved_update()
        source, target = '02R016079', '02R016081'
        moving, person = official(self.db, source)
        destination, _ = official(self.db, target)
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            store.save_record(c, dict(moving, name='Vacant desk', occupancy='vacant'), moving, 'fixture later move')
            store.save_record(c, dict(destination, **{field: moving[field] for field in ('name', 'team', 'occupancy')}),
                              destination, 'fixture later move')
            c.execute('delete from desk_user_links where desk_id in (?,?)', (source, target))
            c.execute('insert into desk_user_links values(?,?,?,?)', (target, person, 'confirmed', 'fixture'))
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            before = snapshot(c)
            version = seating_version(c)
        history = json.dumps(self.sync.state['history'], sort_keys=True)
        backups = set(self.sync.backups.glob('*.db'))
        with self.assertRaises(HTTPException) as caught:
            self.sync.undo(update['backup'])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('same person', caught.exception.detail)
        self.assertIn(target, caught.exception.detail)
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            self.assertEqual(snapshot(c), before, 'Undo neither duplicates the person nor vacates their newer desk')
            self.assertEqual(seating_version(c), version)
        self.assertEqual(json.dumps(self.sync.state['history'], sort_keys=True), history)
        self.assertEqual(set(self.sync.backups.glob('*.db')), backups, 'No replacement backup was created')

    def test_just_saved_busy_large_and_missing(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        self.write('plan.xlsx', self.layout, age=5)
        self.assertEqual(self.sync.check()['status']['state'], 'waiting', 'A file still being saved is read later')
        self.write('plan.xlsx', self.layout)
        self.busy = True
        self.assertEqual(self.sync.check()['status']['state'], 'waiting', 'Seating waits for running jobs')
        self.busy = False
        self.assertEqual(self.sync.check()['status']['state'], 'synced')
        # Vacating 60 desks in one save is held for review, then applied on request.
        free = [[f'Open\n{desk}' for desk in self.desks[i:i + 6]] for i in range(0, 60, 6)]
        self.write('plan.xlsx', free, age=50)
        held = self.sync.check()
        self.assertEqual(held['status']['state'], 'held', held['status'])
        self.assertTrue(held['held']['report']['changes'])
        applied = self.sync.apply_held(held['held']['id'])
        self.assertEqual(applied['status']['state'], 'synced')
        self.assertIsNone(applied['held'])
        self.sync.configure(Settings(folder=str(self.folder / 'missing'), enabled=True))
        self.assertEqual(self.sync.check()['status']['state'], 'error')
        self.assertEqual(self.sync.configure(Settings(folder='', enabled=True))['enabled'], False)

    def hold_plan(self, name='plan.xlsx', count=60, age=120):
        free = [[f'Open\n{desk}' for desk in self.desks[i:i + 6]] for i in range(0, count, 6)]
        self.write(name, free, age=age)
        held = self.sync.check()
        self.assertEqual(held['status']['state'], 'held', held['status'])
        return held['held']

    def test_applying_a_replaced_review_is_rejected_without_writes(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        first = self.hold_plan()
        second = self.hold_plan('new-plan.xlsx', count=66, age=60)
        self.assertNotEqual(first['id'], second['id'])
        with patch('backend.seating.seating_sync.apply_sheet') as apply:
            with self.assertRaises(HTTPException) as caught:
                self.sync.apply_held(first['id'])
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn('out of date', caught.exception.detail)
            apply.assert_not_called()
        self.assertEqual(self.sync.summary()['held']['id'], second['id'])
        self.assertEqual(self.sync.summary()['history'], [])

    def test_held_review_rebuilds_after_restart_without_manual_check(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        first = self.hold_plan()
        restarted = SeatingSync(self.db, self.sync.state_path, self.sync.backups)
        self.assertIsNone(restarted.summary()['held'], 'Only state, not the proposal, is persisted')
        with patch('backend.seating.seating_sync.apply_sheet') as apply:
            rebuilt = restarted.check()
            apply.assert_not_called()
        self.assertEqual(rebuilt['status']['state'], 'held')
        self.assertEqual(rebuilt['held']['report']['changes'], first['report']['changes'])
        self.assertNotEqual(rebuilt['held']['id'], first['id'], 'A rebuilt review gets a fresh identity')
        self.assertEqual(restarted.check()['held']['id'], rebuilt['held']['id'], 'Unchanged checks retain the current review')

    def test_apply_endpoint_requires_the_reviewed_id_and_token(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        held = self.hold_plan()
        app = FastAPI()
        def token(request):
            if request.headers.get('x-atlas-token') != 'fixture':
                raise HTTPException(403, 'Token required')
        with patch('backend.seating.seating_sync.SeatingSync', return_value=self.sync):
            register(app, SimpleNamespace(MASTER_DB=str(self.db)), token, lambda: False, self.sync.state_path)
        client = TestClient(app)
        with patch('backend.seating.seating_sync.apply_sheet') as apply:
            self.assertEqual(client.post('/api/seating-sync/apply', json={'id': held['id']}).status_code, 403)
            self.assertEqual(client.post('/api/seating-sync/apply', json={}, headers={'x-atlas-token': 'fixture'}).status_code, 422)
            response = client.post('/api/seating-sync/apply', json={'id': 'old-review'}, headers={'x-atlas-token': 'fixture'})
            self.assertEqual(response.status_code, 409)
            apply.assert_not_called()

    def test_the_plan_wins_a_person_on_two_desks_is_placed_on_both(self):
        twice = [row[:] for row in self.layout]
        twice[2] = ['Christophe Duriez\n02R015079', 'Christophe Duriez\n02R016079', 'Credit Sales\n02R016081']
        self.write('plan.xlsx', twice)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        result = self.sync.check()
        self.assertEqual(result['status']['state'], 'synced', result['status'])
        self.assertEqual([official(self.db, d)[0]['name'] for d in ('02R015079', '02R016079')], ['Christophe Duriez'] * 2)
        self.assertIn('Same person on 02R015079, 02R016079 in the Excel: placed on each, as written.', result['last']['notes'])

    def test_an_old_desk_holding_only_the_name_is_freed(self):
        # Before the live plan, a person could sit on a second desk by name only, with no account link.
        spare = next(d for d in self.desks if d not in ('02R015079', '02R016079', '02R010070', '02R011079', '02R011081', '02R015081', '02R016081', '02R017069', '02R017071', '02R017073', '02R019069', '02R019071', '02R019073', '02R010086'))
        with sqlite3.connect(self.db, factory=ClosingConnection) as c:
            body = json.loads(c.execute('select body from official_records where id=?', (spare,)).fetchone()[0])
            c.execute('update official_records set body=? where id=?', (json.dumps(dict(body, name='Christophe Duriez', occupancy='assigned')), spare))
            c.execute('delete from desk_user_links where desk_id=?', (spare,))
        self.write('plan.xlsx', self.layout)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        result = self.sync.check()
        self.assertEqual(result['status']['state'], 'synced', result['status'])
        self.assertEqual(official(self.db, spare)[0]['occupancy'], 'vacant', 'The plan places him at 02R015079 only')
        self.assertEqual(official(self.db, '02R015079')[0]['name'], 'Christophe Duriez')

    def test_the_card_lists_people_on_more_than_one_desk(self):
        twice = [row[:] for row in self.layout]
        twice[2] = ['Christophe Duriez\n02R015079', 'Christophe Duriez\n02R016079', 'Credit Sales\n02R016081']
        self.write('plan.xlsx', twice)
        self.sync.configure(Settings(folder=str(self.folder), enabled=True))
        found = {p['name']: p['desks'] for p in self.sync.check()['duplicates']}
        self.assertIn(['02R015079', '02R016079'], found.values())
        self.assertNotIn('Credit Sales', found, 'Repeated team labels are not people')

    def test_large_changes_apply_straight_away_when_review_is_off(self):
        self.sync.configure(Settings(folder=str(self.folder), enabled=True, review_large=False))
        free = [[f'Open\n{desk}' for desk in self.desks[i:i + 6]] for i in range(0, 60, 6)]
        self.write('plan.xlsx', free)
        result = self.sync.check()
        self.assertEqual(result['status']['state'], 'synced', result['status'])
        self.assertFalse(result['review_large'])
        self.assertEqual(official(self.db, self.desks[0])[0]['occupancy'], 'vacant')

    def test_review_threshold(self):
        self.assertFalse(large(40, 100))
        self.assertTrue(large(41, 100))
        self.assertFalse(large(60, 400))
        self.assertTrue(large(61, 400))


if __name__ == '__main__':
    unittest.main()
