from typing import List, Tuple
import cv2
import numpy as np
ROI = (0.0, 0.58, 0.22, 0.985)
MIN_W = 0.025
MAX_H = 0.0095
MIN_ASPECT = 10.0
ROW_GAP = 0.016
X_TOL = 0.035
HUE = (34, 56)
MIN_SAT, MIN_VAL = 150, 160
FLAT = 10

def _bars(frame: np.ndarray) -> List[Tuple[float, float]]:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = int(ROI[0] * w), int(ROI[1] * h), int(ROI[2] * w), int(ROI[3] * h)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (HUE[0], MIN_SAT, MIN_VAL), (HUE[1], 255, 255)) > 0
    ci = crop.astype(np.int16)
    flat = np.pad(np.abs(ci[:, 1:] - ci[:, :-1]).max(axis=2) <= FLAT, ((0, 0), (0, 1)))
    m = (mask & flat).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(0.004 * w)) | 1, 1)))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(0.02 * w)), 1)))
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(m, connectivity=8)
    found = []
    for i in range(1, n):
        bw, bh = int(stats[i, cv2.CC_STAT_WIDTH]), max(1, int(stats[i, cv2.CC_STAT_HEIGHT]))
        if not bw >= MIN_W * w:
            continue
        if not bh <= max(2.0, MAX_H * h):
            continue
        if bw / bh >= MIN_ASPECT:
            found.append(((cent[i][1] + y0) / h, (stats[i, cv2.CC_STAT_LEFT] + x0) / w))
    return found

def count_teammates(frame: np.ndarray) -> int:
    try:
        bars = _bars(frame)
        if not bars:
            return 0
        best = max(bars, key=(lambda b: sum((abs(o[1] - b[1]) <= X_TOL for o in bars))))
        ys = sorted((b[0] for b in bars if abs(b[1] - best[1]) <= X_TOL))
        rows, last = 0, None
        for cy in ys:
            if last is None or cy - last > ROW_GAP:
                rows += 1
            last = cy
        return rows
    except Exception:
        return 0

def squad_size(frame: np.ndarray) -> int:
    return 1 + count_teammates(frame)

