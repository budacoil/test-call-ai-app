import ctypes
import os
import socket
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from typing import (Callable, Dict, List, Optional, Tuple)
import config
import focus
import telemetry
import window_capture as wc
from version import __version__
PROBE_TIMEOUT_S = 6.0

def _admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _variant_name(flags: int) -> str:
    if flags & wc.PW_RENDERFULLCONTENT:
        return 'PW_RENDERFULLCONTENT|' + 'PW_CLIENTONLY'
    return '' + 'PW_CLIENTONLY'

def build_report(api=None, gdi=None) -> List[str]:
    api = api or focus.WinApi()
    gdi = gdi or wc.Win32Gdi()
    lines = [f'pk-auto {__version__} | frozen={bool(getattr(sys, 'frozen', False))} | this program runs as administrator: {_admin()}']
    try:
        windows = api.windows()
    except Exception as e:
        return lines + [f'cannot list windows: {e}']
    related = []
    for h in windows:
        cls, title = api.class_name(h), api.title(h)
        low = (cls + ' ' + title).lower()
        if cls != focus.GAME_CLASS:
            if not any((k in low for k in ('fortnite', 'geforce now', 'フォートナイト'))):
                continue
        related.append((h, cls, title))
    lines.append(f'windows that look related to the game: {len(related)}')
    for h, cls, title in related:
        proc = ''
        try:
            proc = api.process_name(h)
        except Exception:
            pass
        r = gdi.client_rect(h)
        lines.append(f'  hwnd={h} class={cls!r} title={title!r} program={proc!r} client={r[2]}x{r[3] if r else '?'} minimized={gdi.is_iconic(h)}')
    game = focus.find_game(api)
    if not game:
        lines.append('RESULT: the game window was NOT found (start the game first; if it is running, send this report).')
        return lines
    lines.append(f'game window found: hwnd={game}, class={api.class_name(game)!r}, title={api.title(game)!r}')
    if gdi.is_iconic(game):
        lines.append('RESULT: the game window is minimized - Windows does not draw it, so it cannot be captured. Un-minimize it and set the display mode to Windowed Fullscreen.')
        return lines
    rect = gdi.client_rect(game)
    if not rect or rect[2] <= 0 or rect[3] <= 0:
        lines.append(f'RESULT: the window has no usable client area ({rect}).')
        return lines
    left, top, w, h = rect
    lines.append(f'client area: {w}x{h} at screen position ({left}, {top})')
    cap = wc.WindowCapture(wc.GameWindow(finder=(lambda: game), is_window=gdi.is_window), api=gdi)
    working = None
    for flags in wc.FLAG_VARIANTS:
        t0 = time.perf_counter()
        cap._denied = False
        frame = cap._print(game, w, h, flags)
        ms = (time.perf_counter() - t0) * 1000
        if frame is None:
            why = 'ACCESS DENIED (the game runs as administrator; run pk-auto as administrator)' if cap._denied else 'failed'
            lines.append(f'  PrintWindow {_variant_name(flags)}: {why} [{ms:.0f} ms]')
            if cap._denied:
                break
        if wc._is_black(frame):
            lines.append(f'  PrintWindow {_variant_name(flags)}: BLACK picture [{ms:.0f} ms]')
            continue
        lines.append(f'  PrintWindow {_variant_name(flags)}: OK, mean brightness {float(frame.mean()):.0f} [{ms:.0f} ms]')
        working = working or flags
        continue
    if working is not None:
        lines.append('RESULT: the game window can be captured, also behind other windows. Background mode should work.')
        return lines
    lines.append('RESULT: the game window cannot be captured behind other windows with this method. Keep the game uncovered (pk-auto then falls back to the normal screen capture), or send this report.')
    return lines

class NetProbe:
    def resolve(self, host: str) -> str:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return ', '.join(sorted({i[4][0] for i in infos})[:3])

    def handshake(self, host: str) -> str:
        try:
            return self._tls(host, ssl.create_default_context())
        except ssl.SSLCertVerificationError as e:
            ctx = telemetry.bundled_context()
            if ctx is None:
                raise
            note = self._tls(host, ctx)
            raise_msg = f'{e.verify_message or e.reason}'
            return f"{note} - the PC's certificate store REJECTED it ({raise_msg}) but the bundled certificates accept it; pk-auto uses those"

    def _tls(self, host: str, ctx: ssl.SSLContext) -> str:
        with socket.create_connection((host, 443), timeout=PROBE_TIMEOUT_S) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                issuer = dict((x[0] for x in cert.get('issuer', ()))).get('commonName', '?')
                return f'{tls.version()}, issued by {issuer}, valid until {cert.get('notAfter', '?')}'

    def get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={'User-Agent': f'pk-auto-diagnose/{__version__}'})
        with telemetry._open(req, PROBE_TIMEOUT_S) as r:
            return f'HTTP {r.status}'


def _proxy_text() -> str:
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return 'unknown'
    if not proxies:
        return 'none'
    shown = []
    for scheme, url in sorted(proxies.items()):
        u = urllib.parse.urlparse(url if '://' in url else '//' + url)
        shown.append(f'{scheme}={u.hostname}:{u.port}')
    return 'configured (' + ', '.join(shown) + ')'

def _step(label: str, fn: Callable[[], str]) -> Tuple[bool, str]:
    t0 = time.perf_counter()
    try:
        out = fn()
        return True, f'  {label}: OK {out} [{(time.perf_counter() - t0) * 1000:.0f} ms]'
    except Exception as e:
        kind, text = telemetry.classify_error(e)
        return False, f'  {label}: FAILED ({kind}) {text} [{(time.perf_counter() - t0) * 1000:.0f} ms]'

def network_report(probe=None, relay_url: Optional[str]=None) -> List[str]:
    probe = probe or NetProbe()
    relay_url = relay_url or config.DEFAULT_TELEMETRY_URL
    lines = ['', '== network ==']
    lines.append(f'PC time: {time.strftime('%Y-%m-%d %H:%M:%S')} (UTC offset {-time.timezone // 3600:+d} h) - a wrong date or time breaks secure connections')
    lines.append(f'system proxy: {_proxy_text()}')
    targets = [('relay (Discord DM / settings)', urllib.parse.urlparse(relay_url).hostname or '', relay_url.rstrip('/') + '/'), ('GitHub (updates)', 'api.github.com', 'https://api.github.com/'), ('Discord', 'discord.com', 'https://discord.com/api/v10/gateway')]
    ok_by_host = {}
    tls_failed = {}
    for title, host, url in targets:
        lines.append(f'{title}: {host}')
        all_ok = True
        for label, fn in ('name lookup', (lambda h=host: probe.resolve(h))), ('secure connection', (lambda h=host: probe.handshake(h))), ('page request', (lambda u=url: probe.get(u))):
            ok, line = _step(label, fn)
            lines.append(line)
            all_ok = all_ok and ok
            if ok:
                continue
            tls_failed[host] = 'FAILED (tls)' in line
            break
        ok_by_host[host] = all_ok
    others, relay_host = [h for _, h, _ in targets[1:]], targets[0][1]
    if all(ok_by_host.values()):
        lines.append('RESULT: the relay, GitHub and Discord are all reachable. The network is fine; if the DM test still fails, send this report.')
        return lines
    if not any(ok_by_host.values()):
        lines.append('RESULT: nothing can be reached. Check the internet connection, VPN, proxy and the firewall / security software (allow pk-auto.exe).')
        return lines
    if tls_failed.get(relay_host):
        lines.append("RESULT: the relay's security certificate is not accepted on this PC (also not with pk-auto's bundled certificates). Check the PC's date and time and install the pending Windows updates; if security software with 'HTTPS / web scanning' is installed (antivirus, school / company filter), turn that scanning off for pk-auto.exe. Send this report if that does not help.")
        return lines
    if not ok_by_host.get(relay_host):
        if all((ok_by_host.get(h) for h in others)):
            lines.append('RESULT: only the relay server is unreachable while GitHub and Discord work. This network blocks *.workers.dev (or its DNS does not know it). Try another DNS (e.g. 1.1.1.1 / 8.8.8.8), turn a VPN on / off, or another network. Send this report if that does not help.')
            return lines
    lines.append('RESULT: some servers are reachable and some are not. See the FAILED lines above (the stage and kind tell what blocks it).')
    return lines

REPORT_NAME = 'pk-auto_report.txt'

def default_report_path() -> str:
    for folder in config.base_dir(), os.path.join(os.path.expanduser('~'), 'Desktop'), tempfile.gettempdir():
        try:
            if os.path.isdir(folder) and os.access(folder, os.W_OK):
                return os.path.join(folder, REPORT_NAME)
        except Exception:
            continue
    return os.path.join(tempfile.gettempdir(), REPORT_NAME)

def run(out_path: str) -> None:
    try:
        lines = build_report()
    except Exception as e:
        lines = [f'diagnose failed: {type(e).__name__}: {e}']
    try:
        lines += network_report()
    except Exception as e:
        lines.append(f'network check failed: {type(e).__name__}: {e}')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

