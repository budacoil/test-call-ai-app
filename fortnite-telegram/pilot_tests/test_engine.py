import json
import time

import pytest

from spritepilot.automation.state_machine import State
from spritepilot.demo import DemoGame, make_frame, make_icon, seed_demo
from spritepilot.engine import Engine
from spritepilot.rewards import Detection


def engine(settings, store):
    return Engine(settings, store, DemoGame())


def test_remote_control_requires_local_permission(settings, store):
    settings.telegram_user_id = 123
    app = engine(settings, store)
    with pytest.raises(ValueError, match="Разрешите управление"):
        app._command("start", None, 123)
    assert not app.running


def test_remote_screenshot_has_separate_permission(settings, store):
    settings.telegram_user_id = 123
    settings.remote_control = True
    app = engine(settings, store)
    with pytest.raises(ValueError, match="Разрешите скриншоты"):
        app._command("screenshot", None, 123)


def test_pause_and_stop_release_every_held_key(settings, store):
    app = engine(settings, store)
    app._start()
    app.game.hold("w")
    session = app.session
    app._stop(pause=True)
    assert not app.game.held and not app.running and app.session == session
    app._start()
    assert app.session == session
    app._stop()
    assert not app.session and app.machine is None
    assert store.query("SELECT ended FROM sessions WHERE id=?", (session,))[0]["ended"] is not None


def test_saving_unrelated_settings_preserves_match_state(settings, store):
    app = engine(settings, store)
    app._start()
    app.machine.state = State.IN_MATCH
    machine = app.machine
    app._command("configure", {"summary_minutes": 30}, None)
    assert app.machine is machine and app.machine.state is State.IN_MATCH


def test_invalid_wait_does_not_corrupt_settings(settings, store):
    app = engine(settings, store)
    for value in ("nan", "inf", "bad", "601", "9"):
        with pytest.raises(ValueError):
            app._command("wait", value, None)
    assert settings.wait_b == 90


def test_grid_click_requires_recent_image_and_matching_size(settings, store):
    app = engine(settings, store)
    with pytest.raises(ValueError, match="Сетка устарела"):
        app._rescue("D4")
    app._screenshot(grid=True)
    app._rescue("D4")
    assert app.game.calls[-1] == ("click", 1120, 630)
    app.grid_at = time.monotonic()-61
    with pytest.raises(ValueError):
        app._rescue("A1")


def test_rescue_does_not_interrupt_a_healthy_running_loop(settings, store):
    app = engine(settings, store)
    app._start()
    with pytest.raises(ValueError, match="при зависании"):
        app._rescue("esc")
    assert not app.game.calls


def test_favorite_reward_persists_before_pausing(settings, store):
    settings.favorites = ["gizmo_2"]
    settings.pause_on_favorite = True
    app = engine(settings, store)
    app._start()
    app._record(make_frame(2), Detection("gizmo_2", .95, make_icon(2), .99))
    assert store.rewards()[0]["variant"] == "gizmo_2"
    assert app.session_rewards == 1
    assert not app.running and app.state == "Пауза"


def test_unknown_reward_is_saved_even_without_telegram(settings, store):
    app = engine(settings, store)
    app._start()
    app._record(make_frame(1), Detection("unknown", .6, make_icon(1), .99))
    row = store.rewards()[0]
    assert row["variant"] == "unknown"
    assert not store.pending()


def test_five_way_watcher_integrates_with_capture_loop(settings, store):
    seed_demo(settings, store)
    before = len(store.rewards())
    app = engine(settings, store)
    app._start()
    app._tick()
    app._tick()
    app._tick()
    assert len(store.rewards()) == before+1
    assert store.rewards()[0]["variant"] == "gizmo_1"


def test_nonfinite_settings_and_invalid_calibration_are_ignored(settings):
    settings.apply({"threshold": float("nan"), "telegram_user_id": True, "mode": "Z", "calibration": {"anchor": [-1, 0, 20, 20]}})
    assert settings.threshold == .82 and settings.telegram_user_id == 0 and settings.mode == "A"
    assert settings.calibration == {}


def test_profile_excludes_identity_and_privileges(settings, tmp_path):
    settings.telegram_user_id = 123
    settings.remote_control = True
    path = tmp_path / "profile.json"
    settings.export_profile(path)
    values = json.loads(path.read_text())
    assert "telegram_user_id" not in values and "remote_control" not in values
    assert "token" not in path.read_text()


def test_rebinding_rejects_already_queued_remote_commands(settings, store):
    settings.telegram_user_id = 999
    settings.remote_control = True
    app = engine(settings, store)
    with pytest.raises(ValueError, match="получатель изменён"):
        app._command("start", None, 123)
    assert not app.running


def test_settings_cannot_override_object_internals(settings):
    settings.apply({"__dict__": {"mode": "invalid"}, "__class__": {}, "apply": {}})
    assert settings.mode == "A" and settings.lang == "en"


def test_elapsed_time_stops_when_session_ends(settings, store, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("spritepilot.engine.time.time", lambda: now[0])
    app = engine(settings, store)
    app._start()
    now[0] = 1030
    app._stop()
    assert app.snapshot()["elapsed"] == 30
    now[0] = 1200
    assert app.snapshot()["elapsed"] == 30
