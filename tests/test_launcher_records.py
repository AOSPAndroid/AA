"""Recover only stale markers; processes and user data remain protected."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

import launcher


class ServerRecords(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root=Path(folder).resolve();self.runtime=self.root/'data'
        self.runtime.mkdir();(self.runtime/'logs').mkdir()
        self.stack.enter_context(patch.object(launcher,'ROOT',self.root))
        self.stack.enter_context(patch.dict(os.environ,{'ATLAS_ADMIN_PORT':'8770','ATLAS_VIEWER_PORT':'8771','AA_SHARE_VIEWER':'0'}))
        for key in ('AA_DATA_HOME','ATLAS_DB_PATH'):os.environ.pop(key,None)
        self.spec=launcher.servers()[0]
        self.path=launcher.record_path('admin')
        self.factory=self.stack.enter_context(patch.object(launcher,'WindowsProcess'))
        self.process=Mock()
        self.factory.return_value.__enter__.return_value=self.process

    def record(self,**extra):
        record=dict(self.spec,pid=4321,root=str(self.root),instance_id='test-instance',**extra)
        self.path.write_text(json.dumps(record),encoding='utf-8')
        self.process.metadata.return_value=dict(pid=4321,created='12345',executable='python.exe')
        return record

    def test_start_recovers_exited_legacy_pid_and_reaches_ready_server(self):
        self.record()
        def open_process(pid):
            if pid==4321:raise ProcessLookupError(pid)
            return self.factory.return_value
        self.factory.side_effect=open_process
        self.process.metadata.return_value['pid']=8765
        child=Mock(pid=8765);child.poll.return_value=None
        with patch.object(launcher,'running',side_effect=[False,True]),patch.object(launcher.socket,'socket'),patch.object(launcher.subprocess,'Popen',return_value=child) as launch:
            self.assertIs(launcher.start_server(self.spec),child)
        self.assertEqual(launcher.read_record('admin')['pid'],8765)
        launch.assert_called_once();child.terminate.assert_not_called()

    def test_stop_removes_exited_legacy_record(self):
        record=self.record();self.factory.side_effect=ProcessLookupError(4321)
        self.assertEqual(launcher.stop_record('admin',record),0)
        self.assertFalse(self.path.exists())

    def test_recycled_pid_clears_only_marker_without_stopping_new_process(self):
        record=self.record(created='98765',executable='python.exe')
        self.assertTrue(launcher.discard_stale_record('admin',record))
        self.assertFalse(self.path.exists());self.process.stop.assert_not_called()
        self.factory.assert_called_once_with(4321)

    def test_live_legacy_pid_blocks_new_start_with_pid_and_record_path(self):
        self.record()
        with patch.object(launcher,'running',return_value=False),patch.object(launcher.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError,'PID 4321') as error:launcher.start_server(self.spec)
        self.assertIn(str(self.path),str(error.exception));self.assertTrue(self.path.is_file())
        self.process.stop.assert_not_called();launch.assert_not_called()

    def test_live_legacy_pid_cannot_be_stopped_without_identity(self):
        record=self.record()
        self.assertEqual(launcher.stop_record('admin',record),1)
        self.assertTrue(self.path.is_file());self.process.stop.assert_not_called()

    def test_failed_inspection_retains_marker_and_shows_its_path(self):
        record=self.record();self.factory.side_effect=PermissionError('Access denied')
        with self.assertRaisesRegex(RuntimeError,'Cannot inspect admin PID 4321') as error:
            launcher.discard_stale_record('admin',record)
        self.assertIn(str(self.path),str(error.exception));self.assertTrue(self.path.is_file())

    def test_invalid_pid_never_queries_or_stops_a_process(self):
        for pid in (0,-1,True,'4321',2**32):
            with self.subTest(pid=pid):
                record=self.record();record['pid']=pid
                with self.assertRaisesRegex(RuntimeError,'Invalid PID'):launcher.discard_stale_record('admin',record)
                self.assertTrue(self.path.is_file())
        self.factory.assert_not_called()

    def test_live_owned_server_stops_using_verified_handle(self):
        record=self.record(created='12345',executable='python.exe')
        self.assertEqual(launcher.stop_record('admin',record),0)
        self.process.stop.assert_called_once();self.assertFalse(self.path.exists())
        self.assertTrue(self.factory.call_args.kwargs['terminate'])

    def test_live_foreign_root_is_never_stopped(self):
        record=self.record(created='12345',executable='python.exe');record['root']=str(self.root/'other')
        self.assertEqual(launcher.stop_record('admin',record),1)
        self.process.stop.assert_not_called();self.assertTrue(self.path.is_file())

    def test_healthy_server_reuses_its_legacy_record(self):
        self.record()
        with patch.object(launcher,'running',return_value=True),patch.object(launcher.subprocess,'Popen') as launch:
            self.assertIsNone(launcher.start_server(self.spec))
        self.factory.assert_not_called();launch.assert_not_called()

    @unittest.skipUnless(sys.platform=='win32','Windows process handles and PowerShell recovery')
    def test_real_dead_legacy_pid_recovers_through_start_and_stop(self):
        from windows_process import WindowsProcess
        self.factory.side_effect=WindowsProcess
        child=subprocess.Popen([sys.executable,'-c','pass']);child.wait(timeout=10)
        record=self.record();record['pid']=child.pid
        self.assertEqual(launcher.stop_record('admin',record),0)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(sys.platform=='win32','Native Windows repair script')
    def test_repair_archives_dead_markers_and_preserves_live_pid_and_data(self):
        script=Path(launcher.__file__).resolve().parent/'Repair-AA-Startup.ps1'
        (self.root/'launcher.py').touch()
        (self.runtime/'office_atlas.db').write_bytes(b'Preserve user data')
        custom=self.root/'custom workspace';custom.mkdir()
        (self.root/'config.json').write_text(json.dumps({'runtime_folder':str(custom)}))
        dead=subprocess.Popen([sys.executable,'-c','pass']);dead.wait(timeout=10)
        record=self.record();record['pid']=dead.pid;self.path.write_text(json.dumps(record))
        live=dict(record,pid=os.getpid())
        live_path=custom/'viewer-server.json';live_path.write_text(json.dumps(live))
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-InstallRoot',str(self.root)],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('still exists',result.stdout)
        self.assertFalse(self.path.exists());self.assertEqual(len(list(self.runtime.glob('server.json.stale-*'))),1)
        self.assertEqual(json.loads(live_path.read_text()),live)
        self.assertEqual((self.runtime/'office_atlas.db').read_bytes(),b'Preserve user data')
        live['pid']=dead.pid;live_path.write_text(json.dumps(live))
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-InstallRoot',str(self.root)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(live_path.exists())


if __name__=='__main__':unittest.main()
