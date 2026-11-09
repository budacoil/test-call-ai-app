from dataclasses import dataclass
from enum import Enum

from vision import Plate, find_plate, find_template

class State(Enum):
    IDLE = "IDLE"
    SEARCHING_PLAY = "SEARCHING_PLAY"
    IN_MATCH = "IN_MATCH"
    SKIPPING_RESULT = "SKIPPING_RESULT"
    RETURNING_LOBBY = "RETURNING_LOBBY"

    B_LOBBY = "B:LOBBY"
    B_WAIT_MATCH = "B:LOADING"
    B_COUNTDOWN = "B:WAITING"
    B_MENU = "B:MENU"

STAGES = [
    (State.SEARCHING_PLAY, "play"),
    (State.IN_MATCH, "continue"),
    (State.SKIPPING_RESULT, "skip"),
    (State.RETURNING_LOBBY, "return_lobby"),
]

POPUP_KEYS = ("claim", "claim_single", "popup")

@dataclass
class StepResult:
    state: State
    score: float = 0.0
    clicked: bool = False
    note: str = ""

class StateMachine:
    def __init__(self, settings, templates, controller):
        self.s = settings
        self.templates = templates
        self.ctrl = controller
        self.state = State.IDLE
        self.loops = 0

    def start(self):
        if self.state is State.IDLE:
            self.state = State.SEARCHING_PLAY

    def stop(self):
        self.state = State.IDLE

    def step(self, frame, ox = 0, oy = 0):
        if self.state is State.IDLE:
            return StepResult(self.state, note="idle")

        idx = next(i for i, (st, _) in enumerate(STAGES) if st is self.state)
        own_key = STAGES[idx][1]
        n = len(STAGES)

        cands = []

        for i in range(idx, n):
            key = STAGES[i][1]
            if idx == 0 and key == "continue":
                cands.append((key, None, False))
            else:
                cands.append((key, STAGES[(i + 1) % n][0], key == "return_lobby"))

        if idx >= 1:
            cands.append((STAGES[idx - 1][1], None, False))

        if idx >= 2:
            cands.append(("play", State.IN_MATCH, False))

        for key in POPUP_KEYS:
            cands.append((key, None, False))

        own_score = 0.0
        for key, nxt, finishes_loop in cands:
            tpl = self.templates.get(key)
            if tpl is None:
                continue
            if isinstance(tpl, Plate):
                m, score = find_plate(frame, tpl, self.s.scales)
            else:
                m, score = find_template(frame, tpl, self.s.threshold, self.s.scales)
            if key == own_key:
                own_score = score
            if m and self.ctrl.click(m[0] + ox, m[1] + oy):
                if nxt is None:
                    return StepResult(self.state, score, True, f"clicked {key} (stay)")
                if finishes_loop:
                    self.loops += 1
                self.state = nxt
                return StepResult(self.state, score, True, f"clicked {key}")
        if self.templates.get(own_key) is None:
            return StepResult(self.state, 0.0, False, f"{own_key} template missing")
        return StepResult(self.state, own_score, False, f"waiting {own_key}")
