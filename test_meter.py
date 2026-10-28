import unittest
from unittest.mock import patch
import meter

class ResourceTests(unittest.TestCase):
    def test_worker_import_does_not_load_gui(self):
        code="import meter,sys; assert not {'tkinter','pystray','PIL.ImageTk'}.intersection(sys.modules)"
        meter.run([meter.PYTHON,'-c',code],timeout=10)

    @unittest.skipUnless(meter.os.name=='nt','Windows process-tree cancellation')
    def test_quit_cancels_owned_child_tree(self):
        import tempfile,threading
        from pathlib import Path
        failures=[]
        with tempfile.TemporaryDirectory() as tmp:
            child_file=Path(tmp)/'child.txt'
            code="import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
            def work():
                try: meter.run([meter.PYTHON,'-c',code,str(child_file)],timeout=35)
                except RuntimeError as exc: failures.append(str(exc))
            thread=threading.Thread(target=work)
            try:
                thread.start()
                deadline=meter.time.monotonic()+5
                while not child_file.exists() and meter.time.monotonic()<deadline: meter.time.sleep(0.02)
                self.assertTrue(child_file.exists())
                child_pid=int(child_file.read_text())
                meter.cancel_scans();thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertTrue(failures)
                result=meter.subprocess.run(['tasklist','/FI',f'PID eq {child_pid}','/FO','CSV','/NH'],capture_output=True,text=True)
                self.assertNotIn(f'"{child_pid}"',result.stdout)
                self.assertFalse(meter.ACTIVE_PROCESSES)
            finally:
                meter.cancel_scans();thread.join(5);meter.STOP_EVENT.clear()

class ParserTests(unittest.TestCase):
    def test_speed_table(self):
        text = 'Selected history\nModel Normal eff Fast eff Fast÷Norm Normal n Fast n\ngpt-x 23.4 20.1 (0.86×) 12 100\ngpt-y 42.0~ · · 15 ·\n\nOther section\n'
        rows = meter.parse_speed(text)
        self.assertEqual(rows[0]['ratio'], '(0.86×)')
        self.assertEqual(rows[1]['fast'], '·')
        self.assertEqual(rows[1]['normal'], '42.0~')
    def test_missing_table(self):
        with self.assertRaises(ValueError): meter.parse_speed('unexpected output')
    def test_month_and_totals(self):
        import json
        from datetime import datetime
        month=datetime.now().strftime('%Y-%m')
        data={'monthly':[{'month':month,'totalTokens':100,'costUSD':2}], 'totals':{'totalTokens':250,'costUSD':3}}
        with patch.object(meter.shutil,'which',return_value='npx'), patch.object(meter,'run',return_value=json.dumps(data)):
            result=meter.get_usage()
        self.assertEqual(result['month_tokens'],100)
        self.assertEqual(result['total_tokens'],250)
    def test_absent_month(self):
        with patch.object(meter.shutil,'which',return_value='npx'), patch.object(meter,'run',return_value='{"monthly":[],"totals":{"totalTokens":1,"costUSD":1}}'):
            self.assertEqual(meter.get_usage()['month_tokens'],0)

class SpeedBatchTests(unittest.TestCase):
    def test_older_three_argument_engine_and_both_windows(self):
        from types import SimpleNamespace
        from datetime import datetime, timedelta, timezone
        from unittest.mock import MagicMock
        now=datetime.now(timezone.utc)
        samples=[SimpleNamespace(completed_at=(now-timedelta(hours=12)).isoformat(),output_tokens=200),
                 SimpleNamespace(completed_at=(now-timedelta(days=3)).isoformat(),output_tokens=200),
                 SimpleNamespace(completed_at=(now-timedelta(hours=1)).isoformat(),output_tokens=20)]
        engine=SimpleNamespace(find_rollouts=lambda home: [], json=None)
        calls=[]
        def load(home,cache,workers):
            self.assertIsNone(cache)
            return samples,{'unreadable_files':0}
        def report(meta,selected,tz,**kw):
            calls.append(len(selected))
            print('Selected history\nModel Normal eff Fast eff Ratio Normal n Fast n\ngpt-test 10.0 20.0 2.00× 30 40\n')
        engine.load_samples=load;engine.build_report=lambda selected,*args:{};engine.print_report=report
        spec=MagicMock()
        with patch.object(meter.importlib.util,'spec_from_file_location',return_value=spec), patch.object(meter.importlib.util,'module_from_spec',return_value=engine):
            result=meter.speed_batch('test-engine.py')
        self.assertEqual(calls,[1,2])
        self.assertEqual(result['1'][0]['ratio'],'2.00×')
        self.assertEqual(result['14'][0]['normal'],'10.0')
        meter.sys.modules.pop('_codex_meter_speed',None)

class RefreshTests(unittest.TestCase):
    def test_fast_source_is_shown_before_slow_source(self):
        import tempfile, threading
        from pathlib import Path
        gate=threading.Event()
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'):
            app=meter.App()
        app.root.withdraw(); app.settings['interval']=0; app.data={}
        usage={'month':'2026-10','month_tokens':123,'month_cost':1,'total_tokens':123,'total_cost':1}
        def slow_speed(): gate.wait(3); return {},''
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter,'get_usage',return_value=usage), patch.object(meter,'get_limits',return_value={}), patch.object(meter,'get_speed',side_effect=slow_speed):
            app.refresh()
            deadline=meter.time.monotonic()+2
            while 'usage' not in app.data and meter.time.monotonic()<deadline:
                app.root.update(); meter.time.sleep(0.01)
            self.assertEqual(app.data['usage']['month_tokens'],123)
            self.assertTrue(app.busy)
            self.assertNotIn('speed',app.data)
            gate.set()
            while app.busy and meter.time.monotonic()<deadline:
                app.root.update(); meter.time.sleep(0.01)
            self.assertFalse(app.busy)
        app.closed=True
        if app.job: app.root.after_cancel(app.job)
        app.root.destroy()

    def exercise_refresh(self, fail=False):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'):
            app=meter.App()
        app.root.withdraw()
        app.settings['interval']=0
        app.data={'usage':{'month':'2026-10','month_tokens':10,'month_cost':1,'total_tokens':100,'total_cost':1}}
        previous=app.data['usage'].copy()
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter,'get_usage',side_effect=RuntimeError('offline') if fail else None,return_value={**previous,'total_tokens':125}), patch.object(meter,'get_limits',return_value={}), patch.object(meter,'get_speed',return_value=({},'')):
            app.refresh()
            deadline=meter.time.monotonic()+3
            while app.busy and meter.time.monotonic()<deadline:
                app.root.update()
                meter.time.sleep(0.01)
            self.assertFalse(app.busy)
            self.assertTrue(app.dirty)
            self.assertNotIn('Reading',app.status.cget('text'))
            if fail:
                self.assertEqual(app.data['usage'],previous)
                self.assertIn('offline',app.data['details'])
                self.assertIn('Partial refresh',app.status.cget('text'))
            else:
                self.assertEqual(app.data['delta'],25)
                self.assertTrue(app.status.cget('text').startswith('Updated'))
        app.closed=True
        if app.job: app.root.after_cancel(app.job)
        app.root.destroy()
    def test_refresh_completes(self): self.exercise_refresh()
    def test_failed_source_keeps_data_and_stops_loading(self): self.exercise_refresh(True)

if __name__=='__main__': unittest.main()
