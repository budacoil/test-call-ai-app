import contextlib
import random
import time
from typing import Callable, Optional
import humanizer
MOUSEEVENTF_MOVE = 1

def _mouse_event_move(dx: int, dy: int) -> None:
    import ctypes
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)

def move_camera_smooth(dx: int, dy: int, duration_ms: int, mover: Optional[Callable[[int, int], None]]=None, sleeper=time.sleep, rng: Optional[random.Random]=None) -> int:
    mover = mover or _mouse_event_move
    steps = humanizer.camera_steps(int(dx), int(dy), int(duration_ms), rng or random.Random())
    for sx, sy, delay in steps:
        if sx or sy:
            mover(sx, sy)
        sleeper(delay)
    return len(steps)

def _cursor_pos():
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y

class Controller:
    def __init__(self, settings, clicker: Optional[Callable[[int, int], None]]=None, sleeper=time.sleep, clock=time.monotonic, presser: Optional[Callable[[str], None]]=None, focuser: Optional[Callable[[], object]]=None, swapper: Optional[Callable[..., object]]=None, poster: Optional[Callable[[str], bool]]=None, mover: Optional[Callable[[int, int], None]]=None, swinger: Optional[Callable[[int, int, float], None]]=None, cursor: Optional[Callable[[], object]]=None, rng: Optional[random.Random]=None, away: Optional[Callable[[], bool]]=None):
        self.s = settings
        self._clicker = clicker or self._default_click
        self._presser = presser or self._default_press
        self._focuser = focuser
        self._swapper = swapper
        self._poster = poster
        self._mover = mover
        self._swinger = swinger or self._default_swing
        self._cursor = cursor or _cursor_pos
        self._rng = rng or random.Random()
        self._away = away
        self._sleep = sleeper
        self._clock = clock
        self._last_click = -1000000000.0

    def _background(self) -> bool:
        return bool(self._swapper and getattr(self.s, 'background_mode', False))

    def _input_context(self, kind: str='key', point=None):
        if self._background():
            return self._swapper(kind, point)
        return contextlib.nullcontext()

    def _humanize(self) -> bool:
        return bool(getattr(self.s, 'humanizer_enabled', False))

    def _default_click(self, x: int, y: int) -> None:
        import pydirectinput
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.0
        if self._humanize():
            r = self._rng
            start = x - r.randint(8, 16), y - r.randint(4, 8)
            bg = self._background()
            n = 2 if bg else r.randint(3, 6)
            total = 0.015 if bg else r.uniform(0.015, 0.04)
            pydirectinput.moveTo(*start)
            for px, py in humanizer.bezier_points(start, (x, y), n, r):
                pydirectinput.moveTo(px, py)
                time.sleep(total / n)
            time.sleep(r.uniform(0.02, 0.05) if bg else r.uniform(0.06, 0.12))
            pydirectinput.mouseDown(button='left')
            time.sleep(humanizer.click_hold(r))
            pydirectinput.mouseUp(button='left')
            return
        pydirectinput.moveTo(x - random.randint(8, 16), y - random.randint(4, 8))
        time.sleep(random.uniform(0.04, 0.08))
        pydirectinput.moveTo(x, y)
        time.sleep(random.uniform(0.1, 0.2))
        pydirectinput.mouseDown(button='left')
        time.sleep(random.uniform(0.06, 0.12))
        pydirectinput.mouseUp(button='left')

    @staticmethod
    def _default_swing(x: int, y: int, hold: float) -> None:
        import pydirectinput
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.0
        pydirectinput.moveTo(x, y)
        pydirectinput.mouseDown(button='left')
        time.sleep(hold)
        pydirectinput.mouseUp(button='left')

    @staticmethod
    def _default_press(key: str) -> None:
        import pydirectinput
        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.0
        pydirectinput.keyDown(key)
        time.sleep(random.uniform(0.06, 0.12))
        pydirectinput.keyUp(key)

    def press(self, key: str) -> None:
        self._sleep(random.uniform(self.s.delay_min, self.s.delay_max))
        if self._background() and self._poster and getattr(self.s, 'background_post_keys', False) and self._poster(key):
            return
        if self._focuser and not self._background():
            self._focuser()
        with self._input_context('key'):
            self._presser(key)

    def ready(self) -> bool:
        return self._clock() - self._last_click >= self.s.click_cooldown

    def click(self, x: int, y: int) -> bool:
        if not self.ready():
            return False
        j = self.s.jitter_px
        if self._humanize() and j > 0:
            tx, ty = x + humanizer.gauss_offset(self._rng), y + humanizer.gauss_offset(self._rng)
        else:
            tx, ty = x + random.randint(-j, j), y + random.randint(-j, j)
        self._sleep(random.uniform(self.s.delay_min, self.s.delay_max))
        with self._input_context('click', (tx, ty)) as ctx:
            if getattr(ctx, 'click_blocked', False):
                return False
            self._clicker(tx, ty)
        self._last_click = self._clock()
        return True

    def user_away(self) -> bool:
        try:
            return bool(self._background() and self._away and self._away())
        except Exception:
            return False

    def look(self, dx: int, dy: int, duration_ms: int, force: bool=False) -> None:
        if self.user_away() and not force:
            return
        if self._focuser and not self._background():
            self._focuser()
        with self._input_context('key'):
            move_camera_smooth(dx, dy, duration_ms, self._mover, self._sleep, self._rng)

    def swing(self) -> bool:
        if self.user_away():
            return False
        pos = self._cursor()
        if not pos:
            return False
        tx, ty = pos[0] + humanizer.gauss_offset(self._rng), pos[1] + humanizer.gauss_offset(self._rng)
        if self._focuser and not self._background():
            self._focuser()
        with self._input_context('click', (tx, ty)) as ctx:
            if getattr(ctx, 'click_blocked', False):
                return False
            self._swinger(tx, ty, self._rng.uniform(0.06, 0.12))
        return True


