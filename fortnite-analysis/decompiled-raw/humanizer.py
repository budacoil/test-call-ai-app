import math
import random
import time
from typing import (Callable, Optional, Tuple)
LO, HI = 0.65, 1.45
SIDE_TAP_CHANCE = 0.2
SIDE_TAP_S = (0.2, 0.5)
MIN_HOLD_S = 0.3
BREAK_EVERY_MIN = (90.0, 120.0)
BREAK_LENGTH_S = (120.0, 240.0)
LOBBY_STATES = ('SEARCHING_PLAY', 'B:LOBBY')
PATTERNS = (('A', 50), ('B', 20), ('C', 15), ('D', 15))
LOOK_H, LOOK_V = 180, 35
PITCH_LIMIT = 40
CLICK_SIGMA, CLICK_CLAMP = 4.0, 12
CLICK_HOLD_S = (0.055, 0.135)
SESSION_PERIOD_MIN = (15.0, 30.0)
SIDE_KEYS = {'w': ('a', 'd'), 's': ('a', 'd'), 'a': ('w', 's'), 'd': ('w', 's')}

def gauss_offset(rng: random.Random, sigma: float=CLICK_SIGMA, clamp: int=CLICK_CLAMP) -> int:
    return int(round(max(-clamp, min(clamp, rng.gauss(0.0, sigma)))))

def click_hold(rng: random.Random, lo: float=CLICK_HOLD_S[0], hi: float=CLICK_HOLD_S[1]) -> float:
    mu = (math.log(lo) + math.log(hi)) / 2.0
    sigma = (math.log(hi) - math.log(lo)) / 4.0
    return max(lo, min(hi, math.exp(rng.gauss(mu, sigma))))

def bezier_points(p0, p1, n: int, rng: random.Random):
    (x0, y0), (x1, y1) = p0, p1
    cx = (x0 + x1) / 2.0 + rng.uniform(-6, 6)
    cy = (y0 + y1) / 2.0 + rng.uniform(-6, 6)
    pts = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        pts.append((int(round(a * x0 + b * cx + c * x1)), int(round(a * y0 + b * cy + c * y1))))
    pts[-1] = int(x1), int(y1)
    return pts

def _ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)

def camera_steps(dx: int, dy: int, duration_ms: int, rng: random.Random):
    n = rng.randint(10, 25)
    total = max(0.0, duration_ms / 1000.0)
    out, px, py, done_x, done_y = [], 0.0, 0.0, 0, 0
    for i in range(1, n + 1):
        e = _ease(i / n)
        tx, ty = dx * e, dy * e
        sx, sy = int(round(tx - px)), int(round(ty - py))
        px, py = tx, ty
        if i < n:
            sx += rng.choice((-2, -1, 0, 1, 2)) if sx or dx else 0
            sy += rng.choice((-1, 0, 1)) if sy or dy else 0
            sx, sy = sx if abs(dx) > 2 else 0, sy if abs(dy) > 2 else 0
        else:
            sx, sy = dx - done_x, dy - done_y
        done_x, done_y = done_x + sx, done_y + sy
        out.append((sx, sy, total / n * (1.4 - 0.8 * math.sin(math.pi * i / n))))
        continue
    k = sum((d for *_, d in out))
    return [(sx, sy, d * total / k if k > 0 else 0.0) for sx, sy, d in out]

class PitchBalance:
    def __init__(self, rng: Optional[random.Random]=None):
        self._rng = rng or random.Random()
        self.pitch = 0

    def next_look(self) -> Tuple[int, int, int]:
        r = self._rng
        dx = r.randint(-LOOK_H, LOOK_H)
        dy = r.randint(-LOOK_V, LOOK_V)
        if abs(self.pitch) > PITCH_LIMIT // 4:
            back = -int(math.copysign(min(abs(self.pitch), LOOK_V), self.pitch))
            dy = int(round(0.6 * back + 0.4 * dy))
        if abs(self.pitch + dy) > PITCH_LIMIT:
            dy = -self.pitch
        dy = max(-LOOK_V, min(LOOK_V, dy))
        self.pitch += dy
        return dx, dy, r.randint(180, 520)


def pick_pattern(rng: random.Random, relaxed: bool=False) -> str:
    w = dict(PATTERNS)
    if relaxed:
        w['A'], w['D'] = w['A'] - 10, w['D'] + 10
    x = rng.uniform(0, sum(w.values()))
    for name, weight in w.items():
        x -= weight
        if not x < 0:
            continue
        return name
    return 'A'

class SessionDrift:
    def __init__(self, clock: Callable[[], float]=time.monotonic, rng: Optional[random.Random]=None):
        self._clock = clock
        self._rng = rng or random.Random()
        self._t0 = clock()
        self._period = self._rng.uniform(*SESSION_PERIOD_MIN) * 60.0
        self._phase = self._rng.uniform(0.0, 2 * math.pi)
        self._noise = PinkNoise(self._rng)

    def focus(self) -> float:
        wave = math.sin(2 * math.pi * (self._clock() - self._t0) / self._period + self._phase)
        return max(0.0, min(1.0, 0.5 + 0.38 * wave + 0.12 * self._noise.next()))

    def relaxed(self) -> bool:
        return self.focus() < 0.3

    def factor(self) -> float:
        return 1.0 + 0.3 * (1.0 - self.focus())


class PinkNoise:
    def __init__(self, rng: Optional[random.Random]=None, octaves: int=6):
        self._rng = rng or random.Random()
        self._rows = [self._rng.uniform(-1, 1) for _ in range(octaves)]
        self._n = 0

    def next(self) -> float:
        self._n += 1
        n, i = self._n, 0
        while n % 2 == 0 and i < len(self._rows) - 1:
            n //= 2
            i += 1
        self._rows[i] = self._rng.uniform(-1, 1)
        v = sum(self._rows) / (len(self._rows) * 0.5)
        return max(-1.0, min(1.0, v))


class Humanizer:
    def __init__(self, rng: Optional[random.Random]=None):
        self._rng = rng or random.Random()
        self._interval = PinkNoise(self._rng)
        self._hold = PinkNoise(self._rng)
        self.drift = SessionDrift()
        self.pitch = PitchBalance()

    @staticmethod
    def _factor(v: float) -> float:
        u = (v + 1.0) / 2.0
        return math.exp(math.log(LO) + (math.log(HI) - math.log(LO)) * u)

    def interval(self, base: float) -> float:
        return base * self._factor(self._interval.next())

    def hold(self, base: float) -> float:
        return max(MIN_HOLD_S, base * self._factor(self._hold.next()))

    def pattern(self) -> str:
        return pick_pattern(self._rng, self.drift.relaxed())

    def session_factor(self) -> float:
        return self.drift.factor()

    def side_tap(self, key: str, keys, hold: float) -> Optional[Tuple[float, str, float]]:
        if self._rng.random() >= SIDE_TAP_CHANCE:
            return
        options = [k for k in SIDE_KEYS.get(key, ()) if k in keys]
        if not options:
            return
        tap = self._rng.uniform(*SIDE_TAP_S)
        if hold < tap + 0.2:
            return
        lead = self._rng.uniform(0.1, hold - tap - 0.1)
        return lead, self._rng.choice(options), tap


class CoffeeBreak:
    def __init__(self, settings, clock: Callable[[], float]=time.monotonic, rng: Optional[random.Random]=None):
        self.s = settings
        self._clock = clock
        self._rng = rng or random.Random()
        self._t0 = clock()
        self._due = self._rng.uniform(*BREAK_EVERY_MIN) * 60.0

    def check(self, state_value: str) -> float:
        try:
            if not getattr(self.s, 'coffee_break_enabled', False) or state_value not in LOBBY_STATES:
                return 0.0
            now = self._clock()
            if now - self._t0 < self._due:
                return 0.0
            length = self._rng.uniform(*BREAK_LENGTH_S)
            self._t0 = now + length
            self._due = self._rng.uniform(*BREAK_EVERY_MIN) * 60.0
            return length
        except Exception:
            return 0.0


