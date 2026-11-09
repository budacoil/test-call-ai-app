"""Synthetic fixtures for the explicit demo; never used as real recognition templates."""
from pathlib import Path
import time

import cv2
import numpy as np

from .rewards import write_image


def make_icon(number):
    rng = np.random.default_rng(number + 100)
    icon = np.zeros((144, 144, 3), np.uint8)
    icon[:] = (35, 30, 25)
    colors = [(90, 110, 240), (160, 220, 80), (240, 150, 80), (220, 80, 170), (80, 210, 220)]
    cv2.rectangle(icon, (4, 4), (139, 139), (80, 190, 230), 5)
    for _ in range(12):
        x, y = rng.integers(22, 122, 2)
        cv2.circle(icon, (int(x), int(y)), int(rng.integers(5, 18)), colors[number-1], -1)
    cv2.putText(icon, str(number), (44, 98), cv2.FONT_HERSHEY_SIMPLEX, 2, (250, 250, 250), 3)
    return icon


def make_frame(number=1):
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[:] = (32, 25, 18)
    for y in range(240, 720):
        frame[y, :] = (40+int((y-240)*.03), 36, 25)
    frame[30:174, 568:712] = make_icon(number)
    cv2.putText(frame, "YOU FOUND", (500, 218), cv2.FONT_HERSHEY_SIMPLEX, .9, (240, 240, 240), 2)
    cv2.putText(frame, "SPRITE GIZMO", (460, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (80, 210, 240), 3)
    cv2.putText(frame, "DEMO / SYNTHETIC EXAMPLE", (50, 650), cv2.FONT_HERSHEY_SIMPLEX, 1, (160, 160, 160), 2)
    return frame


class DemoGame:
    def __init__(self):
        self.settings = None
        self.shape = (720, 1280)
        self.origin = (0, 0)
        self.held = set()
        self.calls = []

    def capture(self):
        return make_frame(1), 0, 0

    def click(self, x, y, force=False):
        self.calls.append(("click", x, y))
        return True

    def press(self, key):
        self.calls.append(("press", key))

    def hold(self, key):
        self.held.add(key)

    def release_all(self):
        self.held.clear()


def seed_demo(settings, store):
    settings.telegram_enabled = False
    settings.calibration = {"anchor": [450, 184, 390, 90], "icon": [568, 30, 144, 144]}
    frame = make_frame(1)
    write_image(store.root / "templates/anchor.png", frame[184:274, 450:840])
    for number in range(1, 6):
        write_image(store.root / f"templates/gizmo_{number}/demo.png", make_icon(number))
    if store.rewards(limit=1):
        return
    session = store.start_session()
    for number in (1, 3, 5, 2, 4):
        store.save_reward(make_frame(number), make_icon(number), f"gizmo_{number}", .96, session, f"demo-match-{number}")
    store.finish_session(session, 5)
    store.event("Демонстрация: изображения и награды синтетические. Управление игрой и Telegram отключены.")
