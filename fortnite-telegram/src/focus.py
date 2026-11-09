import ctypes
import time
from ctypes import wintypes

GAME_CLASS = "UnrealWindow"
GAME_TITLE = "fortnite"

class WinApi:
    def __init__(self):
        self.u = ctypes.windll.user32
        self.k = ctypes.windll.kernel32

    def windows(self):
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _lp):
            if self.u.IsWindowVisible(h):
                found.append(h)
            return True

        self.u.EnumWindows(proto(cb), 0)
        return found

    def class_name(self, h):
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(h, buf, 256)
        return buf.value

    def title(self, h):
        buf = ctypes.create_unicode_buffer(512)
        self.u.GetWindowTextW(h, buf, 512)
        return buf.value

    def is_minimized(self, h):
        return bool(self.u.IsIconic(h))

    def foreground(self):
        return self.u.GetForegroundWindow() or 0

    def focus(self, h):
        fg = self.foreground()
        me = self.k.GetCurrentThreadId()
        fg_tid = self.u.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_tid and fg_tid != me and self.u.AttachThreadInput(me, fg_tid, True))
        try:
            self.u.SetForegroundWindow(h)
        finally:
            if attached:
                self.u.AttachThreadInput(me, fg_tid, False)

def find_game(api):
    for h in api.windows():
        if api.class_name(h) == GAME_CLASS and GAME_TITLE in api.title(h).lower():
            return h
    return None

def ensure_game_foreground(api=None):
    try:
        api = api or WinApi()
        h = find_game(api)
        if h is None or api.is_minimized(h):
            return False
        if api.foreground() == h:
            return True
        api.focus(h)
        time.sleep(0.15)
        return api.foreground() == h
    except Exception:
        return False
