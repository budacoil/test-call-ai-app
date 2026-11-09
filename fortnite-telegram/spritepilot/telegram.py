from __future__ import annotations

import json
import hashlib
from pathlib import Path
import queue
import secrets
import threading
import time
import urllib.error
import urllib.request

from .settings import read_token


class ApiError(Exception):
    def __init__(self, code=0, retry_after=0):
        super().__init__(f"Telegram: {'нет соединения' if not code else 'код ' + str(code)}")
        self.code, self.retry_after = code, retry_after


class TelegramAPI:
    def __init__(self, token):
        self.token = token

    def call(self, method, body, photo=None):
        if photo:
            boundary = "SpritePilot" + secrets.token_hex(12)
            chunks = []
            for key, value in body.items():
                if value is None:
                    continue
                value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="game.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode(), photo, f"\r\n--{boundary}--\r\n".encode()])
            data, content = b"".join(chunks), f"multipart/form-data; boundary={boundary}"
        else:
            data, content = json.dumps(body).encode(), "application/json"
        request = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data, headers={"Content-Type": content})
        try:
            with urllib.request.urlopen(request, timeout=28) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                info = json.loads(error.read())
                retry = min(86400, max(1, float(info.get("parameters", {}).get("retry_after", 0)))) if error.code == 429 else 0
            except (ValueError, TypeError):
                retry = 0
            raise ApiError(error.code, retry) from None
        except (OSError, ValueError):
            raise ApiError() from None
        if not result.get("ok"):
            raise ApiError(result.get("error_code", 0), result.get("parameters", {}).get("retry_after", 0))
        return result.get("result")


def panel():
    rows = [[("▶ Запустить", "start"), ("■ Остановить", "stop")],
            [("Статус", "status"), ("Скриншот", "screenshot")],
            [("A · Обычный", "mode:A"), ("B · Остров", "mode:B")],
            [("WASD вкл/выкл", "wasd"), ("Награды", "rewards")],
            [("Восстановление", "rescue_panel")]]
    return {"inline_keyboard": [[{"text": title, "callback_data": action} for title, action in row] for row in rows]}


def rescue_panel():
    rows = [[("Esc", "rescue:esc"), ("Центр", "rescue:center"), ("Перезапуск", "rescue:restart")]]
    for row in "ABCD":
        rows.append([(f"{row}{col}", f"rescue:{row}{col}") for col in range(1, 5)])
    return {"inline_keyboard": [[{"text": t, "callback_data": a} for t, a in row] for row in rows]}


class TelegramBridge:
    def __init__(self, settings, store, submit, api_factory=TelegramAPI):
        self.s, self.store, self.submit, self.api_factory = settings, store, submit, api_factory
        self.stop_event = threading.Event()
        self.status = "Отключён"
        self.threads = []
        self.api = None

    def start(self):
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("Telegram ещё завершает предыдущее соединение")
        if not self.s.telegram_enabled:
            self.status = "Отключён"
            return
        token = read_token()
        if not token or self.s.telegram_user_id <= 0:
            self.status = "Укажите токен и Telegram ID"
            return
        self.api = self.api_factory(token)
        self.stop_event.clear()
        self.status = "Подключение…"
        self.threads = [threading.Thread(target=target, daemon=True, name=name)
                        for target, name in ((self._poll, "telegram-poll"), (self._send, "telegram-send"))]
        for thread in self.threads:
            thread.start()

    def stop(self, wait=True):
        self.stop_event.set()
        if wait:
            for thread in self.threads:
                thread.join(timeout=30)
        self.status = "Отключён"

    def _authorized(self, message):
        user = message.get("from", {}).get("id")
        chat = message.get("chat", {})
        return (type(user) is int and user == self.s.telegram_user_id
                and chat.get("type") == "private" and chat.get("id") == user)

    def handle(self, update):
        callback = update.get("callback_query")
        message = callback.get("message", {}) if callback else update.get("message", {})
        actor = dict(message)
        if callback:
            actor["from"] = callback.get("from", {})
        if not self._authorized(actor):
            return
        chat = actor["chat"]["id"]
        if callback:
            try:
                self.api.call("answerCallbackQuery", {"callback_query_id": callback["id"]})
            except ApiError:
                pass
        text = callback.get("data", "") if callback else message.get("text", "")
        if not isinstance(text, str):
            return
        parts = text.strip().split(maxsplit=1)
        command = parts[0].split("@")[0].lstrip("/") if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        if command in ("panel", "help"):
            self.store.enqueue(chat, "Sprite Pilot · управление", markup=panel())
        elif command == "rescue_panel":
            self.submit("rescue_grid", None, chat)
        elif command in ("status", "screenshot", "rewards", "start", "stop", "pause", "wasd"):
            self.submit(command, None, chat)
        elif command.startswith("mode:"):
            self.submit("mode", command.split(":", 1)[1], chat)
        elif command.startswith("rescue:"):
            self.submit("rescue", command.split(":", 1)[1], chat)
        elif command == "wait":
            self.submit("wait", arg, chat)
        else:
            self.store.enqueue(chat, "Команды: /panel /status /start /stop /screenshot /rewards /wait 90", markup=panel())

    def _poll(self):
        # Persist the next update ID so delivered commands aren't replayed on restart.
        offset_path = self.store.root / "telegram-offset.json"
        identity = hashlib.sha256(self.api.token.encode()).hexdigest()[:20]
        try:
            cached = json.loads(offset_path.read_text())
            offset = int(cached["offset"]) if cached.get("bot") == identity else 0
        except (OSError, ValueError, TypeError, KeyError):
            offset = 0
        backoff = 2
        while not self.stop_event.is_set():
            try:
                updates = self.api.call("getUpdates", {"offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]}) or []
                if self.stop_event.is_set():
                    break
                self.status = "Подключён"
                backoff = 2
                for update in updates:
                    if self.stop_event.is_set():
                        break
                    if int(update["update_id"]) < offset:
                        continue
                    # Advance before dispatch. Commands are at-most-once after a
                    # crash; old remote input must never replay unexpectedly.
                    offset = max(offset, int(update["update_id"]) + 1)
                    from .settings import atomic_json
                    atomic_json(offset_path, {"offset": offset, "bot": identity})
                    date = update.get("message", {}).get("date")
                    if date and time.time() - date > 120:
                        continue
                    self.handle(update)
            except ApiError as error:
                self.status = str(error)
                if error.code in (401, 409):
                    self.store.event(f"{error}. Проверьте токен и запуск бота на другом устройстве.", "error")
                    self.stop_event.set()
                    break
                self.stop_event.wait(error.retry_after or backoff)
                backoff = min(60, backoff * 2)
            except (OSError, ValueError, KeyError, TypeError):
                self.status = "Ошибка обработки ответа"
                self.stop_event.wait(5)

    def _send(self):
        while not self.stop_event.is_set():
            row = self.store.due()
            if not row:
                self.stop_event.wait(.5)
                continue
            # Never deliver another account's persisted messages after rebinding.
            if row["chat"] != self.s.telegram_user_id:
                self.store.retry(row["id"], 0, "Получатель изменён", permanent=True)
                continue
            try:
                value = json.loads(row["payload"])
                photo = Path(value["photo"]).read_bytes() if value["photo"] else None
                body = {"chat_id": row["chat"], "reply_markup": value["markup"]}
                if photo:
                    body["caption"] = value["text"][:1000]
                else:
                    body["text"] = value["text"]
                self.api.call("sendPhoto" if photo else "sendMessage", body, photo=photo)
                self.store.delivered(row["id"])
                self.stop_event.wait(1.1)
            except ApiError as error:
                permanent = error.code in (400, 401, 403)
                delay = error.retry_after or min(3600, 2 ** min(row["attempts"] + 1, 11))
                self.store.retry(row["id"], delay, str(error), permanent)
                if permanent:
                    self.store.event(f"Сообщение Telegram не доставлено: {error}", "error")
                self.stop_event.wait(min(delay, 5))
            except (OSError, ValueError, KeyError):
                self.store.retry(row["id"], 0, "Изображение или сообщение недоступно", permanent=True)
