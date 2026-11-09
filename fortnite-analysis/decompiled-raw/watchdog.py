import re
import time
from typing import Callable, Optional
MIN_GAP_S = 600.0
REPEAT_LIMIT = 30
ERROR_LIMIT = 3
STALL_S = 1800.0
MAX_DETAIL = 300
_PATH_RE = re.compile('[A-Za-z]:[\\\\/][^\\s\'\\"<>|]*|(?:\\\\\\\\|/)(?:[\\w.\\-]+[\\\\/])+[\\w.\\-]*')

def clean_detail(text) -> str:
    s = _PATH_RE.sub('<path>', str(text))
    return ' '.join(s.split())[:MAX_DETAIL]

class Watchdog:
    def __init__(self, notify: Callable[[str, str], None], clock: Callable[[], float]=time.monotonic, min_gap: float=MIN_GAP_S, repeat_limit: int=REPEAT_LIMIT, error_limit: int=ERROR_LIMIT, stall_s: float=STALL_S):
        self._notify = notify
        self._clock = clock
        self.min_gap = min_gap
        self.repeat_limit = repeat_limit
        self.error_limit = error_limit
        self.stall_s = stall_s
        self.start()

    def start(self) -> None:
        self._last_alert = None
        self._held = 0
        self._key = ''
        self._repeat = 0
        self._errors = 0
        self._last_action = self._clock()
        self._stall_reported = False

    def action(self, key: str) -> None:
        self._last_action = self._clock()
        self._stall_reported = False
        if key == self._key:
            self._repeat += 1
        else:
            self._key, self._repeat = key, 1
        if self._repeat >= self.repeat_limit:
            n, self._repeat = self._repeat, 0
            self._fire('repeat', f'{key} x{n}')

    def ok(self) -> None:
        self._errors = 0

    def error(self, text) -> None:
        self._errors += 1
        if self._errors >= self.error_limit:
            n, self._errors = self._errors, 0
            self._fire('error', f'{clean_detail(text)} (x{n})')

    def fatal(self, text) -> None:
        self._fire('error', f'worker stopped: {clean_detail(text)}')

    def tick(self) -> None:
        if not self._stall_reported:
            if self._clock() - self._last_action >= self.stall_s:
                self._stall_reported = True
                self._fire('stalled', f'no click for {int((self._clock() - self._last_action) // 60)} min')

    def _fire(self, code: str, detail: str) -> None:
        now = self._clock()
        if self._last_alert is not None and now - self._last_alert < self.min_gap:
            self._held += 1
            return
        if self._held:
            detail += f' (+{self._held} held back)'
            self._held = 0
        self._last_alert = now
        try:
            self._notify(code, detail)
            return
        except Exception:
            return


