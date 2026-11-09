import math
import time
from typing import (Callable, Dict, Optional)
import numpy as np
import config
from autocal import AutoCalibrator, still_visible
from state_machine import (POPUP_KEYS, REWARD_KEYS, RewardCounter, State, StepResult, note_claim, visible_rewards)
import squad_bar
from mode_fix import ModeFix
from reward_fallback import RewardFallback
from survey import SurveyGuard
from vision import (Plate, aim_point, find_checked, find_plate, find_template)
LOAD_FALLBACK_S = 150.0
ESC_GRACE_S = 30.0
MENU_RETRY_S = 8.0
MENU_MAX_ESC = 3
SPACE_STOP_LEAD_S = 10.0
SQUAD_START_S = 100.0
SQUAD_EVERY_S = 10.0
SQUAD_MAX_SIZE = 2
SQUAD_CONFIRM = 2

class ModeB:
    def __init__(self, settings, templates: Dict[str, Optional[np.ndarray]], controller, clock: Callable[[], float]=time.monotonic):
        self.s = settings
        self.templates = templates
        self.ctrl = controller
        self._clock = clock
        self.state = State.IDLE
        self.loops = 0
        self.rewards = RewardCounter(clock)
        self.claims = 0
        self.on_claim = None
        self.log = lambda _m: None
        self.cal = AutoCalibrator(settings, clock, log=(lambda m: self.log(m)))
        self.modefix = ModeFix(settings, clock, log=(lambda m: self.log(m)))
        self.survey = SurveyGuard(clock)
        self.fallback = RewardFallback(clock)
        self._t0 = 0.0
        self._load_since = None
        self._wait_k = 1.0
        self._t_esc = 0.0
        self._esc_tries = 0
        self._space_locked = False
        self._squad_next = 0.0
        self._squad_low_n = 0
        self._squad_hit = False
        self.squad_last = 0

    def start(self) -> None:
        if self.state is State.IDLE:
            self.state = State.B_LOBBY

    def match_active(self) -> bool:
        if self.state is not State.B_COUNTDOWN or self._space_locked:
            return False
        if self._squad_hit:
            self._space_locked = True
            return False
        if self._wait_now() - (self._clock() - self._t0) <= SPACE_STOP_LEAD_S:
            self._space_locked = True
            return False
        return True

    def stop(self) -> None:
        self.state = State.IDLE

    def _wait_s(self) -> float:
        return self.s.wait_b

    def _wait_now(self) -> float:
        return self._wait_s() * self._wait_k

    def _find(self, key: str, frame: np.ndarray):
        if key == 'play':
            m, score = self._find_one(key, frame)
            if m:
                return m, score
            m2, score2 = self._find_one('storefront_play', frame)
            if m2:
                return m2, score2
            return None, max(score, score2)
        return self._find_one(key, frame)

    def _find_one(self, key: str, frame: np.ndarray):
        tpl = self.templates.get(key)
        if tpl is None:
            return (None, 0.0)
        if isinstance(tpl, Plate):
            plate = self.cal.plate(key, tpl)
            return find_checked(frame, key, tpl, (lambda f: find_plate(f, plate, self.s.scales)))
        thr = self.cal.threshold_for(key, self.s.threshold)
        return find_checked(frame, key, tpl, (lambda f: find_template(f, tpl, thr, self.s.scales)))

    def _calibrate(self, frame, key: str, score: float, ox: int, oy: int, nxt: State, finishes_loop: bool=False) -> bool:
        tpl = self.templates.get(key)
        base = tpl.threshold if isinstance(tpl, Plate) else self.s.threshold
        if not self.cal.attempt(self.state, frame, key, tpl, score, base, ox, oy, self.ctrl.click, self.s.scales, meta={'prev': self.state, 'fin': finishes_loop}):
            return False
        if finishes_loop:
            self.loops += 1
        self.state = nxt
        return True

    def _click(self, m, ox: int, oy: int, key: str='') -> bool:
        if not m:
            return False
        x, y = aim_point(key, self.templates.get(key), m) if key else (m[0], m[1])
        return self.ctrl.click(x + ox, y + oy)

    def _press_esc(self, now: float, first: bool) -> None:
        self.ctrl.press('esc')
        self._t_esc = now
        if first:
            self._esc_tries = 1
            return
        self._esc_tries = self._esc_tries + 1

    def _enter_countdown(self, now: float, score: float, note: str) -> StepResult:
        self.state = State.B_COUNTDOWN
        self._t0 = now
        self._load_since = None
        self._space_locked = False
        base = self._wait_s()
        w = config.get_jittered_wait(base, self.s)
        self._wait_k = w / base if base > 0 else 1.0
        if getattr(self.s, 'jitter_enabled', False):
            lo, hi = config.jitter_range(base, self.s)
            self.log(f'[jitter] waiting for {w:.1f}s (range: {lo:.0f}s-{hi:.0f}s)')
        self._squad_next, self._squad_low_n, self._squad_hit, self.squad_last = 0.0, 0, False, 0
        return StepResult(self.state, score, False, note)

    def step(self, frame: np.ndarray, ox: int=0, oy: int=0) -> StepResult:
        if self.state is State.IDLE:
            return StepResult(self.state, note='idle')
        self.cal.check(self.state)
        j = self.cal.judge((lambda k, thr, pos: still_visible(frame, self.templates.get(k), thr, pos, self.s.scales)))
        if j is not None and j[0] == 'fail':
            self.state = j[1]['prev']
            self.loops -= 1 if j[1]['fin'] else 0
        seen = visible_rewards(frame, self.templates, self.s)
        r = self._step(frame, ox, oy)
        self.rewards.update(r.key if r.clicked else '', seen)
        if r.clicked:
            self.fallback.reset()
        if r.clicked and r.key in REWARD_KEYS:
            note_claim(self, r.key, frame)
        return r

    def _step(self, frame: np.ndarray, ox: int=0, oy: int=0) -> StepResult:
        st = self.state
        now = self._clock()
        if st is State.B_COUNTDOWN:
            return self._countdown(frame, now, ox, oy)
        if st is State.B_MENU:
            return self._menu(frame, now, ox, oy)
        if st is State.B_WAIT_MATCH:
            return self._loading(frame, now, ox, oy)
        self._load_since = None
        return self._lobby(frame, now, ox, oy)

    def _lobby(self, frame, now, ox, oy) -> StepResult:
        if self.ctrl.ready():
            fx = self.modefix.poll(frame)
            if fx and self.ctrl.click(fx[0] + ox, fx[1] + oy):
                return StepResult(self.state, 0.0, True, fx[2])
        m, play_score = self._find('play', frame)
        if self._click(m, ox, oy, 'play'):
            self.state = State.B_WAIT_MATCH
            return StepResult(self.state, play_score, True, 'clicked play')
        for key in POPUP_KEYS:
            m, score = self._find(key, frame)
            if self._click(m, ox, oy):
                return StepResult(self.state, score, True, f'clicked {key} (stay)', key)
        pt = self.survey.poll(frame)
        if pt and self.ctrl.click(pt[0] + ox, pt[1] + oy):
            return StepResult(self.state, 0.0, True, 'clicked survey skip (stay)', 'survey')
        m, score = self._find('menu_return', frame)
        if self._click(m, ox, oy):
            return StepResult(self.state, score, True, 'clicked menu_return (retry)')
        m, score = self._find('hud', frame)
        if m:
            return self._enter_countdown(now, score, 'island detected')
        if self._calibrate(frame, 'play', play_score, ox, oy, State.B_WAIT_MATCH):
            return StepResult(self.state, play_score, True, 'auto-calibrate test click on play')
        pt = self.fallback.poll(frame)
        if pt and self.ctrl.click(pt[0] + ox, pt[1] + oy):
            return StepResult(self.state, 0.0, True, 'clicked reward button (fallback)', 'claim_single')
        return StepResult(self.state, play_score, False, 'waiting play')

    def _loading(self, frame, now, ox, oy) -> StepResult:
        m, hud_score = self._find('hud', frame)
        if m:
            return self._enter_countdown(now, hud_score, 'island detected')
        m, score = self._find('play', frame)
        if self._click(m, ox, oy, 'play'):
            self._load_since = None
            return StepResult(self.state, score, True, 'clicked play (retry)')
        if not m:
            if self._load_since is None:
                self._load_since = now
            elif now - self._load_since >= LOAD_FALLBACK_S:
                self.log('island HUD not recognised: assuming the island')
                self._load_since = None
                return self._enter_countdown(now, hud_score, 'island assumed (HUD not recognised)')
        return StepResult(self.state, hud_score, False, 'waiting island')

    def _squad_small(self, frame, now) -> bool:
        try:
            if not getattr(self.s, 'squad_check_enabled', False):
                return False
            if self._squad_hit:
                return True
            if now - self._t0 < SQUAD_START_S or now < self._squad_next:
                return False
            self._squad_next = now + SQUAD_EVERY_S
            if not self._find('hud', frame)[0]:
                return False
            self.squad_last = squad_bar.squad_size(frame)
            self._squad_low_n = self._squad_low_n + 1 if self.squad_last <= SQUAD_MAX_SIZE else 0
            self._squad_hit = self._squad_low_n >= SQUAD_CONFIRM
            if self._squad_hit:
                self.log(f'squad of {self.squad_last}: leaving the island')
        except Exception:
            return False
        return self._squad_hit

    def _countdown(self, frame, now, ox, oy) -> StepResult:
        remaining = self._wait_now() - (now - self._t0)
        if remaining > 0 and not self._squad_small(frame, now):
            return StepResult(self.state, 0.0, False, f'waiting {math.ceil(remaining / 10) * 10}s')
        m, _ = self._find('menu_return', frame)
        if not m:
            m, _ = self._find('menu_btn', frame)
        if m:
            self.state, self._t_esc, self._esc_tries = State.B_MENU, now, 1
            return StepResult(self.state, 0.0, False, 'menu already open')
        m, score = self._find('play', frame)
        if m:
            self.state = State.B_LOBBY
            return StepResult(self.state, score, False, 'back in lobby')
        m, score = self._find('hud', frame)
        if not m:
            if remaining > -ESC_GRACE_S:
                return StepResult(self.state, score, False, 'island not visible')
        self.state = State.B_MENU
        self._press_esc(now, first=True)
        return StepResult(self.state, score, True, 'pressed Esc (small squad)' if self._squad_hit else 'pressed Esc')

    def _menu(self, frame, now, ox, oy) -> StepResult:
        m, score = self._find('menu_return', frame)
        ret_score = score
        if m:
            if self._click(m, ox, oy):
                self.loops += 1
                self.state = State.B_LOBBY
                return StepResult(self.state, score, True, 'clicked menu_return')
            return StepResult(self.state, score, False, 'menu_return (cooldown)')
        m, score = self._find('menu_btn', frame)
        if m:
            if self._click(m, ox, oy):
                self._t_esc = now
                return StepResult(self.state, score, True, 'clicked menu_btn')
            return StepResult(self.state, score, False, 'menu_btn (cooldown)')
        m, score = self._find('play', frame)
        if m:
            self.state = State.B_LOBBY
            return StepResult(self.state, score, False, 'back in lobby')
        if now - self._t_esc >= MENU_RETRY_S and self._esc_tries < MENU_MAX_ESC:
            self._press_esc(now, first=False)
            return StepResult(self.state, 0.0, True, f'pressed Esc again ({self._esc_tries})')
        if self._esc_tries >= MENU_MAX_ESC and now - self._t_esc >= 4 * MENU_RETRY_S:
            self._esc_tries = 0
        if self._calibrate(frame, 'menu_return', ret_score, ox, oy, State.B_LOBBY, True):
            return StepResult(self.state, ret_score, True, 'auto-calibrate test click on menu_return')
        return StepResult(self.state, 0.0, False, 'waiting menu')


