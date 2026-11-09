import random
import time

import pydirectinput

from focus import ensure_game_foreground


class Controller:
    def __init__(self, settings):
        self.s = settings
        self._last_click = -1e9

    @staticmethod
    def _click(x, y):
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.0
        pydirectinput.moveTo(x - random.randint(8, 16), y - random.randint(4, 8))
        time.sleep(random.uniform(0.04, 0.08))
        pydirectinput.moveTo(x, y)
        time.sleep(random.uniform(0.10, 0.20))
        pydirectinput.mouseDown(button="left")
        time.sleep(random.uniform(0.06, 0.12))
        pydirectinput.mouseUp(button="left")

    @staticmethod
    def _press(key):
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.0
        pydirectinput.keyDown(key)
        time.sleep(random.uniform(0.06, 0.12))
        pydirectinput.keyUp(key)

    def press(self, key):
        time.sleep(random.uniform(self.s.delay_min, self.s.delay_max))
        ensure_game_foreground()
        self._press(key)

    def ready(self):
        return time.monotonic() - self._last_click >= self.s.click_cooldown

    def click(self, x, y):
        if not self.ready():
            return False
        j = self.s.jitter_px
        tx, ty = x + random.randint(-j, j), y + random.randint(-j, j)
        time.sleep(random.uniform(self.s.delay_min, self.s.delay_max))
        self._click(tx, ty)
        self._last_click = time.monotonic()
        return True
