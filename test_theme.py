"""Theme checks keep every test window withdrawn and never change Windows settings."""
import os
import threading
import unittest
from unittest.mock import patch
import meter
import system_theme


class ThemeTests(unittest.TestCase):
    def test_compact_height_larger_corners_and_muted_controls(self):
        meter.load_gui()
        with patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'),patch.object(meter.App,'schedule'),patch.object(meter.App,'publish_ready'):
            app=meter.App()
            try:
                app.root.update_idletasks()
                end=app.day1_grid.winfo_y()+app.day1_grid.winfo_reqheight()
                extra=app.compact_requested_height-app.root.winfo_height()
                self.assertEqual(app.canvas.winfo_height()+extra,end+8)
                self.assertLess(app.compact_requested_height,690)
                size=app.root.geometry().split('+')[0]
                app.draw();app.root.update_idletasks()
                self.assertEqual(app.root.geometry().split('+')[0],size)
                self.assertEqual(app.root.state(),'withdrawn')
                if os.name=='nt':
                    import ctypes
                    from ctypes import wintypes
                    gdi=ctypes.windll.gdi32;user=ctypes.windll.user32
                    gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4;gdi.CreateRectRgn.restype=wintypes.HRGN
                    user.GetWindowRgn.argtypes=[wintypes.HWND,wintypes.HRGN]
                    gdi.PtInRegion.argtypes=[wintypes.HRGN,ctypes.c_int,ctypes.c_int]
                    gdi.DeleteObject.argtypes=[wintypes.HANDLE]
                    region=gdi.CreateRectRgn(0,0,1,1)
                    try:
                        self.assertTrue(user.GetWindowRgn(app.window_handle,region))
                        self.assertFalse(gdi.PtInRegion(region,1,1))
                        self.assertTrue(gdi.PtInRegion(region,40,40))
                    finally: gdi.DeleteObject(region)
                with meter.Image.open(meter.ROOT/'assets/codex-clean.ico') as source:
                    icon=source.ico.getimage((32,32)).convert('RGBA')
                self.assertEqual(icon.getpixel((0,0))[3],0)
            finally:
                app.closed=True;app.root.destroy()

    def test_rounded_period_badges_keep_labels_and_follow_both_themes(self):
        meter.load_gui()
        with patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'),patch.object(meter.App,'schedule'),patch.object(meter.App,'publish_ready'):
            app=meter.App()
            try:
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                badges=[w for w in descendants(app.body) if isinstance(w,meter.tk.Canvas) and w.find_withtag('badge_bg')]
                self.assertEqual([w.itemcget('badge_text','text') for w in badges],['1 day','14 days'])
                for dark in (True,False):
                    app.sync_theme(dark);app.root.update_idletasks()
                    for badge in badges:
                        self.assertEqual(badge.itemcget('badge_bg','fill'),app.color('#f0f4f1'))
                        self.assertEqual(badge.itemcget('badge_text','fill'),app.color('#41564b'))
                        self.assertEqual(badge.itemcget('badge_bg','smooth'),'true')
                    self.assertEqual(app.root.state(),'withdrawn')
            finally:
                app.closed=True;app.root.destroy()

    def test_hidden_startup_and_live_roundtrip_preserve_input_and_data(self):
        meter.load_gui()
        for initial in (False,True):
            with self.subTest(initial=initial),patch.object(meter,'system_dark',return_value=initial),patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'),patch.object(meter.App,'schedule'),patch.object(meter.App,'publish_ready'),patch.object(meter.tk.Toplevel,'deiconify'),patch.object(meter.tk.Toplevel,'grab_set'):
                app=meter.App()
                try:
                    app.root.update_idletasks();app.settings_dialog();app.root.update_idletasks()
                    window=app.settings_window
                    box=window.winfo_children()[0]
                    entry=next(w for w in box.winfo_children() if isinstance(w,meter.ttk.Entry) and not isinstance(w,meter.ttk.Combobox))
                    combo=next(w for w in box.winfo_children() if isinstance(w,meter.ttk.Combobox))
                    entry.delete(0,'end');entry.insert(0,'123456');combo.set('Manual')
                    data=app.data;body=app.body;app.busy=True;app.pending={'speed'}
                    for dark in (True,False,True,initial):
                        app.sync_theme(dark);app.root.update_idletasks()
                        self.assertEqual(app.root.cget('bg'),app.color('#ffffff'))
                        self.assertEqual(window.cget('bg'),app.bg)
                        self.assertEqual(app.status.cget('fg'),app.color('#8a8c8f'))
                        self.assertEqual(meter.ttk.Style(app.root).lookup('Meter.TEntry','fieldbackground'),app.bg)
                        self.assertEqual(meter.ttk.Style(app.root).lookup('Meter.TCombobox','fieldbackground',('readonly',)),app.bg)
                        app.style_dropdown(combo)  # Configure a hidden, reused popdown.
                        self.assertEqual(entry.get(),'123456');self.assertEqual(combo.get(),'Manual')
                        self.assertIs(app.data,data);self.assertIs(app.body,body)
                        self.assertEqual(app.pending,{'speed'});self.assertTrue(app.busy)
                        self.assertEqual(app.root.state(),'withdrawn');self.assertEqual(window.state(),'withdrawn')
                    self.assertLessEqual(window.winfo_reqheight(),window.winfo_screenheight()-90)
                finally:
                    app.closed=True;app.root.destroy()

    def test_semantic_colors_and_icon_keep_contrast_and_transparency(self):
        meter.load_gui()
        with meter.Image.open(meter.ROOT/'assets/codex-clean.ico') as source:
            clean=source.ico.getimage((256,256)).convert('RGBA')
        self.assertEqual(clean.getchannel('A').tobytes(),meter.load_icon(256).getchannel('A').tobytes())
        self.assertEqual(len(set(meter.DARK_COLORS.values())),len(meter.DARK_COLORS))
        for color in ('#185c40','#947019','#9b3038'):
            self.assertNotEqual(meter.theme_color(color,True),color)
            self.assertEqual(meter.theme_color(color,False),color)
        light=meter.themed_icon(32,False);dark=meter.themed_icon(32,True)
        self.assertEqual(light.getchannel('A').tobytes(),dark.getchannel('A').tobytes())

    @unittest.skipUnless(os.name=='nt','Windows event-to-Tk delivery')
    def test_event_reaches_running_ui_without_showing_it(self):
        import ctypes
        from ctypes import wintypes
        meter.load_gui()
        with patch.object(meter,'system_dark',return_value=False),patch.object(system_theme,'system_dark',return_value=False) as preference,patch.object(meter.App,'show'),patch.object(meter.App,'setup_tray'),patch.object(meter.App,'refresh'),patch.object(meter.App,'schedule'),patch.object(meter.App,'publish_ready'):
            app=meter.App();result=[]
            kernel=ctypes.WinDLL('kernel32');kernel.SetEvent.argtypes=[wintypes.HANDLE]
            def signal():
                preference.return_value=True
                kernel.SetEvent(app.theme_watcher.change_event)
            def finish():
                result.append((app.dark,app.root.state()));app.root.quit()
            app.root.after(200,signal);app.root.after(600,finish)
            try:
                app.run();app.theme_watcher.thread.join(2)
                self.assertEqual(result,[(True,'withdrawn')])
                self.assertFalse(app.theme_watcher.thread.is_alive())
            finally: app.root.destroy()

    @unittest.skipUnless(os.name=='nt','Windows registry events')
    def test_listener_sleeps_until_event_and_stops_without_registry_writes(self):
        import ctypes
        from ctypes import wintypes
        seen=[];delivered=threading.Event()
        def receive(dark): seen.append(dark);delivered.set()
        with patch.object(system_theme,'system_dark',return_value=False) as preference:
            watcher=system_theme.ThemeWatcher(receive);watcher.start()
            try:
                self.assertTrue(watcher.ready.wait(2));self.assertTrue(delivered.wait(2))
                self.assertTrue(watcher.change_event)
                delivered.clear();preference.return_value=True
                kernel=ctypes.WinDLL('kernel32');kernel.SetEvent.argtypes=[wintypes.HANDLE]
                kernel.SetEvent(watcher.change_event)  # Signal our event, not a system preference.
                self.assertTrue(delivered.wait(2));self.assertEqual(seen,[False,True])
            finally:
                watcher.stop();watcher.thread.join(2)
            self.assertFalse(watcher.thread.is_alive());self.assertIsNone(watcher.stop_event)


if __name__=='__main__': unittest.main()
