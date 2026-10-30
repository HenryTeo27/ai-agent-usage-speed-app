"""Deterministic scheduler checks: simulated hours, no scans or desktop windows."""
import unittest
from unittest.mock import Mock, patch
import meter


class Clock:
    def __init__(self): self.wall=100000.0;self.tick=0


class Root:
    def __init__(self,clock): self.clock=clock;self.jobs={};self.sequence=0
    def after(self,delay,callback):
        self.sequence+=1;self.jobs[self.sequence]=(self.clock.tick+delay,callback)
        return self.sequence
    def after_cancel(self,job): self.jobs.pop(job,None)
    def advance(self,seconds):
        target=self.clock.tick+round(seconds*1000)
        while self.jobs:
            job,(when,callback)=min(self.jobs.items(),key=lambda item:item[1][0])
            if when>target: break
            self.clock.wall+=(when-self.clock.tick)/1000;self.clock.tick=when
            del self.jobs[job];callback()
        self.clock.wall+=(target-self.clock.tick)/1000;self.clock.tick=target


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.root=Root(self.clock)
        self.app=meter.App.__new__(meter.App)
        self.app.root=self.root;self.app.settings={'interval':4};self.app.data={'last_refresh_at':self.clock.wall}
        self.app.job=None;self.app.busy=False;self.app.closed=False
        self.app.status_detail=''
        self.app.status=Mock();self.app.render_results=Mock();self.app.check_results=Mock()
        for target,name,value in ((meter.time,'time',lambda:self.clock.wall),
                                  (meter.time,'monotonic',lambda:self.clock.tick/1000),
                                  (meter.threading,'Thread',Mock()),(meter,'save',Mock())):
            patcher=patch.object(target,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.threads=meter.threading.Thread

    def test_shorter_interval_refreshes_immediately_when_overdue(self):
        self.app.data['last_refresh_at']=self.clock.wall-3*3600
        self.app.schedule();self.assertFalse(self.app.busy)
        self.app.settings['interval']=2;self.app.schedule();self.root.advance(0)
        self.assertTrue(self.app.busy);self.assertEqual(self.threads.call_count,1)

    def test_shorter_interval_waits_only_the_remaining_time(self):
        self.app.data['last_refresh_at']=self.clock.wall-3600
        self.app.settings['interval']=2;self.app.schedule()
        self.root.advance(3599);self.assertEqual(self.threads.call_count,0)
        self.root.advance(1);self.assertEqual(self.threads.call_count,1)

    def test_new_short_intervals_count_from_latest_completed_refresh(self):
        for number,interval in enumerate((0.5,1),1):
            with self.subTest(hours=interval):
                self.app.settings['interval']=interval;self.app.schedule()
                self.root.advance(interval*3600-1)
                self.assertEqual(self.threads.call_count,number-1)
                self.root.advance(1);self.assertEqual(self.threads.call_count,number)
                self.app.finish()

    def test_manual_refresh_cancels_old_timer_and_restarts_from_completion(self):
        self.app.settings['interval']=2;self.app.schedule()
        self.root.advance(3600);self.app.refresh()
        self.root.advance(12);self.app.finish()
        self.assertEqual(self.app.data['last_refresh_attempt_at'],self.clock.wall)
        self.root.advance(7199);self.assertEqual(self.threads.call_count,1)
        self.root.advance(1);self.assertEqual(self.threads.call_count,2)

    def test_manual_mode_cancels_timers_then_auto_checks_the_last_update(self):
        self.app.schedule();self.app.settings['interval']=0;self.app.schedule()
        self.assertEqual(self.root.jobs,{})
        self.assertIn('Automatic refresh: off',self.app.status_tooltip_text())
        self.root.advance(3*3600);self.assertEqual(self.threads.call_count,0)
        self.app.settings['interval']=2;self.app.schedule();self.root.advance(0)
        self.assertEqual(self.threads.call_count,1)

    def test_status_hover_shows_the_next_deadline_without_extra_timers(self):
        self.app.settings['interval']=2;self.app.schedule()
        jobs=dict(self.root.jobs)
        self.assertIn('Next automatic refresh:',self.app.status_tooltip_text())
        self.assertEqual(jobs,self.root.jobs)

    def test_change_during_refresh_uses_new_interval_without_overlap(self):
        self.app.schedule();self.app.refresh();self.app.settings['interval']=2;self.app.schedule()
        self.assertIsNone(self.app.job)
        self.root.advance(90);self.assertEqual(self.threads.call_count,1)
        self.app.finish();self.root.advance(7199);self.assertEqual(self.threads.call_count,1)
        self.root.advance(1);self.assertEqual(self.threads.call_count,2)

    def test_partial_or_failed_attempt_does_not_spin_and_survives_restart(self):
        self.app.settings['interval']=2;last_success=self.app.data['last_refresh_at']
        self.app.refresh();self.root.advance(5);self.app.refresh_errors=['speed: offline'];self.app.finish()
        self.assertEqual(self.app.data['last_refresh_at'],last_success)
        self.assertEqual(self.app.data['last_refresh_attempt_at'],self.clock.wall)
        self.app.schedule();self.root.advance(7199);self.assertEqual(self.threads.call_count,1)
        self.root.advance(1);self.assertEqual(self.threads.call_count,2)

    def test_resume_or_clock_jump_is_caught_without_a_scan_poll(self):
        self.app.settings['interval']=2;self.app.schedule()
        self.clock.wall+=3*3600  # Simulated sleep or wall-clock adjustment.
        self.root.advance(60);self.assertEqual(self.threads.call_count,1)

    def test_returning_to_the_window_checks_an_overdue_deadline_immediately(self):
        from types import SimpleNamespace
        self.app.settings['interval']=2;self.app.schedule()
        self.clock.wall+=3*3600
        self.app.on_focus(SimpleNamespace(widget=self.root));self.root.advance(0)
        self.assertEqual(self.threads.call_count,1)

    def test_backward_clock_rebases_once_without_indefinite_postponement(self):
        self.app.data['last_refresh_at']=self.clock.wall+24*3600
        self.app.settings['interval']=2;self.app.schedule()
        self.root.advance(7199);self.assertEqual(self.threads.call_count,0)
        self.root.advance(1);self.assertEqual(self.threads.call_count,1)
        self.app.finish()
        self.root.advance(7199);self.assertEqual(self.threads.call_count,1)
        self.root.advance(1);self.assertEqual(self.threads.call_count,2)

    def test_legacy_partial_snapshot_uses_the_latest_source_timestamp(self):
        self.app.data={'last_refresh_at':self.clock.wall-5*3600,
                       'updated_at':{'usage':self.clock.wall-3600}}
        self.app.settings['interval']=2;self.app.schedule()
        self.root.advance(3599);self.assertEqual(self.threads.call_count,0)
        self.root.advance(1);self.assertEqual(self.threads.call_count,1)


if __name__=='__main__': unittest.main()
