import os
import sys
import threading
import time

import pydirectinput
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from anti_afk import AntiAfk
from config import Settings

class Keys:
    def __init__(self):
        self.events = []

    def down(self, k):
        self.events.append(("down", k))

    def up(self, k):
        self.events.append(("up", k))

    def presses(self):
        return [k for e, k in self.events if e == "down"]

@pytest.fixture
def keys(monkeypatch):
    k = Keys()
    monkeypatch.setattr(pydirectinput, "keyDown", k.down)
    monkeypatch.setattr(pydirectinput, "keyUp", k.up)
    return k

def make(keys, active=lambda: True, **kw):
    s = Settings(afk_interval=0.3, afk_hold=0.1, **kw)
    return s, keys, AntiAfk(s, active)

def run_for(afk, seconds):
    stop = threading.Event()
    t = threading.Thread(target=afk.run, args=(stop,), daemon=True)
    t.start()
    time.sleep(seconds)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()

def test_press_once_holds_then_releases_a_wasd_key(keys):
    s, keys, afk = make(keys)
    key = afk.press_once(threading.Event())
    assert key in "wasd"
    assert keys.events == [("down", key), ("up", key)]

def test_press_once_releases_immediately_on_stop(keys):
    s = Settings(afk_hold=30.0)
    afk = AntiAfk(s, lambda: True)
    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()
    t0 = time.monotonic()
    afk.press_once(stop)
    assert time.monotonic() - t0 < 2
    assert [e for e, _ in keys.events] == ["down", "up"]

def test_presses_periodically_while_active(keys):
    s, keys, afk = make(keys)
    run_for(afk, 1.5)
    assert len(keys.presses()) >= 2
    assert all(k in s.afk_keys for k in keys.presses())

    assert [e for e, _ in keys.events].count("down") <= [e for e, _ in keys.events].count("up")

def test_no_press_while_inactive_or_disabled(keys):
    s, keys, afk = make(keys, active=lambda: False)
    run_for(afk, 0.9)
    assert keys.presses() == []

    s, keys, afk = make(keys, afk_enabled=False)
    run_for(afk, 0.9)
    assert keys.presses() == []

def test_random_choice_uses_all_keys_eventually(keys):
    s, keys, afk = make(keys)
    s.afk_hold = 0.0
    stop = threading.Event()
    seen = {afk.press_once(stop) for _ in range(200)}
    assert seen == set("wasd")

def test_interval_change_applies_while_running(keys):
    s, keys, afk = make(keys)
    s.afk_interval = 60.0
    stop = threading.Event()
    t = threading.Thread(target=afk.run, args=(stop,), daemon=True)
    t.start()
    time.sleep(0.5)
    assert keys.presses() == []
    s.afk_interval = 0.3
    time.sleep(0.8)
    stop.set()
    t.join(timeout=2)
    assert len(keys.presses()) >= 1
