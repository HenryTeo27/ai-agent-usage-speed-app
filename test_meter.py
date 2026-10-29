import unittest
from unittest.mock import patch
import meter

class InvisibleGuiTests(unittest.TestCase):
    """Exercise real mapped windows without flashing test UI on the desktop."""
    def setUp(self):
        meter.load_gui()
        top_level=meter.tk.Toplevel
        def transparent_window(*args,**kwargs):
            window=top_level(*args,**kwargs);window.attributes('-alpha',0)
            return window
        for target,name,replacement in ((meter.App,'reveal',lambda app:setattr(app,'_show_job',None)),
                                         (meter.App,'show',lambda app:app.root.deiconify()),
                                         (meter.tk,'Toplevel',transparent_window)):
            patcher=patch.object(target,name,replacement);patcher.start();self.addCleanup(patcher.stop)

class SnapshotTests(InvisibleGuiTests):
    def test_interrupted_replace_keeps_last_snapshot(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.json'
            original={'usage':{'total_tokens':1200},'speed':{'1':[]},'limits':{'primary':{'usedPercent':10}}}
            meter.save(path,original)
            with patch.object(meter.os,'replace',side_effect=OSError('simulated interruption')):
                with self.assertRaises(OSError): meter.save(path,{'usage':{'total_tokens':1300}})
            self.assertEqual(meter.read(path,{}),original)
            self.assertEqual([file.name for file in Path(tmp).iterdir()],['snapshot.json'])

    def test_existing_cache_is_shown_without_rescanning_after_upgrade(self):
        import tempfile
        from pathlib import Path
        data={'usage':{'month_tokens':123,'total_tokens':456,'month_cost':1,'total_cost':2},
              'speed':{'1':[],'14':[]},'limits':{},'app_version':'older','last_refresh_at':meter.time.time()}
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh') as refresh:
            meter.save(meter.SNAPSHOT,data)
            app=meter.App();app.root.update()
            self.assertEqual(app.data['usage'],data['usage'])
            refresh.assert_not_called()
            self.assertFalse(hasattr(app,'_window_proc'))
            app.closed=True
            if app.job: app.root.after_cancel(app.job)
            app.root.destroy()

class WindowLifecycleTests(InvisibleGuiTests):
    def test_startup_and_restore_wait_for_reveal(self):
        with patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'):
            app=meter.App()
        try:
            app.root.update()
            self.assertEqual(app.root.attributes('-alpha'),0)
            self.assertTrue(app.body.winfo_children())
            app.hide();app.root.update();app.show();app.root.update()
            self.assertEqual(app.root.attributes('-alpha'),0)
            self.assertTrue(app.body.winfo_children())
        finally:
            app.closed=True
            if app.job: app.root.after_cancel(app.job)
            app.root.destroy()

    def test_redraw_keeps_previous_frame_until_replacement_is_ready(self):
        with patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'):
            app=meter.App()
        try:
            app.root.update();previous=app.body
            with patch.object(app,'draw_content',side_effect=RuntimeError('render failed')):
                with self.assertRaises(RuntimeError): app.draw()
            self.assertIs(app.body,previous)
            self.assertTrue(previous.winfo_exists())
            self.assertEqual(app.canvas.itemcget(app.body_window,'window'),str(previous))
            app.draw();app.root.update()
            self.assertFalse(previous.winfo_exists())
            self.assertTrue(app.body.winfo_children())
            self.assertEqual(app.canvas.itemcget(app.body_window,'window'),str(app.body))
        finally:
            app.closed=True
            if app.job: app.root.after_cancel(app.job)
            app.root.destroy()
    @unittest.skipUnless(meter.os.name=='nt','Windows drag positioning')
    def test_header_drag_moves_multiple_times_and_stops_on_release(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'):
            app=meter.App();app.root.geometry('+100+100');app.root.update()
            try:
                x,y=app.root.winfo_x(),app.root.winfo_y()
                app.drag_window(SimpleNamespace(x_root=x+50,y_root=y+20))
                for dx,dy in [(30,20),(90,50),(160,80)]:
                    app.drag_motion(SimpleNamespace(x_root=x+50+dx,y_root=y+20+dy));app.root.update()
                    self.assertEqual((app.root.winfo_x(),app.root.winfo_y()),(x+dx,y+dy))
                app.end_drag()
                self.assertIsNone(app._drag_origin)
                self.assertIsNone(app._drag_job)
                app.drag_motion(SimpleNamespace(x_root=0,y_root=0));app.root.update()
                self.assertEqual((app.root.winfo_x(),app.root.winfo_y()),(x+160,y+80))
            finally:
                app.closed=True
                if app.job: app.root.after_cancel(app.job)
                app.root.destroy()

    @unittest.skipUnless(meter.os.name=='nt','Native Windows window selection')
    def test_tooltip_is_not_selected_as_main_and_is_closed_on_hide(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'):
            app=meter.App();app.root.update()
            label=meter.tk.Label(app.root,text='tip');label.pack()
            tip=meter.Tooltip(label,'Example');tip.show();app.root.update()
            self.assertEqual(tip.popup.title(),'Codex Meter tooltip')
            self.assertEqual(meter.find_ready_window(),app.window_handle)
            app.hide();app.root.update()
            self.assertIsNone(tip.popup)
            self.assertEqual(meter.find_ready_window(),app.window_handle)
            app.closed=True
            if app.job: app.root.after_cancel(app.job)
            app.root.destroy()

    @unittest.skipUnless(meter.os.name=='nt','Native Windows restore')
    def test_restore_rebinds_native_window_and_keeps_cached_data(self):
        import ctypes,tempfile
        from ctypes import wintypes
        from pathlib import Path
        saved={'usage':{'month_tokens':123,'total_tokens':456,'month_cost':1,'total_cost':2},
               'speed':{'1':[],'14':[]},'limits':{},'last_refresh_at':meter.time.time()}
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'):
            meter.save(meter.SNAPSHOT,saved)
            app=meter.App();app.root.title('Codex Meter lifecycle test');app.root.update()
            user=ctypes.windll.user32
            user.GetPropW.argtypes=[wintypes.HWND,wintypes.LPCWSTR];user.GetPropW.restype=wintypes.HANDLE
            user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
            try:
                for cycle in range(4):
                    app.hide();app.root.update();app.dirty=True
                    user.ShowWindow(app.window_handle,4);app.root.update()
                    current=user.GetParent(app.root.winfo_id())
                    self.assertEqual(current,app.window_handle)
                    self.assertEqual(user.GetPropW(current,'CodexMeter.Ready'),1)
                    self.assertEqual(app.root.state(),'normal')
                    self.assertFalse(app.dirty)
                    self.assertEqual(app.data['usage'],saved['usage'])
                    self.assertTrue(app.body.winfo_children())
            finally:
                app.closed=True
                if app.job: app.root.after_cancel(app.job)
                app.root.destroy()

class SettingsTests(InvisibleGuiTests):
    def test_project_link_and_settings_save(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(meter,'CONFIG',Path(tmp)/'settings.json'), patch.object(meter,'SNAPSHOT',Path(tmp)/'snapshot.json'), patch.object(meter.App,'setup_tray'), patch.object(meter.App,'refresh'), patch.object(meter.App,'publish_ready'):
            app=meter.App()
            try:
                app.root.geometry('+100+600');app.root.update()
                app.settings_dialog();app.root.update()
                window=app.settings_window
                app.settings_dialog()
                self.assertIs(app.settings_window,window)
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                widgets=list(descendants(window))
                labels=[widget for widget in widgets if isinstance(widget,meter.tk.Label)]
                self.assertIn('Codex Meter · v'+meter.VERSION,[label.cget('text') for label in labels])
                project=next(label for label in labels if label.cget('text')==meter.REPOSITORY)
                with patch.object(meter.webbrowser,'open') as browser:
                    project.event_generate('<Button-1>');app.root.update()
                    browser.assert_called_once_with(meter.REPOSITORY)
                self.assertLessEqual(window.winfo_y()+window.winfo_height(),window.winfo_screenheight()-90)
                interval=next(widget for widget in widgets if isinstance(widget,meter.ttk.Combobox) and 'Manual' in widget.cget('values'))
                reserve=next(widget for widget in widgets if isinstance(widget,meter.ttk.Entry) and not isinstance(widget,meter.ttk.Combobox))
                interval.set('4 hours');reserve.delete(0,'end');reserve.insert(0,'1,234')
                next(widget for widget in widgets if isinstance(widget,meter.ttk.Button) and widget.cget('text')=='Save').invoke()
                self.assertEqual(app.settings,{'interval':4,'reserve':1234,'appearance':'system'})
                self.assertEqual(meter.read(meter.CONFIG,{}),app.settings)
                self.assertIsNotNone(app.job)
            finally:
                app.closed=True
                if app.job: app.root.after_cancel(app.job)
                app.root.destroy()

class DeltaTests(unittest.TestCase):
    def test_adjacent_refreshes_replace_large_previous_delta(self):
        data={'usage':{'total_tokens':1_000_000_000},'delta':150_000_000}
        meter.apply_usage_result(data,{'total_tokens':1_150_000_000},dict(data['usage']),1)
        self.assertEqual(data['delta'],150_000_000)
        meter.apply_usage_result(data,{'total_tokens':1_150_200_000},dict(data['usage']),2)
        self.assertEqual(data['delta'],200_000)
        self.assertIn('Difference: +200,000',meter.delta_tooltip(data))
        meter.apply_usage_result(data,{'total_tokens':1_150_200_000},dict(data['usage']),3)
        self.assertEqual(data['delta'],0)

    def test_restart_uses_last_successful_usage_and_month_rollover(self):
        import tempfile
        from pathlib import Path
        data={'usage':{'month':'2026-10','total_tokens':1000},'delta':900}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.json'
            meter.apply_usage_result(data,{'month':'2026-10','total_tokens':1200},dict(data['usage']),1)
            meter.save(path,data)
            restored=meter.read(path,{})
            meter.apply_usage_result(restored,{'month':'2026-11','total_tokens':1207},dict(restored['usage']),2)
            self.assertEqual(restored['delta'],7)
            self.assertEqual(restored['delta_comparison']['previous_tokens'],1200)

    def test_first_scan_has_no_invented_delta(self):
        data={}
        meter.apply_usage_result(data,{'total_tokens':1000},None,1)
        self.assertIsNone(data['delta'])

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

class RefreshTests(InvisibleGuiTests):
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
            while ('usage' not in app.data or 'limits' not in app.data) and meter.time.monotonic()<deadline:
                app.root.update(); meter.time.sleep(0.01)
            self.assertEqual(app.data['usage']['month_tokens'],123)
            self.assertEqual(meter.read(meter.SNAPSHOT,{})['usage'],usage)
            self.assertEqual(meter.read(meter.SNAPSHOT,{})['limits'],{})
            self.assertTrue(app.busy)
            self.assertNotIn('speed',app.data)
            gate.set()
            deadline=meter.time.monotonic()+3
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
                self.assertRegex(app.status.cget('text'),r'^Updated \d{2}:\d{2}$')
        app.closed=True
        if app.job: app.root.after_cancel(app.job)
        app.root.destroy()
    def test_refresh_completes(self): self.exercise_refresh()
    def test_failed_source_keeps_data_and_stops_loading(self): self.exercise_refresh(True)

if __name__=='__main__': unittest.main()
