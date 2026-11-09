import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config

def read(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def save(key, img, alpha):
    out = os.path.join(config.assets_dir(), config.TEMPLATE_NAMES[key])
    ok, buf = cv2.imencode(".png", np.dstack([img, alpha]))
    buf.tofile(out)
    print(f"{key:12s} -> {os.path.basename(out)} {img.shape[1]}x{img.shape[0]}")

def hud(shot):
    x0, y0, x1, y1 = 40, 1108, 346, 1148
    img = shot[y0:y1, x0:x1]
    alpha = np.zeros(img.shape[:2], np.uint8)
    alpha[1112 - y0:1143 - y0, 62 - x0:330 - x0] = 255
    plus = np.zeros_like(alpha)
    plus[1119 - y0:1136 - y0, 42 - x0:58 - x0] = 255
    alpha[(plus > 0) & (img.min(axis=2) > 190)] = 255
    save("hud", img, alpha)

def menu_btn(shot):
    x0, y0, x1, y1 = 1652, 48, 1704, 94
    img = shot[y0:y1, x0:x1]
    save("menu_btn", img, np.full(img.shape[:2], 255, np.uint8))

def menu_return(shot):
    x0, y0, x1, y1 = 1389, 38, 1735, 308
    img = shot[y0:y1, x0:x1]
    alpha = np.full(img.shape[:2], 255, np.uint8)
    for ya, yb in ((152, 194), (224, 266)):
        alpha[ya - y0:yb - y0, :] = 0
    save("menu_return", img, alpha)

def main(paths):
    if len(paths) != 3:
        sys.exit(__doc__)
    island, social, menu = (read(p) for p in paths)
    hud(island)
    menu_btn(social)
    menu_return(menu)

if __name__ == "__main__":
    main(sys.argv[1:])
