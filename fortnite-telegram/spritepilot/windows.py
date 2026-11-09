"""Windows game-window access. Imports cleanly elsewhere for tests and previews."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

import cv2
import numpy as np


class GameUnavailable(RuntimeError):
    pass


class WindowsGame:
    def __init__(self):
        self.hwnd = 0
        self.origin = (0, 0)
        self.shape = (0, 0)
        self.last_click = -1e9
        self.held = set()
        self.settings = None
        if sys.platform == "win32":
            self.user = ctypes.WinDLL("user32", use_last_error=True)
            self.user.GetForegroundWindow.restype = wintypes.HWND
            self.user.IsWindowVisible.argtypes = [wintypes.HWND]
            self.user.IsIconic.argtypes = [wintypes.HWND]
            self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self.user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            try:
                self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                pass
        else:
            self.user = None

    def _find(self):
        if not self.user:
            raise GameUnavailable("Захват и управление игрой доступны на Windows")
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _):
            title = ctypes.create_unicode_buffer(512)
            kind = ctypes.create_unicode_buffer(256)
            self.user.GetWindowTextW(hwnd, title, 512)
            self.user.GetClassNameW(hwnd, kind, 256)
            if self.user.IsWindowVisible(hwnd) and kind.value == "UnrealWindow" and "fortnite" in title.value.lower():
                found.append(hwnd)
            return True
        self.user.EnumWindows(proto(callback), 0)
        self.hwnd = found[0] if found else 0
        if not self.hwnd:
            raise GameUnavailable("Откройте Fortnite: окно игры не найдено")
        if self.user.IsIconic(self.hwnd):
            raise GameUnavailable("Разверните окно Fortnite")
        if self.user.GetForegroundWindow() != self.hwnd:
            raise GameUnavailable("Откройте окно Fortnite на переднем плане")
        return self.hwnd

    def capture(self):
        hwnd = self._find()
        rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
        if not self.user.GetClientRect(hwnd, ctypes.byref(rect)) or not self.user.ClientToScreen(hwnd, ctypes.byref(point)):
            raise GameUnavailable("Не удалось определить область игры")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 100 or height < 100:
            raise GameUnavailable("Окно игры слишком мало")
        import mss
        with mss.mss() as screen:
            raw = np.asarray(screen.grab(dict(left=point.x, top=point.y, width=width, height=height)))
        # Check again: never send an unrelated foreground window after a switch.
        if self.user.GetForegroundWindow() != hwnd:
            raise GameUnavailable("Окно игры потеряло фокус")
        self.origin, self.shape = (point.x, point.y), (height, width)
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR), point.x, point.y

    def _input(self):
        self._find()
        import pydirectinput
        pydirectinput.PAUSE = 0
        return pydirectinput

    def ready(self):
        return time.monotonic() - self.last_click >= (self.settings.click_cooldown if self.settings else 3)

    def click(self, x, y, force=False):
        if not force and not self.ready():
            return False
        height, width = self.shape
        if not (self.origin[0] <= x < self.origin[0]+width and self.origin[1] <= y < self.origin[1]+height):
            raise ValueError("Клик вне окна игры отклонён")
        control = self._input()
        control.click(int(x), int(y))
        self.last_click = time.monotonic()
        return True

    def press(self, key):
        self._input().press(key)

    def hold(self, key):
        self._input().keyDown(key)
        self.held.add(key)

    def release_all(self):
        if self.held and sys.platform == "win32":
            import pydirectinput
            for key in tuple(self.held):
                pydirectinput.keyUp(key)
                self.held.discard(key)


def enable_dpi():
    if sys.platform == "win32":
        try:
            ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
