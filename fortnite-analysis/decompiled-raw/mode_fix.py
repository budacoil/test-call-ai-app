import time
from typing import (Callable, List, Optional, Tuple)
import cv2
import numpy as np
SOLO_RATIO = 0.72
VERIFY_EVERY_S = 900.0
OPEN_COOLDOWN_S = 25.0
MAX_OPENS = 3
OPEN_WINDOW_S = 150.0
BACKOFF_S = 600.0
MAX_TILE_CLICKS = 3
MAX_FILL_CLICKS = 3
Click = Tuple[int, int, str]

def _yellow(a: np.ndarray) -> np.ndarray:
    return ((a[(..., 0)] > 215) & (a[(..., 1)] > 215) & (a[(..., 2)] < 110)).astype(np.uint8)

def _rgb(frame_bgr: np.ndarray) -> np.ndarray:
    return frame_bgr[..., ::-1]

def find_lobby_play(frame: np.ndarray):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = 0, int(0.62 * h), int(0.32 * w), int(0.98 * h)
    m = _yellow(_rgb(frame[y0:y1, x0:x1]))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in st[i])
        if bw >= 0.09 * w:
            if 0.04 * h <= bh <= 0.09 * h:
                if 3.0 <= bw / bh <= 5.5:
                    if area >= 0.6 * bw * bh and (best is None or y > best[1]):
                        best = x, y, bw, bh
    if best is None:
        return
    return best[0] + x0, best[1] + y0, best[0] + x0 + best[2], best[1] + y0 + best[3]

def find_mode_label(frame: np.ndarray):
    try:
        play = find_lobby_play(frame)
        if play is None:
            return
        px0, py0, px1, py1 = play
        pw, ph = px1 - px0, py1 - py0
        top = max(0, py0 - int(4.5 * ph))
        strip = _rgb(frame[top:py0, px0:px1]).astype(np.int16)
        light = (strip.min(axis=2) >= 150).astype(np.float32).mean(axis=1) > 0.55
        bands, s = [], None
        for i, v in enumerate(list(light) + [False]):
            if v and s is None:
                s = i
            if v:
                continue
            if s is None:
                continue
            if bands and s - bands[-1][1] <= max(6, int(0.15 * ph)):
                bands[-1] = bands[-1][0], i
            else:
                bands.append((s, i))
            s = None
        cands = []
        for a, b in bands:
            if not 0.8 * ph <= b - a <= 1.2 * ph:
                continue
            block = strip[a:b]
            r, g, bl = (float(block[..., c].mean()) for c in range(3))
            cream = r > 215 and g > 195 and 110 <= bl <= 200 and r - bl >= 45
            if cream:
                cands.append((a, b))
        if not cands:
            return
        a, b = cands[-1]
        band = _rgb(frame[top + a:top + b, px0:px1])
        gray = cv2.cvtColor(np.ascontiguousarray(band[..., ::-1]), cv2.COLOR_BGR2GRAY)
        cols = np.nonzero((gray < 110).sum(axis=0) > 0)[0]
        if len(cols) < 3:
            return
        ratio = (cols.max() - cols.min()) / float(pw)
        return px0 + pw // 2, top + (a + b) // 2, float(ratio)
    except Exception:
        return

def find_tiles(frame: np.ndarray):
    try:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = int(0.55 * w), int(0.15 * h), w, int(0.5 * h)
        reg = _rgb(frame[y0:y1, x0:x1]).astype(np.int16)
        r, g, b = reg[(..., 0)], reg[(..., 1)], reg[(..., 2)]
        blue = (r < 50) & (g > 80) & (g < 135) & (b > 225)
        purple = (r > 80) & (r < 125) & (g > 45) & (g < 90) & (b > 200) & (b < 250)
        m = (blue | purple).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        cand = []
        for i in range(1, n):
            x, y, bw, bh, area = (int(v) for v in st[i])
            if 0.035 * h <= bh <= 0.08 * h:
                if 0.8 <= bw / bh <= 1.25:
                    if not area >= 0.7 * bw * bh:
                        continue
            cand.append((x + bw / 2.0 + x0, y + bh / 2.0 + y0, (bw + bh) / 2.0, i, blue[lab == i].mean()))
        cand.sort()
        for i in range(len(cand) - 3):
            row = cand[i:i + 4]
            s = sum((c[2] for c in row)) / 4.0
            pitch = [row[k + 1][0] - row[k][0] for k in range(3)]
            if not max((abs(c[1] - row[0][1]) for c in row)) <= 0.25 * s:
                continue
            if not all((1.1 * s <= p <= 1.6 * s for p in pitch)):
                continue
            if not max(pitch) - min(pitch) <= 0.15 * s:
                continue
            sel = [k for k, c in enumerate(row) if c[4] > 0.5]
            if len(sel) != 1:
                continue
            return [(int(c[0]), int(c[1])) for c in row], float(s), sel[0]
    except Exception:
        return

def fill_switch(frame: np.ndarray, tiles) -> Tuple[Optional[Tuple[int, int]], Optional[bool]]:
    try:
        (cx, cy), s = tiles[0][3], tiles[1]
        x, y = int(cx - 1.0 * s), int(cy + 1.97 * s)
        h, w = frame.shape[:2]
        x0, x1, y0, y1 = int(x - 1.5 * s), int(x + 1.5 * s), int(y - 0.53 * s), int(y + 0.53 * s)
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            return (None, None)
        return (x, y), bool(_yellow(_rgb(frame[y0:y1, x0:x1])).mean() >= 0.04)
    except Exception:
        return (None, None)

def panel_play(frame: np.ndarray) -> Optional[Tuple[int, int]]:
    try:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = int(0.5 * w), int(0.75 * h), int(0.97 * w), h
        m = cv2.morphologyEx(_yellow(_rgb(frame[y0:y1, x0:x1])), cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8))
        n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        best = None
        for i in range(1, n):
            x, y, bw, bh, area = (int(v) for v in st[i])
            if bw >= 0.09 * w:
                if 0.04 * h <= bh <= 0.09 * h:
                    if 3.0 <= bw / bh <= 5.5:
                        if area >= 0.6 * bw * bh and (best is None or bw > best[2]):
                            best = x, y, bw, bh
        if best is None:
            return
        return x0 + best[0] + best[2] // 2, y0 + best[1] + best[3] // 2
    except Exception:
        return

class ModeFix:
    def __init__(self, settings, clock: Callable[[], float]=time.monotonic, log: Callable[[str], None]=(lambda _m: None)):
        self.s = settings
        self._clock = clock
        self.log = log
        self._next_open = 0.0
        self._next_verify = clock() + 30.0
        self._opens = []
        self._blocked_until = 0.0
        self._tile_clicks = 0
        self._fill_clicks = 0
        self._in_panel = False
        self.fixes = 0

    def poll(self, frame: np.ndarray) -> Optional[Click]:
        try:
            if not getattr(self.s, 'mode_fix_enabled', False):
                return
            now = self._clock()
            tiles = find_tiles(frame)
            if tiles is not None:
                return self._in_the_panel(frame, tiles, now)
            if self._in_panel:
                self._in_panel, self._tile_clicks, self._fill_clicks = False, 0, 0
            if now < self._blocked_until or now < self._next_open:
                return
            label = find_mode_label(frame)
            if label is None:
                return
            solo = label[2] < SOLO_RATIO
            if not solo:
                if now < self._next_verify:
                    return
        except Exception:
            return
        try:
            self._opens = [t for t in self._opens if now - t < OPEN_WINDOW_S]
            if len(self._opens) >= MAX_OPENS:
                self._blocked_until = now + BACKOFF_S
                self._opens = []
                self.log('mode fix: the mode panel did not open - pausing the fix for 10 minutes')
                return
            self._opens.append(now)
            self._next_open = now + OPEN_COOLDOWN_S
            self._next_verify = now + VERIFY_EVERY_S
            self.log(f'mode fix: {'Solo suspected' if solo else 'routine check'} (label {label[2]:.2f}) - opening the mode panel')
            return label[0], label[1], 'mode fix: open mode panel'
        except Exception:
            return

    def _in_the_panel(self, frame, tiles, now) -> Optional[Click]:
        self._in_panel = True
        self._opens = []
        pts, _s, sel = tiles
        if sel != 3 and self._tile_clicks < MAX_TILE_CLICKS:
            self._tile_clicks += 1
            self.log('mode fix: selecting Squad')
            return pts[3][0], pts[3][1], 'mode fix: select squad'
        sw, on = fill_switch(frame, tiles)
        if sel == 3 and on is False and sw is not None and self._fill_clicks < MAX_FILL_CLICKS:
            self._fill_clicks += 1
            self.log('mode fix: switching Fill ON')
            return sw[0], sw[1], 'mode fix: fill on'
        p = panel_play(frame)
        if p is not None:
            self.fixes += 1
            self._tile_clicks = self._fill_clicks = 0
            self.log('mode fix: done - confirming with Play')
            return p[0], p[1], 'mode fix: confirm'


