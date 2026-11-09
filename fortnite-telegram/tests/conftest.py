import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import anti_afk
import controller


@pytest.fixture(autouse=True)
def no_focus(monkeypatch):
    monkeypatch.setattr(controller, "ensure_game_foreground", lambda *a, **k: None)
    monkeypatch.setattr(anti_afk, "ensure_game_foreground", lambda *a, **k: None)
