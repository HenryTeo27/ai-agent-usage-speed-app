"""Test the updater with temporary data, fake releases, and no visible windows."""
import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock,patch

import app_updater as updater
import meter


def metadata(tag='v1.2.3',digest='a'*64):
    return {'tag_name':tag,'draft':False,'prerelease':False,'assets':[{
        'name':updater.ARCHIVE,'size':123,'digest':'sha256:'+digest,
        'browser_download_url':f'https://github.com/{updater.REPO}/releases/download/{tag}/{updater.ARCHIVE}'}]}


def archive(entries=None):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as bundle:
        for name,data in (entries or [('CodexMeter/CodexMeter.exe',b'exe'),
                                       ('CodexMeter/_internal/runtime.txt',b'runtime')]):
            bundle.writestr(name,data)
    return output.getvalue()


class ReleaseTests(unittest.TestCase):
    def test_only_new_stable_releases_with_verified_exact_assets_are_selected(self):
        release=metadata()
        self.assertEqual(updater.release_candidate(release,'1.2.2')['version'],'1.2.3')
        self.assertIsNone(updater.release_candidate(release,'1.2.3'))
        self.assertIsNone(updater.release_candidate({**release,'prerelease':True},'1.0.0'))
        self.assertIsNone(updater.release_candidate({**release,'draft':True},'1.0.0'))
        for changes in ({'digest':None},{'size':updater.MAX_DOWNLOAD+1},
                        {'browser_download_url':'https://example.com/app.zip'}):
            broken=metadata();broken['assets'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                updater.release_candidate(broken,'1.0.0')
        with self.assertRaises(ValueError): updater.release_candidate(metadata('v1.2.3-rc1'),'1.0.0')

    def test_untrusted_redirects_are_rejected(self):
        for url in ('http://github.com/file','https://example.com/file','https://github.com.evil.test/file',
                    'https://github.com@evil.test/file','https://github.com:444/file'):
            with self.subTest(url=url),self.assertRaises(ValueError): updater.check_url(url)
        updater.check_url('https://release-assets.githubusercontent.com/example')

    def test_download_verifies_hash_and_runs_health_check(self):
        content=archive();candidate={'url':'unused','size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'version':'1.2.3'}
        with tempfile.TemporaryDirectory() as folder,patch.object(updater,'open_url',side_effect=lambda *args,**kwargs:io.BytesIO(content)):
            health=Mock();stage=updater.download_and_stage(candidate,folder,health)
            health.assert_called_once_with(stage/'CodexMeter'/'CodexMeter.exe','1.2.3',stage)
            self.assertTrue((stage/'CodexMeter'/'_internal'/'runtime.txt').is_file())
            self.assertFalse((stage/updater.ARCHIVE).exists())
            updater.remove_stage(stage,Path(folder)/'updates')
            with self.assertRaises(ValueError):
                updater.download_and_stage({**candidate,'sha256':'0'*64},folder,health)
            self.assertEqual(list((Path(folder)/'updates').iterdir()),[])

    def test_installer_does_not_hold_the_app_or_staging_directory_as_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);updates=data/'updates';stage=updates/('update-'+uuid.uuid4().hex)
            (stage/'CodexMeter').mkdir(parents=True)
            (stage/'CodexMeter'/'CodexMeter.exe').write_bytes(b'test')
            helper=data/'helper.ps1';helper.write_text('test')
            with patch.object(updater.subprocess,'Popen') as popen:
                updater.start_installer(stage,data/'installed',data,helper,'1.2.3',True)
            self.assertEqual(popen.call_args.kwargs['cwd'],str(updates.resolve()))
            self.assertEqual(popen.call_args.kwargs['creationflags'],updater.CREATE_NO_WINDOW)

    def test_unsafe_archive_paths_and_links_are_rejected(self):
        for name in ('CodexMeter/../outside','CodexMeter/_internal/x:stream',
                     'CodexMeter/_internal/CON.txt','CodexMeter/_internal/name.'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'bad.zip';file.write_bytes(archive([('CodexMeter/CodexMeter.exe',b'x'),(name,b'x')]))
                with self.assertRaises(ValueError): updater.extract_bundle(file,Path(folder)/'stage')
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'bad.zip'
            with zipfile.ZipFile(file,'w') as bundle:
                path=zipfile.ZipInfo('CodexMeter/_internal/safe');path.filename='CodexMeter/_internal/evil\\file'
                bundle.writestr(path,'bad')
            with self.assertRaises(ValueError): updater.extract_bundle(file,Path(folder)/'stage')
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'bad.zip'
            with zipfile.ZipFile(file,'w') as bundle:
                link=zipfile.ZipInfo('CodexMeter/_internal/link');link.create_system=3;link.external_attr=(0o120777 << 16)
                bundle.writestr(link,'../../outside')
            with self.assertRaises(ValueError): updater.extract_bundle(file,Path(folder)/'stage')

    def test_failed_health_check_and_cancellation_leave_no_staged_update(self):
        content=archive();candidate={'url':'unused','size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'version':'1.2.3'}
        with tempfile.TemporaryDirectory() as folder,patch.object(updater,'open_url',side_effect=lambda *args,**kwargs:io.BytesIO(content)):
            with self.assertRaises(RuntimeError): updater.download_and_stage(candidate,folder,Mock(side_effect=RuntimeError('bad')))
            with self.assertRaises(RuntimeError): updater.download_and_stage(candidate,folder,Mock(),lambda:True)
            self.assertEqual(list((Path(folder)/'updates').iterdir()),[])


class ApplyPolicyTests(unittest.TestCase):
    def test_ready_marker_confirms_the_version_and_process(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);stage=data/'updates'/('update-'+uuid.uuid4().hex);stage.mkdir(parents=True)
            marker=stage/'ready.json';app=meter.App.__new__(meter.App)
            with patch.object(meter,'DATA',data),patch.object(meter.sys,'argv',['meter','--update-ready',str(marker)]):
                app.signal_update_ready()
            self.assertEqual(json.loads(marker.read_text()),{'version':meter.VERSION,'pid':os.getpid()})
            outside=data/'outside.json'
            with patch.object(meter,'DATA',data),patch.object(meter.sys,'argv',['meter','--update-ready',str(outside)]):
                app.signal_update_ready()
            self.assertFalse(outside.exists())

    def test_update_waits_for_hidden_idle_app_and_saves_before_restarting(self):
        app=meter.App.__new__(meter.App);app.pending_app_update=('1.2.3',Path('test'))
        app.closed=False;app.busy=False;app.root=Mock();app.root.state.return_value='normal'
        app.save_exit_state=Mock();app.begin_app_update=Mock();app.shutdown=Mock()
        app.maybe_apply_app_update();app.begin_app_update.assert_not_called()
        app.root.state.return_value='withdrawn';app.busy=True
        app.maybe_apply_app_update();app.begin_app_update.assert_not_called()
        app.busy=False;app.maybe_apply_app_update()
        app.save_exit_state.assert_called_once_with(require_readable=True)
        app.begin_app_update.assert_called_once_with(relaunch=True)
        app.shutdown.assert_called_once();self.assertIsNone(app.pending_app_update)

    def test_storage_failure_never_starts_the_installer(self):
        app=meter.App.__new__(meter.App);app.pending_app_update=('1.2.3',Path('test'))
        app.closed=False;app.busy=False;app.root=Mock();app.root.state.return_value='withdrawn'
        app.save_exit_state=Mock(side_effect=OSError('locked'));app.begin_app_update=Mock();app.shutdown=Mock()
        app.maybe_apply_app_update()
        app.begin_app_update.assert_not_called();app.shutdown.assert_not_called()
        self.assertIn('locked',app.app_update_detail)
        app.root.after.assert_called_once()

    def test_check_runs_off_the_ui_thread_and_does_not_overlap(self):
        app=meter.App.__new__(meter.App)
        app.closed=False;app.app_update_running=False;app.pending_app_update=None
        app.app_update_results=queue.Queue();app.root=Mock();app.data={};app.schedule_app_update_check=Mock()
        started=threading.Event();release=threading.Event();calls=[]
        def check():
            calls.append(1);started.set();release.wait(5)
            return {'candidate':None,'stage':None}
        with patch.object(meter,'get_app_update',check),patch.object(meter,'save'):
            try:
                app.check_app_updates();self.assertTrue(started.wait(2))
                app.check_app_updates();self.assertEqual(len(calls),1)
                release.set();deadline=time.monotonic()+3
                while app.app_update_results.empty() and time.monotonic()<deadline: time.sleep(0.01)
                self.assertFalse(app.app_update_results.empty());app.poll_app_update()
                self.assertFalse(app.app_update_running)
                self.assertFalse(app.data['app_update_check']['retry'])
                app.schedule_app_update_check.assert_called_once()
            finally: release.set()

    def test_update_checks_sleep_until_due_and_retry_after_failure(self):
        from test_schedule import Clock,Root
        clock=Clock();root=Root(clock);app=meter.App.__new__(meter.App)
        app.root=root;app.data={'app_update_check':{'checked_at':clock.wall,'retry':False}}
        app.closed=False;app.app_update_job=None;app.app_update_running=False;app.pending_app_update=None
        app.check_app_updates=Mock()
        with patch.object(meter.time,'time',lambda:clock.wall),patch.object(updater,'installed_root',return_value=Path('installed')):
            app.schedule_app_update_check()
            root.advance(23*3600);app.check_app_updates.assert_not_called()
            root.advance(3600);app.check_app_updates.assert_called_once()
            app.check_app_updates.reset_mock()
            app.data['app_update_check']={'checked_at':clock.wall,'retry':True}
            app.schedule_app_update_check();root.advance(6*3600-1)
            app.check_app_updates.assert_not_called()
            root.advance(1);app.check_app_updates.assert_called_once()


@unittest.skipUnless(os.name=='nt','Windows updater helper')
class InstallerTests(unittest.TestCase):
    def run_helper(self,folder,relaunch,valid_runner=False):
        local=Path(folder);target=local/'Programs'/'CodexMeter';target.mkdir(parents=True)
        (target/'old.txt').write_text('old')
        (target/'CodexMeter.exe').write_bytes(b'old executable')
        stage=local/'CodexMeter'/'updates'/('update-'+uuid.uuid4().hex)
        payload=stage/'CodexMeter';payload.mkdir(parents=True)
        executable=payload/'CodexMeter.exe'
        if valid_runner:
            source=local/'fake-app.cs'
            source.write_text('''using System; using System.IO; using System.Threading; using System.Diagnostics;
class FakeApp { static void Main(string[] args) {
    var pid = Process.GetCurrentProcess().Id;
    File.WriteAllText(args[2], "{\\\"version\\\":\\\"1.2.3\\\",\\\"pid\\\":" + pid + "}");
    Thread.Sleep(1500);
} }''')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            compiled=subprocess.run([str(compiler),'/nologo','/target:winexe',f'/out:{executable}',str(source)],
                                    capture_output=True,text=True,creationflags=updater.CREATE_NO_WINDOW,timeout=20)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
        else: executable.write_bytes(b'new executable')
        (payload/'new.txt').write_text('new')
        child=subprocess.Popen([sys.executable,'-c','pass'],creationflags=updater.CREATE_NO_WINDOW)
        child.wait(timeout=10)
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        script=Path(__file__).parent/'scripts/apply-update.ps1'
        result=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),
                               '-ParentPid',str(child.pid),'-Target',str(target),'-Stage',str(stage),
                               '-Version','1.2.3','-Relaunch',str(relaunch)],
                              env={**os.environ,'LOCALAPPDATA':str(local),'APPDATA':str(local)},
                              capture_output=True,text=True,creationflags=updater.CREATE_NO_WINDOW,timeout=25)
        return target,stage,result

    def test_successful_replacement_preserves_separate_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'CodexMeter'/'snapshot.json';data.parent.mkdir();data.write_text('saved')
            target,stage,result=self.run_helper(folder,0)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((target/'new.txt').read_text(),'new')
            self.assertEqual(data.read_text(),'saved');self.assertFalse(stage.exists())
            self.assertEqual(list(target.parent.glob('.CodexMeter-backup-*')),[])

    def test_failed_restart_restores_previous_app(self):
        with tempfile.TemporaryDirectory() as folder:
            target,stage,result=self.run_helper(folder,1)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((target/'old.txt').read_text(),'old')
            self.assertFalse((target/'new.txt').exists());self.assertFalse(stage.exists())
            failure=updater.previous_failure(Path(folder)/'CodexMeter','1.0.0')
            self.assertEqual(failure['version'],'1.2.3')
            self.assertIsNone(updater.previous_failure(Path(folder)/'CodexMeter','1.2.3'))

    def test_successful_hidden_restart_acknowledges_new_version(self):
        with tempfile.TemporaryDirectory() as folder:
            target,stage,result=self.run_helper(folder,1,valid_runner=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((target/'new.txt').read_text(),'new');self.assertFalse(stage.exists())
            self.assertEqual(list(target.parent.glob('.CodexMeter-backup-*')),[])
            time.sleep(2)  # Let the owned, hidden test process release its executable.


if __name__=='__main__': unittest.main()
