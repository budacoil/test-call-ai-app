import json
import time
from pathlib import Path

import pytest

from spritepilot.telegram import ApiError, TelegramAPI, TelegramBridge


class FakeAPI:
    token = "fake-test-token-never-networked"

    def __init__(self):
        self.calls = []

    def call(self, method, body, photo=None):
        self.calls.append((method, body, photo))
        return True


def message(user=123, chat=None, kind="private", text="/status"):
    return {"message": {"from": {"id": user}, "chat": {"id": user if chat is None else chat, "type": kind}, "text": text}}


@pytest.mark.parametrize("update", [message(999), message(chat=-1, kind="group"), message(chat=456), message(user="123")])
def test_unauthorized_commands_are_ignored(update, settings, store):
    settings.telegram_user_id = 123
    commands = []
    bridge = TelegramBridge(settings, store, lambda *args: commands.append(args))
    bridge.api = FakeAPI()
    bridge.handle(update)
    assert not commands
    assert store.pending() == 0


def test_callback_checks_actor_instead_of_bot_message_author(settings, store):
    settings.telegram_user_id = 123
    commands = []
    bridge = TelegramBridge(settings, store, lambda *args: commands.append(args))
    bridge.api = FakeAPI()
    callback = {"callback_query": {"id": "a", "from": {"id": 123}, "data": "mode:B",
        "message": {"from": {"id": 555}, "chat": {"id": 123, "type": "private"}}}}
    bridge.handle(callback)
    assert commands == [("mode", "B", 123)]
    assert bridge.api.calls[0][0] == "answerCallbackQuery"


def test_callback_from_another_user_is_ignored(settings, store):
    settings.telegram_user_id = 123
    calls = []
    bridge = TelegramBridge(settings, store, lambda *args: calls.append(args))
    bridge.api = FakeAPI()
    bridge.handle({"callback_query": {"id": "x", "from": {"id": 999}, "data": "start", "message": message()["message"]}})
    assert not calls and not bridge.api.calls


def test_retry_after_is_persisted_without_losing_message(settings, store):
    settings.telegram_user_id = 123
    bridge = TelegramBridge(settings, store, lambda *args: None)
    key = store.enqueue(123, "award")
    class Limited:
        def call(self, *args, **kwargs):
            bridge.stop_event.set()
            raise ApiError(429, 37)
    bridge.api = Limited()
    before = time.time()
    bridge._send()
    row = store.query("SELECT * FROM outbox WHERE id=?", (key,))[0]
    assert row["state"] == "pending" and row["attempts"] == 1
    assert row["next_try"] >= before + 37


def test_rebinding_never_sends_previous_users_images(settings, store):
    settings.telegram_user_id = 123
    bridge = TelegramBridge(settings, store, lambda *args: None)
    bridge.api = FakeAPI()
    key = store.enqueue(999, "previous account", "/secret/nonexistent.jpg")
    def wait(_):
        bridge.stop_event.set()
    bridge.stop_event.wait = wait
    bridge._send()
    assert not bridge.api.calls
    assert store.query("SELECT state FROM outbox WHERE id=?", (key,))[0]["state"] == "failed"


def test_successful_delivery_leaves_persistent_sent_record(settings, store):
    settings.telegram_user_id = 123
    bridge = TelegramBridge(settings, store, lambda *args: None)
    class Delivered(FakeAPI):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            bridge.stop_event.set()
            return result
    bridge.api = Delivered()
    key = store.enqueue(123, "hello")
    bridge._send()
    assert store.query("SELECT state FROM outbox WHERE id=?", (key,))[0]["state"] == "sent"
    assert bridge.api.calls[0][0] == "sendMessage"


def test_api_error_never_exposes_token(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("sensitive-token-in-url")
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ApiError) as raised:
        TelegramAPI("sensitive-token-in-url").call("getMe", {})
    assert "sensitive" not in str(raised.value)
