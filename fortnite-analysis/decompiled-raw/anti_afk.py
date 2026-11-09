import contextlib
import random
import threading
import time
from typing import Callable, Optional
import config
from humanizer import Humanizer
DIVE_PITCH = 1400
DIVE_RESTORE = 0.55
PICKAXE_EVERY_S = (10.0, 30.0)

class _Guard:
    def __init__(self, stop, active: Callable[[], bool], slice_s: float=0.05):
        self._stop, self._active, self._slice = stop, active, slice_s

    def _alive(self) -> bool:
        try:
            return bool(self._active())
        except Exception:
            return False

    def is_set(self) -> bool:
        return self._stop.is_set() or not self._alive()

    def wait(self, timeout=None) -> bool:
        end = time.monotonic() + (timeout or 0.0)
        while True:
            if self.is_set():
                return True
            left = end - time.monotonic()
            if left <= 0:
                return False
            if self._stop.wait(min(self._slice, left)):
                return True


def _halted(stop) -> bool:
    f = getattr(stop, 'is_set', None)
    return bool(f and f())

def _default_key_down(key: str) -> None:
    import pydirectinput
    pydirectinput.keyDown(key)

def _default_key_up(key: str) -> None:
    import pydirectinput
    pydirectinput.keyUp(key)

class AntiAfk:
    def __init__(self, settings, active: Callable[[], bool], key_down: Optional[Callable[[str], None]]=None, key_up: Optional[Callable[[str], None]]=None, clock: Callable[[], float]=time.monotonic, focuser: Optional[Callable[[], object]]=None, swapper: Optional[Callable[..., object]]=None, defer: Optional[Callable[[], bool]]=None, post_down: Optional[Callable[[str], bool]]=None, post_up: Optional[Callable[[str], bool]]=None, look: Optional[Callable[[int, int, int], None]]=None, swing: Optional[Callable[[], object]]=None, dive_look: Optional[Callable[[int, int, int], None]]=None, rng: Optional[random.Random]=None, away: Optional[Callable[[], bool]]=None):
        self.s = settings
        self.active = active
        self._focuser = focuser
        self._swapper = swapper
        self._defer = defer
        self._post_down, self._post_up = post_down, post_up
        self._down = key_down or _default_key_down
        self._up = key_up or _default_key_up
        self._clock = clock
        self._look = look
        self._swing = swing
        self._dive_look = dive_look
        self._diving = threading.Event()
        self._away = away
        self._rng = rng or random.Random()
        self._hum = Humanizer()
        self._pickaxe_due = None
        self.last_pattern = ''
        self._ratio = 1.0
        self.last_hold = 0.0

    def _humanize(self) -> bool:
        return bool(getattr(self.s, 'humanizer_enabled', False))

    def _background(self) -> bool:
        return bool(self._swapper and getattr(self.s, 'background_mode', False))

    def _input_context(self):
        if self._background():
            return self._swapper('key', None)
        return contextlib.nullcontext()

    def _use_post(self) -> bool:
        return bool(self._background() and self._post_down and self._post_up and getattr(self.s, 'background_post_keys', False))

    def _can_look(self) -> bool:
        return bool(self._look and getattr(self.s, 'afk_mouse_look', True)) and not self._user_away()

    def _user_away(self) -> bool:
        try:
            return bool(self._background() and self._away and self._away())
        except Exception:
            return False

    def _look_around(self) -> None:
        if not self._can_look():
            return
        try:
            dx, dy, ms = self._hum.pitch.next_look()
            self._look(dx, dy, ms)
            return
        except Exception:
            return

    def _tap(self, key: str, dur: float) -> None:
        with self._input_context():
            self._down(key)
            try:
                if dur > 0:
                    time.sleep(dur)
            finally:
                self._up(key)

    def press_once(self, stop: threading.Event) -> str:
        if not self._humanize():
            self.last_pattern = '-'
            return self._strafe(stop)
        pat = self._hum.pattern()
        if pat == 'D' and not self._can_look():
            pat = 'A'
        self.last_pattern = pat
        try:
            if pat == 'B':
                return self._jump_walk(stop)
            if pat == 'C':
                return self._fidget(stop)
            if pat == 'D':
                return self._micro_pause(stop)
            if self._can_look() and self._rng.random() < 0.35 and not _halted(stop):
                self._look_around()
            return self._strafe(stop)
        except Exception:
            self.release_all()
            raise

    def _strafe(self, stop: threading.Event) -> str:
        key = random.choice(self.s.afk_keys)
        hold = self._hum.hold(self.s.afk_hold) if self._humanize() else self.s.afk_hold
        self.last_hold = hold
        posted = self._use_post() and self._post_down(key)
        if not posted:
            if self._focuser and not self._background():
                self._focuser()
            with self._input_context():
                self._down(key)
        try:
            tap = self._hum.side_tap(key, self.s.afk_keys, hold) if self._humanize() and not posted else None
            if tap is None:
                stop.wait(hold)
            else:
                lead, side, dur = tap
                stop.wait(lead)
                with self._input_context():
                    self._down(side)
                try:
                    stop.wait(dur)
                finally:
                    with self._input_context():
                        self._up(side)
                    try:
                        pass
                    finally:
                        if posted:
                            self._post_up(key)
                        with self._input_context():
                            self._up(key)
                stop.wait(max(0.0, hold - lead - dur))
        finally:
            if posted:
                self._post_up(key)
            with self._input_context():
                self._up(key)
        if posted:
            self._post_up(key)
            return key
        with self._input_context():
            self._up(key)
        return key

    def _jump_walk(self, stop: threading.Event) -> str:
        r = self._rng
        hold = self._hum.hold(self.s.afk_hold)
        self.last_hold = hold
        if self._focuser and not self._background():
            self._focuser()
        with self._input_context():
            self._down('w')
        try:
            lead = r.uniform(0.3, 0.8)
            if not (stop.wait(lead) or _halted(stop)):
                self._tap('space', r.uniform(0.08, 0.18))
                stop.wait(max(0.0, hold - lead))
        finally:
            with self._input_context():
                self._up('w')
        return 'w'

    def _fidget(self, stop: threading.Event) -> str:
        r = self._rng
        key = random.choice(self.s.afk_keys)
        self.last_hold = 0.0
        if self._focuser and not self._background():
            self._focuser()
        for n in range(2):
            if _halted(stop):
                break
            dur = r.uniform(0.12, 0.25)
            self.last_hold += dur
            self._tap(key, dur)
            if n == 0:
                stop.wait(r.uniform(0.06, 0.18))
        return key

    def _micro_pause(self, stop: threading.Event) -> str:
        r = self._rng
        self.last_hold = 0.0
        for _ in range(r.randint(1, 3)):
            if _halted(stop):
                return '-'
            self._look_around()
            if stop.wait(r.uniform(0.4, 1.2)):
                return '-'
        return '-'

    def pickaxe_swing(self, stop: threading.Event) -> bool:
        if not self._swing or self._user_away():
            return False
        r = self._rng
        slot = getattr(self.s, 'pickaxe_slot_key', '1') or '1'
        self.release_all()
        if self._focuser and not self._background():
            self._focuser()
        try:
            if _halted(stop):
                self.release_all()
                return False
        finally:
            self.release_all()
        try:
            self._tap(slot, r.uniform(0.08, 0.15))
            if stop.wait(r.uniform(0.2, 0.4)) or _halted(stop):
                self.release_all()
                return False
        finally:
            self.release_all()
        try:
            return bool(self._swing())
        finally:
            self.release_all()

    def dive_async(self, stop: threading.Event, log: Callable[[str], None]=(lambda _m: None)) -> bool:
        if self._diving.is_set():
            return False
        self._diving.set()
        def work() -> None:
            try:
                self.dive(stop, log)
            except Exception as e:
                log(f'bus drop error: {e}')
            finally:
                self.release_all()
                self._diving.clear()

        threading.Thread(target=work, daemon=True, name='pk-auto-dive').start()
        return True

    def dive(self, stop: threading.Event, log: Callable[[str], None]=(lambda _m: None)) -> bool:
        guard = _Guard(stop, self.active)
        r = self._rng
        self._diving.set()
        self.release_all()
        if self._focuser and not self._background():
            self._focuser()
        if guard.is_set():
            return False
        self._tap('space', r.uniform(0.08, 0.15))
        log('anti-afk: bus drop - jumped')
        if guard.wait(r.uniform(0.35, 0.7)):
            return False
        look = self._dive_look or self._look
        down = 0
        if look:
            if not guard.is_set():
                try:
                    for part in (0.6, 0.4):
                        look(r.randint(-12, 12), int(DIVE_PITCH * part), r.randint(260, 420))
                        down += int(DIVE_PITCH * part)
                        if guard.wait(0.12):
                            break
                except Exception:
                    pass
        secs = max(0.0, float(getattr(self.s, 'bus_dive_seconds', 8.0)))
        if secs > 0 and not guard.is_set():
            with self._input_context():
                self._down('w')
            try:
                guard.wait(secs)
            finally:
                with self._input_context():
                    self._up('w')
        if look and down and not guard.is_set():
            try:
                look(0, -int(down * DIVE_RESTORE), r.randint(300, 500))
            except Exception:
                pass
        self._hum.pitch.pitch = 0
        log('anti-afk: bus drop - done')
        return True

    def _pickaxe_delay(self) -> float:
        try:
            lo, hi = float(self.s.pickaxe_min_s), float(self.s.pickaxe_max_s)
        except Exception:
            lo, hi = PICKAXE_EVERY_S
        lo, hi = max(1.0, min(lo, hi)), max(1.0, max(lo, hi))
        return self._rng.uniform(lo, hi)

    def _pickaxe_tick(self, now: float, stop: threading.Event, log: Callable[[str], None]) -> None:
        if not getattr(self.s, 'pickaxe_afk_enabled', False) or not self._swing:
            self._pickaxe_due = None
            return
        if self._pickaxe_due is None:
            self._pickaxe_due = now + self._pickaxe_delay()
            return
        if not now < self._pickaxe_due:
            if self._defer and self._defer() or self.active():
                return
        self._pickaxe_due = now + self._pickaxe_delay()
        try:
            ok = self.pickaxe_swing(_Guard(stop, self.active))
            if ok:
                log('anti-afk: pickaxe swing')
                return
            None('anti-afk: pickaxe swing skipped')
            return
        except Exception as e:
            log(f'anti-afk pickaxe error: {e}')

    def _next_ratio(self, log: Callable[[str], None]) -> None:
        ratio = 1.0
        if self._humanize():
            ratio = self._hum.interval(1.0) * self._hum.session_factor()
        jitter = bool(getattr(self.s, 'jitter_enabled', False))
        if jitter:
            lo, hi = config.jitter_range(1.0, self.s)
            ratio *= self._rng.uniform(lo, hi)
        self._ratio = ratio
        if jitter:
            base = self.s.afk_interval
            lo, hi = config.jitter_range(base, self.s)
            log(f'[jitter] waiting for {base * ratio:.1f}s (range: {lo:.0f}s-{hi:.0f}s)')

    def release_all(self) -> None:
        with self._input_context():
            for k in self.s.afk_keys:
                try:
                    self._up(k)
                except Exception:
                    continue

    def run(self, stop: threading.Event, log: Callable[[str], None]=(lambda _m: None)) -> None:
        last = self._clock()
        try:
            while not stop.wait(0.2):
                now = self._clock()
                if self._diving.is_set():
                    last = now
                    continue
                if self.s.afk_enabled:
                    if not self.active():
                        last = now
                        self._pickaxe_due = None
                        continue
                self._pickaxe_tick(now, stop, log)
                if now - last < self.s.afk_interval * self._ratio:
                    continue
                if self._defer:
                    if self._defer():
                        continue
                last = now
                self._next_ratio(log)
                try:
                    guard = _Guard(stop, (lambda: self.s.afk_enabled and self.active()))
                    key = self.press_once(guard)
                    if guard.is_set():
                        self.release_all()
                    if self._humanize():
                        log(f'anti-afk: {self.last_pattern} {key.upper()} {self.last_hold:.1f}s')
                    else:
                        log(f'anti-afk: held {key.upper()} {self.s.afk_hold:g}s')
                except Exception as e:
                    log(f'anti-afk error: {e}')
        finally:
            self.release_all()


# WARNING: Decompyle incomplete
