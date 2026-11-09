import time
from typing import (Callable, Optional, Tuple)
import cv2
import numpy as np
IDLE_S = 60.0
RETRY_S = 30.0
GAP_S = 10.0
BAND = (0.3, 0.76, 0.97, 0.98)

def find_white_button(frame: np.ndarray) -> Optional[Tuple[int, int]]:
    try:
        fh, fw = frame.shape[:2]
        x0, y0, x1, y1 = int(BAND[0] * fw), int(BAND[1] * fh), int(BAND[2] * fw), int(BAND[3] * fh)
        region = frame[y0:y1, x0:x1]
        if region.size == 0 or region.ndim != 3:
            return
        mn, mx = region.min(axis=2), region.max(axis=2)
        mask = ((mn >= 205) & (mx - mn <= 40)).astype(np.uint8) * 255
        k = max(3, int(fw * 0.004)) | 1
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k * 3, k)))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best, best_area = None, 0
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if 0.07 * fw <= w <= 0.3 * fw:
                if not 0.025 * fh <= h <= 0.075 * fh:
                    continue
            if 2.5 <= w / h <= 8.0:
                if area / float(w * h) < 0.75:
                    continue
            if area > best_area:
                best, best_area = (x0 + x + w // 2, y0 + y + h // 2), area
        return best
    except Exception:
        return

class RewardFallback:
    def __init__(self, clock: Callable[[], float]=time.monotonic):
        self._clock = clock
        self._since = None
        self._last_poll = -1000000000.0
        self._next = 0.0

    def reset(self) -> None:
        self._since = None

    def poll(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        now = self._clock()
        if self._since is None or now - self._last_poll > GAP_S:
            self._since = now
        self._last_poll = now
        if now - self._since < IDLE_S or now < self._next:
            return
        self._next = now + RETRY_S
        return find_white_button(frame)


