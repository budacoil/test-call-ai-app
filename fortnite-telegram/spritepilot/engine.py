from __future__ import annotations

from datetime import datetime
import queue
import random
import threading
import time
import uuid

import cv2

from .automation.mode_b import ModeB
from .automation.state_machine import State, StateMachine
from .automation.vision import load_template_auto
from .rewards import RewardWatcher, write_image
from .settings import resource_root
from .telegram import panel, rescue_panel
from .windows import GameUnavailable, WindowsGame

FILENAMES = {"play": "play_btn", "continue": "continue_btn", "skip": "skip_btn",
             "return_lobby": "return_lobby_btn", "claim": "claim_btn", "claim_single": "claim_single_btn",
             "popup": "popup_btn", "hud": "hud_btn", "menu_btn": "menu_btn", "menu_return": "menu_return_btn"}
PLATES = {"play": {"roi": (0, .7, .4, 1), "threshold": .92},
          "return_lobby": {"roi": (.55, .3, 1, .52), "threshold": .80},
          "claim": {"roi": (.503, .8, 1, 1), "threshold": .93}}


class Engine:
    def __init__(self, settings, store, game=None):
        self.s, self.store = settings, store
        self.game = game or WindowsGame()
        self.game.settings = settings
        self.commands = queue.Queue(maxsize=64)
        self.quit_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, daemon=True, name="spritepilot-engine")
        self.running = False
        self.session = ""
        self.match_id = ""
        self.started_at = 0.0
        self.ended_at = 0.0
        self.loops = 0
        self.session_rewards = 0
        self.last_frame = None
        self.frame_at = 0.0
        self.capture_error = "Ожидание запуска"
        self.machine = None
        self.watcher = RewardWatcher(store.root, settings)
        self.last_progress = time.monotonic()
        self.last_alert = 0.0
        self.last_summary = time.monotonic()
        self.next_step = 0.0
        self.next_afk = 0.0
        self.release_at = 0.0
        self.grid_at = 0.0
        self.grid_size = None
        self.last_note = ""
        self.claim_saved_match = ""
        self.emergency = threading.Event()
        self.state = "Остановлен"
        self.hotkey = None

    def start_thread(self):
        self.thread.start()
        try:
            import sys
            if sys.platform == "win32":
                import keyboard
                self.hotkey = keyboard.add_hotkey("f8", self.emergency.set)
        except Exception:
            self.store.event("Глобальная клавиша F8 недоступна; используйте кнопку остановки", "warning")

    def submit(self, action, arg=None, chat=None):
        try:
            self.commands.put_nowait((action, arg, chat))
            return True
        except queue.Full:
            self.store.event("Очередь команд заполнена", "warning")
            return False

    def snapshot(self):
        with self.lock:
            return dict(running=self.running, state=self.state, mode=self.s.mode, loops=self.loops,
                        rewards=self.session_rewards, elapsed=self.duration(),
                        session=self.session, game=self.capture_error, note=self.last_note,
                        detector=self.watcher.last_debug, calibrated=len(self.watcher.classifier.features),
                        configured=self.watcher.configured, pending=self.store.pending())

    def current_frame(self, fresh=False):
        if fresh:
            frame, ox, oy = self.game.capture()
            with self.lock:
                self.last_frame, self.frame_at = frame.copy(), time.monotonic()
                self.capture_error = "Окно игры доступно"
            return frame, ox, oy
        with self.lock:
            if self.last_frame is None or time.monotonic()-self.frame_at > 5:
                raise GameUnavailable("Нет свежего кадра. Откройте игру и запросите снимок ещё раз.")
            return self.last_frame.copy()

    def _reply(self, chat, text, photo="", markup=None):
        if chat:
            self.store.enqueue(chat, text, photo, markup)
        else:
            self.store.event(text)

    def _notify(self, text, photo=""):
        if self.s.telegram_enabled and self.s.telegram_user_id:
            self.store.enqueue(self.s.telegram_user_id, text, photo)

    def _templates(self):
        result = {}
        for key, stem in FILENAMES.items():
            plate = None
            if self.s.lang in ("ru", "es", "pt") and key in PLATES:
                stem += "_plate"
                plate = PLATES[key]
            elif self.s.lang == "en" and key in ("play", "return_lobby", "claim", "claim_single"):
                stem += "_en"
            external = self.store.root / "buttons" / (stem + ".png")
            path = external if external.exists() else resource_root() / "assets" / (stem + ".png")
            result[key] = load_template_auto(str(path), plate)
        if result["play"] is None or result["return_lobby"] is None:
            raise ValueError("Не найдены изображения кнопок игры")
        return result

    def _machine(self):
        cls = StateMachine if self.s.mode == "A" else ModeB
        self.machine = cls(self.s, self._templates(), self.game)
        self.machine.start()
        self.last_progress = time.monotonic()
        self.last_note = ""

    def _start(self):
        if self.running:
            return "Автоматизация уже работает"
        # Validate access before creating a session or enabling keyboard input.
        self.current_frame(fresh=True)
        if self.machine is None:
            self._machine()
        if not self.session:
            self.session = self.store.start_session()
            self.match_id = uuid.uuid4().hex
            self.started_at = time.time()
            self.ended_at = 0.0
            self.loops = self.session_rewards = 0
            self.watcher.reset()
        self.running = True
        self.last_summary = self.last_progress = time.monotonic()
        self.state = "Запуск"
        return "Автоматизация запущена · F8 — остановить"

    def _stop(self, pause=False):
        self.running = False
        self.game.release_all()
        self.state = "Пауза" if pause else "Остановлен"
        if not pause:
            if self.session:
                self.ended_at = time.time()
                self.store.finish_session(self.session, self.loops)
                self._notify(self.summary())
            self.session = ""
            self.machine = None
        return "Автоматизация приостановлена" if pause else "Автоматизация остановлена"

    def summary(self):
        duration = self.duration()
        return f"Sprite Pilot · сессия {duration//60} мин\nЦиклы: {self.loops}\nНаграды: {self.session_rewards}\nСостояние: {self.state}"

    def duration(self):
        return max(0, int((self.ended_at or time.time())-self.started_at)) if self.started_at else 0

    def _screenshot(self, grid=False):
        frame, _, _ = self.current_frame(fresh=True)
        if grid:
            self.grid_at = time.monotonic()
            self.grid_size = frame.shape[:2]
            h, w = frame.shape[:2]
            for row in range(4):
                for col in range(4):
                    x0, y0, x1, y1 = col*w//4, row*h//4, (col+1)*w//4, (row+1)*h//4
                    cv2.rectangle(frame, (x0, y0), (x1-1, y1-1), (255, 200, 80), 2)
                    cv2.putText(frame, f"{'ABCD'[row]}{col+1}", (x0+12, y0+32), cv2.FONT_HERSHEY_SIMPLEX, .9, (255, 255, 255), 2)
        path = self.store.root / "screenshots" / (uuid.uuid4().hex + ".jpg")
        write_image(path, frame)
        return str(path)

    def _rescue(self, action):
        if self.running and time.monotonic()-self.last_progress < self.s.stuck_minutes*60:
            raise ValueError("Восстановление доступно при зависании или на паузе")
        frame, ox, oy = self.current_frame(fresh=True)
        if action == "restart":
            self.game.release_all()
            self._machine()
            return "Цикл сброшен; запуск и пауза сохранены"
        if action == "esc":
            self.game.press("esc")
        elif action == "center":
            self.game.click(ox+frame.shape[1]//2, oy+frame.shape[0]//2, force=True)
        elif len(action) == 2 and action[0] in "ABCD" and action[1] in "1234":
            if time.monotonic()-self.grid_at > 60 or self.grid_size != frame.shape[:2]:
                raise ValueError("Сетка устарела. Запросите новый снимок восстановления.")
            row, col = "ABCD".index(action[0]), int(action[1])-1
            self.game.click(ox+int((col+.5)*frame.shape[1]/4), oy+int((row+.5)*frame.shape[0]/4), force=True)
        else:
            raise ValueError("Неизвестная команда восстановления")
        return f"Выполнено: {action}"

    def _command(self, action, arg, chat):
        if chat and chat != self.s.telegram_user_id:
            raise ValueError("Telegram-получатель изменён; старая команда отклонена")
        if chat and not self.s.remote_control and action in ("start", "stop", "pause", "mode", "wasd", "wait", "rescue"):
            raise ValueError("Разрешите управление через Telegram в приложении")
        if chat and not self.s.remote_screenshots and action in ("screenshot", "rescue_grid"):
            raise ValueError("Разрешите скриншоты через Telegram в приложении")
        text, photo, markup = "", "", None
        if action == "start":
            text = self._start()
        elif action in ("stop", "pause"):
            text = self._stop(action == "pause")
        elif action == "mode":
            if arg not in ("A", "B"):
                raise ValueError("Неизвестный режим")
            self.s.mode = arg
            self.game.release_all()
            if self.machine:
                self._machine()
            self.s.save(self.store.root)
            text = f"Режим {arg} выбран"
        elif action == "wasd":
            self.s.afk_enabled = not self.s.afk_enabled
            self.game.release_all()
            self.s.save(self.store.root)
            text = "WASD включён" if self.s.afk_enabled else "WASD выключен"
        elif action == "wait":
            try:
                seconds = float(arg)
            except (ValueError, TypeError):
                raise ValueError("Используйте /wait 90 · от 10 до 600 секунд") from None
            if not 10 <= seconds <= 600:
                raise ValueError("Ожидание должно быть от 10 до 600 секунд")
            self.s.wait_b = seconds
            self.s.save(self.store.root)
            text = f"Ожидание режима B: {seconds:g} с"
        elif action == "status":
            text, markup = self.summary()+f"\n{self.capture_error}", panel()
        elif action in ("screenshot", "rescue_grid"):
            photo = self._screenshot(action == "rescue_grid")
            text = "Окно Fortnite · " + datetime.now().strftime("%H:%M:%S")
            if action == "rescue_grid":
                markup = rescue_panel()
        elif action == "rescue":
            text = self._rescue(str(arg))
        elif action == "rewards":
            rows = self.store.rewards(self.session or None, 10)
            text = "Последние награды:\n"+"\n".join(f"{datetime.fromtimestamp(r['at']):%H:%M} · {self.label(r['variant'])}" for r in rows) if rows else "Награды пока не обнаружены"
        elif action == "configure":
            old_mode, old_lang = self.s.mode, self.s.lang
            self.s.apply(arg)
            self.s.save(self.store.root)
            self.game.release_all()
            if "calibration" in arg or "variants" in arg:
                self.watcher = RewardWatcher(self.store.root, self.s)
            if self.machine and (old_mode != self.s.mode or old_lang != self.s.lang):
                self._machine()
            text = "Настройки сохранены"
        elif action == "reload_detector":
            self.watcher = RewardWatcher(self.store.root, self.s)
            text = "Шаблоны наград обновлены"
        elif action == "reload_buttons":
            if self.machine:
                self.machine.templates = self._templates()
            text = "Шаблоны кнопок обновлены"
        else:
            raise ValueError("Неизвестная команда")
        self._reply(chat, text, photo, markup)

    def label(self, variant):
        return self.s.variants.get(variant, "Экран наград" if variant == "reward_screen" else "Sprite Gizmo · вариант не определён")

    def _record(self, frame, detection):
        row = self.store.save_reward(frame, detection.crop, detection.variant, detection.confidence, self.session, self.match_id)
        self.session_rewards += 1
        label = self.label(detection.variant)
        self.store.event(f"Награда: {label} · совпадение {detection.confidence:.0%}")
        selected = not self.s.favorites or detection.variant in self.s.favorites
        if self.s.notify_rewards and ((detection.variant == "unknown" and self.s.notify_unknown) or (detection.variant != "unknown" and selected)):
            self._notify(f"{label}\n{datetime.fromtimestamp(row['at']):%d.%m %H:%M:%S}\nСовпадение с образцом: {detection.confidence:.0%}", row["full_path"])
        if self.s.pause_on_favorite and detection.variant in self.s.favorites:
            self._stop(pause=True)
            self._notify(f"Пауза: найдена выбранная награда «{label}»", row["full_path"])

    def _tick(self):
        now = time.monotonic()
        if self.release_at and now >= self.release_at:
            self.game.release_all()
            self.release_at = 0
        frame, ox, oy = self.current_frame(fresh=True)
        detection = self.watcher.observe(frame)
        if detection:
            self._record(frame, detection)
        if not self.running:
            return
        if now >= self.next_step:
            self.next_step = now+self.s.poll_interval
            previous, before = self.machine.state, self.machine.loops
            result = self.machine.step(frame, ox, oy)
            self.state = result.state.value
            delta = max(0, self.machine.loops-before)
            self.loops += delta
            if delta or (previous != result.state and result.state in (State.IN_MATCH, State.B_COUNTDOWN)):
                self.match_id = uuid.uuid4().hex
            if result.clicked or previous != result.state:
                self.last_progress = now
                if result.note != self.last_note:
                    self.store.event(result.note)
            self.last_note = result.note
            # Preserve ordinary reward screens as well as in-match detections.
            if (result.clicked and result.note.startswith(("clicked claim ", "clicked claim_single "))
                    and self.claim_saved_match != self.match_id):
                from .rewards import Detection
                self._record(frame, Detection("reward_screen", 1., frame, 1.))
                self.claim_saved_match = self.match_id
        if self.s.afk_enabled and self.machine.state is State.IN_MATCH and now >= self.next_afk:
            self.game.release_all()
            self.game.hold(random.choice("wasd"))
            self.release_at = now+self.s.afk_hold
            self.next_afk = now+max(self.s.afk_interval, self.s.afk_hold+.1)
        elif self.machine.state is not State.IN_MATCH:
            self.game.release_all()
        if now-self.last_progress >= self.s.stuck_minutes*60 and now-self.last_alert >= 600:
            self.last_alert = now
            text = f"Нет прогресса {self.s.stuck_minutes} мин · {self.state}"
            self.store.event(text, "warning")
            photo = self._screenshot(grid=True) if self.s.remote_screenshots else ""
            self._notify(text, photo)
        if self.s.summary_minutes and now-self.last_summary >= self.s.summary_minutes*60:
            self.last_summary = now
            self._notify(self.summary())

    def _run(self):
        while not self.quit_event.is_set():
            if self.emergency.is_set():
                self.emergency.clear()
                self._stop()
                self.store.event("Остановка по F8")
            for _ in range(10):
                try:
                    action, arg, chat = self.commands.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._command(action, arg, chat)
                except Exception as error:
                    self._reply(chat, f"Не выполнено: {error}")
            if self.running:
                try:
                    self._tick()
                except GameUnavailable as error:
                    self.game.release_all()
                    if self.capture_error != str(error):
                        self.store.event(str(error), "warning")
                    self.capture_error = str(error)
                    self.state = "Ожидание окна игры"
                except Exception as error:
                    self._stop(pause=True)
                    self.store.event(f"Пауза после ошибки: {type(error).__name__}: {error}", "error")
                    self._notify("Автоматизация приостановлена после ошибки. Подробности в журнале.")
            self.quit_event.wait(self.s.capture_interval)
        self._stop()

    def close(self):
        self.quit_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)
        self.game.release_all()
        if self.hotkey is not None:
            import keyboard
            keyboard.remove_hotkey(self.hotkey)
