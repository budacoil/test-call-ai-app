import numpy as np

from spritepilot.automation import state_machine as sm
from spritepilot.automation import mode_b
from spritepilot.demo import DemoGame


def test_complete_match_cycle_counts_one_loop(monkeypatch, settings):
    active = ["play"]
    def find(frame, template, *args):
        return ((40, 40, .99), .99) if template == active[0] else (None, .1)
    monkeypatch.setattr(sm, "find_template", find)
    keys = ("play", "continue", "skip", "return_lobby")
    machine = sm.StateMachine(settings, {key: key for key in keys}, DemoGame())
    machine.start()
    for key, expected in zip(keys, (sm.State.IN_MATCH, sm.State.SKIPPING_RESULT, sm.State.RETURNING_LOBBY, sm.State.SEARCHING_PLAY)):
        active[0] = key
        assert machine.step(np.zeros((100,100,3), np.uint8)).state is expected
    assert machine.loops == 1


def test_island_wait_uses_hud_then_menu_in_order(monkeypatch, settings):
    now = [0.0]
    monkeypatch.setattr(mode_b.time, "monotonic", lambda: now[0])
    active = ["play"]
    def find(frame, template, *args):
        return ((40, 40, .99), .99) if template == active[0] else (None, .1)
    monkeypatch.setattr(mode_b, "find_template", find)
    keys = ("play", "hud", "menu_btn", "menu_return")
    game = DemoGame()
    machine = mode_b.ModeB(settings, {key: key for key in keys}, game)
    machine.start()
    frame = np.zeros((100,100,3), np.uint8)
    assert machine.step(frame).state is sm.State.B_WAIT_MATCH
    active[0] = "hud"
    assert machine.step(frame).state is sm.State.B_COUNTDOWN
    now[0] = 91
    assert machine.step(frame).state is sm.State.B_MENU
    assert game.calls[-1] == ("press", "esc")
    active[0] = "menu_return"
    assert machine.step(frame).state is sm.State.B_LOBBY
    assert machine.loops == 1
