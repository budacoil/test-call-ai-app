import time
from typing import (Callable, Optional, Tuple)
import cv2
import numpy as np
DISC_BAND = (0.25, 0.3, 0.75, 0.7)
BUTTON_BAND = (0.2, 0.72, 0.8, 0.98)
MIN_DISCS = 4
GAP_S = 4.0
WHITE_MIN = 228

def _disc_row(frame: np.ndarray) -> bool:
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = int(DISC_BAND[0] * fw), int(DISC_BAND[1] * fh), int(DISC_BAND[2] * fw), int(DISC_BAND[3] * fh)
    region = frame[y0:y1, x0:x1]
    if region.size == 0 or region.ndim != 3:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= 98) & (hsv[:, :, 0] <= 114) & (hsv[:, :, 1] >= 200) & (hsv[:, :, 2] >= 190)).astype(np.uint8) * 255
    k = max(3, int(fw * 0.006)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k * 2 + 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    discs = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if 0.03 * fw <= w <= 0.08 * fw:
            if not 0.85 <= w / float(h) <= 1.18:
                continue
        if area / float(w * h) < 0.65:
            continue
        discs.append((y + h / 2.0, x + w / 2.0, w))
    if len(discs) < MIN_DISCS:
        return False
    discs.sort()
    for i, (cy, _cx, w) in enumerate(discs):
        row = sorted((c for c in discs if abs(c[0] - cy) <= 0.2 * w if abs(c[2] - w) <= 0.2 * w), key=(lambda c: c[1]))
        if len(row) < MIN_DISCS:
            continue
        gaps = [b[1] - a[1] for a, b in zip(row, row[1:])]
        if not min(gaps) >= 1.1 * w:
            continue
        if max(gaps) - min(gaps) <= 0.25 * w:
            return True
    return False

def _white_pill(frame: np.ndarray) -> Optional[Tuple[int, int]]:
    fh, fw = frame.shape[:2]
    x0, y0, x1, y1 = int(BUTTON_BAND[0] * fw), int(BUTTON_BAND[1] * fh), int(BUTTON_BAND[2] * fw), int(BUTTON_BAND[3] * fh)
    region = frame[y0:y1, x0:x1]
    if region.size == 0 or region.ndim != 3:
        return
    mn, mx = region.min(axis=2), region.max(axis=2)
    mask = ((mn >= WHITE_MIN) & (mx - mn <= 40)).astype(np.uint8) * 255
    k = max(3, int(fw * 0.004)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k * 3, k)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best, best_area = None, 0
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if 0.05 * fw <= w <= 0.2 * fw:
            if not 0.025 * fh <= h <= 0.08 * fh:
                continue
        if 2.0 <= w / float(h) <= 8.0:
            if area / float(w * h) < 0.75:
                continue
        if area > best_area:
            best, best_area = (x0 + x + w // 2, y0 + y + h // 2), area
    return best

def find_skip(frame: np.ndarray) -> Optional[Tuple[int, int]]:
    try:
        if frame is None or frame.ndim != 3 or not _disc_row(frame):
            return
        return _white_pill(frame)
    except Exception:
        return

class SurveyGuard:
    def __init__(self, clock: Callable[[], float]=time.monotonic):
        self._clock = clock
        self._next = 0.0

    def poll(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        now = self._clock()
        if now < self._next:
            return
        pt = find_skip(frame)
        if pt:
            self._next = now + GAP_S
        return pt


