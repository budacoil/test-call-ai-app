import os
import queue
import threading
import time
import config
import i18n
from anti_afk import AntiAfk
from audio_mute import GameAudioController
from bus_drop import BusDrop
from background_input import BackgroundInput
from config import Settings
from controller import Controller
from focus import ensure_game_foreground
from humanizer import CoffeeBreak
from loot_vault import LootVault
from mode_b import ModeB
from mode_c import ModeC
from reward_shot import RewardShotSender
from rescue import Rescue
from space_press import SpacePresser
from state_machine import (POPUP_KEYS, State, StateMachine)
from telemetry import TelemetryManager
from vision import (Plate, capture_for_matching, find_plate, find_template, load_template_auto)
from watchdog import Watchdog
from window_capture import GameWindow, WindowCapture
BG_HINTS = {'minimized': 'log_bg_minimized', 'black': 'log_bg_black', 'denied': 'log_bg_denied'}

def load_templates(lang: str) -> dict:
    return {k: load_template_auto(config.template_path(k, lang), config.PLATES.get(k)) if config.uses_template(k, lang) else None for k in config.TEMPLATE_NAMES}

class Worker(threading.Thread):
    def __init__(self, settings: Settings, log_q: 'queue.Queue[str]', status: dict, tm: 'TelemetryManager | None'=None):
        super().__init__(daemon=True)
        self.s = settings
        self.log_q = log_q
        self.status = status
        self.tm = tm
        self.stop_event = threading.Event()

    def _load_templates(self, lang: str) -> dict:
        templates = load_templates(lang)
        for k, v in templates.items():
            if v is not None:
                continue
            if k in config.OPTIONAL_TEMPLATES:
                continue
            if config.uses_template(k, lang):
                self.log_q.put(f'template missing: {config.template_filename(k, lang)}')
        return templates

    def run(self) -> None:
        lang = self.s.lang
        templates = self._load_templates(lang)
        locator = GameWindow()
        wcap = WindowCapture(locator)
        bg = BackgroundInput(locator, self.s, marker_path=os.path.join(config.base_dir(), 'pk-auto_shield.json'))
        bg.start()
        bg_stop = threading.Event()
        threading.Thread(target=bg.watch, args=(bg_stop,), daemon=True, name='pk-auto-ghost').start()
        ctrl = Controller(self.s, focuser=ensure_game_foreground, swapper=bg.context, poster=(lambda key: bg.post_tap(key)), away=getattr(bg, 'other_window_in_front', None))
        mode_a = StateMachine(self.s, templates, ctrl)
        machines = {'A': mode_a, 'B': ModeB(self.s, templates, ctrl), 'C': ModeC(self.s, templates, ctrl, mode_a)}
        mode = self.s.mode if self.s.mode in machines else 'A'
        sm = machines[mode]
        sm.start()
        vault = LootVault(log=self.log_q.put)
        rshot = RewardShotSender(self.s, log=self.log_q.put)
        def on_claim(key, frame, loops):
            if self.s.loot_vault_enabled:
                vault.save(frame, loops)
            rshot.notify(frame)

        for m in machines.values():
            m.log = self.log_q.put
            m.on_claim = on_claim
        audio = GameAudioController(log=self.log_q.put)
        audio_t = 0.0
        coffee = CoffeeBreak(self.s)
        def find_popup(frame):
            for key in POPUP_KEYS:
                tpl = templates.get(key)
                if tpl is None:
                    continue
                m, _ = find_plate(frame, tpl, self.s.scales) if isinstance(tpl, Plate) else find_template(frame, tpl, self.s.threshold, self.s.scales)
                if m:
                    return m[0], m[1]

        def send_stuck(state: str, minutes: int) -> None:
            if self.tm:
                if self.s.telemetry_enabled:
                    if self.s.alert_enabled:
                        grid = None
                        try:
                            from rescue_grid import grid_b64
                            grid = grid_b64(resc.last_frame)
                        except Exception:
                            grid = None
                        self.tm.send_stuck(self.s.discord_link_key, self.s.telemetry_api_url, state, minutes, grid_image_b64=grid)

        resc = Rescue(self.s, ctrl, (lambda: sm), find_popup=find_popup, send_stuck=send_stuck, log=self.log_q.put)
        def in_match() -> bool:
            if isinstance(sm, ModeB):
                return sm.match_active()
            return sm.state is State.IN_MATCH

        afk = AntiAfk(self.s, active=in_match, focuser=ensure_game_foreground, swapper=bg.context, look=ctrl.look, swing=ctrl.swing, dive_look=(lambda dx, dy, ms: ctrl.look(dx, dy, ms, force=True)), away=getattr(bg, 'other_window_in_front', None), defer=bg.user_busy, post_down=(lambda k: bg.post_key(k, True)), post_up=(lambda k: bg.post_key(k, False)))
        bus = BusDrop(self.s, log=self.log_q.put)
        afk_thread = threading.Thread(target=afk.run, args=(self.stop_event, self.log_q.put), daemon=True)
        afk_thread.start()
        space = SpacePresser(self.s, active=in_match, press=(lambda: ctrl.press('space')), defer=bg.user_busy)
        space_thread = threading.Thread(target=space.run, args=(self.stop_event, self.log_q.put), daemon=True)
        space_thread.start()
        last_note, last_score, last_src = '', -1.0, ''
        def alert(code: str, detail: str) -> None:
            if self.tm:
                if self.s.telemetry_enabled:
                    if self.s.alert_enabled:
                        self.tm.send_alert(self.s.discord_link_key, self.s.telemetry_api_url, code, detail)

        dog = Watchdog(alert)
        try:
            while not self.stop_event.is_set():
                pass
            try:
                if self.s.lang != lang:
                    lang = self.s.lang
                    templates = self._load_templates(lang)
                    for m in machines.values():
                        m.templates = templates
                if self.s.mode != mode and self.s.mode in machines:
                    sm.stop()
                    mode = self.s.mode
                    sm = machines[mode]
                    sm.start()
                    if self.tm:
                        self.tm.set_mode(mode)
                now_m = time.monotonic()
                if now_m - audio_t >= 30.0:
                    audio_t = now_m
                    if self.s.auto_mute_enabled:
                        audio.refresh()
                    else:
                        audio.restore()
                pause = coffee.check(sm.state.value)
                if pause:
                    self.log_q.put(f'[humanizer] coffee break ({int(pause)}s)')
                    self.stop_event.wait(pause)
                    resc.progress()
            except Exception as e:
                self.log_q.put(f'error: {e}')
                dog.error(f'{type(e).__name__}: {e}')
        except BaseException as e:
            dog.fatal(f'{type(e).__name__}: {e}')
            raise
        bg_stop.set()
        self.s.rescue_listening = False
        try:
            audio.restore()
        except Exception:
            pass
        try:
            afk_thread.join(timeout=2)
            space_thread.join(timeout=2)
        finally:
            bg.release_all()
        self.status.update(state=State.IDLE.value, score=0.0)


