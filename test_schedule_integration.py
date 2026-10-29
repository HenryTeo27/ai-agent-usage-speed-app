"""Exercise a real hidden Tk event loop and the Settings auto-save callback."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import meter


class HiddenScheduleIntegrationTests(unittest.TestCase):
    def test_manual_mode_does_not_start_a_first_scan(self):
        meter.load_gui()
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'settings.json';snapshot=Path(folder)/'snapshot.json'
            meter.save(config,{'interval':0,'reserve':0,'appearance':'system'})
            with patch.object(meter,'CONFIG',config),patch.object(meter,'SNAPSHOT',snapshot),patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'publish_ready'),patch.object(meter.App,'refresh') as refresh:
                app=meter.App()
                try:
                    app.root.update();refresh.assert_not_called()
                    self.assertIsNone(app.job)
                    self.assertEqual(app.root.state(),'withdrawn')
                finally:
                    app.closed=True;app.root.destroy()

    def test_changing_settings_starts_overdue_refresh_in_tray(self):
        meter.load_gui()
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'settings.json';snapshot=Path(folder)/'snapshot.json'
            now=time.time()
            previous={'month':'2026-10','month_tokens':10,'month_cost':1,'total_tokens':111,'total_cost':2}
            meter.save(config,{'interval':4,'reserve':0,'appearance':'system'})
            meter.save(snapshot,{'usage':previous,'limits':{},'speed':{'1':[],'14':[]},'last_refresh_at':now-3*3600})
            fresh={**previous,'total_tokens':130}
            with patch.object(meter,'CONFIG',config),patch.object(meter,'SNAPSHOT',snapshot),patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'publish_ready'),patch.object(meter.tk.Toplevel,'deiconify'),patch.object(meter.tk.Toplevel,'grab_set'),patch.object(meter,'get_usage',return_value=fresh),patch.object(meter,'get_limits',return_value={}),patch.object(meter,'get_speed',return_value=({'1':[],'14':[]},'')):
                app=meter.App()
                try:
                    app.root.update();self.assertFalse(app.busy)
                    app.settings_dialog();app.settings_vars['interval'].set('2 hours')
                    self.assertEqual(meter.read(config,{})['interval'],2)
                    deadline=time.monotonic()+5;started=False
                    while time.monotonic()<deadline:
                        app.root.update();started=started or app.busy
                        if started and not app.busy: break
                        time.sleep(0.01)
                    self.assertTrue(started);self.assertFalse(app.busy)
                    self.assertEqual(app.data['usage']['total_tokens'],130)
                    self.assertEqual(app.data['delta'],19)
                    self.assertIn('last_refresh_attempt_at',meter.read(snapshot,{}))
                    self.assertEqual(app.root.state(),'withdrawn')
                finally:
                    app.closed=True
                    if app.job: app.root.after_cancel(app.job)
                    app.root.destroy()


if __name__=='__main__': unittest.main()
