import hashlib
import io
import json
import time
import urllib.error

import pytest

from spritepilot.storage import Store
from spritepilot.telegram import TelegramAPI, ApiError, TelegramBridge


def test_outbox_survives_process_restart(tmp_path):
    store = Store(tmp_path)
    key = store.enqueue(123, "saved offline")
    store.retry(key, 0, "offline")
    store.close()
    reopened = Store(tmp_path)
    try:
        row = reopened.due()
        assert row["id"] == key and row["attempts"] == 1
        assert json.loads(row["payload"])["text"] == "saved offline"
    finally:
        reopened.close()


def test_http_429_parses_telegram_retry_after(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://redacted", 429, "limited", {},
            io.BytesIO(json.dumps({"ok": False, "parameters": {"retry_after": 37}}).encode()))
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ApiError) as raised:
        TelegramAPI("test-token").call("sendMessage", {"chat_id": 123, "text": "a"})
    assert raised.value.code == 429 and raised.value.retry_after == 37


def test_old_commands_are_acknowledged_without_being_executed(settings, store):
    settings.telegram_user_id = 123
    commands = []
    bridge = TelegramBridge(settings, store, lambda *args: commands.append(args))
    class PollAPI:
        token = "fake-bot"
        calls = []
        def call(self, method, body):
            self.calls.append(body)
            if len(self.calls) > 1:
                bridge.stop_event.set()
                return []
            return [{"update_id": 41, "message": {"date": time.time()-300, "from": {"id": 123},
                "chat": {"id": 123, "type": "private"}, "text": "/start"}}]
    bridge.api = PollAPI()
    bridge._poll()
    assert not commands
    cached = json.loads((store.root/"telegram-offset.json").read_text())
    assert cached["offset"] == 42
    assert "fake-bot" not in (store.root/"telegram-offset.json").read_text()


def test_new_bot_does_not_inherit_old_bot_offset(settings, store):
    settings.telegram_user_id = 123
    (store.root/"telegram-offset.json").write_text(json.dumps({"offset": 90000, "bot": "another-bot"}))
    bridge = TelegramBridge(settings, store, lambda *args: None)
    class NewBot:
        token = "new-fake-bot"
        def call(self, method, body):
            assert body["offset"] == 0
            bridge.stop_event.set()
            return []
    bridge.api = NewBot()
    bridge._poll()
