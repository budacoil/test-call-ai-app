import time
from typing import (Callable, List, Optional)
GAME_CLASS = 'UnrealWindow'
GAME_TITLE = 'fortnite'
FORTNITE_EXES = ('fortniteclient-win64-shipping.exe',)
GFN_CLASS = 'CEFCLIENT'
GFN_TITLE = 'geforce now'
GFN_GAME_NAMES = ('fortnite', 'フォートナイト')

class WinApi:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ct, self._wt = ctypes, wintypes
        self.u = ctypes.windll.user32
        self.k = ctypes.windll.kernel32

    def windows(self) -> List[int]:
        found = []
        proto = self._ct.WINFUNCTYPE(self._wt.BOOL, self._wt.HWND, self._wt.LPARAM)
        def cb(h, _lp):
            if self.u.IsWindowVisible(h):
                found.append(h)
            return True

        self.u.EnumWindows(proto(cb), 0)
        return found

    def class_name(self, h: int) -> str:
        buf = self._ct.create_unicode_buffer(256)
        self.u.GetClassNameW(h, buf, 256)
        return buf.value

    def title(self, h: int) -> str:
        buf = self._ct.create_unicode_buffer(512)
        self.u.GetWindowTextW(h, buf, 512)
        return buf.value

    def is_minimized(self, h: int) -> bool:
        return bool(self.u.IsIconic(h))

    def process_name(self, h: int) -> str:
        ct, wt = self._ct, self._wt
        class ENTRY(ct.Structure):
            _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD), ('th32DefaultHeapID', ct.c_size_t), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ct.c_long), ('dwFlags', wt.DWORD), ('szExeFile', ct.c_wchar * 260)]

        pid = wt.DWORD(0)
        self.u.GetWindowThreadProcessId(h, ct.byref(pid))
        k = self.k
        k.CreateToolhelp32Snapshot.restype = ct.c_void_p
        k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k.Process32FirstW.argtypes = [ct.c_void_p, ct.POINTER(ENTRY)]
        k.Process32NextW.argtypes = [ct.c_void_p, ct.POINTER(ENTRY)]
        k.CloseHandle.argtypes = [ct.c_void_p]
        snap = k.CreateToolhelp32Snapshot(2, 0)
        if not snap or snap == ct.c_void_p(-1).value:
            return ''
        try:
            e = ENTRY()
            e.dwSize = ct.sizeof(ENTRY)
            ok = k.Process32FirstW(snap, ct.byref(e))
            while ok:
                if e.th32ProcessID == pid.value:
                    k.CloseHandle(snap)
                    return e.szExeFile
                ok = k.Process32NextW(snap, ct.byref(e))
        finally:
            k.CloseHandle(snap)
        return ''

    def foreground(self) -> int:
        return self.u.GetForegroundWindow() or 0

    def focus(self, h: int) -> None:
        fg = self.foreground()
        me = self.k.GetCurrentThreadId()
        fg_tid = self.u.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_tid and fg_tid != me and self.u.AttachThreadInput(me, fg_tid, True))
        try:
            self.u.SetForegroundWindow(h)
        finally:
            if attached:
                self.u.AttachThreadInput(me, fg_tid, False)


def is_game_window(cls: str, title: str) -> bool:
    t = (title or '').lower()
    if cls == GAME_CLASS and GAME_TITLE in t:
        return True
    return cls == GFN_CLASS and GFN_TITLE in t and any((name in t for name in GFN_GAME_NAMES))

def find_game(api) -> Optional[int]:
    windows = api.windows()
    for h in windows:
        if not is_game_window(api.class_name(h), api.title(h)):
            continue
        return h
    process_name = getattr(api, 'process_name', None)
    if process_name:
        for h in windows:
            if api.class_name(h) != GAME_CLASS:
                continue
            try:
                if process_name(h).lower() in FORTNITE_EXES:
                    return h
            except Exception:
                continue

def ensure_game_foreground(api=None, sleeper: Callable[[float], None]=time.sleep) -> bool:
    try:
        api = api or WinApi()
        h = find_game(api)
        if h is None or api.is_minimized(h):
            return False
        if api.foreground() == h:
            return True
        api.focus(h)
        sleeper(0.15)
        return api.foreground() == h
    except Exception:
        return False

