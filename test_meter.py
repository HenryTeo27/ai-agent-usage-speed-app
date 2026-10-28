import unittest
from unittest.mock import patch
import meter

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

class RefreshTests(unittest.TestCase):
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
            self.assertNotIn('Reading',app.status.cget('text'))
            if fail:
                self.assertEqual(app.data['usage'],previous)
                self.assertIn('offline',app.status.cget('text'))
            else:
                self.assertEqual(app.data['delta'],25)
                self.assertTrue(app.status.cget('text').startswith('Updated'))
        app.closed=True
        if app.job: app.root.after_cancel(app.job)
        app.root.destroy()
    def test_refresh_completes(self): self.exercise_refresh()
    def test_failed_source_keeps_data_and_stops_loading(self): self.exercise_refresh(True)

if __name__=='__main__': unittest.main()
