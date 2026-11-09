import random
import threading
import time
from typing import (Callable, List, Optional, Tuple)

class SpacePresser:
    def __init__(self, settings, active: Callable[[], bool], press: Callable[[], None], clock: Callable[[], float]=time.monotonic, rng: Optional[random.Random]=None, tick: float=0.05, defer: Optional[Callable[[], bool]]=None):
        self.s = settings
        self.active = active
        self._press = press
        self._clock = clock
        self._rng = rng or random.Random()
        self.tick = tick
        self._defer = defer
        self._times = []
        self._end = 0.0
        self._running = False
        self.presses = 0

    def _enabled(self) -> bool:
        s = self.s
        return bool(s.space_enabled) and int(s.space_count) >= 1 and float(s.space_seconds) > 0

    def _window(self, start: float) -> Tuple[List[float], float]:
        n = max(1, int(self.s.space_count))
        length = max(0.5, float(self.s.space_seconds))
        slot = length / n
        return [start + k * slot + self._rng.uniform(0.05, 0.95) * slot for k in range(n)], start + length

    def poll(self) -> int:
        if not (self._enabled() and self.active()):
            self._running, self._times = False, []
            return 0
        now = self._clock()
        if not self._running:
            self._running = True
            self._times, self._end = self._window(now)
        elif not self._times:
            if now >= self._end:
                self._times, self._end = self._window(now)
        made = 0
        if self._defer and self._defer():
            return made
        while self._times and now >= self._times[0]:
            self._times.pop(0)
            if self.active():
                self._press()
                self.presses += 1
                made += 1
        return made

    def run(self, stop: threading.Event, log: Callable[[str], None]=(lambda _m: None)) -> None:
        while not stop.wait(self.tick):
            try:
                self.poll()
            except Exception as e:
                log(f'space error: {e}')


