import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config

MARGIN = 6

BOXES = {
    "play": (0, (88, 984, 432, 1080)),
    "return_lobby": (1, (1332, 466, 1828, 536)),
    "claim": (2, (972, 1072, 1284, 1142)),
}

def read(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def make_plate(shot, box):
    x0, y0, x1, y1 = box
    img = shot[y0:y1, x0:x1]
    h, w = img.shape[:2]
    alpha = np.full((h, w), 255, np.uint8)
    pw, ph = w - 2 * MARGIN, h - 2 * MARGIN

    alpha[int(MARGIN + ph * 0.20):int(h - MARGIN - ph * 0.20), int(MARGIN + pw * 0.08):int(w - MARGIN - pw * 0.08)] = 0
    return np.dstack([img, alpha])

def main(paths):
    if len(paths) != 3:
        sys.exit(__doc__)
    shots = [read(p) for p in paths]
    for key, (idx, box) in BOXES.items():
        out = os.path.join(config.assets_dir(), config.plate_filename(key))
        ok, buf = cv2.imencode(".png", make_plate(shots[idx], box))
        buf.tofile(out)
        print(f"{key:13s} -> {os.path.basename(out)}")

if __name__ == "__main__":
    main(sys.argv[1:])
