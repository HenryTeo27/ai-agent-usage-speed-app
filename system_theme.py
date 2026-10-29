"""Windows app-theme preference, with an idle registry-notification listener."""
import os
import threading

PERSONALIZE = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def system_dark(value='AppsUseLightTheme'):
    if os.name != 'nt': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            return winreg.QueryValueEx(key, value)[0] == 0
    except OSError:
        return False


class ThemeWatcher:
    """Wait on Windows events; no timer, registry writes or repeated polling."""
    def __init__(self, callback):
        self.callback = callback
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.stop_event = self.change_event = None

    def start(self):
        self.thread = threading.Thread(target=self.watch, daemon=True, name='system-theme')
        self.thread.start()

    def watch(self):
        if os.name != 'nt': self.ready.set(); return
        import ctypes
        import winreg
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        notify = ctypes.WinDLL('advapi32').RegNotifyChangeKeyValue
        notify.argtypes = [wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD, wintypes.HANDLE, wintypes.BOOL]
        self.stop_event = kernel.CreateEventW(None, True, False, None)
        self.change_event = kernel.CreateEventW(None, False, False, None)
        try:
            if not self.stop_event or not self.change_event: return
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_READ) as key:
                handles = (wintypes.HANDLE * 2)(self.stop_event, self.change_event)
                while not self.closed.is_set():
                    if notify(int(key), False, 4, self.change_event, True) != 0: break
                    # Arm before reading, so a change during startup is not lost.
                    self.ready.set()
                    self.callback(system_dark())
                    if kernel.WaitForMultipleObjects(2, handles, False, 0xffffffff) != 1: break
        except OSError:
            pass  # Startup preference remains usable if notifications are unavailable.
        finally:
            self.ready.set()
            for handle in (self.stop_event, self.change_event):
                if handle: kernel.CloseHandle(handle)
            self.stop_event = self.change_event = None

    def stop(self):
        self.closed.set()
        if self.stop_event:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32')
            kernel.SetEvent.argtypes = [wintypes.HANDLE]
            kernel.SetEvent(self.stop_event)
