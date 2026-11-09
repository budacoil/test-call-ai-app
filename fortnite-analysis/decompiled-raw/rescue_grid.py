import base64
from typing import Optional
import cv2
import numpy as np
MAX_BYTES = 51200

def render_rescue_grid(frame: np.ndarray, max_width: int=640, jpeg_quality: int=70) -> bytes:
    if frame is None or frame.ndim != 3 or frame.shape[0] < 4 or frame.shape[1] < 4:
        raise ValueError('bad frame')
    h, w = frame.shape[:2]
    if w > max_width:
        img = cv2.resize(frame, (max_width, max(4, int(round(h * max_width / w)))), interpolation=cv2.INTER_AREA)
    else:
        img = frame.copy()
    h, w = img.shape[:2]
    cyan = (255, 230, 0)
    for i in range(1, 4):
        x, y = int(w * i / 4), int(h * i / 4)
        for p0, p1 in ((x, 0), (x, h - 1)), ((0, y), (w - 1, y)):
            cv2.line(img, p0, p1, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.line(img, p0, p1, cyan, 1, cv2.LINE_AA)
    scale = max(0.4, w / 1100.0)
    for row in range(4):
        for col in range(4):
            label = f'{'ABCD'[col]}{row + 1}'
            org = int(w * col / 4) + 5, int(h * row / 4) + int(22 * scale / 0.58) + 2
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    q = int(jpeg_quality)
    while True:
        ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            raise ValueError('encode failed')
        if len(buf) <= MAX_BYTES or q <= 25:
            return buf.tobytes()
        q -= 10

def grid_b64(frame) -> Optional[str]:
    try:
        return base64.b64encode(render_rescue_grid(frame)).decode('ascii')
    except Exception:
        return

