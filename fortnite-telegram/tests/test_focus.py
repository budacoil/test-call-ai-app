import os
import sys
import threading
import time

import pydirectinput

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anti_afk
import controller
from anti_afk import AntiAfk
from config import Settings
from controller import Controller
from focus import GAME_CLASS, ensure_game_foreground, find_game

class FakeApi:
    def __init__(self, wins, foreground=0, minimized=(), focus_works=True):
        self.wins = wins
        self.fg = foreground
        self.minimized = set(minimized)
        self.focus_works = focus_works
        self.focused = []

    def windows(self):
        return list(self.wins)

    def class_name(self, h):
        return self.wins[h][0]

    def title(self, h):
        return self.wins[h][1]

    def is_minimized(self, h):
        return h in self.minimized

    def foreground(self):
        return self.fg

    def focus(self, h):
        self.focused.append(h)
        if self.focus_works:
            self.fg = h

GAME = (GAME_CLASS, "Fortnite  ")
BROWSER = ("Chrome_WidgetWin_1", "Fortnite highlights - YouTube - Google Chrome")

def test_game_is_found_by_class_and_title_not_by_title_alone():
    api = FakeApi({1: BROWSER, 2: GAME})
    assert find_game(api) == 2
    assert find_game(FakeApi({1: BROWSER})) is None
    assert find_game(FakeApi({1: (GAME_CLASS, "Some Other Game")})) is None

def test_game_is_brought_to_the_front_when_a_browser_has_focus():
    api = FakeApi({1: BROWSER, 2: GAME}, foreground=1)
    assert ensure_game_foreground(api) is True
    assert api.focused == [2]

def test_nothing_happens_when_the_game_already_has_focus():
    api = FakeApi({2: GAME}, foreground=2)
    assert ensure_game_foreground(api) is True
    assert api.focused == []

def test_missing_or_minimized_game_is_left_alone():
    api = FakeApi({1: BROWSER}, foreground=1)
    assert ensure_game_foreground(api) is False and api.focused == []
    api = FakeApi({2: GAME}, foreground=1, minimized=[2])
    assert ensure_game_foreground(api) is False and api.focused == []

def test_failed_focus_is_reported_and_errors_never_escape():
    api = FakeApi({2: GAME}, foreground=1, focus_works=False)
    assert ensure_game_foreground(api) is False

    class Broken(FakeApi):
        def windows(self):
            raise OSError("boom")

    assert ensure_game_foreground(Broken({})) is False

def test_controller_focuses_the_game_before_every_key_tap_but_not_before_clicks(monkeypatch):
    s = Settings(click_cooldown=0, delay_min=0, delay_max=0, jitter_px=0)
    order = []
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(controller, "ensure_game_foreground", lambda: order.append("focus"))
    monkeypatch.setattr(Controller, "_click", staticmethod(lambda x, y: order.append("click")))
    monkeypatch.setattr(Controller, "_press", staticmethod(lambda k: order.append(f"key:{k}")))
    c = Controller(s)
    c.click(10, 10)
    c.press("esc")
    assert order == ["click", "focus", "key:esc"]

def test_anti_afk_focuses_the_game_before_holding_a_key(monkeypatch):
    s = Settings(afk_hold=0.0)
    order = []
    monkeypatch.setattr(anti_afk, "ensure_game_foreground", lambda: order.append("focus"))
    monkeypatch.setattr(pydirectinput, "keyDown", lambda k: order.append("down"))
    monkeypatch.setattr(pydirectinput, "keyUp", lambda k: order.append("up"))
    AntiAfk(s, active=lambda: True).press_once(threading.Event())
    assert order == ["focus", "down", "up"]
