import time
from dataclasses import replace
from typing import (Callable, Dict, Optional, Tuple)
from vision import (COLOUR_CHECKED, Plate, aim_point, colour_matches, find_plate, find_template)
STUCK_S = 30.0
BAND = 0.1
MIN_SCORE = 0.68
SAME_PX = 14
NEED_SEEN = 3
JUDGE_AFTER_S = 3.0
TRIAL_WINDOW_S = 12.0
COOLDOWN_S = 300.0

class AutoCalibrator:
    def __init__(self, settings, clock: Callable[[], float]=time.monotonic, log: Optional[Callable[[str], None]]=None):
        self.s = settings
        self._clock = clock
        self.log = log or (lambda _m: None)
        self.adapted = {}
        self._state = None
        self._since = clock()
        self._seen = ('', (0, 0), 0)
        self.trial = None
        self._cool = {}

    def threshold_for(self, key: str, base: float) -> float:
        v = self.adapted.get(key)
        if v is not None:
            return min(base, v)
        return base

    def plate(self, key: str, plate: Plate) -> Plate:
        v = self.adapted.get(key)
        if v is not None and v < plate.threshold:
            return replace(plate, threshold=v)
        return plate

    def check(self, state) -> None:
        if state != self._state:
            self._state, self._since = state, self._clock()
            self._seen = ('', (0, 0), 0)

    def judge(self, visible: Callable[[str, float, Tuple[int, int]], bool]) -> Optional[Tuple[str, dict]]:
        t = self.trial
        if t is None:
            return
        try:
            now = self._clock()
            dt = now - t['t']
            if dt < JUDGE_AFTER_S:
                return
            if not visible(t['key'], t['thr'], t['pos']):
                self.adapted[t['key']] = t['thr']
                self.trial = None
                self.log(f'[auto-calibrate] {t['key']} threshold adapted to {t['thr']:.2f}')
                return 'ok', t
            if dt >= TRIAL_WINDOW_S:
                self._cool[t['key']] = now + COOLDOWN_S
                self.trial = None
                self.log(f'[auto-calibrate] {t['key']} test click did not advance; paused for {int(COOLDOWN_S // 60)} min')
                return 'fail', t
        except Exception:
            self.trial = None

    def attempt(self, state, frame, key: str, tpl, score: float, base: float, ox: int, oy: int, click: Callable[[int, int], bool], scales, meta: Optional[dict]=None) -> bool:
        try:
            if not getattr(self.s, 'auto_calibrate', False) or tpl is None or self.trial is not None:
                return False
            now = self._clock()
            if now < self._cool.get(key, 0.0) or now - self._since < STUCK_S:
                return False
            lo = max(MIN_SCORE, base - BAND)
            if not lo <= score < base:
                self._seen = ('', (0, 0), 0)
                return False
            thr = max(MIN_SCORE, round(score - 0.02, 2))
            if isinstance(tpl, Plate):
                m, _ = find_plate(frame, replace(tpl, threshold=thr), scales)
            else:
                m, _ = find_template(frame, tpl, thr, scales)
            if m:
                if key in COLOUR_CHECKED and not colour_matches(frame, tpl, m):
                    return False
            pos = int(m[0]), int(m[1])
            k, p, n = self._seen
            same = k == key and abs(p[0] - pos[0]) <= SAME_PX and abs(p[1] - pos[1]) <= SAME_PX
            self._seen = key, pos, n + 1 if same else 1
            if self._seen[2] < NEED_SEEN:
                return False
            self._seen = ('', (0, 0), 0)
            ax, ay = aim_point(key, tpl, m)
            if not click(ax + ox, ay + oy):
                return False
            self.trial = {'key': key, 'thr': thr, 'pos': pos, 'state': state, 't': now, **(meta or {})}
            self.log(f'[auto-calibrate] {key} score {score:.2f} < {base:.2f} for {int(now - self._since)}s: test click at a lowered threshold ({thr:.2f})')
            return True
        except Exception:
            return False


def still_visible(frame, tpl, thr: float, pos: Tuple[int, int], scales) -> bool:
    if tpl is None:
        return False
    if isinstance(tpl, Plate):
        m, _ = find_plate(frame, replace(tpl, threshold=thr), scales)
    else:
        m, _ = find_template(frame, tpl, thr, scales)
    return bool(m) and abs(m[0] - pos[0]) <= 3 * SAME_PX and abs(m[1] - pos[1]) <= 3 * SAME_PX

