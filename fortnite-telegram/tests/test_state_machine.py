import os
import sys
import time

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import Settings
from controller import Controller
from state_machine import State, StateMachine
from vision import find_template

KEYS = ["play", "continue", "skip", "return_lobby"]

def make_button(seed, size=(40, 120)):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(size[0], size[1], 3), dtype=np.uint8)

def make_frame(button=None, pos=(300, 200), shape=(600, 900)):
    frame = np.full((shape[0], shape[1], 3), 30, dtype=np.uint8)
    if button is not None:
        h, w = button.shape[:2]
        frame[pos[1]:pos[1] + h, pos[0]:pos[0] + w] = button
    return frame

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt

@pytest.fixture(autouse=True)
def fake_time(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return clock

def build(templates, monkeypatch, clock):
    s = Settings(click_cooldown=1.0, delay_min=0, delay_max=0)
    clicks = []
    monkeypatch.setattr(Controller, "_click", staticmethod(lambda x, y: clicks.append((x, y))))
    return s, clock, clicks, StateMachine(s, templates, Controller(s))

@pytest.fixture
def env(monkeypatch, fake_time):
    tpls = {k: make_button(i + 1) for i, k in enumerate(KEYS)}
    tpls["claim"] = make_button(5)
    tpls["popup"] = make_button(6)
    s, clock, clicks, sm = build(tpls, monkeypatch, fake_time)
    return s, clock, clicks, tpls, sm

def test_find_template_exact_and_scaled():
    btn = make_button(1)
    m, score = find_template(make_frame(btn, (300, 200)), btn, 0.82)
    assert m is not None and score > 0.99
    assert abs(m[0] - 360) <= 1 and abs(m[1] - 220) <= 1

    scaled = cv2.resize(btn, None, fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)
    m, _ = find_template(make_frame(scaled, (300, 200)), btn, 0.82)
    assert m is not None

def test_find_template_absent():
    m, _ = find_template(make_frame(None), make_button(1), 0.82)
    assert m is None

def test_idle_does_nothing(env):
    _, _, clicks, tpls, sm = env
    r = sm.step(make_frame(tpls["play"]))
    assert r.state is State.IDLE and not clicks

def test_full_loop(env):
    s, clock, clicks, tpls, sm = env
    sm.start()
    assert sm.state is State.SEARCHING_PLAY

    sm.step(make_frame())
    assert sm.state is State.SEARCHING_PLAY and not clicks

    expected = [
        ("play", State.IN_MATCH),
        ("continue", State.SKIPPING_RESULT),
        ("skip", State.RETURNING_LOBBY),
        ("return_lobby", State.SEARCHING_PLAY),
    ]
    for n, (key, nxt) in enumerate(expected, start=1):
        clock.advance(2)
        r = sm.step(make_frame(tpls[key]))
        assert r.clicked and sm.state is nxt and len(clicks) == n
    cx, cy = clicks[0]
    assert abs(cx - 360) <= s.jitter_px + 1 and abs(cy - 220) <= s.jitter_px + 1
    assert sm.loops == 1

def test_reclicks_previous_button_if_still_visible(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    sm.step(make_frame(tpls["play"]))
    assert len(clicks) == 1
    clock.advance(2)
    r = sm.step(make_frame(tpls["play"]))
    assert r.clicked and sm.state is State.IN_MATCH and len(clicks) == 2
    assert sm.loops == 0

def test_earlier_than_previous_button_ignored(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    clock.advance(2)
    sm.step(make_frame(tpls["continue"]))
    clock.advance(2)
    sm.step(make_frame(tpls["skip"]))
    clock.advance(2)
    sm.step(make_frame(tpls["continue"]))
    assert sm.state is State.RETURNING_LOBBY and len(clicks) == 3

def test_skips_ahead_when_continue_missed(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    clock.advance(2)
    sm.step(make_frame(tpls["skip"]))
    assert sm.state is State.RETURNING_LOBBY and len(clicks) == 2

def test_cooldown_blocks_double_click(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    sm.stop()
    sm.start()
    sm.step(make_frame(tpls["play"]))
    assert len(clicks) == 1 and sm.state is State.SEARCHING_PLAY

def test_missing_template_is_reported(monkeypatch, fake_time):
    tpls = {k: make_button(i + 1) for i, k in enumerate(KEYS)}
    tpls["play"] = None
    _, _, clicks, sm = build(tpls, monkeypatch, fake_time)
    sm.start()
    r = sm.step(make_frame())
    assert "missing" in r.note and not clicks

def test_claim_popup_in_lobby_is_clicked_and_state_kept(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    r = sm.step(make_frame(tpls["claim"]))
    assert r.clicked and sm.state is State.SEARCHING_PLAY and len(clicks) == 1
    clock.advance(2)
    sm.step(make_frame(tpls["play"]))
    assert sm.state is State.IN_MATCH and len(clicks) == 2

def test_lobby_continue_popup_does_not_advance_state(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    r = sm.step(make_frame(tpls["continue"]))
    assert r.clicked and sm.state is State.SEARCHING_PLAY
    clock.advance(2)
    sm.step(make_frame(tpls["play"]))
    assert sm.state is State.IN_MATCH

def test_optional_popup_button(env):
    _, _, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["popup"]))
    assert len(clicks) == 1 and sm.state is State.SEARCHING_PLAY

def test_popup_handled_in_any_state(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    clock.advance(2)
    sm.step(make_frame(tpls["claim"]))
    assert sm.state is State.IN_MATCH and len(clicks) == 2

def test_play_in_lobby_recovers_from_late_states(env):
    _, clock, clicks, tpls, sm = env
    sm.start()
    sm.step(make_frame(tpls["play"]))
    clock.advance(2)
    sm.step(make_frame(tpls["continue"]))
    clock.advance(2)
    sm.step(make_frame(tpls["skip"]))
    assert sm.state is State.RETURNING_LOBBY
    clock.advance(2)
    sm.step(make_frame(tpls["play"]))
    assert sm.state is State.IN_MATCH and len(clicks) == 4

def test_claim_single_popup_is_also_clicked(env):
    _, _, clicks, tpls, sm = env
    sm.start()
    tpls["claim_single"] = make_button(7)
    sm.templates["claim_single"] = tpls["claim_single"]
    r = sm.step(make_frame(tpls["claim_single"]))
    assert r.clicked and sm.state is State.SEARCHING_PLAY and len(clicks) == 1
