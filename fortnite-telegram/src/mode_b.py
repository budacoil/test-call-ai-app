import math
import time

from state_machine import POPUP_KEYS, State, StepResult
from vision import Plate, find_plate, find_template

ESC_GRACE_S = 30.0
MENU_RETRY_S = 8.0
MENU_MAX_ESC = 3

class ModeB:
    def __init__(self, settings, templates, controller):
        self.s = settings
        self.templates = templates
        self.ctrl = controller
        self.state = State.IDLE
        self.loops = 0
        self._t0 = 0.0
        self._t_esc = 0.0
        self._esc_tries = 0

    def start(self):
        if self.state is State.IDLE:
            self.state = State.B_LOBBY

    def stop(self):
        self.state = State.IDLE

    def _find(self, key, frame):
        tpl = self.templates.get(key)
        if tpl is None:
            return None, 0.0
        if isinstance(tpl, Plate):
            return find_plate(frame, tpl, self.s.scales)
        return find_template(frame, tpl, self.s.threshold, self.s.scales)

    def _click(self, m, ox, oy):
        return bool(m) and self.ctrl.click(m[0] + ox, m[1] + oy)

    def _press_esc(self, now, first):
        self.ctrl.press("esc")
        self._t_esc = now
        self._esc_tries = 1 if first else self._esc_tries + 1

    def _enter_countdown(self, now, score, note):
        self.state = State.B_COUNTDOWN
        self._t0 = now
        return StepResult(self.state, score, False, note)

    def step(self, frame, ox = 0, oy = 0):
        st = self.state
        if st is State.IDLE:
            return StepResult(st, note="idle")
        now = time.monotonic()
        if st is State.B_COUNTDOWN:
            return self._countdown(frame, now, ox, oy)
        if st is State.B_MENU:
            return self._menu(frame, now, ox, oy)
        if st is State.B_WAIT_MATCH:
            return self._loading(frame, now, ox, oy)
        return self._lobby(frame, now, ox, oy)

    def _lobby(self, frame, now, ox, oy):
        m, play_score = self._find("play", frame)
        if self._click(m, ox, oy):
            self.state = State.B_WAIT_MATCH
            return StepResult(self.state, play_score, True, "clicked play")
        for key in POPUP_KEYS:
            m, score = self._find(key, frame)
            if self._click(m, ox, oy):
                return StepResult(self.state, score, True, f"clicked {key} (stay)")

        m, score = self._find("menu_return", frame)
        if self._click(m, ox, oy):
            return StepResult(self.state, score, True, "clicked menu_return (retry)")

        m, score = self._find("hud", frame)
        if m:
            return self._enter_countdown(now, score, "island detected")
        return StepResult(self.state, play_score, False, "waiting play")

    def _loading(self, frame, now, ox, oy):
        m, hud_score = self._find("hud", frame)
        if m:
            return self._enter_countdown(now, hud_score, "island detected")
        m, score = self._find("play", frame)
        if self._click(m, ox, oy):
            return StepResult(self.state, score, True, "clicked play (retry)")
        return StepResult(self.state, hud_score, False, "waiting island")

    def _countdown(self, frame, now, ox, oy):
        remaining = self.s.wait_b - (now - self._t0)
        if remaining > 0:
            return StepResult(self.state, 0.0, False, f"waiting {math.ceil(remaining / 10) * 10}s")

        m, _ = self._find("menu_return", frame)
        if not m:
            m, _ = self._find("menu_btn", frame)
        if m:
            self.state, self._t_esc, self._esc_tries = State.B_MENU, now, 1
            return StepResult(self.state, 0.0, False, "menu already open")
        m, score = self._find("play", frame)
        if m:
            self.state = State.B_LOBBY
            return StepResult(self.state, score, False, "back in lobby")
        m, score = self._find("hud", frame)
        if not m and remaining > -ESC_GRACE_S:
            return StepResult(self.state, score, False, "island not visible")
        self.state = State.B_MENU
        self._press_esc(now, first=True)
        return StepResult(self.state, score, True, "pressed Esc")

    def _menu(self, frame, now, ox, oy):
        m, score = self._find("menu_return", frame)
        if m:
            if self._click(m, ox, oy):
                self.loops += 1
                self.state = State.B_LOBBY
                return StepResult(self.state, score, True, "clicked menu_return")
            return StepResult(self.state, score, False, "menu_return (cooldown)")
        m, score = self._find("menu_btn", frame)
        if m:
            if self._click(m, ox, oy):
                self._t_esc = now
                return StepResult(self.state, score, True, "clicked menu_btn")
            return StepResult(self.state, score, False, "menu_btn (cooldown)")
        m, score = self._find("play", frame)
        if m:
            self.state = State.B_LOBBY
            return StepResult(self.state, score, False, "back in lobby")
        if now - self._t_esc >= MENU_RETRY_S and self._esc_tries < MENU_MAX_ESC:
            self._press_esc(now, first=False)
            return StepResult(self.state, 0.0, True, f"pressed Esc again ({self._esc_tries})")
        if self._esc_tries >= MENU_MAX_ESC and now - self._t_esc >= 4 * MENU_RETRY_S:
            self._esc_tries = 0
        return StepResult(self.state, 0.0, False, "waiting menu")
