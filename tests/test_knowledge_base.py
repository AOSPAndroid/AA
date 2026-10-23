import tempfile, unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from knowledge_base import register

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'kb.sqlite3'
        self.app=FastAPI();register(self.app,self.path);self.client=TestClient(self.app)
        self.doc={'title':'Network','notes':'Private runbook','xml':'<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>','revision':0}
    def tearDown(self):self.tmp.cleanup()
    def test_persistence_revision_conflicts_and_delete(self):
        self.assertEqual(self.client.get('/api/knowledge').json()['documents'],[])
        self.assertEqual(self.client.put('/api/knowledge/test',json=self.doc).json()['revision'],1)
        second=FastAPI();register(second,self.path);client=TestClient(second)
        self.assertEqual(client.get('/api/knowledge/test').json()['notes'],'Private runbook')
        self.assertEqual(client.put('/api/knowledge/test',json=self.doc).status_code,409)
        self.doc['revision']=1;self.doc['title']='Revised'
        self.assertEqual(client.put('/api/knowledge/test',json=self.doc).json()['revision'],2)
        self.assertEqual(client.delete('/api/knowledge/test?revision=1').status_code,409)
        self.assertEqual(client.delete('/api/knowledge/test?revision=2').status_code,200)
        self.assertEqual(client.get('/api/knowledge/test').status_code,404)
    def test_invalid_xml_rejected_without_writes(self):
        for xml in ['<html/>', '<mxfile>', '<!DOCTYPE mxfile [<!ENTITY a "x">]><mxfile/>']:
            self.doc['xml']=xml
            self.assertEqual(self.client.put('/api/knowledge/test',json=self.doc).status_code,422)
        self.assertEqual(self.client.get('/api/knowledge').json()['documents'],[])
    def test_limits(self):
        self.doc['notes']='x'*100001
        self.assertEqual(self.client.put('/api/knowledge/test',json=self.doc).status_code,422)
if __name__=='__main__':unittest.main()
