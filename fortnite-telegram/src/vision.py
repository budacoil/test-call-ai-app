import os
from dataclasses import dataclass

import cv2
import mss
import numpy as np

def load_template(path):
    if not os.path.isfile(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img

@dataclass
class Plate:

    image: np.ndarray
    mask: np.ndarray
    roi: tuple
    threshold: float

def load_template_auto(path, plate=None):
    if not os.path.isfile(path):
        return None
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        if plate is not None:
            return Plate(np.ascontiguousarray(img[:, :, :3]), np.ascontiguousarray(img[:, :, 3]), tuple(plate["roi"]), plate["threshold"])
        return np.ascontiguousarray(img[:, :, :3])
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img

def capture_screen(monitor_index=1, region=None):
    with mss.mss() as sct:
        mon = region or sct.monitors[min(monitor_index, len(sct.monitors) - 1)]
        shot = np.array(sct.grab(mon))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR), mon["left"], mon["top"]

def find_template(
    frame,
    template,
    threshold = 0.82,
    scales = (0.9, 0.95, 1.0, 1.05, 1.1),
):
    fg = _gray(frame)
    tg = _gray(template)

    half_f = cv2.resize(fg, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    half_t = cv2.resize(tg, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = [(_match(half_f, half_t, s)[0], s) for s in scales]
    coarse = [c for c in coarse if c[0] > -1]
    if not coarse:
        return None, 0.0
    best_scale = max(coarse)[1]

    best = (-1.0, 0, 0)
    for s in (best_scale - 0.05, best_scale, best_scale + 0.05):
        score, x, y = _match(fg, tg, s)
        if score > best[0]:
            best = (score, x, y)
    score, x, y = best
    if score >= threshold:
        return (x, y, score), score
    return None, max(score, 0.0)

def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

def _match(frame, template, scale):
    t = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    th, tw = t.shape[:2]
    if th > frame.shape[0] or tw > frame.shape[1] or th < 4 or tw < 4:
        return -2.0, 0, 0
    _, max_val, _, max_loc = cv2.minMaxLoc(cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED))
    return float(max_val), max_loc[0] + tw // 2, max_loc[1] + th // 2

def find_plate(
    frame,
    plate,
    scales = (0.9, 0.95, 1.0, 1.05, 1.1),
):
    fh, fw = frame.shape[:2]
    x0, y0 = int(plate.roi[0] * fw), int(plate.roi[1] * fh)
    x1, y1 = int(plate.roi[2] * fw), int(plate.roi[3] * fh)
    region = frame[y0:y1, x0:x1]
    if region.size == 0:
        return None, 0.0

    def match(img, base, scale):
        f = base * scale
        t = cv2.resize(plate.image, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
        m = cv2.resize(plate.mask, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_NEAREST)
        if t.shape[0] >= img.shape[0] or t.shape[1] >= img.shape[1] or min(t.shape[:2]) < 6 or not m.any():
            return -2.0, 0, 0
        res = np.nan_to_num(cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED, mask=m), nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, val, _, loc = cv2.minMaxLoc(res)
        return float(val), x0 + loc[0] + t.shape[1] // 2, y0 + loc[1] + t.shape[0] // 2

    half = cv2.resize(region, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = [(match(half, 0.5, s)[0], s) for s in scales]
    coarse = [c for c in coarse if c[0] > -2]
    if not coarse:
        return None, 0.0
    best_scale = max(coarse)[1]
    best = (-1.0, 0, 0)
    for s in (best_scale - 0.05, best_scale, best_scale + 0.05):
        cand = match(region, 1.0, s)
        if cand[0] > best[0]:
            best = cand
    score, x, y = best
    score = min(score, 1.0)
    if score >= plate.threshold:
        return (x, y, score), score
    return None, max(score, 0.0)
