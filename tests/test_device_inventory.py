"""Mixed asset imports, old databases and Windows action boundaries."""
from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import directory_exports as exports
from device_inventory import ASSET_COLUMNS
from directory_lookup import linked_machines, prepare_views, search_directory
from directory_workbook import build
from merge_data import merge_directory
from test_directory_exports import device_sheets, workbook


class DeviceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.xlsx = self.root/'mixed.xlsx'; self.db = self.root/'mixed.db'
        sheets = device_sheets()
        sheets['devices'][1][2:5] = ['Laptop','testpc-1','Dell Latitude 7450']
        sheets['devices'].append(['Example Person','PHONE-1','Mobile Device - Handheld','iPhone-EXAMPLE123','APPLE iPhone 13','46297.5','In Use','EXAMPLE123','46296','Corporate phone','Paris'])
        workbook(self.xlsx, sheets); build(self.xlsx,self.db)

    def connection(self, path=None):
        c=sqlite3.connect(path or self.db); c.row_factory=sqlite3.Row
        self.addCleanup(c.close); return c

    def test_laptop_and_phone_metadata_and_links(self):
        c=self.connection(); prepare_views(c)
        rows=linked_machines(c,1)
        self.assertEqual({r['device_kind'] for r in rows},{'laptop','iphone'})
        phone=next(r for r in rows if r['device_kind']=='iphone')
        self.assertEqual(phone['windows_remote_supported'],0)
        self.assertEqual((phone['last_used'],phone['assigned_at']),('2026-10-02 12:00:00','2026-10-01 00:00:00'))
        self.assertEqual((phone['asset_tag'],phone['device_location'],phone['install_status']),('PHONE-1','Paris','In Use'))
        self.assertEqual(phone['operational_status'],'')
        for term in ['PHONE-1','asset:PHONE-1','asset_tag:PHONE-1','type:iphone','model_category:Handheld','iPhone-EXAMPLE123','source_ci:iPhone-EXAMPLE123']:
            self.assertEqual(search_directory(c,term)['machines'][0]['name'],'INVENTORY-SERIAL:RAW-EXAMPLE123')
        self.assertEqual(len(search_directory(c,'device_location:Paris')['machines']),2)
        self.assertEqual(len(search_directory(c,'location:Paris')['users']),1)
        self.assertEqual(search_directory(c,'TESTPC-2')['machines'][0]['assigned_to'],'')
        fields=exports.record(c,'machine','inventory-serial:raw-example123')['fields']
        used=next(f for f in fields if f['header']=='cmp_last_used')
        self.assertEqual((used['value'],used['stored_value']),('46297.5','2026-10-02 12:00:00'))

    def test_old_database_read_migration_and_restore_clear_metadata(self):
        old=self.root/'old.db'
        src=self.connection(); dest=self.connection(old); src.backup(dest)
        dest.execute('drop index ix_machines_asset_lower')
        dest.execute('drop index ix_machines_source_ci_lower')
        for column in ASSET_COLUMNS: dest.execute('alter table machines drop column '+column)
        for table in reversed(exports.TABLES): dest.execute('drop table '+table)
        dest.commit(); prepare_views(dest)
        # The read-only viewer works without a schema migration or fabricated values.
        row=search_directory(dest,'testpc-1')['machines'][0]
        self.assertEqual(row['asset_tag'],''); self.assertEqual(row['device_kind'],'laptop')
        self.assertEqual(next(s for s in exports.coverage(dest)['sheets'] if s['kind']=='machine')['columns'][-1]['populated'],0)
        self.assertEqual(exports.record(dest,'machine','testpc-1')['fields'][-1]['value'],'')
        with patch.object(exports,'copy_archive',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): merge_directory(old,self.db)
        self.assertFalse(set(ASSET_COLUMNS)&{r[1] for r in dest.execute('pragma table_info(machines)')})
        merge_directory(old,self.db)
        self.assertEqual(dest.execute("select asset_tag from machines where machine_name='INVENTORY-SERIAL:RAW-EXAMPLE123'").fetchone()[0],'PHONE-1')
        older=self.root/'older.db'; original=self.connection(older); src.backup(original)
        original.execute('drop index ix_machines_asset_lower')
        original.execute('drop index ix_machines_source_ci_lower')
        for column in ASSET_COLUMNS: original.execute('alter table machines drop column '+column)
        original.commit()
        merge_directory(old,older)
        self.assertEqual(dest.execute("select asset_tag,last_used from machines where machine_name='INVENTORY-SERIAL:RAW-EXAMPLE123'").fetchone()[:],('',''))

    def test_phone_actions_rejected_before_windows_transport(self):
        from backend import main as m
        from fastapi.testclient import TestClient
        from atlas_api import TOKEN
        headers={'x-atlas-token':TOKEN}
        con=self.connection();con.execute("update machines set source_ci='CORPMOBILE01' where machine_name='INVENTORY-SERIAL:RAW-EXAMPLE123'");con.commit()
        with patch.object(m,'MASTER_DB',self.db), patch.object(m,'run') as run, patch.object(m,'ps') as ps, TestClient(m.app,base_url='http://127.0.0.1',client=('127.0.0.1',50000)) as client:
            calls=[('GET','/api/ping/IPHONE-EXAMPLE123',None),
                   ('GET','/api/ping/INVENTORY-SERIAL:RAW-EXAMPLE123',None),
                   ('GET','/api/ping/CORPMOBILE01',None),
                   ('GET','/api/machine-health/IPHONE-EXAMPLE123/ping',None),
                   ('POST','/api/deploy',{'computer':'IPHONE-EXAMPLE123','folder':'Example','script':'setup_i.ps1'}),
                   ('POST','/api/services',{'computer':'IPHONE-EXAMPLE123'}),
                   ('POST','/api/psexec/run',{'id':'9de36b62-c1d8-45a4-85c8-5d8c165c0e6f','template':'hostname','target':'IPHONE-EXAMPLE123','path':'C:\\Tools\\PsExec.exe'})]
            for method,url,body in calls:
                response=client.request(method,url,json=body,headers=headers)
                self.assertEqual(response.status_code,400,(url,response.text))
                self.assertIn('inventory only',response.text)
            run.assert_not_called(); ps.assert_not_called()
            self.assertEqual(m.validate_pc('testpc-1'),'TESTPC-1')
            self.assertEqual(m.validate_pc('GBRPWMF20847983'),'GBRPWMF20847983')


if __name__=='__main__': unittest.main()
