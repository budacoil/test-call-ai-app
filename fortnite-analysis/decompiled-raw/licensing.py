import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Callable
import config
import ed25519_verify
import telemetry
import version
PREFIX = 'PKA-'
KEY_RE = re.compile('^PKA-[A-Z2-7]{5}-[A-Z2-7]{5}-[A-Z2-7]{5}-[A-Z2-7]{5}$')
SIGN_PUBKEY = '6348eba862d36ed3ed7cf72ebf47dbf5de3d0eeb99a67b92fd9fcf5c89704da8'
GRACE_S = 259200
RECHECK_S = 86400
TEMP_PASS_S = 86400
GRACE_MAX_S = 604800
OK, NEED_KEY, INVALID, USED, REVOKED, OFFLINE, SERVER = 'ok', 'need_key', 'invalid_key', 'used_elsewhere', 'revoked', 'offline', 'server'
BUSY = 'busy'
_NOTICES: list = []

def note(msg: str) -> None:
    if not _NOTICES or _NOTICES[-1] != msg:
        _NOTICES.append(msg)
        del _NOTICES[:-20]

def pop_notices() -> list:
    out = list(_NOTICES)
    _NOTICES.clear()
    return out

class Busy(Exception):
    pass

def _default_post(url: str, payload: dict) -> dict:
    data = telemetry._http_post(url, payload)
    if isinstance(data, dict):
        if 'ok' not in data and 'error' not in data:
            raise Busy('no JSON answer')
    return data

def required() -> bool:
    return bool(getattr(version, 'LICENSE_REQUIRED', False))

def clean_key(key) -> str:
    if not isinstance(key, str):
        return ''
    s = unicodedata.normalize('NFKC', key)
    s = re.sub('[‐-―−ー]', '-', s)
    s = ''.join(s.split()).strip('"\'`“”‘’').upper()
    raw = s.replace('-', '')
    if re.fullmatch('(PKA)?[A-Z2-7]{20}', raw):
        raw = raw[3:] if raw.startswith('PKA') and len(raw) == 23 else raw
        return PREFIX + '-'.join((raw[i:i + 5] for i in range(0, 20, 5)))
    return s

def valid_format(key) -> bool:
    return bool(KEY_RE.match(key or ''))

def machine_id() -> str:
    raw = ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\Cryptography', 0, winreg.KEY_READ | getattr(winreg, 'KEY_WOW64_64KEY', 0)) as k:
            raw = str(winreg.QueryValueEx(k, 'MachineGuid')[0])
    except Exception:
        pass
    if not raw:
        import uuid
        raw = f'mac:{uuid.getnode()}'
    return hashlib.sha256(('pka-hw:' + raw).encode('utf-8')).hexdigest()[:24]

def key_id(key: str) -> str:
    k = clean_key(key)
    if valid_format(k):
        return k[4:15].replace('-', '')
    return ''

def _proof_ok(key: str, hw: str, iat: float, sig_hex: str, now: float, max_age: float) -> bool:
    try:
        if not -300 <= now - float(iat) < max_age:
            return False
    except Exception:
        return False
    try:
        if not SIGN_PUBKEY:
            return True
        msg = f'pka-token:{key_id(key)}:{hw}:{int(iat)}'.encode('utf-8')
        return bool(key_id(key)) and ed25519_verify.verify(bytes.fromhex(SIGN_PUBKEY), msg, bytes.fromhex(sig_hex or ''))
    except Exception:
        return False

def _remembered(s, key: str, hw: str, now: float, max_age: float) -> bool:
    return bool(key) and clean_key(s.license_key) == clean_key(key) and _proof_ok(key, hw, s.license_ok_at, s.license_sig, now, max_age)

def _temp_pass_live(s, key: str, now: float) -> bool:
    return bool(key) and clean_key(s.license_key) == clean_key(key) and now < s.license_grace_until

def is_fresh(s, now: Callable[[], float]=time.time, hwid: str='') -> bool:
    try:
        t = now()
        return _temp_pass_live(s, s.license_key, t) or _remembered(s, s.license_key, hwid or machine_id(), t, RECHECK_S)
    except Exception:
        return False

def verify(s, key: str, post=None, now: Callable[[], float]=time.time, hwid: str='') -> str:
    post = post or _default_post
    key = clean_key(key)
    hw = hwid or machine_id()
    if key and not valid_format(key):
        return INVALID
    if _temp_pass_live(s, key, float(now())):
        return OK
    try:
        url = config.DEFAULT_TELEMETRY_URL
        if not telemetry.valid_endpoint(url):
            raise OSError('no server address')
        ans = post(telemetry.api_url(url, '/api/license'), {'key': key, 'hwid': hw, 'v': getattr(version, '__version__', '')})
    except Exception as e:
        return _outage(s, key, hw, now, e)
    if ans.get('ok') is True:
        if ans.get('required') is False:
            return OK
        sig, iat = str(ans.get('sig', '')), ans.get('iat', 0)
        if not _proof_ok(key, hw, iat, sig, now(), RECHECK_S):
            return _outage(s, key, hw, now, Busy('unsigned answer'))
        s.license_key, s.license_ok_at, s.license_ok_hwid, s.license_sig = key, float(iat), hw, sig
        s.license_grace_until = s.license_grace_since = 0.0
        return OK
    err = str(ans.get('error', ''))
    if err in (NEED_KEY, INVALID, USED, REVOKED):
        if err in (USED, REVOKED, INVALID):
            s.license_ok_at, s.license_sig = 0.0, ''
        return err
    return _outage(s, key, hw, now, Busy(err or 'unknown answer'))

def _outage(s, key: str, hw: str, now, why) -> str:
    try:
        t = float(now())
        note('[license] server busy (429), running in offline grace mode')
        if _remembered(s, key, hw, t, float('inf')):
            return OK
        if key and valid_format(key):
            since = s.license_grace_since if 0 < s.license_grace_since <= t else t
            if t - since <= GRACE_MAX_S:
                s.license_key, s.license_grace_until, s.license_grace_since = key, t + TEMP_PASS_S, since
                return OK
    except Exception:
        pass
    if isinstance(why, Busy):
        return BUSY
    return OFFLINE

def _grace(s, key: str, hw: str, now) -> str:
    try:
        if _remembered(s, key, hw, now(), float('inf')):
            return OK
        return OFFLINE
    except Exception:
        return OFFLINE

