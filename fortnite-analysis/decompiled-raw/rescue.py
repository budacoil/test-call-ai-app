import queue
import re
import time
from typing import (Callable, List, Optional, Tuple)
STAGE2_AFTER_S = 120.0
MATCH_STUCK_S = 2100.0
ACTION_TTL_S = 60.0
ACTION_RE = re.compile('^(esc|click_center|restart_loop|grid:[A-D][1-4])$')
incoming: 'queue.Queue[str]' = queue.Queue(maxsize=8)

def valid_action(a) -> bool:
    return isinstance(a, str) and bool(ACTION_RE.match(a))

def push(action: str) -> bool:
    if not valid_action(action):
        return False
    try:
        incoming.put_nowait(action)
        return True
    except queue.Full:
        return False

def cell_center(action: str) -> Optional[Tuple[float, float]]:
    if action == 'click_center':
        return (0.5, 0.5)
    if action.startswith('grid:') and valid_action(action):
        col, row = ord(action[5]) - ord('A'), int(action[6]) - 1
        return (col + 0.5) / 4.0, (row + 0.5) / 4.0

class Rescue:
    def __init__(self, settings, ctrl, get_machine: Callable[[], object], find_popup: Optional[Callable[[object], Optional[Tuple[int, int]]]]=None, send_stuck: Optional[Callable[[str, int], None]]=None, log: Optional[Callable[[str], None]]=None, clock: Callable[[], float]=time.monotonic, source: Optional['queue.Queue[str]']=None):
        self.s = settings
        self.ctrl = ctrl
        self._machine = get_machine
        self._find_popup = find_popup
        self._send_stuck = send_stuck
        self.log = log or (lambda _m: None)
        self._clock = clock
        self._source = source if source is not None else incoming
        self._pending = []
        self.stage = 0
        self.last_frame = None
        self._state = None
        self._t_progress = clock()
        self._t_stage1 = 0.0

    @property
    def stuck(self) -> bool:
        return self.stage >= 1

    def progress(self) -> None:
        self._t_progress = self._clock()
        if self.stage:
            self.stage = 0
            self.s.rescue_listening = False

    def tick(self, state_value: str, clicked: bool, frame, ox: int=0, oy: int=0) -> None:
        try:
            self._tick(state_value, clicked, frame, ox, oy)
            return
        except Exception as e:
            self.log(f'[rescue] error: {type(e).__name__}: {e}')

    def _tick(self, state_value, clicked, frame, ox, oy) -> None:
        now = self._clock()
        self.last_frame = frame
        if clicked or state_value != self._state:
            self._state = state_value
            self.progress()
        self._intake(now)
        timeout = float(getattr(self.s, 'stuck_timeout_min', 0.0)) * 60.0
        if timeout > 0 and state_value == 'IN_MATCH':
            timeout = max(timeout, MATCH_STUCK_S)
        if timeout > 0:
            idle = now - self._t_progress
            if self.stage == 0 and idle >= timeout:
                self.stage, self._t_stage1 = 1, now
                self.log('[rescue] stuck detected, attempting Esc recovery')
                self.ctrl.press('esc')
                if self._find_popup is not None:
                    p = self._find_popup(frame)
                    if p:
                        self.ctrl.click(p[0] + ox, p[1] + oy)
            elif self.stage == 1 and now - self._t_stage1 >= STAGE2_AFTER_S:
                self.stage = 2
                minutes = int(idle // 60)
                self.log(f'[rescue] still stuck after {minutes} min: alerting')
                if self._send_stuck is not None:
                    self._send_stuck(str(state_value), minutes)
        elif self.stage:
            self.progress()
        self.s.rescue_listening = bool(self.stage >= 1 and getattr(self.s, 'rescue_remote_enabled', False))
        self._run_pending(now, frame, ox, oy)

    def _intake(self, now: float) -> None:
        while True:
            try:
                action = self._source.get_nowait()
            except queue.Empty:
                return
            if getattr(self.s, 'rescue_remote_enabled', False):
                if not self.stuck:
                    self.log(f'[rescue] remote action {action} ignored (the loop is not stuck)')
                    continue
            self._pending.append((action, now + ACTION_TTL_S))
            continue

    def _run_pending(self, now: float, frame, ox: int, oy: int) -> None:
        keep = []
        for action, deadline in self._pending:
            if now > deadline:
                self.log(f'[rescue] remote action {action} dropped (could not be executed)')
                continue
            if self._execute(action, now, frame, ox, oy):
                continue
            keep.append((action, deadline))
        self._pending = keep

    def _execute(self, action: str, now: float, frame, ox: int, oy: int) -> bool:
        if action == 'esc':
            self.ctrl.press('esc')
        elif action == 'restart_loop':
            m = self._machine()
            m.stop()
            m.start()
        else:
            pt = cell_center(action)
            if pt is None or frame is None:
                return True
            fh, fw = frame.shape[:2]
            if not self.ctrl.click(ox + int(pt[0] * fw), oy + int(pt[1] * fh)):
                return False
        self.log(f'[rescue] remote action {action} executed')
        self._t_progress = now
        self.stage = 0
        self.s.rescue_listening = False
        return True


