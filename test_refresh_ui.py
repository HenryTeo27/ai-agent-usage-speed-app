"""Refresh checks use a withdrawn window and isolated fake sources only."""
import gc
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import meter


class HiddenRefreshTests(unittest.TestCase):
    def setUp(self):
        meter.load_gui()
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        p=patch.object(meter,'DATA',Path(self.folder.name));p.start();self.addCleanup(p.stop)
        for name in ('CONFIG','SNAPSHOT'):
            p=patch.object(meter,name,Path(self.folder.name)/(name.lower()+'.json'))
            p.start();self.addCleanup(p.stop)
        for name in ('show','setup_tray','publish_ready','schedule'):
            p=patch.object(meter.App,name);p.start();self.addCleanup(p.stop)
        meter.save(meter.CONFIG,{'interval':0,'reserve':7,'appearance':'light'})
        self.old_row={'model':'gpt-test','normal':'10.0','fast':'12.0','ratio':'1.20×','normal_n':'2','fast_n':'3'}
        self.old_usage={'month':'2026-10','month_tokens':100,'month_cost':1,'total_tokens':1000,'total_cost':2}
        meter.save(meter.SNAPSHOT,{'usage':self.old_usage,'limits':{'primary':{'usedPercent':20}},
                                   'speed':{'1':[self.old_row],'14':[]}})
        self.app=meter.App()
        self.collect_done=threading.Event()
        collect=self.app.collect;done=self.collect_done
        def tracked_collect():
            try: collect()
            finally: done.set()
        self.app.collect=tracked_collect
        self.addCleanup(self.destroy_app)

    def destroy_app(self):
        app=self.app;app.closed=True
        if hasattr(app,'refresh_started'): self.assertTrue(self.collect_done.wait(5))
        del app.collect
        app.root.update_idletasks()
        for job in app.root.tk.splitlist(app.root.tk.call('after','info')):
            app.root.after_cancel(job)
        if hasattr(app,'settings_vars'): app.settings_vars.clear()
        app.root.destroy();self.app=None
        del app
        gc.collect()

    def pump_until(self,predicate,timeout=4):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.app.root.update();time.sleep(0.01)
        self.assertTrue(predicate(),'Timed out waiting for a refresh result')

    def test_sources_start_together_and_only_changed_widgets_are_updated(self):
        app=self.app;widgets=app.content_widgets
        body=app.body;grid=app.day1_grid
        row=widgets['speed']['1'][('gpt-test',0)]
        normal=row['labels'][1];primary=widgets['primary'];month=widgets['usage']['month_tokens']
        buttons=[child for child in primary.master.winfo_children() if isinstance(child,meter.tk.Button)]
        new_row={**self.old_row,'normal':'20.0','fast':'18.0','ratio':'0.90×','normal_n':'20'}
        extra={**new_row,'model':'gpt-new','ratio':'1.60×'}
        fresh_usage={**self.old_usage,'month_tokens':150,'total_tokens':1050}
        values={'limits':{'primary':{'usedPercent':30},'secondary':{'usedPercent':50}},
                'usage':fresh_usage,'speed':({'1':[new_row,extra],'14':[extra]},'')}
        started={name:threading.Event() for name in values}
        release={name:threading.Event() for name in values}
        def source(name):
            def run():
                started[name].set()
                if not release[name].wait(10): raise RuntimeError('Test source timed out')
                return values[name]
            return run
        try:
            with patch.object(meter,'get_limits',source('limits')),patch.object(meter,'get_usage',source('usage')),patch.object(meter,'get_speed',source('speed')),patch.object(app,'draw',side_effect=AssertionError('Refresh rebuilt the page')),patch.object(app.root,'state',return_value='normal'):
                app.refresh()
                self.assertTrue(all(event.wait(2) for event in started.values()),'Sources did not start concurrently')
                self.assertEqual(app.pending,{'limits','usage','speed'})
                self.assertEqual(month.cget('text'),'100')
                release['limits'].set();self.pump_until(lambda:'limits' not in app.pending)
                self.assertEqual(primary.cget('text'),'70% remaining')
                self.assertEqual(widgets['secondary'].cget('text'),'50% remaining')
                self.assertEqual(month.cget('text'),'100')
                release['usage'].set();self.pump_until(lambda:'usage' not in app.pending)
                self.assertEqual(month.cget('text'),'150')
                self.assertEqual(widgets['usage']['total_tokens'].cget('text'),'1,057')
                self.assertEqual(widgets['delta'].cget('text'),'+50 tokens')
                self.assertEqual(normal.cget('text'),'10.0')
                release['speed'].set();self.pump_until(lambda:not app.busy)
                self.assertIs(app.body,body);self.assertIs(app.day1_grid,grid)
                self.assertIs(widgets['primary'],primary);self.assertIs(widgets['usage']['month_tokens'],month)
                self.assertIs(widgets['speed']['1'][('gpt-test',0)]['labels'][1],normal)
                self.assertTrue(all(button.winfo_exists() for button in buttons))
                self.assertEqual(normal.cget('text'),'20.0')
                self.assertIn('20 timed responses',row['tips'][1].text)
                self.assertEqual(row['labels'][3].cget('fg'),app.color('#9b3038'))
                self.assertIn(('gpt-new',0),widgets['speed']['1'])
                self.assertEqual(widgets['empty']['14'].winfo_manager(),'')
                self.assertEqual(meter.read(meter.SNAPSHOT,{})['usage'],fresh_usage)
                self.assertIn('Difference: +50',next(tip.text() for tip in meter.Tooltip.instances if tip.widget is widgets['delta']))
        finally:
            for event in release.values(): event.set()
        self.assertEqual(app.root.state(),'withdrawn')

    def test_hidden_results_update_when_restored_without_rebuilding_page(self):
        app=self.app;body=app.body;widgets=app.content_widgets
        app.data['usage']={**self.old_usage,'month_tokens':222}
        app.data['speed']={'1':[],'14':[]}
        app.render_results('usage');app.render_results('speed')
        self.assertTrue(app.dirty)
        self.assertEqual(widgets['usage']['month_tokens'].cget('text'),'100')
        with patch.object(app,'draw',side_effect=AssertionError('Restore rebuilt the page')),patch.object(app,'configure_window'),patch.object(app,'publish_ready'):
            app.on_map(SimpleNamespace(widget=app.root))
        self.assertFalse(app.dirty);self.assertIs(app.body,body)
        self.assertEqual(widgets['usage']['month_tokens'].cget('text'),'222')
        self.assertEqual(widgets['speed']['1'],{})
        self.assertEqual(widgets['empty']['1'].winfo_manager(),'grid')
        self.assertEqual(app.root.state(),'withdrawn')

    def test_failed_source_keeps_its_previous_values(self):
        app=self.app;body=app.body
        with patch.object(meter,'get_usage',return_value={**self.old_usage,'total_tokens':1050}),patch.object(meter,'get_limits',return_value={'primary':{'usedPercent':40}}),patch.object(meter,'get_speed',side_effect=RuntimeError('Speed is unavailable')),patch.object(app,'draw',side_effect=AssertionError('Refresh rebuilt the page')),patch.object(app.root,'state',return_value='normal'):
            app.refresh();self.pump_until(lambda:not app.busy)
        self.assertIs(app.body,body)
        self.assertEqual(app.data['speed']['1'],[self.old_row])
        self.assertEqual(app.content_widgets['speed']['1'][('gpt-test',0)]['labels'][1].cget('text'),'10.0')
        self.assertEqual(app.content_widgets['primary'].cget('text'),'60% remaining')
        self.assertEqual(app.data['delta'],50)
        self.assertIn('Partial refresh',app.status.cget('text'))
        self.assertIn('Speed is unavailable',app.status_detail)
        self.assertEqual(app.root.state(),'withdrawn')

    def test_reserve_edit_updates_only_the_existing_total_label(self):
        app=self.app;body=app.body;label=app.content_widgets['usage']['total_tokens']
        with patch.object(meter.tk.Toplevel,'deiconify'),patch.object(meter.tk.Toplevel,'grab_set'),patch.object(app,'draw',side_effect=AssertionError('Settings rebuilt the page')),patch.object(app.root,'state',return_value='normal'):
            app.settings_dialog();app.settings_vars['reserve'].set('320')
            self.assertTrue(app.close_settings())
        self.assertIs(app.body,body);self.assertEqual(label.cget('text'),'1,320')
        self.assertEqual(meter.load_settings()['reserve'],320)
        self.assertEqual(app.root.state(),'withdrawn')

    def test_new_speed_rows_follow_appearance_changes(self):
        app=self.app;app.settings['appearance']='system';app.sync_theme(True)
        app.data['speed']['1'].append({**self.old_row,'model':'gpt-new','ratio':'1.60×'})
        with patch.object(app.root,'state',return_value='normal'): app.render_results('speed')
        ratio=app.content_widgets['speed']['1'][('gpt-new',0)]['labels'][3]
        self.assertEqual(ratio.cget('fg'),meter.theme_color('#185c40',True))
        app.sync_theme(False)
        self.assertEqual(ratio.cget('fg'),'#185c40')
        self.assertEqual(app.root.state(),'withdrawn')


if __name__=='__main__': unittest.main()
