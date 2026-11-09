import random
import time

import pydirectinput

from focus import ensure_game_foreground


class AntiAfk:
    def __init__(self, settings, active):
        self.s = settings
        self.active = active

    def press_once(self, stop):
        key = random.choice(self.s.afk_keys)
        ensure_game_foreground()
        pydirectinput.keyDown(key)
        try:
            stop.wait(self.s.afk_hold)
        finally:
            pydirectinput.keyUp(key)
        return key

    def release_all(self):
        for k in self.s.afk_keys:
            try:
                pydirectinput.keyUp(k)
            except Exception:
                pass

    def run(self, stop, log=None):
        last = time.monotonic()
        try:
            while not stop.wait(0.2):
                now = time.monotonic()
                if not (self.s.afk_enabled and self.active()):
                    last = now
                    continue
                if now - last < self.s.afk_interval:
                    continue
                last = now
                try:
                    key = self.press_once(stop)
                    if log:
                        log(f"anti-afk: held {key.upper()} {self.s.afk_hold}s")
                except Exception as e:
                    if log:
                        log(f"anti-afk error: {e}")
        finally:
            self.release_all()
