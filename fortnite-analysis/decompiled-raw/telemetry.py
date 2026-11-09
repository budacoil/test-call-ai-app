import json
import socket
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import deque
from typing import (Callable, Dict, List, Optional, Tuple)
import breaker
import relay
import netfix
KEY_PREFIX = 'LAP-'
MAX_GRID_B64 = 100000
MIN_ACTIONS = 5
WINDOW_S = 60.0
PERIODIC_RETRY_S = 180.0
HTTP_TIMEOUT_S = 15.0
PLACEHOLDER = 'your-worker'
OK, INVALID_KEY, NO_URL, NETWORK, DM_CLOSED, RATE_LIMITED, SERVER = 'ok', 'invalid_key', 'no_url', 'network', 'dm_closed', 'rate_limited', 'server'
NETWORK_DNS, NETWORK_TLS, NETWORK_TIMEOUT, NETWORK_BLOCKED = 'network_dns', 'network_tls', 'network_timeout', 'network_blocked'
BLOCKED_WINERRORS = (10013, 10053, 10054, 10061)

def classify_error(e: BaseException) -> Tuple[str, str]:
    reason = getattr(e, 'reason', None)
    if not isinstance(reason, BaseException):
        reason = e
    text = f'{type(reason).__name__}: {reason}'[:200]
    low = str(reason).lower()
    code = getattr(reason, 'winerror', None) or getattr(reason, 'errno', None)
    if isinstance(reason, socket.gaierror):
        kind = 'dns'
        return kind, text
    if isinstance(reason, ssl.SSLError) or 'certificate' in low or 'ssl' in type(reason).__name__.lower():
        kind = 'tls'
        return kind, text
    if isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in low:
        kind = 'timeout'
        return kind, text
    if isinstance(reason, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, PermissionError)) or code in BLOCKED_WINERRORS:
        kind = 'blocked'
        return kind, text
    kind = 'other'
    return kind, text

def network_status(kind: str) -> str:
    return {'dns': NETWORK_DNS, 'tls': NETWORK_TLS, 'timeout': NETWORK_TIMEOUT, 'blocked': NETWORK_BLOCKED}.get(kind, NETWORK)

def is_cert_error(e: BaseException) -> bool:
    reason = getattr(e, 'reason', None)
    if not isinstance(reason, BaseException):
        reason = e
    return isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(reason)

def bundled_context() -> Optional[ssl.SSLContext]:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return

def _open(req: urllib.request.Request, timeout: float):
    pref = netfix.preferred()
    if pref:
        try:
            return netfix.open_with(pref, req, timeout)
        except urllib.error.HTTPError:
            raise
        except Exception:
            pass
    try:
        return _open_basic(req, timeout)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError:
        try:
            r = netfix.rescue(req, timeout)
        except urllib.error.HTTPError:
            raise
        except Exception:
            r = None
        if r is not None:
            return r
        raise
    if r is not None:
        return r
    raise

def _open_basic(req: urllib.request.Request, timeout: float):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError) as e:
        if is_cert_error(e):
            ctx = bundled_context()
            if ctx is None:
                raise
            return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx)).open(req, timeout=timeout)
        if not urllib.request.getproxies():
            raise
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)

_DASHES = '‐‑‒–—―−ー－ｰ'
_JUNK = dict.fromkeys(map(ord, '​‌‍‎‏⁠﻿"\'`<>“”‘’「」'), None)

def clean_key(key) -> str:
    if not isinstance(key, str):
        return ''
    s = key.translate(str.maketrans({c: '-' for c in _DASHES}))
    s = unicodedata.normalize('NFKC', s).translate(_JUNK)
    s = ''.join(s.split()).upper()
    if s.startswith(KEY_PREFIX):
        return s
    return key.strip()

def valid_link_key(key) -> bool:
    key = clean_key(key)
    return key.startswith(KEY_PREFIX) and len(key) > len(KEY_PREFIX)

def valid_endpoint(url) -> bool:
    return isinstance(url, str) and url.strip().lower().startswith('https://') and PLACEHOLDER not in url.lower()

def api_url(endpoint_url: str, path: str) -> str:
    u = endpoint_url.strip().rstrip('/')
    for suffix in ('/api/telemetry', '/api/sync'):
        if u.endswith(suffix):
            u = u[:-len(suffix)]
    return u + path

def telemetry_url(endpoint_url: str) -> str:
    return api_url(endpoint_url, '/api/telemetry')

def _http_post(url: str, payload: dict) -> Dict[str, object]:
    cands = relay.candidates(url)
    last_exc = None
    last_ans = None
    for i, (base, full) in enumerate(cands):
        br = relay.breaker_for(base, i == 0)
        if br.blocked():
            last_exc = breaker.BreakerOpen(f'relay cooling down for {int(br.remaining())} s')
            continue
        has_next = i + 1 < len(cands)
        try:
            ans, failed = _post_one(full, payload, br)
        except urllib.error.URLError as e:
            last_exc = e
            if has_next:
                br.trip_for(relay.CONNECT_FAIL_COOLDOWN_S)
            continue
        except OSError as e:
            last_exc = e
            if has_next:
                br.trip_for(relay.CONNECT_FAIL_COOLDOWN_S)
            else:
                raise
            continue
        if failed and has_next:
            last_ans = ans
            continue
        return ans
    if last_ans is not None:
        return last_ans
    raise last_exc or breaker.BreakerOpen('no relay address')

def _post_one(url: str, payload: dict, br) -> Tuple[Dict[str, object], bool]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'User-Agent': 'pk-auto/1.0'}, method='POST')
    if br.blocked():
        raise breaker.BreakerOpen(f'relay cooling down for {int(br.remaining())} s')
    status = 200
    try:
        with _open(req, HTTP_TIMEOUT_S) as r:
            body = r.read(65536)
            status = getattr(r, 'status', 200) or 200
    except urllib.error.HTTPError as e:
        body = e.read(65536)
        status = e.code
    try:
        data = json.loads(body.decode('utf-8'))
    except Exception:
        data = None
    parsed = data if isinstance(data, dict) else {}
    failed = False
    try:
        if status == 429 and not parsed:
            br.trip_quota()
            failed = True
        elif status >= 500:
            br.trip_error()
            failed = True
        elif status < 400:
            br.success()
    except Exception:
        pass
    return parsed, failed

def _status_of(answer: dict) -> str:
    if answer.get('ok') is True:
        return OK
    err = str(answer.get('error', ''))
    if err in (INVALID_KEY, DM_CLOSED, RATE_LIMITED):
        return err
    return SERVER

class TelemetryManager:
    def __init__(self, clock: Callable[[], float]=time.monotonic, post: Optional[Callable[[str, dict], dict]]=None, sync: bool=False, log: Optional[Callable[[str], None]]=None):
        self._clock = clock
        self._post = post or _http_post
        self._sync = sync
        self.log = log or (lambda _m: None)
        self._lock = threading.Lock()
        self._threads = []
        self._window = deque()
        self._modes = set()
        self.lang = 'ja'
        self.session_start_time = 0.0
        self._t0 = clock()
        self.total_actions = 0
        self.peak_apm = 0
        self.popups = 0
        self.loops = 0
        self.claims = 0
        self._sent = True
        self._last_report = clock()
        self.extra = None
        self.on_answer = None

    def begin_session(self, mode: str='A', lang: str='ja') -> None:
        with self._lock:
            self._last_report = self._clock()
            self._window.clear()
            self._modes = {mode}
            self.lang = lang
            self.session_start_time = time.time()
            self._t0 = self._clock()
            self.total_actions = self.peak_apm = self.popups = self.loops = 0
            self.claims = 0
            self._sent = False

    def record_action(self, popup: bool=False) -> None:
        try:
            now = self._clock()
            with self._lock:
                self.total_actions += 1
                if popup:
                    self.popups += 1
                w = self._window
                w.append(now)
                cutoff = now - WINDOW_S
                while w and w[0] <= cutoff:
                    w.popleft()
                if len(w) > self.peak_apm:
                    self.peak_apm = len(w)
        except Exception:
            return

    def set_loops(self, n: int) -> None:
        self.loops = int(n)

    def set_claims(self, n: int) -> None:
        self.claims = int(n)

    def set_popups(self, n: int) -> None:
        self.popups = int(n)

    def set_mode(self, mode: str) -> None:
        self._modes.add(mode)

    def snapshot(self) -> dict:
        with self._lock:
            return {'duration_s': int(max(0.0, self._clock() - self._t0)), 'total_actions': self.total_actions, 'peak_apm': self.peak_apm, 'loops': self.loops, 'popups': self.popups, 'claims': self.claims, 'mode': '+'.join(sorted(self._modes)) or 'A', 'lang': self.lang, 'version': '1'}

    def _spawn(self, fn: Callable[[], None]) -> Optional[threading.Thread]:
        if self._sync:
            fn()
            return
        t = threading.Thread(target=fn, daemon=True, name='pk-auto-telemetry')
        self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()
        return t

    def _deliver(self, link_key: str, endpoint_url: str, kind: str, callback, interval_h: float=0.0, alert: Optional[dict]=None, stuck: Optional[dict]=None) -> None:
        status = SERVER
        try:
            payload = {'link_key': clean_key(link_key), 'stats': self.snapshot(), 'is_test': kind == 'test', 'kind': kind}
            if interval_h:
                payload['interval_h'] = interval_h
            if alert:
                payload['alert'] = alert
            if stuck:
                payload['stuck'] = stuck
            if self.extra:
                try:
                    pass
                except Exception:
                    pass
                try:
                    payload.update({k: v for k, v in (self.extra() or {}).items() if k not in payload})
                except Exception:
                    pass
        except Exception as e:
            kind, text = classify_error(e)
            status = network_status(kind)
            self.log(f'telemetry: {type(e).__name__} ({kind}) {text}')
        important = kind in ('summary', 'stuck')
        if important:
            with breaker.BREAKER.override():
                answer = self._post(telemetry_url(endpoint_url), payload)
        else:
            answer = self._post(telemetry_url(endpoint_url), payload)
        status = _status_of(answer)
        if self.on_answer and isinstance(answer, dict) and answer.get('ok') is True:
            try:
                try:
                    pass
                except Exception:
                    try:
                        self.on_answer(answer)
                    except Exception as e:
                        kind, text = classify_error(e)
                        status = network_status(kind)
                        self.log(f'telemetry: {type(e).__name__} ({kind}) {text}')
            except Exception as e:
                kind, text = classify_error(e)
                status = network_status(kind)
                self.log(f'telemetry: {type(e).__name__} ({kind}) {text}')
        if status != OK:
            self.log(f'telemetry: not delivered ({status})')
            if kind == 'periodic' and status not in (INVALID_KEY, DM_CLOSED, NO_URL):
                try:
                    self._last_report = self._clock() - max(0.0, interval_h * 3600.0 - PERIODIC_RETRY_S)
                except Exception:
                    pass
        if callback:
            try:
                callback(status)
            except Exception:
                pass

    def _early(self, link_key, endpoint_url, callback) -> Optional[str]:
        if not valid_link_key(link_key):
            return INVALID_KEY
        if not valid_endpoint(endpoint_url):
            return NO_URL

    def send_test_dm(self, link_key: str, endpoint_url: str, callback: Optional[Callable[[str], None]]=None):
        bad = self._early(link_key, endpoint_url, callback)
        if bad:
            if callback:
                callback(bad)
            return
        return self._spawn((lambda: self._deliver(link_key, endpoint_url, 'test', callback)))

    def send_session_summary(self, link_key: str, endpoint_url: str, callback: Optional[Callable[[str], None]]=None, min_actions: int=MIN_ACTIONS):
        if self._sent or not valid_link_key(link_key) or not valid_endpoint(endpoint_url):
            return
        if self.total_actions < min_actions:
            return
        self._sent = True
        return self._spawn((lambda: self._deliver(link_key, endpoint_url, 'summary', callback)))

    def maybe_send_periodic(self, link_key: str, endpoint_url: str, hours: float, callback=None):
        try:
            if not hours or hours <= 0 or self._sent:
                return
            period = max(0.5, float(hours)) * 3600.0
            now = self._clock()
            if now - self._last_report < period:
                return
            self._last_report = now
            if not (valid_link_key(link_key) and valid_endpoint(endpoint_url)):
                return
            return self._spawn((lambda: self._deliver(link_key, endpoint_url, 'periodic', callback, max(0.5, float(hours)))))
        except Exception:
            return

    def send_alert(self, link_key: str, endpoint_url: str, code: str, detail: str, callback=None):
        try:
            if not (valid_link_key(link_key) and valid_endpoint(endpoint_url)):
                return
            alert = {'code': str(code)[:20], 'detail': str(detail)[:300]}
            return self._spawn((lambda: self._deliver(link_key, endpoint_url, 'alert', callback, alert=alert)))
        except Exception:
            return

    def send_stuck(self, link_key: str, endpoint_url: str, state: str, minutes: int, callback=None, grid_image_b64: Optional[str]=None):
        try:
            if not (valid_link_key(link_key) and valid_endpoint(endpoint_url)):
                return
            stuck = {'state': str(state)[:24], 'minutes': max(0, min(100000, int(minutes)))}
            if isinstance(grid_image_b64, str):
                if 0 < len(grid_image_b64) <= MAX_GRID_B64:
                    stuck['grid_image_b64'] = grid_image_b64
            return self._spawn((lambda: self._deliver(link_key, endpoint_url, 'stuck', callback, stuck=stuck)))
        except Exception:
            return

    def flush(self, timeout: float=3.0) -> None:
        end = time.monotonic() + timeout
        for t in list(self._threads):
            left = end - time.monotonic()
            if left <= 0:
                return
            t.join(left)


