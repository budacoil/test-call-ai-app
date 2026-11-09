import ctypes
from dataclasses import dataclass, field
from typing import (Callable, Dict, List, Optional, Tuple)
import cv2
import numpy as np
import i18n
SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0)
OK_SCALE = (0.9, 1.1)
MIN_SCORE = 0.85
MIN_PX = 28
SCAN_KEYS = ('play', 'continue', 'skip', 'return_lobby', 'claim', 'hud', 'menu_btn', 'menu_return')
MIN_W, MIN_H = 1280, 720

@dataclass
class Item:
    level: str
    code: str
    params: Dict[str, object] = field(default_factory=dict)

class SystemEnv:
    def __init__(self, settings):
        self.s = settings

    def dpi(self) -> Dict[str, object]:
        out = {'system_dpi': None, 'aware': None, 'logical': None}
        try:
            out['system_dpi'] = int(ctypes.windll.user32.GetDpiForSystem())
        except Exception:
            pass
        try:
            aware = ctypes.c_int(-1)
            if ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(aware)) == 0:
                out['aware'] = aware.value != 0
        except Exception:
            pass
        try:
            out['logical'] = int(ctypes.windll.user32.GetSystemMetrics(0)), int(ctypes.windll.user32.GetSystemMetrics(1))
        except Exception:
            pass
        return out

    def monitors(self) -> List[Tuple[int, int, int, int]]:
        import mss
        with mss.mss() as sct:
            return [(m['left'], m['top'], m['width'], m['height']) for m in sct.monitors[1:]]

    def game(self):
        import focus
        import window_capture as wc
        gdi = wc.Win32Gdi()
        hwnd = focus.find_game(focus.WinApi())
        if not hwnd:
            return
        if gdi.is_iconic(hwnd):
            return 'minimized'
        r = gdi.client_rect(hwnd)
        if r and r[2] > 0 and r[3] > 0:
            return tuple(r)

    def frame(self) -> Optional[np.ndarray]:
        import shot
        return shot.grab_frame(self.s)

    def templates(self) -> dict:
        import worker
        return worker.load_templates(self.s.lang)


def scan_scale(frame: np.ndarray, templates: dict, find_template=None, find_plate=None) -> Optional[Tuple[float, float, str]]:
    import vision
    find_template = find_template or vision.find_template
    find_plate = find_plate or vision.find_plate
    half = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    best = None
    for key in SCAN_KEYS:
        tpl = templates.get(key)
        if tpl is None:
            continue
        base = tpl.image if isinstance(tpl, vision.Plate) else tpl
        for s in SCALES:
            if min(base.shape[:2]) * s < MIN_PX:
                continue
            try:
                if isinstance(tpl, vision.Plate):
                    _m, score = find_plate(half, tpl, scales=(s * 0.5,))
                else:
                    _m, score = find_template(half, tpl, 2.0, scales=(s * 0.5,))
            except Exception:
                continue
            if score >= MIN_SCORE and (best is None or score > best[1]):
                best = s, float(score), key
    return best

def _monitor_of(rect: Tuple[int, int, int, int], monitors: List[Tuple[int, int, int, int]]) -> int:
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    for i, (l, t, w, h) in enumerate(monitors, 1):
        if l <= cx < l + w:
            if t <= cy:
                if cy < t + h:
                    return cx
                    i
    return 0

def run_checks(settings, env=None) -> List[Item]:
    env = env or SystemEnv(settings)
    items = []
    try:
        d = env.dpi()
    except Exception:
        d = {}
    monitors = []
    try:
        monitors = env.monitors()
    except Exception:
        pass
    dpi = d.get('system_dpi')
    if d.get('aware') is False:
        items.append(Item('warn', 'dpi_unaware'))
    elif dpi:
        pct = round(dpi * 100 / 96)
        items.append(Item('ok' if pct == 100 else 'info', 'dpi_ok', {'pct': pct}))
    logical = d.get('logical')
    if logical and monitors and d.get('aware') is not False:
        pw, ph = monitors[0][2], monitors[0][3]
        if abs(logical[0] - pw) > 2 or abs(logical[1] - ph) > 2:
            items.append(Item('warn', 'dpi_mismatch', {'lw': logical[0], 'lh': logical[1], 'pw': pw, 'ph': ph}))
    idx = int(getattr(settings, 'monitor_index', 1) or 1)
    if monitors:
        if idx > len(monitors):
            items.append(Item('warn', 'monitor_invalid', {'i': idx, 'n': len(monitors)}))
            idx = 1
        _l, _t, mw, mh = monitors[idx - 1]
        items.append(Item('info', 'res', {'i': idx, 'w': mw, 'h': mh}))
        if mw < MIN_W or mh < MIN_H:
            items.append(Item('warn', 'res_low', {'w': mw, 'h': mh}))
        elif abs(mw / mh - 1.7777777777777777) > 0.05:
            items.append(Item('info', 'aspect', {'w': mw, 'h': mh}))
    g = None
    try:
        g = env.game()
    except Exception:
        pass
    background = bool(getattr(settings, 'background_mode', False))
    if g is None:
        items.append(Item('warn', 'game_none'))
    elif g == 'minimized':
        items.append(Item('warn', 'game_min'))
    else:
        items.append(Item('info', 'game_size', {'w': g[2], 'h': g[3]}))
        if monitors and not background:
            on = _monitor_of(g, monitors)
            if on and on != idx:
                items.append(Item('warn', 'monitor_mismatch', {'game': on, 'sel': idx}))
            elif on:
                _l, _t, mw, mh = monitors[on - 1]
                if g[2] < mw * 0.95 or g[3] < mh * 0.95:
                    items.append(Item('warn', 'game_small', {'w': g[2], 'h': g[3], 'mw': mw, 'mh': mh}))
    try:
        frame = env.frame()
        found = scan_scale(frame, env.templates()) if frame is not None else None
    except Exception:
        frame, found = None, None
    if found is None:
        items.append(Item('info', 'scale_unknown'))
    else:
        s, score, key = found
        if OK_SCALE[0] <= s <= OK_SCALE[1]:
            items.append(Item('ok', 'scale_ok', {'pct': round(s * 100), 'name': key}))
        else:
            items.append(Item('warn', 'scale_bad', {'pct': round(s * 100), 'name': key}))
    warns = sum((1 for it in items if it.level == 'warn'))
    items.append(Item('warn' if warns else 'ok', 'summary_warn' if warns else 'summary_ok', {'n': warns}))
    return items

MARK = {'ok': '✔', 'info': '•', 'warn': '⚠'}

def format_items(items: List[Item], lang: str, translate: Callable[..., str]=None) -> str:
    t = translate or i18n.t
    return '\n'.join((f'{MARK.get(it.level, '•')} {t(lang, 'ac_' + it.code, **it.params)}' for it in items))

