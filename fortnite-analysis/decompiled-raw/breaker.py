import contextlib
import random
import threading
import time
from typing import Callable
_TL = threading.local()
QUOTA_COOLDOWN_S = (1800.0, 3600.0)
ERROR_BASE_S, ERROR_MAX_S = 120.0, 1800.0

class BreakerOpen(OSError):
    pass

class Breaker:
    def __init__(self, clock: Callable[[], float]=time.monotonic, rng=random):
        self._clock = clock
        self._rng = rng
        self._until = 0.0
        self._errors = 0
        self._lock = threading.Lock()
        self._local = _TL

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._until - self._clock())

    def blocked(self) -> bool:
        return self.remaining() > 0 and not getattr(self._local, 'override', False)

    def trip_quota(self) -> float:
        d = self._rng.uniform(*QUOTA_COOLDOWN_S)
        with self._lock:
            self._until = max(self._until, self._clock() + d)
            self._errors = 0
        return d

    def trip_error(self) -> float:
        with self._lock:
            self._errors += 1
            d = min(ERROR_MAX_S, ERROR_BASE_S * 2 ** (self._errors - 1)) * self._rng.uniform(1.0, 1.25)
            d = min(d, ERROR_MAX_S)
            self._until = max(self._until, self._clock() + d)
        return d

    def trip_for(self, seconds: float) -> float:
        with self._lock:
            self._until = max(self._until, self._clock() + seconds)
        return seconds

    def success(self) -> None:
        with self._lock:
            self._errors = 0

    def reset(self) -> None:
        with self._lock:
            self._until, self._errors = 0.0, 0

    @contextlib.contextmanager
    def override(self):
        self._local.override = True
        try:
            yield None
        finally:
            self._local.override = False


BREAKER = Breaker()
