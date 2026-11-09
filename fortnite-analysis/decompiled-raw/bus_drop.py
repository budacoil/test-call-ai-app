import os
import time
from typing import (Callable, List, Optional, Tuple)
import cv2
import numpy as np
import config
GW, GH = 20, 28
MIN_SCORE = 0.55
MIN_MARGIN = 0.06
LOST_S = 20.0
CONFIRM = 2
WINDOW_S = 12.0
SAMPLE_LIMIT = 30
NPZ_NAME = 'countdown_digits.npz'

def find_plate(frame: np.ndarray):
    try:
        h, w = frame.shape[:2]
        x0, x1, y1 = int(0.45 * w), int(0.75 * w), int(0.25 * h)
        reg = frame[:y1, x0:x1]
        g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
        sat = reg.max(axis=2).astype(np.int16) - reg.min(axis=2).astype(np.int16)
        white = cv2.morphologyEx(((g >= 205) & (sat <= 60)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
        best = None
        for i in range(1, n):
            x, y, bw, bh, area = (int(v) for v in st[i])
            if 0.022 * h <= bh <= 0.07 * h:
                if not 1.0 <= bw / bh <= 2.6:
                    continue
            inside = (lab[y:y + bh, x:x + bw] == i).astype(np.uint8)
            cnts, _ = cv2.findContours(inside, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            hull = np.zeros_like(inside)
            cv2.fillPoly(hull, [cv2.convexHull(max(cnts, key=cv2.contourArea))], 1)
            core = cv2.erode(hull, np.ones((7, 7), np.uint8))
            dark = ((g[y:y + bh, x:x + bw] < 120) & (inside == 0)).astype(np.uint8) & core
            share = dark.sum() / float(max(1, hull.sum()))
            if 0.1 <= share:
                if not share <= 0.5:
                    continue
            else:
                bw / bh
                continue
            if best is not None and not area > best[4]:
                continue
            best = x + x0, y, bw, bh, area, dark
            continue
        if best is None:
            return
        return best[0], best[1], best[2], best[3], best[5]
    except Exception:
        return

def split_digits(dark: np.ndarray) -> List[np.ndarray]:
    m = dark.astype(np.float32)
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    big = max((int(st[i][4]) for i in range(1, n)), default=0)
    if big < 12:
        return []
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i][4] >= max(12, 0.12 * big):
            keep[lab == i] = 1.0
    best_k, best = 0.0, -1.0
    for k in np.arange(-0.5, 0.51, 0.05):
        col = _shear(keep, float(k)).sum(axis=0)
        sc = float((col ** 2).sum())
        if sc > best:
            best_k, best = float(k), sc
    sh = _shear(keep, best_k) > 0.5
    ys, xs = np.nonzero(sh)
    if len(xs) < 12:
        return []
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    sh = sh[y0:y1, x0:x1].astype(np.float32)
    hgt, wid = sh.shape
    if wid / float(hgt) < 0.8:
        return [sh]
    cols = sh.sum(axis=0)
    lo, hi = int(0.3 * wid), int(0.7 * wid) + 1
    c = lo + int(np.argmin(cols[lo:hi] + 0.01 * np.abs(np.arange(lo, hi) - wid / 2.0)))
    return [sh[:, :c], sh[:, c:]]

def _crop(m: np.ndarray) -> Optional[np.ndarray]:
    ys, xs = np.nonzero(m > 0.5)
    if len(xs) < 5:
        return
    return cv2.resize(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32), (GW, GH), interpolation=cv2.INTER_AREA)

def _shear(m: np.ndarray, k: float) -> np.ndarray:
    hgt, wid = m.shape
    mat = np.float32([[1, k, -0.5 * hgt * k], [0, 1, 0]])
    return cv2.warpAffine(m.astype(np.float32), mat, (wid + int(abs(k) * hgt) + 4, hgt), flags=cv2.INTER_LINEAR)

def _unit(g: np.ndarray) -> np.ndarray:
    v = g - g.mean()
    return v / (np.linalg.norm(v) + 1e-6)

def prepare_template(mask: np.ndarray) -> Optional[np.ndarray]:
    return _crop(mask)

_TEMPLATES: Optional[dict] = None

def load_templates(path: str='') -> dict:
    global _TEMPLATES
    if _TEMPLATES is not None and not path:
        return _TEMPLATES
    out = {}
    try:
        cands = [path] if path else [os.path.join(config.assets_dir(), NPZ_NAME), os.path.join(config.bundled_assets_dir(), NPZ_NAME)]
        for p in cands:
            if not p:
                continue
            if not os.path.isfile(p):
                continue
            data = np.load(p)
            for ch in '0123456789':
                if f'd{ch}' in data:
                    out[ch] = [_unit(t.astype(np.float32)) for t in data[f'd{ch}']]
            break
    except Exception:
        out = {}
    if not path:
        _TEMPLATES = out
    return out

def classify(raw: np.ndarray, templates: dict) -> Optional[Tuple[str, float, float]]:
    scores = {ch: -1.0 for ch in templates}
    for k in np.arange(-0.15, 0.16, 0.05):
        g = _crop(_shear(raw, float(k)))
        if g is not None:
            v = _unit(g)
            for ch, lst in templates.items():
                for t in lst:
                    s = float((t * v).sum())
                    if s > scores[ch]:
                        scores[ch] = s
    ranked = sorted(scores.items(), key=(lambda kv: -kv[1]))
    if len(ranked) < 2:
        return
    return ranked[0][0], ranked[0][1], ranked[0][1] - ranked[1][1]

def read_countdown(frame: np.ndarray, templates: Optional[dict]=None) -> Tuple[bool, Optional[int], float, Optional[np.ndarray]]:
    plate = find_plate(frame)
    if plate is None:
        return (False, None, 0.0, None)
    x, y, w, h, dark = plate
    crop = frame[y:y + h, x:x + w]
    templates = templates if templates is not None else load_templates()
    try:
        masks = split_digits(dark)
        if templates:
            if not 1 <= len(masks) <= 2:
                return True, None, 0.0, crop
        digits, conf = '', 9.0
        for m in masks:
            c = classify(m, templates)
            if c is None or c[1] < MIN_SCORE or c[2] < MIN_MARGIN:
                return len(masks)
            digits += c[0]
            conf = min(conf, c[1])
        return True, int(digits), conf, crop
    except Exception:
        return True, None, 0.0, crop

class BusDrop:
    def __init__(self, settings, clock: Callable[[], float]=time.monotonic, log: Callable[[str], None]=(lambda _m: None), templates: Optional[dict]=None, sample_dir: str=''):
        self.s = settings
        self._clock = clock
        self.log = log
        self._templates = templates
        self._reads = []
        self._last_seen = -1000000000.0
        self._fired = False
        self._samples = 0
        self._sample_dir = sample_dir or os.path.join(config.base_dir(), 'bus_samples')
        self.last_value = None

    def _window(self) -> Tuple[int, int]:
        lo, hi = int(getattr(self.s, 'bus_drop_min', 15)), int(getattr(self.s, 'bus_drop_max', 25))
        return min(lo, hi), max(lo, hi)

    def estimate(self, now: float) -> Tuple[Optional[float], int]:
        reads = [(t, v) for t, v in self._reads if now - t <= WINDOW_S]
        if not reads:
            return (None, 0)
        anchors = [v + t for t, v in reads]
        best = []
        for a in anchors:
            grp = [x for x in anchors if abs(x - a) <= 1.0]
            if not len(grp) > len(best):
                if len(grp) != len(best):
                    continue
                if not a > (best[0] if best else -1e18):
                    continue
            best = grp
        if len(best) < CONFIRM:
            return None, len(best)
        best.sort()
        return best[len(best) // 2] - now, len(best)

    def observe(self, frame: np.ndarray) -> bool:
        try:
            if not getattr(self.s, 'bus_drop_enabled', False):
                return False
            now = self._clock()
            seen, value, conf, crop = read_countdown(frame, self._templates)
            if not seen:
                if now - self._last_seen > LOST_S:
                    self._reads, self._fired = [], False
                return False
            if now - self._last_seen > LOST_S:
                self._reads, self._fired = [], False
            self._last_seen = now
            if value is None:
                self._save_sample(crop)
                return False
            self.last_value = value
            self._reads.append((now, value))
        except Exception:
            return False
        try:
            self._reads = [(t, v) for t, v in self._reads if now - t <= WINDOW_S]
            if self._fired:
                return False
            est, agree = self.estimate(now)
            lo, hi = self._window()
            self.log(f'[bus] countdown {value} (conf {conf:.2f}, {agree} agree, jump at {lo}-{hi})')
            if est is not None and est <= hi:
                self._fired = True
                return True
            return False
        except Exception:
            return False

    def _save_sample(self, crop) -> None:
        try:
            if crop is None or self._samples >= SAMPLE_LIMIT:
                return
            os.makedirs(self._sample_dir, exist_ok=True)
            ok, buf = cv2.imencode('.png', cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
            if ok:
                buf.tofile(os.path.join(self._sample_dir, f'plate_{int(time.time())}_{self._samples}.png'))
                self._samples += 1
                return
        except Exception:
            pass


