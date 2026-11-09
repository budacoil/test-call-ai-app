import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
from config import Settings
from controller import Controller
from mode_b import ESC_GRACE_S, MENU_MAX_ESC, MENU_RETRY_S, ModeB
from state_machine import State

KEYS = ["play", "hud", "menu_btn", "menu_return", "claim"]

def make_button(seed, size=(40, 120)):
    return np.random.default_rng(seed).integers(0, 255, size=(size[0], size[1], 3), dtype=np.uint8)

def make_frame(*placed, shape=(600, 900)):
    frame = np.full((shape[0], shape[1], 3), 30, dtype=np.uint8)
    for btn, (x, y) in placed:
        h, w = btn.shape[:2]
        frame[y:y + h, x:x + w] = btn
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

@pytest.fixture
def env(monkeypatch, fake_time):
    tpls = {k: make_button(i + 1) for i, k in enumerate(KEYS)}
    s = Settings(click_cooldown=1.0, delay_min=0, delay_max=0, jitter_px=0, wait_b=90.0)
    clock = fake_time
    clicks, keys = [], []
    monkeypatch.setattr(Controller, "_click", staticmethod(lambda x, y: clicks.append((x, y))))
    monkeypatch.setattr(Controller, "_press", staticmethod(keys.append))
    mb = ModeB(s, tpls, Controller(s))
    mb.start()
    return s, clock, clicks, keys, tpls, mb

def frame_of(tpls, key, pos=(300, 200)):
    return make_frame((tpls[key], pos))

def test_idle_until_started(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.stop()
    r = mb.step(frame_of(tpls, "play"))
    assert r.state is State.IDLE and not clicks

def test_full_loop(env):
    s, clock, clicks, keys, tpls, mb = env
    assert mb.state is State.B_LOBBY

    r = mb.step(frame_of(tpls, "play"))
    assert r.clicked and mb.state is State.B_WAIT_MATCH
    assert clicks == [(360, 220)]

    clock.advance(5)
    assert mb.step(make_frame()).state is State.B_WAIT_MATCH

    mb.step(frame_of(tpls, "hud"))
    assert mb.state is State.B_COUNTDOWN
    clock.advance(60)
    r = mb.step(frame_of(tpls, "hud"))
    assert mb.state is State.B_COUNTDOWN and not keys and "waiting" in r.note
    clock.advance(31)
    r = mb.step(frame_of(tpls, "hud"))
    assert keys == ["esc"] and r.clicked and mb.state is State.B_MENU

    clock.advance(2)
    n = len(clicks)
    mb.step(frame_of(tpls, "menu_btn", (500, 30)))
    assert len(clicks) == n + 1 and mb.state is State.B_MENU

    clock.advance(2)
    r = mb.step(frame_of(tpls, "menu_return", (500, 100)))
    assert r.clicked and mb.state is State.B_LOBBY and mb.loops == 1
    assert clicks[-1] == (500 + 60, 100 + 20)

    clock.advance(2)
    mb.step(frame_of(tpls, "play"))
    assert mb.state is State.B_WAIT_MATCH

def test_wait_time_is_adjustable(env):
    s, clock, clicks, keys, tpls, mb = env
    s.wait_b = 20.0
    mb.state = State.B_WAIT_MATCH
    mb.step(frame_of(tpls, "hud"))
    clock.advance(15)
    mb.step(frame_of(tpls, "hud"))
    assert not keys
    clock.advance(6)
    mb.step(frame_of(tpls, "hud"))
    assert keys == ["esc"]

def test_reward_popup_in_lobby_is_clicked_and_state_kept(env):
    s, clock, clicks, keys, tpls, mb = env
    r = mb.step(frame_of(tpls, "claim", (100, 100)))
    assert r.clicked and mb.state is State.B_LOBBY and clicks == [(160, 120)]

def test_menu_already_open_when_time_is_up_does_not_press_esc(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.state = State.B_WAIT_MATCH
    mb.step(frame_of(tpls, "hud"))
    clock.advance(100)
    mb.step(frame_of(tpls, "menu_return", (500, 100)))
    assert not keys and mb.state is State.B_MENU
    clock.advance(2)
    mb.step(frame_of(tpls, "menu_return", (500, 100)))
    assert mb.state is State.B_LOBBY and mb.loops == 1

def test_back_in_lobby_when_time_is_up_does_not_press_esc(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.state = State.B_WAIT_MATCH
    mb.step(frame_of(tpls, "hud"))
    clock.advance(100)
    mb.step(frame_of(tpls, "play"))
    assert not keys and mb.state is State.B_LOBBY

def test_esc_is_pressed_again_when_no_panel_appears_but_not_forever(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.state = State.B_WAIT_MATCH
    mb.step(frame_of(tpls, "hud"))
    clock.advance(100)
    mb.step(frame_of(tpls, "hud"))
    assert keys == ["esc"]
    clock.advance(MENU_RETRY_S - 1)
    mb.step(frame_of(tpls, "hud"))
    assert keys == ["esc"]
    for _ in range(5):
        clock.advance(MENU_RETRY_S + 1)
        mb.step(frame_of(tpls, "hud"))
    assert keys == ["esc"] * MENU_MAX_ESC

def test_no_esc_while_the_island_hud_is_hidden_until_the_grace_period_ends(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.state = State.B_WAIT_MATCH
    mb.step(frame_of(tpls, "hud"))
    clock.advance(100)
    r = mb.step(make_frame())
    assert not keys and mb.state is State.B_COUNTDOWN and "not visible" in r.note
    clock.advance(ESC_GRACE_S)
    mb.step(make_frame())
    assert keys == ["esc"] and mb.state is State.B_MENU

def test_lobby_that_sees_the_island_starts_the_countdown(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.step(frame_of(tpls, "hud"))
    assert mb.state is State.B_COUNTDOWN and not clicks

def test_leave_click_that_did_not_land_is_retried_in_lobby(env):
    s, clock, clicks, keys, tpls, mb = env
    r = mb.step(frame_of(tpls, "menu_return", (500, 100)))
    assert r.clicked and mb.state is State.B_LOBBY and mb.loops == 0

def test_play_click_that_did_not_land_is_retried_while_loading(env):
    s, clock, clicks, keys, tpls, mb = env
    mb.state = State.B_WAIT_MATCH
    clock.advance(5)
    r = mb.step(frame_of(tpls, "play"))
    assert r.clicked and mb.state is State.B_WAIT_MATCH

def test_mode_b_templates_exist_and_are_language_independent():
    for key in ("hud", "menu_btn", "menu_return"):
        names = {config.template_filename(key, lang) for lang in config.LANGS}
        assert len(names) == 1
        assert os.path.isfile(config.template_path(key, "ja"))
        assert key in config.PLATES
