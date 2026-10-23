from sqlite_fixture import connect as fixture_connect
"""Verify bundled template downloads and filled-template import compatibility."""
import io,tempfile,unittest,zipfile,sys
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import seating_excel as sx
from refresh_directory import prepare
from database_manager import register_database_manager
from fastapi import FastAPI
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]

def filled(template,entries):
 # Simulate values entered by a user into each actual template, preserving its format.
 parts=dict(sx.workbook_parts(template));out=io.BytesIO()
 with zipfile.ZipFile(template) as source,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as target:
  for name in source.namelist():
   data=source.read(name)
   for sheet,values in entries.items():
    if name!=parts[sheet]:continue
    xml=ET.fromstring(data);sd=xml.find(sx.NS+'sheetData')
    row=next((r for r in sd if r.get('r')=='2'),None)
    if row is None:row=ET.SubElement(sd,sx.NS+'row',r='2')
    for cell in list(row):row.remove(cell)
    for i,value in enumerate(values):
     cell=ET.SubElement(row,sx.NS+'c',r=chr(65+i)+'2',t='inlineStr');ET.SubElement(ET.SubElement(cell,sx.NS+'is'),sx.NS+'t').text=value
    data=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
   target.writestr(name,data)
 return out.getvalue()

class ExcelTemplates(unittest.TestCase):
 def test_seating_templates_blank_and_filled(self):
  for layout in ('official','previous'):
   template=ROOT/'templates'/f'users-and-desks-{layout}-template.xlsx'
   with self.assertRaises(ValueError):sx.read_sheet(template)
   parts=dict(sx.workbook_parts(template));rows=list(sx.iter_rows(template,parts['Desk reference']));desk=rows[1][1][0]
   with zipfile.ZipFile(template) as z:
    xml=ET.fromstring(z.read(parts['Users and desks']));self.assertIsNotNone(xml.find(sx.NS+'dataValidations'));self.assertIsNone(xml.find('.//'+sx.NS+'f'))
   with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'filled.xlsx';path.write_bytes(filled(template,{'Users and desks':[desk,'Template Test','IT','','assigned']}))
    with fixture_connect(ROOT/'office_atlas.db') as c:plan=sx.plan_sheet(c,sx.read_sheet(path),layout)
    self.assertFalse(plan['report']['errors']);self.assertEqual(plan['updates'][desk]['record']['name'],'Template Test')
 def test_directory_template_builds_records_and_links(self):
  template=ROOT/'templates/users-and-computers-template.xlsx'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   with self.assertRaises((ValueError,StopIteration)):prepare(template,root/'blank.db')
   path=root/'filled.xlsx';path.write_bytes(filled(template,{'Users':['u123','Template User','template@example.invalid','00123','IT','Paris','Support'],'computers':['PC123','u123','','SERIAL123','Dell','Test']}))
   counts=prepare(path,root/'ready.db');self.assertEqual(counts,{'users':1,'machines':1,'assignments':1})
   with fixture_connect(root/'ready.db') as c:
    self.assertEqual(c.execute('select employee_number from users').fetchone()[0],'00123');self.assertEqual(c.execute('select login_id,machine_name from user_machine_links').fetchone(),('u123','PC123'))
 def test_downloads_and_ui_links(self):
  with tempfile.TemporaryDirectory() as tmp:
   app=FastAPI();w=SimpleNamespace(MASTER_DB=Path(tmp)/'empty.db',jobs={},queue_jobs={});register_database_manager(app,w,lambda r:None);cli=TestClient(app)
   html=cli.get('/manage-database').text
   for kind,name in [('seating-official','users-and-desks-official-template.xlsx'),('seating-previous','users-and-desks-previous-template.xlsx'),('directory','users-and-computers-template.xlsx')]:
    self.assertIn('/api/excel-templates/'+kind,html);r=cli.get('/api/excel-templates/'+kind);self.assertEqual(r.status_code,200);self.assertEqual(r.content,(ROOT/'templates'/name).read_bytes());self.assertIn(name,r.headers['content-disposition'])
   self.assertEqual(cli.get('/api/excel-templates/unknown').status_code,404)
if __name__=='__main__':unittest.main()
