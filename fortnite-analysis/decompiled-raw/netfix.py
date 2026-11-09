import http.client
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import (Callable, List, Optional, Tuple)
SPECS = ('system', 'bundled', 'direct', 'direct-bundled', 'ipv4', 'ipv4-bundled', 'doh', 'doh-bundled')
RESCUE_SPECS = ('ipv4', 'ipv4-bundled', 'doh', 'doh-bundled')
DOH_SERVERS = ('https://1.1.1.1/dns-query', 'https://8.8.8.8/resolve', 'https://9.9.9.9:5053/dns-query')
DOH_TTL_S = 600.0
PROBE_TIMEOUT_S = 8.0
_lock = threading.Lock()
_preferred: Optional[str] = None
_doh_cache: dict = {}

def preferred() -> Optional[str]:
    return _preferred

def set_preferred(spec: Optional[str]) -> None:
    global _preferred
    with _lock:
        _preferred = spec

def _context(bundled: bool) -> ssl.SSLContext:
    if not bundled:
        return ssl.create_default_context()
    import telemetry
    ctx = telemetry.bundled_context()
    if ctx is None:
        raise ValueError('bundled certificates not available')
    return ctx

def _addrs_v4(host: str, port: int) -> List[str]:
    return sorted({i[4][0] for i in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)})

def _addrs_doh(host: str, port: int) -> List[str]:
    hit = _doh_cache.get(host)
    if hit and time.monotonic() - hit[0] < DOH_TTL_S:
        return list(hit[1])
    last = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for base in DOH_SERVERS:
        try:
            req = urllib.request.Request(f'{base}?name={urllib.parse.quote(host)}&type=A', headers={'Accept': 'application/dns-json', 'User-Agent': 'pk-auto-net'})
            with opener.open(req, timeout=PROBE_TIMEOUT_S) as r:
                data = json.loads(r.read(65536).decode('utf-8'))
        except Exception as e:
            last = e
        try:
            ips = [a['data'] for a in data.get('Answer', []) if a.get('type') == 1 if isinstance(a.get('data'), str)]
            if ips:
                _doh_cache[host] = time.monotonic(), ips
                return ips
        except Exception as e:
            last = e
    raise OSError(f'DNS-over-HTTPS lookup failed: {last}')

def _connect_any(addrs: List[str], port: int, timeout: float) -> socket.socket:
    last = None
    for a in addrs:
        try:
            pass
        except OSError as e:
            last = e
            continue
        return socket.create_connection((a, port), timeout)
    raise last or OSError('no address')

class _PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext, lookup: Callable[[str, int], List[str]]):
        super().__init__(context=context)
        self._ctx, self._lookup = context, lookup

    def https_open(self, req):
        ctx, lookup = self._ctx, self._lookup
        class Conn(http.client.HTTPSConnection):
            def connect(self):
                sock = _connect_any(lookup(self.host, self.port), self.port, self.timeout)
                self.sock = ctx.wrap_socket(sock, server_hostname=self.host)


        return self.do_open(Conn, req, context=ctx)


def open_with(spec: str, req: urllib.request.Request, timeout: float):
    base = spec.split('-')[0]
    ctx = _context(spec.endswith('-bundled') or base == 'bundled')
    if base in ('system', 'bundled'):
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    elif base == 'direct':
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
    elif base == 'ipv4':
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHandler(ctx, _addrs_v4))
    elif base == 'doh':
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHandler(ctx, _addrs_doh))
    else:
        raise ValueError(spec)
    return opener.open(req, timeout=timeout)

def rescue(req: urllib.request.Request, timeout: float):
    for spec in RESCUE_SPECS:
        try:
            r = open_with(spec, req, timeout)
        except urllib.error.HTTPError:
            set_preferred(spec)
            raise
        except Exception:
            continue
        set_preferred(spec)
        return r

def repair(relay_url: str, timeout: float=PROBE_TIMEOUT_S) -> Tuple[str, List[str]]:
    lines = []
    base = relay_url.strip().rstrip('/') + '/'
    for spec in SPECS:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(base, headers={'User-Agent': 'pk-auto-net'})
        except Exception as e:
            lines.append(f'{spec}: FAILED {type(e).__name__} [{(time.perf_counter() - t0) * 1000:.0f} ms]')
            continue
        try:
            try:
                with open_with(spec, req, timeout) as r:
                    r.read(256)
            except urllib.error.HTTPError:
                pass
        except Exception as e:
            lines.append(f'{spec}: FAILED {type(e).__name__} [{(time.perf_counter() - t0) * 1000:.0f} ms]')
            continue
        lines.append(f'{spec}: OK [{(time.perf_counter() - t0) * 1000:.0f} ms]')
        if spec == 'system':
            set_preferred(None)
            return 'fix_same', lines
        set_preferred(spec)
        return 'fix_ok', lines
    return 'fix_fail', lines

def repair_async(relay_url: str, callback: Callable[[str], None]) -> threading.Thread:
    def work() -> None:
        try:
            status, _lines = repair(relay_url)
        except Exception:
            status = 'fix_fail'
        try:
            callback(status)
        except Exception:
            return

    t = threading.Thread(target=work, daemon=True, name='pk-auto-netfix')
    t.start()
    return t

