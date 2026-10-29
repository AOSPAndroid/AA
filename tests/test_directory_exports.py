"""Export retention, scope and refresh atomicity, using synthetic workbooks."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from backend.directory import directory_exports as exports
from backend.directory.directory_workbook import build, NS, REL
from backend.directory.directory_lookup import prepare_views, search_directory
from backend.directory.merge_data import merge_directory
from backend.directory.refresh_directory import prepare
from sqlite_fixture import connect as fixture_connect


def workbook(path, sheets):
    book = ET.Element(NS+'workbook'); tabs = ET.SubElement(book, NS+'sheets')
    rels = ET.Element('Relationships')
    with zipfile.ZipFile(path, 'w') as z:
        for index, (name, rows) in enumerate(sheets.items(), 1):
            ET.SubElement(tabs, NS+'sheet', {'name': name, 'sheetId': str(index), REL+'id': 'r'+str(index)})
            ET.SubElement(rels, 'Relationship', {'Id': 'r'+str(index), 'Target': 'worksheets/sheet'+str(index)+'.xml'})
            sheet = ET.Element(NS+'worksheet'); data = ET.SubElement(sheet, NS+'sheetData')
            for number, values in enumerate(rows, 1):
                row = ET.SubElement(data, NS+'row', r=str(number))
                for col, value in enumerate(values):
                    cell = ET.SubElement(row, NS+'c', r=chr(65+col)+str(number), t='inlineStr')
                    ET.SubElement(ET.SubElement(cell, NS+'is'), NS+'t').text = value
            z.writestr('xl/worksheets/sheet'+str(index)+'.xml', ET.tostring(sheet))
        z.writestr('xl/workbook.xml', ET.tostring(book))
        z.writestr('xl/_rels/workbook.xml.rels', ET.tostring(rels))


def device_sheets():
    # The columns from the user's exports, with fictional data only.
    return {
        'devices': [['assigned_to','asset_tag','model_category','ci','model','cmp_last_used','install_status','serial_number','assigned','display_name','location'],
                    ['E001','ASSET-1','Computer','testpc-1','Dell Example','02/10/2026 10:00','In Use','000123','01/10/2026','ASSET-1 - Dell Example','Paris'],
                    ['','ASSET-2','Computer','TESTPC-2','HP Example','','In Stock','000124','','ASSET-2 - HP Example','London'],
                    ['','ASSET-3','Computer','','Stock Example','','In Stock','000125','','Unidentified stock device','Paris']],
        'users': [['user_name','name','email','u_organisational_unit','u_business_unit','u_start_date','manager','location','title','u_job_type','employee_number'],
                  ['u1','Example Person','e@example.invalid','IT','Technology','01/10/2024','Example Manager','Paris','Support','Permanent','E001'],
                  ['u2','Other Person','other@example.invalid','IT','Technology','','Example Manager','London','Support','Permanent','E002']],
    }


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.xlsx = self.root/'export.xlsx'; self.db = self.root/'directory.db'
        self.sheets = {
            'Users': [['user_name','name','email','department','u_business_unit','last_login_time','future flag','future-flag',''],
                      ['u1','Example Person','e@example.invalid','Support','Technology','46265.39671296296','0','false','  unchanged  '],
                      ['','','','','','','orphan value','','']],
            'computers': [['name','assigned_to','serial_number','u_barclays_correlation_id','model_id','future note'],
                          ['PC-1','u1','SER_1','ASSET%1','Model%test','<script>example</script>']],
            'Extra data': [['Column','Column'],['left','right']],
        }
        workbook(self.xlsx, self.sheets); prepare(self.xlsx, self.db)

    def connect(self):
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def test_every_cell_and_header_retained_including_unlinked_and_extra_sheets(self):
        c = self.connect(); coverage = exports.coverage(c)
        self.assertTrue(coverage['original_cells'])
        for sheet, rows in self.sheets.items():
            archived = c.execute('select headers from directory_export_sheets where sheet=?', (sheet,)).fetchone()[0]
            self.assertEqual(json.loads(archived), rows[0])
            cells = [json.loads(r[0]) for r in c.execute('select cells from directory_export_rows where sheet=? order by row_number', (sheet,))]
            self.assertEqual(cells, rows[1:])
        user = exports.record(c, 'user', 'uid:u1')
        self.assertEqual([f['value'] for f in user['fields']][-3:], ['0','false','  unchanged  '])
        self.assertEqual(user['row'], 2)
        limited = exports.record(c, 'user', 'uid:u1', include_unmapped=False)
        self.assertEqual(limited['restricted_columns'], 3)
        self.assertEqual(len(limited['fields']), 6)
        self.assertIsNone(exports.record(c, 'user', 'missing'))
        with self.assertRaises(ValueError): exports.record(c, 'users;drop table users', 'uid:u1')

    def test_new_search_fields_and_literal_wildcards(self):
        c = self.connect(); prepare_views(c)
        for term in ['SER_1','ASSET%1','serial:SER_1','asset:ASSET%1','model:Model%test']:
            self.assertEqual(search_directory(c, term)['machines'][0]['name'], 'PC-1')
        for term in ['business:Technology','department:Support','last_login_time:46265']:
            self.assertEqual(search_directory(c, term)['users'][0]['canonical_key'], 'uid:u1')
        self.assertEqual(search_directory(c, "serial:' OR 1=1 --")['machines'], [])
        self.assertEqual(search_directory(c, 'model:Model_test')['machines'], [])
        self.assertEqual(search_directory(c, 'team:')['users'], [])

    def test_refresh_replaces_archive_and_old_restore_clears_it_atomically(self):
        older = self.root/'older.db'
        with fixture_connect(self.db) as source, fixture_connect(older) as target: source.backup(target)
        with fixture_connect(older) as c:
            for table in reversed(exports.TABLES): c.execute('drop table '+table)
        merge_directory(self.db, older)
        c = self.connect()
        self.assertFalse(exports.coverage(c)['original_cells'])
        self.assertEqual(len(exports.record(c, 'user', 'uid:u1')['fields']), 14)
        candidate = self.root/'new.db'; prepare(self.xlsx, candidate)
        merge_directory(self.db, candidate)
        self.assertTrue(exports.coverage(c)['original_cells'])
        before = [tuple(r) for r in c.execute('select * from directory_export_rows')]
        with patch.object(exports, 'copy_archive', side_effect=RuntimeError('copy interrupted')):
            with self.assertRaises(RuntimeError): merge_directory(self.db, older)
        self.assertEqual(before, [tuple(r) for r in c.execute('select * from directory_export_rows')])

    def test_duplicate_mapped_headers_coalesced_with_original_cells_retained(self):
        self.sheets['Users'][0].append('business_unit')
        self.sheets['Users'][1].append('Conflicting')
        workbook(self.xlsx, self.sheets)
        build(self.xlsx,self.db)
        c=self.connect()
        self.assertEqual(c.execute('select business_unit from users').fetchone()[0],'Technology')
        self.assertEqual(exports.record(c,'user','uid:u1')['fields'][-1]['value'],'Conflicting')

    def test_admin_archive_download_and_legacy_fallback(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.database_manager import register_database_manager
        app=FastAPI()
        register_database_manager(app, SimpleNamespace(MASTER_DB=self.db,jobs={},queue_jobs={}), lambda request:None)
        with TestClient(app,base_url='http://127.0.0.1') as client:
            response=client.get('/api/directory/record',params={'kind':'machine','key':'pc-1'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['fields'][-1]['value'],'<script>example</script>')
            rows=[json.loads(line) for line in client.get('/api/database/export-archive').text.splitlines()]
            self.assertEqual(len(rows),5)
            self.assertTrue(rows[0]['original_cells'])
            with fixture_connect(self.db) as c:
                for table in reversed(exports.TABLES): c.execute('delete from '+table)
            rows=[json.loads(line) for line in client.get('/api/database/export-archive').text.splitlines()]
            self.assertEqual(len(rows),3)
            self.assertFalse(rows[0]['original_cells'])
            self.assertEqual(rows[1]['type'],'stored_record')

    def test_viewer_exposes_only_known_fields_and_never_the_archive(self):
        from backend import viewer
        from fastapi.testclient import TestClient
        with patch.object(viewer,'DB',self.db),TestClient(viewer.app) as client:
            data=client.get('/api/directory/record',params={'kind':'user','key':'uid:u1'}).json()
            self.assertEqual(len(data['fields']),6)
            self.assertEqual(data['restricted_columns'],3)
            self.assertNotIn('future flag',json.dumps(data))
            self.assertEqual(client.get('/api/database/export-archive').status_code,404)
            self.assertEqual(client.post('/api/directory/record',json={}).status_code,403)
            self.assertEqual(client.get('/api/directory/record?kind=bad&key=uid:u1').status_code,400)

    def test_devices_users_headers_records_and_complete_source_retention(self):
        sheets=device_sheets()
        sheets={' DeViCeS ':sheets['devices'],'uSeRs':sheets['users']}
        workbook(self.xlsx,sheets)
        self.assertEqual(prepare(self.xlsx,self.db),{'users':2,'machines':2,'assignments':1})
        c=self.connect();prepare_views(c)
        machine=c.execute("select * from machines where machine_name='TESTPC-1'").fetchone()
        self.assertEqual((machine['model_id'],machine['serial_number'],machine['assigned_to']),('Dell Example','000123','E001'))
        self.assertEqual(machine['operational_status'],'','Asset state must not be treated as online/operational status')
        self.assertEqual(c.execute("select count(*) from assignments a join machines m on m.id=a.machine_id where m.machine_name='TESTPC-2'").fetchone()[0],0)
        user=c.execute("select * from users where user_id='u1'").fetchone()
        for column,expected in [('organisational_unit','IT'),('business_unit','Technology'),('start_date','01/10/2024'),('manager','Example Manager'),('location','Paris'),('job_role','Support'),('job_type','Permanent'),('employee_number','E001')]:
            self.assertEqual(user[column],expected)
        self.assertEqual(c.execute('select login_id,machine_name,relationship_type from user_machine_links').fetchone()[:],('u1','TESTPC-1','assigned_to'))
        for term in ['TESTPC-1','serial:000123','model:Dell Example']:
            self.assertEqual(search_directory(c,term)['machines'][0]['name'],'TESTPC-1')
        fields=exports.record(c,'machine','testpc-1')['fields']
        self.assertEqual([f['header'] for f in fields],sheets[' DeViCeS '][0])
        self.assertEqual([f['value'] for f in fields],sheets[' DeViCeS '][1])
        self.assertEqual(fields[3]['field'],'machine_name');self.assertEqual(fields[4]['field'],'model_id')
        coverage=next(s for s in exports.coverage(c)['sheets'] if s['kind']=='machine')
        self.assertEqual((coverage['rows'],coverage['linked']),(3,2))
        orphan=c.execute("select entity_key,cells from directory_export_rows where sheet=' DeViCeS ' and row_number=4").fetchone()
        self.assertEqual(orphan['entity_key'],'');self.assertEqual(json.loads(orphan['cells']),sheets[' DeViCeS '][3])
        from backend import viewer
        from fastapi.testclient import TestClient
        with patch.object(viewer,'DB',self.db),TestClient(viewer.app) as client:
            data=client.get('/api/directory/record',params={'kind':'machine','key':'testpc-1'}).json()
            self.assertEqual({f['header'] for f in data['fields']},set(sheets[' DeViCeS '][0]))
            self.assertEqual(data['restricted_columns'],0)
            self.assertEqual(client.post('/api/database/preview',content=self.xlsx.read_bytes()).status_code,403)

    def test_unreadable_or_empty_extracts_preserve_the_existing_directory(self):
        cases=[]
        sheets=device_sheets();sheets['computers']=[['name'],['ANOTHERPC']];cases.append((sheets,'Multiple machine worksheets'))
        sheets=device_sheets();sheets['devices'][0][3]='asset_identifier';cases.append((sheets,'ci or name'))
        sheets=device_sheets()
        for row in sheets['devices'][1:]:row[3]=''
        cases.append((sheets,'Empty user or device extract'))
        before=self.db.read_bytes()
        for sheets,error in cases:
            with self.subTest(error=error):
                workbook(self.xlsx,sheets)
                with self.assertRaisesRegex(ValueError,error):prepare(self.xlsx,self.db)
                self.assertEqual(self.db.read_bytes(),before,'Rejected imports must preserve the existing database')

    def test_actual_device_upload_preview_apply_backup_and_seating_preservation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import database_manager as manager
        with fixture_connect(self.db) as c:
            c.execute('create table desk_user_links(desk_id text primary key,user_key text,method text,updated_at text)')
            c.execute("insert into desk_user_links values('D1','uid:u1','confirmed','fixture')")
        sheets=device_sheets();workbook(self.xlsx,sheets)
        app=FastAPI()
        with patch.object(manager,'__file__',str(self.root/'backend'/'database_manager.py')):
            manager.register_database_manager(app,SimpleNamespace(MASTER_DB=self.db,jobs={},queue_jobs={}),lambda request:None)
        with TestClient(app) as client:
            response=client.post('/api/database/preview',content=self.xlsx.read_bytes(),headers={'X-File-Name':'EMEA.xlsx'})
            self.assertEqual(response.status_code,200,response.text)
            data=response.json();report=data['report']
            self.assertEqual((report['users']['after'],report['machines']['after']),(2,2))
            self.assertEqual(report['devices_without_hostnames'],1)
            self.assertTrue(any('no ci/name hostname' in w for w in report['warnings']))
            column_warning=' '.join(w for w in report['warnings'] if w.startswith('Columns absent'))
            for retained in ['computers.name','computers.model_id','computers.assigned_to','computers.serial_number','Users.user_name','Users.name','Users.email']:
                self.assertNotIn(retained,column_warning,'Renamed tabs/header aliases must not appear as missing fields')
            self.assertIn('computers.u_barclays_correlation_id',column_warning,'Actually absent fields remain visible')
            with fixture_connect(self.db) as c:self.assertEqual(c.execute('select machine_name from machines').fetchone()[0],'PC-1','Preview cannot mutate the live directory')
            path='/api/database/apply/'+data['id']
            self.assertEqual(client.post(path,json={'confirmation':'APPLY'}).status_code,400)
            response=client.post(path,json={'confirmation':'APPLY','full_snapshot':True})
            self.assertEqual(response.status_code,200,response.text)
            backup=self.root/'backups'/response.json()['backup'];self.assertTrue(backup.is_file())
            with fixture_connect(backup) as c:self.assertEqual(c.execute('select machine_name from machines').fetchone()[0],'PC-1')
            with fixture_connect(self.db) as c:
                self.assertEqual(c.execute('select desk_id,user_key from desk_user_links').fetchone(),('D1','uid:u1'))
                self.assertEqual(c.execute('select count(*) from machines').fetchone()[0],2)
                self.assertEqual(c.execute("select kind from directory_export_sheets where sheet='devices'").fetchone()[0],'machine')
            self.assertEqual(client.post(path,json={'confirmation':'APPLY','full_snapshot':True}).status_code,409)


if __name__ == '__main__':
    unittest.main()
