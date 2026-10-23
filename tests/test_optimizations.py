from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import main, viewer
import atlas_store
from job_service import JobService
from runtime_paths import prepare_runtime_database
from sqlite_fixture import connect


class OptimizationTests(unittest.TestCase):
    def test_custom_official_location_survives_reload_and_export(self):
        from seating_excel import layout_records
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'atlas.db'
            with connect(atlas_store.DB) as source,connect(db) as dest:source.backup(dest)
            with patch.object(atlas_store,'DB',db),patch.object(viewer,'DB',db):
                record=dict(id='custom-regression',layout='official',floor=2,name='Regression location',team='Fixture',kind='desk',occupancy='unconfirmed',x=.2,y=.3,angle=90)
                with atlas_store.connect() as c:atlas_store.save_record(c,record,None,'test create')
                with TestClient(viewer.app) as client:
                    records=client.get('/api/official/state').json()['records']
                    self.assertIn(record['id'],[r['id'] for r in records])
                with atlas_store.connect() as c:
                    current=atlas_store.get_record(c,record['id']);self.assertEqual(current['layout'],'official')
                    self.assertIn(record['id'],layout_records(c,'official')[0]);self.assertNotIn(record['id'],layout_records(c,'previous')[0])
                    atlas_store.save_record(c,dict(current,name='Updated'),current,'test edit')
                    self.assertEqual(atlas_store.get_record(c,record['id'])['name'],'Updated')

    def test_compact_index_revalidation_and_session_size(self):
        with TestClient(main.app,base_url='http://127.0.0.1',client=('127.0.0.1',42)) as client:
            session=client.get('/api/session');self.assertLess(len(session.content),200);self.assertNotIn('records',session.json())
            first=client.get('/api/palette/desks');self.assertEqual(first.status_code,200)
            self.assertEqual(set(first.json()['records'][0]),{'id','name','team','hostname','floor'})
            self.assertEqual(client.get('/api/palette/desks',headers={'If-None-Match':first.headers['etag']}).status_code,304)

    def test_static_assets_revalidate_but_viewer_data_does_not_cache(self):
        with TestClient(viewer.app) as client:
            self.assertIn('must-revalidate',client.get('/official.css').headers['cache-control'])
            self.assertEqual(client.get('/api/official/state').headers['cache-control'],'no-store')
            self.assertEqual(client.get('/api/session').status_code,404)

    def test_recovery_does_not_replay_and_retention_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'jobs.db';service=JobService(lambda:db,retained=2)
            service.jobs['running']={'state':'running','target':'PC1','events':[]};service.save('running')
            recovered=JobService(lambda:db,retained=2);recovered.recover()
            self.assertEqual(recovered.jobs['running']['state'],'interrupted');self.assertIn('PC1',recovered.unresolved)
            recovered.jobs['running']['recovery_acknowledged']=True;recovered.save('running');recovered.acknowledge('PC1')
            again=JobService(lambda:db);again.recover();self.assertNotIn('PC1',again.unresolved)
            for i in range(5):service.jobs[str(i)]={'state':'complete','events':[{}]*250};service.save(str(i))
            self.assertEqual(len([v for v in service.jobs.values() if v['state']=='complete']),2)
            self.assertEqual(len(service.jobs['4']['events']),200)
            service.jobs['uncertain']={'state':'unknown','target':'PC2','events':[]};service.save('uncertain')
            for i in range(5,10):service.jobs[str(i)]={'state':'complete','events':[]};service.save(str(i))
            after_prune=JobService(lambda:db);after_prune.recover();self.assertIn('PC2',after_prune.unresolved)
            for item in (service,recovered,again,after_prune):item.pool.shutdown(wait=True)

    def test_queue_resume_and_cancel_keep_same_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);service=JobService(lambda:root/'jobs.db');repo=root/'repo';package=repo/'Example';package.mkdir(parents=True);(package/'setup_i.ps1').write_text('exit 0')
            with patch.multiple(main,job_service=service,jobs=service.jobs,queue_jobs=service.queues,lock=service.lock,HISTORY_DB=root/'jobs.db',REPO=repo),patch.object(main,'identity',return_value='FIXTURE'):
                item=main.QueueItem(computer='PC1',folder=str(package),script='setup_i.ps1')
                service.queues['q']={'id':'q','state':'running','pause_requested':True,'items':[{'target':'PC1','package':'Example','state':'waiting','events':[],'payload':item.model_dump()}]}
                main._queue_worker('q',[item]);self.assertEqual(service.queues['q']['state'],'paused')
                def finish(j,p):main.emit(j,'Fixture completed','complete')
                with patch.object(main,'deploy_worker',finish):
                    self.assertEqual(main.resume_queue('q'),{'queue':'q'})
                    for _ in range(100):
                        if service.queues['q']['state']=='complete':break
                        time.sleep(.01)
                self.assertEqual(service.queues['q']['state'],'complete');self.assertEqual(list(service.queues),['q'])
                service.queues['q'].update(state='paused');service.queues['q']['items'][0]['state']='waiting'
                main.cancel_queue('q');self.assertEqual(service.queues['q']['state'],'cancelled')
            service.pool.shutdown(wait=True)

    def test_runtime_migration_preserves_seed_and_is_one_time(self):
        import runtime_paths
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed=root/'office_atlas.db'
            with connect(seed) as c:c.execute('create table evidence(value text)');c.execute("insert into evidence values('seed')")
            before=seed.read_bytes()
            with patch.object(runtime_paths,'ROOT',root),patch.dict('os.environ',{},clear=True):
                target=prepare_runtime_database()
                with connect(target) as c:c.execute("insert into evidence values('runtime')")
                self.assertEqual(prepare_runtime_database(),target)
                with connect(target) as c:self.assertEqual(c.execute('select count(*) from evidence').fetchone()[0],2)
            self.assertEqual(seed.read_bytes(),before)
