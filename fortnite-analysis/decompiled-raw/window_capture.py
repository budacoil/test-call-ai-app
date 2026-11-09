import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
PW_CLIENTONLY = 1
PW_RENDERFULLCONTENT = 2
BI_RGB = 0
DIB_RGB_COLORS = 0
OK, MINIMIZED, NO_WINDOW, BLACK, ERROR, DENIED = 'ok', 'minimized', 'no_window', 'black', 'error', 'denied'
ERROR_ACCESS_DENIED = 5
FLAG_VARIANTS = PW_CLIENTONLY | PW_RENDERFULLCONTENT, PW_CLIENTONLY

@dataclass
class Capture:
    status: str
    frame: Optional[np.ndarray] = None
    origin: Tuple[int, int] = (0, 0)
    def to_screen(self, x: int, y: int) -> Tuple[int, int]:
        return self.origin[0] + int(x), self.origin[1] + int(y)


def to_screen(origin: Tuple[int, int], rel_x: int, rel_y: int) -> Tuple[int, int]:
    return origin[0] + int(rel_x), origin[1] + int(rel_y)

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]

class _BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', _BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]

class Win32Gdi:
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.g = ctypes.WinDLL('gdi32', use_last_error=True)
        h, i, b = wintypes.HANDLE, ctypes.c_int, wintypes.BOOL
        self.u.IsWindow.argtypes = [h]
        self.u.IsWindow.restype = b
        self.u.IsIconic.argtypes = [h]
        self.u.IsIconic.restype = b
        self.u.GetClientRect.argtypes = [h, ctypes.POINTER(wintypes.RECT)]
        self.u.GetClientRect.restype = b
        self.u.ClientToScreen.argtypes = [h, ctypes.POINTER(wintypes.POINT)]
        self.u.ClientToScreen.restype = b
        self.u.GetDC.argtypes = [h]
        self.u.GetDC.restype = h
        self.u.ReleaseDC.argtypes = [h, h]
        self.u.ReleaseDC.restype = i
        self.u.PrintWindow.argtypes = [h, h, wintypes.UINT]
        self.u.PrintWindow.restype = b
        self.g.CreateCompatibleDC.argtypes = [h]
        self.g.CreateCompatibleDC.restype = h
        self.g.CreateCompatibleBitmap.argtypes = [h, i, i]
        self.g.CreateCompatibleBitmap.restype = h
        self.g.SelectObject.argtypes = [h, h]
        self.g.SelectObject.restype = h
        self.g.DeleteObject.argtypes = [h]
        self.g.DeleteObject.restype = b
        self.g.DeleteDC.argtypes = [h]
        self.g.DeleteDC.restype = b
        self.g.GetDIBits.argtypes = [h, h, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        self.g.GetDIBits.restype = i

    def is_window(self, hwnd) -> bool:
        return bool(self.u.IsWindow(hwnd))

    def is_iconic(self, hwnd) -> bool:
        return bool(self.u.IsIconic(hwnd))

    def client_rect(self, hwnd) -> Optional[Tuple[int, int, int, int]]:
        rc, pt = wintypes.RECT(), wintypes.POINT(0, 0)
        if not (self.u.GetClientRect(hwnd, ctypes.byref(rc)) and self.u.ClientToScreen(hwnd, ctypes.byref(pt))):
            return
        return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top

    def get_dc(self, hwnd):
        return self.u.GetDC(hwnd)

    def release_dc(self, hwnd, hdc):
        return self.u.ReleaseDC(hwnd, hdc)

    def create_compatible_dc(self, hdc):
        return self.g.CreateCompatibleDC(hdc)

    def create_compatible_bitmap(self, hdc, w, h):
        return self.g.CreateCompatibleBitmap(hdc, w, h)

    def select_object(self, hdc, obj):
        return self.g.SelectObject(hdc, obj)

    def delete_object(self, obj):
        return self.g.DeleteObject(obj)

    def delete_dc(self, hdc):
        return self.g.DeleteDC(hdc)

    def print_window(self, hwnd, hdc, flags) -> bool:
        ctypes.set_last_error(0)
        return bool(self.u.PrintWindow(hwnd, hdc, flags))

    def last_error(self) -> int:
        return ctypes.get_last_error()

    def get_dibits(self, hdc, bitmap, w: int, h: int) -> Optional[bytes]:
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = w
        info.bmiHeader.biHeight = -h
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        buf = (ctypes.c_ubyte * (w * h * 4))()
        lines = self.g.GetDIBits(hdc, bitmap, 0, h, buf, ctypes.byref(info), DIB_RGB_COLORS)
        if lines == h:
            return bytes(buf)


class GameWindow:
    def __init__(self, finder=None, is_window=None, clock=time.monotonic, retry_s: float=1.0):
        if finder is None or is_window is None:
            import focus
            api = focus.WinApi()
            finder = finder or (lambda: focus.find_game(api))
            is_window = is_window or (lambda h: bool(api.u.IsWindow(h)))
        self._find, self._is_window, self._clock, self._retry_s = finder, is_window, clock, retry_s
        self._hwnd = None
        self._next_search = 0.0

    def hwnd(self) -> Optional[int]:
        try:
            if self._hwnd and self._is_window(self._hwnd):
                return self._hwnd
            self._hwnd = None
            now = self._clock()
            if now >= self._next_search:
                self._hwnd = self._find()
                if not self._hwnd:
                    self._next_search = now + self._retry_s
        except Exception:
            self._hwnd = None
        return self._hwnd
        return self._hwnd


class WindowCapture:
    def __init__(self, locator: Optional[GameWindow]=None, api=None, clock=time.monotonic, black_limit: int=3, black_pause_s: float=60.0):
        self.api = api or Win32Gdi()
        self.locator = locator or GameWindow()
        self._clock = clock
        self.black_limit, self.black_pause_s = black_limit, black_pause_s
        self._black = 0
        self._paused_until = 0.0
        self._denied = False
        self._last_paused_status = BLACK
        self._flags_ok = FLAG_VARIANTS[0]
        self.last_flags = None

    def _failed(self, status: str) -> Capture:
        self._black += 1
        if self._black >= self.black_limit:
            self._paused_until = self._clock() + self.black_pause_s
            self._last_paused_status = status
            self._black = 0
        return Capture(status)

    def grab(self) -> Capture:
        try:
            self._denied = False
            if self._clock() < self._paused_until:
                return Capture(self._last_paused_status)
            hwnd = self.locator.hwnd()
            if not hwnd:
                return Capture(NO_WINDOW)
            if self.api.is_iconic(hwnd):
                return Capture(MINIMIZED)
            rect = self.api.client_rect(hwnd)
            if not rect or rect[2] <= 0 or rect[3] <= 0:
                return Capture(ERROR)
            left, top, w, h = rect
            saw_black = saw_denied = False
            for flags in sorted(FLAG_VARIANTS, key=(lambda f: f != self._flags_ok)):
                self._denied = False
                frame = self._print(hwnd, w, h, flags)
                if frame is None:
                    if self._denied:
                        saw_denied = True
                        break
                    continue
                if _is_black(frame):
                    saw_black = True
                    continue
                self._black = 0
                self._flags_ok = self.last_flags = flags
                return Capture(OK, frame, (left, top))
            if saw_denied:
                return self._failed(DENIED)
            if saw_black:
                return self._failed(BLACK)
            return Capture(ERROR)
        except Exception:
            return Capture(ERROR)

    def _print(self, hwnd, w: int, h: int, flags: int=PW_CLIENTONLY | PW_RENDERFULLCONTENT) -> Optional[np.ndarray]:
        api = self.api
        hdc = memdc = bitmap = old = None
        try:
            hdc = api.get_dc(hwnd)
            if not hdc:
                if old:
                    _quiet(api.select_object, memdc, old)
                if bitmap:
                    _quiet(api.delete_object, bitmap)
                if memdc:
                    _quiet(api.delete_dc, memdc)
                if hdc:
                    _quiet(api.release_dc, hwnd, hdc)
                    return
                return
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)
        try:
            memdc = api.create_compatible_dc(hdc)
            if not memdc:
                if old:
                    _quiet(api.select_object, memdc, old)
                if bitmap:
                    _quiet(api.delete_object, bitmap)
                if memdc:
                    _quiet(api.delete_dc, memdc)
                if hdc:
                    _quiet(api.release_dc, hwnd, hdc)
                    return
                return
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)
        try:
            bitmap = api.create_compatible_bitmap(hdc, w, h)
            if not bitmap:
                if old:
                    _quiet(api.select_object, memdc, old)
                if bitmap:
                    _quiet(api.delete_object, bitmap)
                if memdc:
                    _quiet(api.delete_dc, memdc)
                if hdc:
                    _quiet(api.release_dc, hwnd, hdc)
                    return
                return
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)
        try:
            old = api.select_object(memdc, bitmap)
            ok = api.print_window(hwnd, memdc, flags)
            if not ok:
                try:
                    self._denied = getattr(api, 'last_error', (lambda: 0))() == ERROR_ACCESS_DENIED
                except Exception:
                    self._denied = False
            if old:
                api.select_object(memdc, old)
                old = None
            if not ok:
                if old:
                    _quiet(api.select_object, memdc, old)
                if bitmap:
                    _quiet(api.delete_object, bitmap)
                if memdc:
                    _quiet(api.delete_dc, memdc)
                if hdc:
                    _quiet(api.release_dc, hwnd, hdc)
                    return
                return
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)
        try:
            data = api.get_dibits(memdc, bitmap, w, h)
            if data is None or len(data) != w * h * 4:
                if old:
                    _quiet(api.select_object, memdc, old)
                if bitmap:
                    _quiet(api.delete_object, bitmap)
                if memdc:
                    _quiet(api.delete_dc, memdc)
                if hdc:
                    _quiet(api.release_dc, hwnd, hdc)
                    return
                return
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)
        try:
            return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].copy()
        finally:
            if old:
                _quiet(api.select_object, memdc, old)
            if bitmap:
                _quiet(api.delete_object, bitmap)
            if memdc:
                _quiet(api.delete_dc, memdc)
            if hdc:
                _quiet(api.release_dc, hwnd, hdc)


def _quiet(fn, *args) -> None:
    try:
        fn(*args)
        return
    except Exception:
        return

def _is_black(frame: np.ndarray) -> bool:
    return not frame[::8, ::8].any() and not frame.any()

# WARNING: Decompyle incomplete
