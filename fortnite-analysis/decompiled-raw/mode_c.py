import time
from typing import (Callable, Dict, Optional)
import numpy as np
from state_machine import (State, StateMachine, StepResult)
from mode_b import ModeB

class ModeC(ModeB):
    def __init__(self, settings, templates: Dict[str, Optional[np.ndarray]], controller, mode_a: StateMachine, clock: Callable[[], float]=time.monotonic):
        super().__init__(settings, templates, controller, clock)
        self._mode_a = mode_a

    def _wait_s(self) -> float:
        return self.s.wait_c

    def _countdown(self, frame, now, ox, oy) -> StepResult:
        m, score = self._find_one('item_found', frame)
        if m:
            self.log('item found: switching to mode A')
            self._mode_a.state = State.IN_MATCH
            self.s.mode = 'A'
            return StepResult(self.state, score, False, 'item found: switching to mode A')
        return super()._countdown(frame, now, ox, oy)


