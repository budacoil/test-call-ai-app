import time
from dataclasses import dataclass
from enum import Enum
from typing import (Callable, Dict, Optional)
import numpy as np
from autocal import AutoCalibrator, still_visible
from mode_fix import ModeFix
from reward_fallback import RewardFallback
from survey import SurveyGuard
from vision import (Plate, aim_point, find_checked, find_plate, find_template)

class State(Enum):
    IDLE = 'IDLE'
    SEARCHING_PLAY = 'SEARCHING_PLAY'
    IN_MATCH = 'IN_MATCH'
    SKIPPING_RESULT = 'SKIPPING_RESULT'
    RETURNING_LOBBY = 'RETURNING_LOBBY'
    B_LOBBY = 'B:LOBBY'
    B_WAIT_MATCH = 'B:LOADING'
    B_COUNTDOWN = 'B:WAITING'
    B_MENU = 'B:MENU'

STAGES = [(State.SEARCHING_PLAY, 'play'), (State.IN_MATCH, 'continue'), (State.SKIPPING_RESULT, 'skip'), (State.RETURNING_LOBBY, 'return_lobby')]
POPUP_KEYS = ('claim', 'claim_single', 'popup')
REWARD_KEYS = ('claim', 'claim_single')

@dataclass
class StepResult:
    state: State
    score: float = 0.0
    clicked: bool = False
    note: str = ''
    key: str = ''

def note_claim(machine, key: str, frame: np.ndarray) -> None:
    machine.claims += 1
    cb = machine.on_claim
    if cb is not None:
        try:
            cb(key, frame, machine.loops)
            return
        except Exception:
            pass

def visible_rewards(frame: np.ndarray, templates: Dict[str, Optional[np.ndarray]], settings) -> set:
    seen = set()
    for key in REWARD_KEYS:
        tpl = templates.get(key)
        if tpl is None:
            continue
        if isinstance(tpl, Plate):
            m, _ = find_plate(frame, tpl, settings.scales)
        else:
            m, _ = find_template(frame, tpl, settings.threshold, settings.scales)
        if m:
            seen.add(key)
    return seen

class RewardCounter:
    def __init__(self, clock: Callable[[], float]=time.monotonic):
        self.count = 0
        self._pending = set()

    def update(self, clicked_key: str, seen: set) -> None:
        if clicked_key in REWARD_KEYS:
            self._pending.add(clicked_key)
        for key in list(self._pending):
            if key in seen or key == clicked_key:
                continue
            self.count += 1
            self._pending.discard(key)


class StateMachine:
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

    def start(self) -> None:
        if self.state is State.IDLE:
            self.state = State.SEARCHING_PLAY

    def stop(self) -> None:
        self.state = State.IDLE

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
        if self.state is State.SEARCHING_PLAY and self.ctrl.ready():
            fx = self.modefix.poll(frame)
            if fx and self.ctrl.click(fx[0] + ox, fx[1] + oy):
                return StepResult(self.state, 0.0, True, fx[2])
        idx = next((i for i, (st, _) in enumerate(STAGES) if st is self.state))
        own_key = STAGES[idx][1]
        n = len(STAGES)
        cands = []
        for i in range(idx, n):
            key = STAGES[i][1]
            if idx == 0 and key == 'continue':
                cands.append((key, None, False))
            else:
                cands.append((key, STAGES[(i + 1) % n][0], key == 'return_lobby'))
        if idx >= 1:
            cands.append((STAGES[idx - 1][1], None, False))
        if idx >= 2:
            cands.append(('play', State.IN_MATCH, False))
        cands = cands + [('storefront_play', nxt, fin) for key, nxt, fin in cands if key == 'play']
        for key in POPUP_KEYS:
            cands.append((key, None, False))
        own_score = 0.0
        for key, nxt, finishes_loop in cands:
            tpl = self.templates.get(key)
            if tpl is None:
                continue
            if isinstance(tpl, Plate):
                plate = self.cal.plate(key, tpl)
                m, score = find_checked(frame, key, tpl, (lambda f: find_plate(f, plate, self.s.scales)))
            else:
                thr = self.cal.threshold_for(key, self.s.threshold)
                m, score = find_checked(frame, key, tpl, (lambda f: find_template(f, tpl, thr, self.s.scales)))
            if key == own_key:
                own_score = score
            if not m:
                continue
            if not self.ctrl.click(*(a + o for a, o in zip(aim_point(key, tpl, m), (ox, oy)))):
                continue
            if nxt is None:
                return StepResult(self.state, score, True, f'clicked {key} (stay)', key)
            if finishes_loop:
                self.loops += 1
            self.state = nxt
            return StepResult(self.state, score, True, f'clicked {key}', key)
        own_tpl = self.templates.get(own_key)
        if own_tpl is None:
            return StepResult(self.state, 0.0, False, f'{own_key} template missing')
        base = own_tpl.threshold if isinstance(own_tpl, Plate) else self.s.threshold
        own_nxt, own_fin = next(((n, f) for k, n, f in cands if k == own_key), (None, False))
        if self.cal.attempt(self.state, frame, own_key, own_tpl, own_score, base, ox, oy, self.ctrl.click, self.s.scales, meta={'prev': self.state, 'fin': own_fin}):
            if own_fin:
                self.loops += 1
            if own_nxt is not None:
                self.state = own_nxt
            return StepResult(self.state, own_score, True, f'auto-calibrate test click on {own_key}')
        if self.state is State.SEARCHING_PLAY:
            pt = self.survey.poll(frame)
            if pt and self.ctrl.click(pt[0] + ox, pt[1] + oy):
                return StepResult(self.state, 0.0, True, 'clicked survey skip (stay)', 'survey')
            pt = self.fallback.poll(frame)
            if pt and self.ctrl.click(pt[0] + ox, pt[1] + oy):
                return StepResult(self.state, 0.0, True, 'clicked reward button (fallback)', 'claim_single')
        return StepResult(self.state, own_score, False, f'waiting {own_key}')


