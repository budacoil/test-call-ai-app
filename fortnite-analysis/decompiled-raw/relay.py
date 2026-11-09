import json
import os
import re
import threading
import time
from typing import (Callable, List, Optional, Tuple)
import breaker
import config
MAX_URLS = 6
REFRESH_S = 21600.0
CACHE_NAME = 'relay_endpoints.json'
CONNECT_FAIL_COOLDOWN_S = 60.0
_lock = threading.Lock()
_user: List[str] = []
_remote: List[str] = []
_breakers: dict = {}
_started = False

def clean_url(u) -> str:
    if not isinstance(u, str):
        return ''
    u = u.strip().strip('"\'').rstrip('/')
    for suffix in ('/api/telemetry', '/api/sync', '/api/license'):
        if u.endswith(suffix):
            u = u[:-len(suffix)]
    if not re.fullmatch('https://[A-Za-z0-9.\\-]+(:\\d{2,5})?(/[A-Za-z0-9._~/\\-]*)?', u) or 'your-worker' in u.lower():
        return ''
    return u.rstrip('/')

def parse_list(text) -> List[str]:
    parts = re.split('[\\s,;]+', text) if isinstance(text, str) else list(text or [])
    out = []
    for p in parts:
        c = clean_url(p)
        if not c:
            continue
        if c not in out:
            out.append(c)
    return out[:MAX_URLS]

def set_user_urls(text) -> None:
    global _user
    urls = parse_list(text) + [u for u in parse_list(os.environ.get('PKA_RELAY_URLS', '')) if u not in parse_list(text)]
    with _lock:
        _user = urls[:MAX_URLS]

def candidates(url: str) -> List[Tuple[str, str]]:
    m = re.match('^(https://[^/]+(?:/[^?]*?)?)(/api/[A-Za-z0-9_\\-/]+)(\\?.*)?$', url or '')
    if not m:
        return [(url, url)]
    base, path = m.group(1), m.group(2) + (m.group(3) or '')
    primary = clean_url(base) or base
    out = [primary]
    with _lock:
        extra = list(_user) + list(_remote)
    for u in extra + [clean_url(x) for x in getattr(config, 'FALLBACK_RELAY_URLS', ())]:
        if not u:
            continue
        if u not in out:
            out.append(u)
    return [(b, b + path) for b in out[:MAX_URLS + 1]]

def breaker_for(base: str, is_primary: bool) -> 'breaker.Breaker':
    if is_primary:
        return breaker.BREAKER
    with _lock:
        b = _breakers.get(base)
        if b is None:
            _breakers[base] = (b := breaker.Breaker())
        return b

def cache_path() -> str:
    return os.path.join(config.base_dir(), CACHE_NAME)

def load_cache() -> None:
    global _remote
    try:
        with open(cache_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        urls = parse_list(data.get('urls', []) if isinstance(data, dict) else [])
        with _lock:
            _remote = urls
    except Exception:
        return

def fetch_list(opener: Optional[Callable]=None) -> List[str]:
    try:
        import urllib.request
        import telemetry
        url = getattr(config, 'RELAY_LIST_URL', '')
        if not url.lower().startswith('https://'):
            return []
        req = urllib.request.Request(url, headers={'User-Agent': 'pk-auto/1.0', 'Cache-Control': 'no-cache'})
        with (opener or telemetry._open)(req, 15) as r:
            data = json.loads(r.read(65536).decode('utf-8'))
        return parse_list(data.get('urls', []) if isinstance(data, dict) else [])
    except Exception:
        return []

def refresh(opener: Optional[Callable]=None) -> List[str]:
    global _remote
    urls = fetch_list(opener)
    if urls:
        with _lock:
            _remote = urls
        try:
            with open(cache_path(), 'w', encoding='utf-8') as f:
                json.dump({'urls': urls, 'at': int(time.time())}, f)
        except Exception:
            pass
        return urls
    return urls

def start(settings=None, sleep: Callable[[float], None]=time.sleep) -> None:
    global _started
    set_user_urls(getattr(settings, 'relay_fallback_urls', '') if settings is not None else '')
    load_cache()
    if _started:
        return
    _started = True
    def loop() -> None:
        sleep(5.0)
        while True:
            try:
                refresh()
            except Exception:
                pass
            sleep(REFRESH_S)

    threading.Thread(target=loop, daemon=True, name='pk-auto-relay-list').start()

