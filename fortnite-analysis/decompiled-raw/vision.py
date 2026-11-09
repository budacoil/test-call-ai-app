import os
from dataclasses import dataclass
from typing import (Optional, Sequence, Tuple)
import cv2
import numpy as np
Match = Tuple[int, int, float]

def load_template(path: str) -> Optional[np.ndarray]:
    if not os.path.isfile(path):
        return
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img

@dataclass
class Plate:
    image: np.ndarray
    mask: np.ndarray
    roi: Tuple[float, float, float, float]
    threshold: float

def load_template_auto(path: str, plate: Optional[dict]=None):
    if not os.path.isfile(path):
        return
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return
    if img.ndim == 3 and img.shape[2] == 4:
        if plate is not None:
            return Plate(np.ascontiguousarray(img[:, :, :3]), np.ascontiguousarray(img[:, :, 3]), tuple(plate['roi']), plate['threshold'])
        return np.ascontiguousarray(img[:, :, :3])
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img

def capture_screen(monitor_index: int=1, region: Optional[dict]=None) -> Tuple[np.ndarray, int, int]:
    import mss
    with mss.mss() as sct:
        mon = region or sct.monitors[min(monitor_index, len(sct.monitors) - 1)]
        shot = np.array(sct.grab(mon))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR), mon['left'], mon['top']

def capture_for_matching(monitor_index: int=1, window_capture=None) -> Tuple[np.ndarray, int, int, str]:
    if window_capture is not None:
        try:
            cap = window_capture.grab()
        except Exception:
            cap = None
        if cap is not None and cap.frame is not None:
            return cap.frame, cap.origin[0], cap.origin[1], 'window'
        frame, ox, oy = capture_screen(monitor_index)
        return frame, ox, oy, cap.status if cap is None else 'error'
    frame, ox, oy = capture_screen(monitor_index)
    return frame, ox, oy, 'screen'

def capture_game_window(monitor_index: int=1, background_mode: bool=False, window_capture=None) -> Tuple[np.ndarray, int, int]:
    if background_mode:
        if window_capture is None:
            try:
                from window_capture import WindowCapture
                window_capture = WindowCapture()
            except Exception:
                window_capture = None
        frame, ox, oy, _src = capture_for_matching(monitor_index, window_capture)
        return frame, ox, oy
    return capture_screen(monitor_index)

def find_template(frame: np.ndarray, template: np.ndarray, threshold: float=0.82, scales: Sequence[float]=(0.9, 0.95, 1.0, 1.05, 1.1)) -> Tuple[Optional[Match], float]:
    fg = _gray(frame)
    tg = _gray(template)
    half_f = cv2.resize(fg, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    half_t = cv2.resize(tg, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = [(_match(half_f, half_t, s)[0], s) for s in scales]
    coarse = [c for c in coarse if c[0] > -1]
    if not coarse:
        return (None, 0.0)
    best_scale = max(coarse)[1]
    best = (-1.0, 0, 0)
    for s in best_scale - 0.05, best_scale, best_scale + 0.05:
        score, x, y = _match(fg, tg, s)
        if score > best[0]:
            best = score, x, y
    score, x, y = best
    if score >= threshold:
        return (x, y, score), score
    return None, max(score, 0.0)

def _gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img

def _match(frame: np.ndarray, template: np.ndarray, scale: float) -> Tuple[float, int, int]:
    t = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    th, tw = t.shape[:2]
    if th > frame.shape[0] or tw > frame.shape[1] or th < 4 or tw < 4:
        return (-2.0, 0, 0)
    _, max_val, _, max_loc = cv2.minMaxLoc(cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED))
    return float(max_val), max_loc[0] + tw // 2, max_loc[1] + th // 2

def find_plate(frame: np.ndarray, plate: Plate, scales: Sequence[float]=(0.9, 0.95, 1.0, 1.05, 1.1)) -> Tuple[Optional[Match], float]:
    fh, fw = frame.shape[:2]
    x0, y0 = int(plate.roi[0] * fw), int(plate.roi[1] * fh)
    x1, y1 = int(plate.roi[2] * fw), int(plate.roi[3] * fh)
    region = frame[y0:y1, x0:x1]
    if region.size == 0:
        return (None, 0.0)
    def match(img: np.ndarray, base: float, scale: float) -> Tuple[float, int, int]:
        f = base * scale
        t = cv2.resize(plate.image, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
        m = cv2.resize(plate.mask, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_NEAREST)
        if t.shape[0] >= img.shape[0] or t.shape[1] >= img.shape[1] or min(t.shape[:2]) < 6 or not m.any():
            return (-2.0, 0, 0)
        res = np.nan_to_num(cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED, mask=m), nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, val, _, loc = cv2.minMaxLoc(res)
        return float(val), x0 + loc[0] + t.shape[1] // 2, y0 + loc[1] + t.shape[0] // 2

    half = cv2.resize(region, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    coarse = [(match(half, 0.5, s)[0], s) for s in scales]
    coarse = [c for c in coarse if c[0] > -2]
    if not coarse:
        return (None, 0.0)
    best_scale = max(coarse)[1]
    best = (-1.0, 0, 0)
    for s in best_scale - 0.05, best_scale, best_scale + 0.05:
        cand = match(region, 1.0, s)
        if cand[0] > best[0]:
            best = cand
    score, x, y = best
    score = min(score, 1.0)
    if score >= plate.threshold:
        return (x, y, score), score
    return None, max(score, 0.0)

COLOUR_CHECKED = ('play', 'storefront_play')
PLAY_AIM_DOWN = 0.15
COLOUR_TOL = 70.0

def _median_colour(img: np.ndarray, mask: Optional[np.ndarray]=None) -> Optional[np.ndarray]:
    px = img.reshape(-1, img.shape[2] if img.ndim == 3 else 1)
    if mask is not None:
        px = px[mask.reshape(-1) > 0]
    if len(px) < 16:
        return
    return np.median(px.astype(np.float32), axis=0)

def colour_matches(frame: np.ndarray, tpl, centre, tol: float=COLOUR_TOL) -> bool:
    try:
        if tpl is None:
            return True
        img = tpl.image if isinstance(tpl, Plate) else tpl
        mask = tpl.mask if isinstance(tpl, Plate) else None
        if img.ndim != 3:
            return True
        th, tw = img.shape[:2]
        fh, fw = frame.shape[:2]
        x0, y0 = int(centre[0]) - tw // 2, int(centre[1]) - th // 2
        x1, y1 = x0 + tw, y0 + th
        if x0 < 0 or y0 < 0 or x1 > fw or y1 > fh:
            return True
        want = _median_colour(img, mask)
        got = _median_colour(frame[y0:y1, x0:x1], mask)
        if want is None or got is None:
            return True
        return float(np.linalg.norm(want - got)) <= tol
    except Exception:
        return True

def aim_point(key: str, tpl, m) -> Tuple[int, int]:
    x, y = int(m[0]), int(m[1])
    if key == 'play' and tpl is not None:
        try:
            h = (tpl.image if isinstance(tpl, Plate) else tpl).shape[0]
            y += int(round(PLAY_AIM_DOWN * h))
        except Exception:
            pass
        return x, y
    return x, y

def find_checked(frame: np.ndarray, key: str, tpl, find):
    m, score = find(frame)
    if not m or key not in COLOUR_CHECKED:
        return m, score
    img = tpl.image if isinstance(tpl, Plate) else tpl
    th, tw = img.shape[:2] if getattr(img, 'ndim', 0) >= 2 else (40, 120)
    work = frame
    for _ in range(3):
        if colour_matches(frame, tpl, m):
            return m, score
        if work is frame:
            work = frame.copy()
        x, y = int(m[0]), int(m[1])
        work[max(0, y - th // 2 - 2):y + th // 2 + 2, max(0, x - tw // 2 - 2):x + tw // 2 + 2] = 0
        m, score = find(work)
        if m:
            continue
        return None, score
    return None, score

