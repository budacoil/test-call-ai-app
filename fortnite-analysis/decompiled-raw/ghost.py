import ctypes
import json
import os
import threading
import time
from collections import deque
from ctypes import wintypes
from typing import (Callable, Deque, Optional, Tuple)
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 32
WS_EX_LAYERED = 524288
GHOST_BITS = WS_EX_LAYERED | WS_EX_TRANSPARENT
LWA_ALPHA = 2
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 1, 2, 16
GA_ROOT = 2
MASK32 = 4294967295
GHOST_ALPHA = 1
IDLE_BEFORE_INPUT_MS = 1000
IDLE_WAIT_MAX_S = 5.0
OWN_MARGIN_MS = 60
RETRY_AFTER_FAIL_S = 10.0
MARKER_NAME = 'pk-auto_shield.json'

class GhostApi:
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        h, b, i = wintypes.HANDLE, wintypes.BOOL, ctypes.c_int
        self.u.IsWindow.argtypes = [h]
        self.u.IsWindow.restype = b
        self.u.GetAncestor.argtypes = [h, wintypes.UINT]
        self.u.GetAncestor.restype = h
        self.u.WindowFromPoint.argtypes = [wintypes.POINT]
        self.u.WindowFromPoint.restype = h
        self.u.SetWindowPos.argtypes = [h, h, i, i, i, i, wintypes.UINT]
        self.u.SetWindowPos.restype = b
        self.u.GetWindowLongPtrW.argtypes = [h, i]
        self.u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.u.SetWindowLongPtrW.argtypes = [h, i, ctypes.c_ssize_t]
        self.u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.u.SetLayeredWindowAttributes.argtypes = [h, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
        self.u.SetLayeredWindowAttributes.restype = b
        self.u.GetClassNameW.argtypes = [h, wintypes.LPWSTR, i]
        self.u.GetClassNameW.restype = i
        self.k.GetTickCount.restype = wintypes.DWORD
        try:
            self.dwm = ctypes.WinDLL('dwmapi')
            return
        except OSError:
            self.dwm = None

    def is_window(self, h) -> bool:
        return bool(self.u.IsWindow(h))

    def root_at(self, x: int, y: int) -> Optional[int]:
        w = self.u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if w:
            return self.u.GetAncestor(w, GA_ROOT) or w

    def class_name(self, h) -> str:
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(h, buf, 256)
        return buf.value

    def to_bottom(self, h) -> bool:
        return bool(self.u.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))

    def raise_top(self, h) -> bool:
        return bool(self.u.SetWindowPos(h, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))

    def flush(self) -> None:
        try:
            if self.dwm:
                self.dwm.DwmFlush()
                return
        except Exception:
            pass

    def get_exstyle(self, h) -> int:
        return int(self.u.GetWindowLongPtrW(h, GWL_EXSTYLE)) & MASK32

    def set_exstyle(self, h, value: int) -> bool:
        ctypes.set_last_error(0)
        self.u.SetWindowLongPtrW(h, GWL_EXSTYLE, ctypes.c_ssize_t(value))
        return ctypes.get_last_error() == 0 and self.get_exstyle(h) == value & MASK32

    def set_alpha(self, h, alpha: int=255) -> bool:
        return bool(self.u.SetLayeredWindowAttributes(h, 0, alpha, LWA_ALPHA))

    def tick(self) -> int:
        return int(self.k.GetTickCount())

    def last_input_tick(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        self.u.GetLastInputInfo(ctypes.byref(info))
        return int(info.dwTime)


class UserActivity:
    def __init__(self, api):
        self.api = api
        self._own = deque(maxlen=64)
        self._seen = None
        self._user_tick = None

    def own_begin(self) -> None:
        self._own.append((self.api.tick(), None))

    def own_end(self) -> None:
        if self._own:
            if self._own[-1][1] is None:
                start = self._own.pop()[0]
                self._own.append((start, self.api.tick()))

    def _is_own(self, t: int) -> bool:
        for start, end in self._own:
            span = (end if end is not None else self.api.tick()) - start & MASK32
            if t - start & MASK32 <= span + OWN_MARGIN_MS:
                return True
        return False

    def scan(self) -> None:
        t = self.api.last_input_tick()
        if t != self._seen:
            self._seen = t
            if not self._is_own(t):
                self._user_tick = t

    def idle_ms(self) -> int:
        self.scan()
        if self._user_tick is None:
            return 1000000000
        return self.api.tick() - self._user_tick & MASK32


class GhostWindow:
    def __init__(self, api=None, activity: Optional[UserActivity]=None, game_hwnd: Callable[[], Optional[int]]=(lambda: None), marker_path: Optional[str]=None, clock: Callable[[], float]=time.monotonic):
        self.api = api or GhostApi()
        self.activity = activity or UserActivity(self.api)
        self._game = game_hwnd
        self.marker_path = marker_path
        self._clock = clock
        self.hwnd = None
        self.orig = 0
        self.added = 0
        self.ghosted = False
        self.hidden = False
        self.disabled = ''
        self.failed = ''
        self._retry_at = 0.0
        self.cap_lock = threading.RLock()
        self._lock = threading.RLock()

    def _write_marker(self) -> None:
        if not self.marker_path or not self.hwnd:
            return
        try:
            with open(self.marker_path, 'w', encoding='utf-8') as f:
                json.dump({'ghost': True, 'hwnd': self.hwnd, 'class': self.api.class_name(self.hwnd), 'added': self.added}, f)
        except Exception:
            return

    def _clear_marker(self) -> None:
        if self.marker_path:
            try:
                os.remove(self.marker_path)
                return
            except OSError:
                pass

    def recover(self) -> bool:
        if not self.marker_path or not os.path.isfile(self.marker_path):
            return False
        try:
            with open(self.marker_path, 'r', encoding='utf-8') as f:
                m = json.load(f)
            h = int(m.get('hwnd', 0))
            if m.get('ghost') is True and h and self.api.is_window(h) and self.api.class_name(h) == m.get('class'):
                self.api.set_alpha(h, 255)
                self.api.set_exstyle(h, self.api.get_exstyle(h) & ~int(m.get('added') or 0))
        except Exception:
            pass
        self._clear_marker()
        return True

    def wanted(self) -> bool:
        return not self.disabled

    def ensure(self) -> bool:
        if not self.cap_lock.acquire(blocking=False):
            return self.ghosted
        try:
            try:
                with self._lock:
                    pass
            finally:
                pass
        finally:
            self.cap_lock.release()
        return self._ensure()

    def _ensure(self) -> bool:
        try:
            h = self._game()
            if not self.wanted() or not h or not self.api.is_window(h):
                if self.hwnd and (not h or not self.api.is_window(h)):
                    self._forget()
                return False
            if self.hwnd and self.hwnd != h:
                self.restore()
            if self.ghosted:
                ex = self.api.get_exstyle(h)
                if not ex & WS_EX_LAYERED:
                    self.api.set_exstyle(h, ex | WS_EX_LAYERED)
                self.api.set_alpha(h, 255)
                return True
            if self.failed and self._clock() < self._retry_at:
                return False
            orig = self.api.get_exstyle(h)
            self.hwnd, self.orig, self.added = h, orig, GHOST_BITS & ~orig
            self._write_marker()
            if self.api.set_exstyle(h, orig | WS_EX_LAYERED) and self.api.set_alpha(h, 255):
                self.ghosted, self.hidden, self.failed = True, False, ''
                self.api.to_bottom(h)
                return True
            self.failed, self._retry_at = 'denied', self._clock() + RETRY_AFTER_FAIL_S
            self.restore()
        except Exception:
            self.failed, self._retry_at = 'error', self._clock() + RETRY_AFTER_FAIL_S
            self.restore()
        return False

    def hide(self, click: bool) -> bool:
        with self._lock:
            try:
                h = self.hwnd
                if not self.ghosted or not h or not self.api.is_window(h):
                    return False
            except Exception:
                return False
            try:
                ex = self.api.get_exstyle(h) | WS_EX_LAYERED
                ex = ex & ~WS_EX_TRANSPARENT if click else ex | WS_EX_TRANSPARENT
                if ex != self.api.get_exstyle(h):
                    self.api.set_exstyle(h, ex)
                self.api.set_alpha(h, GHOST_ALPHA)
                self.hidden = True
                self.api.flush()
            except Exception:
                return False
        return True

    def sink(self) -> None:
        with self._lock:
            h = self.hwnd
            if not self.ghosted or not h:
                return
            try:
                if self.api.is_window(h):
                    self.api.to_bottom(h)
                    self.api.flush()
                return
            except Exception:
                pass

    def rest(self) -> None:
        with self._lock:
            h = self.hwnd
            self.hidden = False
            if not self.ghosted or not h:
                return
            try:
                if self.api.is_window(h):
                    self.api.flush()
                    ex = self.api.get_exstyle(h)
                    if ex & WS_EX_TRANSPARENT and WS_EX_TRANSPARENT & self.added:
                        self.api.set_exstyle(h, ex & ~WS_EX_TRANSPARENT)
                    self.api.set_alpha(h, 255)
                return
            except Exception:
                pass

    def _forget(self) -> None:
        self.hwnd, self.orig, self.added = None, 0, 0
        self.ghosted = self.hidden = False
        self._clear_marker()

    def restore(self) -> None:
        got = self.cap_lock.acquire(timeout=2)
        try:
            with self._lock:
                h, added = self.hwnd, self.added
                was = self.ghosted or bool(added)
                self._forget()
                if h and was and self.api.is_window(h):
                    self.api.set_alpha(h, 255)
                    self.api.set_exstyle(h, self.api.get_exstyle(h) & ~added)
        except Exception:
            pass
        finally:
            if got:
                self.cap_lock.release()

    def disable(self, reason: str) -> None:
        self.disabled = reason
        self.restore()

    def reset(self) -> None:
        with self._lock:
            self.disabled, self.failed, self._retry_at = '', '', 0.0

    def watch(self, stop: threading.Event, wanted: Callable[[], bool], interval: float=0.5) -> None:
        while not stop.wait(interval):
            try:
                if wanted():
                    self.ensure()
                elif self.hwnd:
                    self.restore()
            except Exception:
                pass


def recover_at_launch(marker_path: str) -> bool:
    try:
        return GhostWindow(marker_path=marker_path).recover()
    except Exception:
        return False

