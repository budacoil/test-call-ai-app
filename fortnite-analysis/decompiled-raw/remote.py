import threading
from typing import (Callable, Dict, Optional)
import time
import telemetry
SYNC_INTERVAL_S = 900.0
MIN_INTERVAL_S, MAX_INTERVAL_S = 60.0, 900.0
FIRST_DELAY_S = 3.0
RESCUE_POLL_S = 60.0
RESCUE_MAX_POLLS = 30
SHOT_POLL_S = 90.0
LANGS = ('ja', 'en', 'es', 'pt', 'ru', 'fr')

def _bounded(v, lo: float, hi: float) -> Optional[float]:
    if v is None or isinstance(v, (bool, str)):
        return
    try:
        v = float(v)
    except (TypeError, ValueError):
        return
    if v != v or v in (float('inf'), float('-inf')):
        return
    return min(hi, max(lo, v))

def clean_config(c) -> Dict[str, object]:
    out = {}
    if not isinstance(c, dict):
        return out
    if c.get('mode') in ('A', 'B', 'C'):
        out['mode'] = c['mode']
    if c.get('lang') in LANGS:
        out['lang'] = c['lang']
    for key, lo, hi, nd in (('wait_b', 10, 600, 0), ('wait_c', 10, 600, 0), ('afk_interval', 1, 600, 0), ('afk_hold', 0.5, 30, 1)):
        v = _bounded(c.get(key), lo, hi)
        if v is not None:
            v = min(hi, max(lo, v))
            out[key] = round(v) if nd == 0 else round(v, nd)
    v = _bounded(c.get('report_hours'), 0, 24)
    if v is not None:
        v = min(24.0, max(0.0, v))
        out['report_hours'] = 0.0 if v == 0 else max(0.5, round(v, 1))
    if isinstance(c.get('afk_enabled'), bool):
        out['afk_enabled'] = c['afk_enabled']
    return out

def current_of(s) -> Dict[str, object]:
    return {'mode': s.mode, 'lang': s.lang, 'wait_b': round(float(s.wait_b)), 'wait_c': round(float(s.wait_c)), 'report_hours': float(s.report_hours), 'afk_enabled': bool(s.afk_enabled), 'afk_interval': round(float(s.afk_interval)), 'afk_hold': round(float(s.afk_hold), 1)}

def apply_config(s, cfg) -> Dict[str, tuple]:
    changed = {}
    for k, v in clean_config(cfg).items():
        old = getattr(s, k)
        if old != v:
            setattr(s, k, v)
            changed[k] = old, v
    return changed

class RemoteSync:
    def __init__(self, settings, on_config: Callable[[dict, int], None], on_shot: Optional[Callable[[str], None]]=None, on_rescue: Optional[Callable[[str], None]]=None, post: Optional[Callable[[str, dict], dict]]=None, interval: float=SYNC_INTERVAL_S, log: Optional[Callable[[str], None]]=None, active: Optional[Callable[[], bool]]=None, clock: Callable[[], float]=time.monotonic):
        self.s = settings
        self.on_config = on_config
        self.on_shot = on_shot
        self.on_rescue = on_rescue
        self.rescue_done = ''
        self.shot_done = ''
        self._post = post or telemetry._http_post
        self.interval = interval
        self.log = log or (lambda _m: None)
        self._active = active or (lambda: True)
        self._clock = clock
        self._last_answer = -1000000000.0
        self._rescue_polls = 0
        self.applied_rev = 0
        self._last_failure = ''
        self._last_key = ''
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    def _log_failure(self, e: BaseException) -> None:
        kind, text = telemetry.classify_error(e)
        line = f'remote: {type(e).__name__} ({kind}) {text}'
        if line != self._last_failure:
            self._last_failure = line
            self.log(line)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name='pk-auto-remote')
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poke(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        self._wake.wait(FIRST_DELAY_S)
        forced = True
        while not self._stop.is_set():
            self._wake.clear()
            try:
                if forced or self._active() and not self._fresh():
                    self.poll_once()
            except Exception as e:
                self._log_failure(e)
            forced = self._sleep()

    def _fresh(self) -> bool:
        return self._clock() - self._last_answer < self.interval * 0.5

    def _rescue_fast(self) -> bool:
        return bool(getattr(self.s, 'rescue_listening', False) and self.on_rescue and self._rescue_polls < RESCUE_MAX_POLLS)

    def _sleep(self) -> bool:
        waited = 0.0
        while not self._stop.is_set():
            step = min(5.0, self.interval - waited)
            if step <= 0:
                return False
            if self._wake.wait(step):
                return True
            waited += step
            if self._rescue_fast() and waited >= RESCUE_POLL_S:
                return False
        return False

    def piggy_body(self) -> dict:
        s = self.s
        if s.remote_enabled:
            if not telemetry.valid_link_key(telemetry.clean_key(s.discord_link_key or '')):
                return {}
        body = {'applied_rev': self.applied_rev}
        self._flags(body)
        return body

    def _flags(self, body: dict) -> None:
        s = self.s
        if getattr(s, 'screenshot_enabled', False) and self.on_shot:
            body['shot'], body['shot_done'] = True, self.shot_done
        if getattr(s, 'rescue_listening', False):
            if self.on_rescue:
                body['rescue'], body['rescue_done'] = True, self.rescue_done

    def poll_once(self) -> Optional[str]:
        s = self.s
        key = telemetry.clean_key(s.discord_link_key or '')
        if not s.remote_enabled or not telemetry.valid_link_key(key) or not telemetry.valid_endpoint(s.telemetry_api_url):
            return
        if key != self._last_key:
            self._last_key, self.applied_rev = key, 0
        try:
            body = {'link_key': key, 'applied_rev': self.applied_rev, 'current': current_of(s)}
            self._flags(body)
            ans = self._post(telemetry.api_url(s.telemetry_api_url, '/api/sync'), body)
        except Exception as e:
            self._log_failure(e)
        return self.handle_answer(ans)

    def handle_answer(self, ans) -> Optional[str]:
        s = self.s
        if not isinstance(ans, dict) or ans.get('ok') is not True:
            return
        self._last_answer = self._clock()
        hint = _bounded(ans.get('poll_hint_s'), MIN_INTERVAL_S, MAX_INTERVAL_S)
        if hint is None:
            hint = _bounded(ans.get('poll_s'), MIN_INTERVAL_S, MAX_INTERVAL_S)
        if hint is not None:
            self.interval = hint
        if getattr(s, 'rescue_listening', False) and self.on_rescue:
            self._rescue_polls += 1
            if self._rescue_polls <= RESCUE_MAX_POLLS:
                self.interval = min(self.interval, RESCUE_POLL_S)
            r = ans.get('rescue_req')
            if isinstance(r, dict) and isinstance(r.get('id'), str) and r['id'].isdigit() and r['id'] != self.rescue_done:
                self.rescue_done = r['id']
                try:
                    self.on_rescue(str(r.get('action', '')))
                except Exception:
                    pass
        else:
            self._rescue_polls = 0
        if getattr(s, 'screenshot_enabled', False) and self.on_shot:
            self.interval = min(self.interval, SHOT_POLL_S)
            req = ans.get('shot_req')
            if isinstance(req, str) and req.isdigit() and req != self.shot_done:
                self.shot_done = req
                try:
                    self.on_shot(req)
                except Exception:
                    pass
        try:
            rev = int(ans.get('rev', 0))
        except (TypeError, ValueError):
            return
        if rev < self.applied_rev:
            self.applied_rev = rev
            return 'idle'
        cfg = clean_config(ans.get('config'))
        if rev > self.applied_rev:
            if cfg:
                self.on_config(cfg, rev)
            self.applied_rev = rev
            return 'applied' if cfg else 'idle'
        return 'idle'


