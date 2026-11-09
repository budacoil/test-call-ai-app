import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
from config import Settings
from controller import Controller
from state_machine import State, StateMachine
from vision import Plate, find_plate, load_template_auto

H, W = 600, 960
ROI = (0.0, 0.5, 0.5, 1.0)

def make_plate_parts(seed=1, size=(60, 180)):
    rng = np.random.default_rng(seed)
    rim = rng.integers(0, 255, size=(size[0], size[1], 3), dtype=np.uint8)
    mask = np.full(size, 255, np.uint8)
    mask[int(size[0] * 0.25):int(size[0] * 0.75), int(size[1] * 0.15):int(size[1] * 0.85)] = 0
    return rim, mask

def button_with_label(rim, mask, label_seed):
    out = rim.copy()
    label = np.random.default_rng(label_seed).integers(0, 255, size=rim.shape, dtype=np.uint8)
    out[mask == 0] = label[mask == 0]
    return out

def frame_with(img, pos):
    frame = np.full((H, W, 3), 30, dtype=np.uint8)
    if img is not None:
        h, w = img.shape[:2]
        frame[pos[1]:pos[1] + h, pos[0]:pos[0] + w] = img
    return frame

def make_plate(threshold=0.9):
    rim, mask = make_plate_parts()
    return Plate(rim, mask, ROI, threshold), rim, mask

def test_plate_found_whatever_the_label_says():
    plate, rim, mask = make_plate()
    for label_seed in (11, 22, 33):
        frame = frame_with(button_with_label(rim, mask, label_seed), (100, 450))
        m, score = find_plate(frame, plate, Settings().scales)
        assert m is not None and score > 0.95, (label_seed, score)
        assert abs(m[0] - 190) <= 3 and abs(m[1] - 480) <= 3

def test_plate_absent_is_not_found():
    plate, _, _ = make_plate()
    m, _ = find_plate(frame_with(None, (0, 0)), plate, Settings().scales)
    assert m is None

def test_plate_outside_its_search_region_is_ignored():
    plate, rim, mask = make_plate()
    frame = frame_with(button_with_label(rim, mask, 5), (600, 100))
    m, _ = find_plate(frame, plate, Settings().scales)
    assert m is None

def test_load_template_auto_reads_alpha_as_plate(tmp_path):
    rim, mask = make_plate_parts()
    path = tmp_path / "plate.png"
    cv2.imencode(".png", np.dstack([rim, mask]))[1].tofile(str(path))
    loaded = load_template_auto(str(path), {"roi": ROI, "threshold": 0.9})
    assert isinstance(loaded, Plate) and loaded.mask.shape == mask.shape and loaded.threshold == 0.9
    assert (loaded.mask == mask).all()

    plain = load_template_auto(str(path))
    assert plain.ndim == 3 and plain.shape[2] == 3
    assert load_template_auto(str(tmp_path / "missing.png")) is None

def test_state_machine_clicks_a_plate_in_any_language(monkeypatch):
    plate, rim, mask = make_plate()
    s = Settings(click_cooldown=1.0, delay_min=0, delay_max=0)
    clicks = []
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(Controller, "_click", staticmethod(lambda x, y: clicks.append((x, y))))
    ctrl = Controller(s)
    sm = StateMachine(s, {"play": plate}, ctrl)
    sm.start()
    sm.step(frame_with(button_with_label(rim, mask, 77), (100, 450)))
    assert sm.state is State.IN_MATCH and len(clicks) == 1
    assert abs(clicks[0][0] - 190) <= s.jitter_px + 3 and abs(clicks[0][1] - 480) <= s.jitter_px + 3

LABEL_PLATES = [k for k in config.PLATES if k not in config.LANG_INDEPENDENT]

def test_plate_languages_use_shared_plate_files():
    for lang in config.PLATE_LANGS:
        for key in LABEL_PLATES:
            assert config.template_filename(key, lang) == config.plate_filename(key)
            assert os.path.isfile(config.template_path(key, lang)), (lang, key)

        assert config.template_filename("continue", lang) == "continue_btn.png"
        assert not config.uses_template("claim_single", lang)
    assert config.uses_template("claim_single", "en")

def test_every_language_has_its_core_templates():
    for lang in config.LANGS:
        for key in ("play", "continue", "skip", "return_lobby"):
            assert os.path.isfile(config.template_path(key, lang)), (lang, key)

def test_shipped_plates_are_real_plates():
    for key in LABEL_PLATES:
        p = load_template_auto(config.template_path(key, "es"), config.PLATES[key])
        assert isinstance(p, Plate), key
        assert 0.2 < (p.mask == 0).mean() < 0.6
