"""Unedited ServiceNow extracts: identity collisions, reconciliation and source retention."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.database_manager import register_database_manager
from backend.directory.device_inventory import inventory_identity, supports_windows
from backend.directory.directory_exports import record, copy_archive
from backend.directory.directory_lookup import linked_machines, prepare_views, search_directory
from backend.directory.directory_workbook import build
from backend.directory.merge_data import atlas_schema
from test_directory_exports import device_sheets, workbook


class RawExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.xlsx=self.root/'emea.xlsx';self.db=self.root/'candidate.db'

    def connect(self,path=None):
        con=sqlite3.connect(path or self.db);con.row_factory=sqlite3.Row
        self.addCleanup(con.close);return con

    def load(self,sheets):
        workbook(self.xlsx,sheets);build(self.xlsx,self.db)
        con=self.connect();prepare_views(con);return con

    def test_generic_iphone_labels_distinguish_hardware_and_keep_every_original_row(self):
        sheets=device_sheets();headers=sheets['devices'][0]
        first=['u1','PHONE-1','Mobile Device - Handheld','iphone','APPLE iPhone 13','','In Use','SER-ONE','','Phone','Paris']
        second=['u2','PHONE-2','Mobile Device - Handheld',' iPhone ','APPLE iPhone 13','','In Use','SER-TWO','','Phone','London']
        sheets['devices']=[headers,first,second,list(first),['','','Mobile Device - Handheld','','APPLE iPhone 15','','In Stock','SER-STOCK','','Phone','Paris']]
        c=self.load(sheets)
        self.assertEqual(c.execute('select count(*) from machines').fetchone()[0],3)
        self.assertEqual([r['name'] for r in linked_machines(c,1)],['INVENTORY-SERIAL:RAW-SER-ONE'])
        self.assertEqual([r['name'] for r in linked_machines(c,2)],['INVENTORY-SERIAL:RAW-SER-TWO'])
        unassigned=search_directory(c,'serial:SER-STOCK')['machines'][0]
        self.assertEqual(unassigned['name'],'INVENTORY-SERIAL:RAW-SER-STOCK');self.assertEqual(unassigned['windows_remote_supported'],0)
        self.assertFalse(supports_windows(unassigned))
        self.assertEqual(len(search_directory(c,'source_ci:iphone')['machines']),2)
        fields=record(c,'machine','inventory-serial:raw-ser-one')
        self.assertEqual(fields['source_rows'],2);self.assertEqual(fields['row'],4)
        self.assertEqual([f['value'] for f in fields['fields']],first)
        archived=[json.loads(r[0]) for r in c.execute("select cells from directory_export_rows where sheet='devices' order by row_number")]
        self.assertEqual(archived,sheets['devices'][1:])
        stats=json.loads(c.execute("select value from metadata where key='import_resolution'").fetchone()[0])
        self.assertEqual(stats['machine']['duplicate_rows'],1);self.assertEqual(stats['machine']['conflicting_rows'],0)

    def test_newest_duplicate_wins_and_stale_user_aliases_and_assignments_disappear(self):
        sheets=device_sheets();sheets['users'][0].append('sys_updated_on')
        sheets['users'][1].append('2026-10-03 12:00:00');sheets['users'][2].append('2026-10-03 12:00:00')
        stale=list(sheets['users'][1]);stale[1:3]=['Old Person','old@example.invalid'];stale[-1]='2026-10-01 12:00:00'
        sheets['users'].append(stale)
        sheets['devices'][0].append('sys_updated_on')
        for row in sheets['devices'][1:]:row.append('2026-10-03 12:00:00')
        newer=list(sheets['devices'][1]);newer[0]='';newer[-1]='2026-10-04 12:00:00'
        older=list(sheets['devices'][1]);older[0]='u2';older[3]=' TESTPC-1 ';older[-1]='2026-10-02 12:00:00'
        sheets['devices'] += [newer,older]
        c=self.load(sheets)
        self.assertEqual(c.execute("select full_name,email from users where user_id='u1'").fetchone()[:],('Example Person','e@example.invalid'))
        self.assertEqual(c.execute("select count(*) from user_aliases where alias_value like 'Old%' or alias_value='old@example.invalid'").fetchone()[0],0)
        self.assertEqual(c.execute("select assigned_to from machines where machine_name='TESTPC-1'").fetchone()[0],'')
        self.assertEqual(c.execute('select count(*) from assignments').fetchone()[0],0,'Do not carry forward a stale assignment from another duplicate row')
        selected=record(c,'machine','testpc-1');self.assertEqual(selected['row'],5);self.assertEqual(selected['source_rows'],3)
        self.assertEqual([f['value'] for f in selected['fields']],newer)
        self.assertEqual(record(c,'user','uid:u1')['row'],2)
        stats=json.loads(c.execute("select value from metadata where key='import_resolution'").fetchone()[0])
        self.assertEqual(stats['user']['duplicate_rows'],1);self.assertEqual(stats['machine']['duplicate_rows'],2)
        self.assertEqual(stats['machine']['conflicting_rows'],2)

    def test_no_dates_uses_last_row_and_coalesces_duplicate_headers_without_cleanup(self):
        sheets=device_sheets();sheets['devices'][0].extend(['name','model_id'])
        for row in sheets['devices'][1:]:row.extend(['Friendly asset name',''])
        sheets['devices'][1][-1]='Alternate model'
        duplicate=list(sheets['devices'][1]);duplicate[0]='u2';duplicate[3]='testpc-1'
        sheets['devices'].append(duplicate)
        user_duplicate=list(sheets['users'][1]);user_duplicate[3]='New department'
        sheets['users'].append(user_duplicate)
        c=self.load(sheets)
        device=c.execute("select * from machines where machine_name='TESTPC-1'").fetchone()
        self.assertEqual(device['assigned_to'],'u2');self.assertEqual(device['model_id'],'Dell Example')
        self.assertEqual(c.execute("select organisational_unit from users where user_id='u1'").fetchone()[0],'New department')
        raw=record(c,'machine','testpc-1');self.assertEqual(raw['row'],5)
        self.assertEqual([f['value'] for f in raw['fields']],duplicate)
        self.assertEqual(len(raw['fields']),len(sheets['devices'][0]))
        self.assertEqual([m['name'] for m in linked_machines(c,2)],['TESTPC-1'])

    def test_identifier_namespaces_and_unknown_mobile_rows_do_not_merge_unrelated_devices(self):
        common={'machine_name':'iphone','model_category':'Mobile Device - Handheld'}
        records=[dict(common,serial_number='ASSET-123'),dict(common,asset_tag='123'),
                 dict(common,serial_number='A/B'),dict(common,serial_number='A B'),
                 dict(common,sys_id='123'),dict(common,serial_number='123'),common,common]
        names=[inventory_identity(d,i+2)[0] for i,d in enumerate(records)]
        self.assertEqual(len(set(names)),len(records));self.assertTrue(all(len(n)<=64 for n in names))
        self.assertEqual(inventory_identity(dict(common,serial_number='SER-1'),2),inventory_identity(dict(common,serial_number='SER-1'),999))
        self.assertEqual(inventory_identity({'machine_name':'GBRPWMF20847983'},2),('GBRPWMF20847983','hostname'))
        self.assertEqual(inventory_identity({'asset_tag':'ASSET-1'},2),('',''),'Do not invent a Windows remote target from an asset ID')
        sheets=device_sheets();headers=sheets['devices'][0]
        row=['u1','','Mobile Device - Handheld','iphone','APPLE iPhone 13','','In Use','','','Phone','Paris']
        sheets['devices']=[headers,row,list(row)]
        c=self.load(sheets);self.assertEqual(c.execute('select count(*) from machines').fetchone()[0],2)
        stats=json.loads(c.execute("select value from metadata where key='import_resolution'").fetchone()[0])
        self.assertEqual(stats['mobile_without_identifiers'],2);self.assertEqual(stats['machine']['duplicate_rows'],0)

    def test_preview_apply_backup_retains_duplicate_source_selection_and_phone_guards(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import database_manager as manager
        sheets=device_sheets();workbook(self.xlsx,sheets);build(self.xlsx,self.db)
        c=self.connect();atlas_schema(c);c.commit()
        before=c.execute('select machine_name from machines order by id').fetchall()
        phone=['u1','PHONE-1','Mobile Device - Handheld','iphone','APPLE iPhone 13','','In Use','SER-1','','Phone','Paris']
        sheets['devices'] += [phone,list(phone)];workbook(self.xlsx,sheets)
        app=FastAPI()
        with patch.object(manager,'__file__',str(self.root/'backend'/'database_manager.py')):
            register_database_manager(app,SimpleNamespace(MASTER_DB=self.db,jobs={},queue_jobs={}),lambda request:None)
        with TestClient(app) as client:
            response=client.post('/api/database/preview',content=self.xlsx.read_bytes(),headers={'X-File-Name':'emea2oct.xlsx'})
            self.assertEqual(response.status_code,200,response.text);preview=response.json()
            self.assertEqual(preview['report']['import_resolution']['machine']['duplicate_rows'],1)
            self.assertEqual(preview['report']['machines']['after'],3)
            self.assertEqual(c.execute('select machine_name from machines order by id').fetchall(),before)
            result=client.post('/api/database/apply/'+preview['id'],json={'confirmation':'APPLY','full_snapshot':True})
            self.assertEqual(result.status_code,200,result.text)
            backup=self.root/'backups'/result.json()['backup'];self.assertTrue(backup.is_file())
            data=client.get('/api/directory/record',params={'kind':'machine','key':'inventory-serial:raw-ser-1'}).json()
            self.assertEqual(data['source_rows'],2);self.assertEqual(data['row'],6)
            archive=[json.loads(line) for line in client.get('/api/database/export-archive').text.splitlines()]
            self.assertEqual(sum(r.get('type')=='row' and r.get('sheet')=='devices' for r in archive),5)
            history=client.get('/api/database/status').json()['history'][0]
            restore=client.post('/api/database/restore-preview/'+history['id']).json()
            self.assertEqual(client.post('/api/database/apply/'+restore['id'],json={'confirmation':'APPLY','full_snapshot':True}).status_code,200)
            self.assertEqual(c.execute('select count(*) from machines').fetchone()[0],2)

    def test_older_archives_without_selected_column_still_restore_and_read(self):
        c=self.load(device_sheets());c.execute('alter table directory_export_rows drop column selected');c.commit()
        self.assertEqual(record(c,'machine','testpc-1')['row'],2)
        restored=self.connect(self.root/'restored.db');copy_archive(c,restored)
        self.assertEqual(restored.execute('select count(*) from directory_export_rows').fetchone()[0],5)
        self.assertEqual(restored.execute('select sum(selected) from directory_export_rows').fetchone()[0],0)


if __name__=='__main__':unittest.main()
