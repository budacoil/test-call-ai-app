import json
import os
import random
import sys
from dataclasses import dataclass
FALLBACK_RELAY_URLS: tuple = ()
RELAY_LIST_URL = 'https://raw.githubusercontent.com/ppkk12/fortnite-automatic-lap/main/relay_endpoints.json'
DEFAULT_TELEMETRY_URL = 'https://pk-auto-relay.pkaringo103.workers.dev'
DISCORD_INVITE_URL = 'https://discord.gg/jXgyWsYfUd'
TEMPLATE_NAMES = {'play': 'play_btn.png', 'continue': 'continue_btn.png', 'skip': 'skip_btn.png', 'return_lobby': 'return_lobby_btn.png', 'claim': 'claim_btn.png', 'claim_single': 'claim_single_btn.png', 'popup': 'popup_btn.png', 'hud': 'hud_btn.png', 'menu_btn': 'menu_btn.png', 'menu_return': 'menu_return_btn.png', 'storefront_play': 'storefront_play_btn.png', 'item_found': 'item_found_btn.png'}
MODES = {'A': 'A: 通常ループ (続行→スキップ→ロビーへ)', 'B': 'B: 待機島で待ってEscから退出', 'C': 'C: 待機島で待って退出、アイテム発見でAへ切替'}
OPTIONAL_TEMPLATES = {'claim', 'popup', 'item_found', 'claim_single', 'storefront_play'}
LANGS = {'ja': '日本語', 'en': 'English', 'es': 'Español (beta)', 'pt': 'Português (beta)', 'ru': 'Русский (beta)', 'fr': 'Français (beta)'}
PLATE_LANGS = ('es', 'pt', 'ru', 'fr')
LANG_INDEPENDENT = {'hud', 'skip', 'continue', 'menu_btn', 'item_found', 'menu_return', 'storefront_play'}
PLATES = {'play': {'roi': (0.0, 0.7, 0.4, 1.0), 'threshold': 0.92}, 'return_lobby': {'roi': (0.55, 0.3, 1.0, 0.52), 'threshold': 0.8}, 'claim': {'roi': (0.503, 0.8, 1.0, 1.0), 'threshold': 0.93}, 'hud': {'roi': (0.0, 0.8, 0.3, 1.0), 'threshold': 0.85}, 'menu_btn': {'roi': (0.7, 0.0, 1.0, 0.18), 'threshold': 0.85}, 'menu_return': {'roi': (0.55, 0.0, 1.0, 0.36), 'threshold': 0.85}, 'storefront_play': {'roi': (0.0, 0.55, 0.3, 0.8), 'threshold': 0.8}, 'item_found': {'roi': (0.3, 0.0, 0.7, 0.4), 'threshold': 0.75}}
PLATE_UNUSED = {'claim_single'}

def plate_filename(key: str) -> str:
    return TEMPLATE_NAMES[key].replace('.png', '_plate.png')

def uses_template(key: str, lang: str) -> bool:
    return not (lang in PLATE_LANGS and key in PLATE_UNUSED)

def template_filename(key: str, lang: str='ja') -> str:
    name = TEMPLATE_NAMES[key]
    if key in LANG_INDEPENDENT:
        return name
    if lang in PLATE_LANGS and key in PLATES:
        return plate_filename(key)
    if lang == 'ja' or lang in PLATE_LANGS:
        return name
    return name.replace('.png', f'_{lang}.png')

def base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def assets_dir() -> str:
    return os.path.join(base_dir(), 'assets')

def bundled_assets_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(getattr(sys, '_MEIPASS', base_dir()), 'assets_default')
    return assets_dir()

def external_template_path(key: str, lang: str='ja') -> str:
    return os.path.join(assets_dir(), template_filename(key, lang))

def template_path(key: str, lang: str='ja') -> str:
    ext = external_template_path(key, lang)
    if os.path.isfile(ext):
        return ext
    bundled = os.path.join(bundled_assets_dir(), template_filename(key, lang))
    if os.path.isfile(bundled):
        return bundled
    return ext

@dataclass
class Settings:
    threshold: float = 0.82
    lang: str = 'ja'
    mode: str = 'A'
    wait_b: float = 90.0
    wait_c: float = 90.0
    poll_interval: float = 2.0
    scales: tuple = tuple((round(0.6 + 0.1 * i, 2) for i in range(9)))
    jitter_px: int = 5
    delay_min: float = 0.15
    delay_max: float = 0.45
    click_cooldown: float = 3.0
    monitor_index: int = 1
    afk_enabled: bool = True
    afk_interval: float = 10.0
    afk_hold: float = 3.0
    afk_keys: tuple = ('w', 'a', 's', 'd')
    discord_link_key: str = ''
    telemetry_enabled: bool = True
    reward_shot_enabled: bool = False
    screenshot_enabled: bool = False
    alert_enabled: bool = True
    telemetry_api_url: str = DEFAULT_TELEMETRY_URL
    report_hours: float = 0.0
    remote_enabled: bool = True
    space_enabled: bool = False
    space_seconds: float = 10.0
    space_count: int = 3
    auto_update_check: bool = True
    background_mode: bool = True
    background_ghost: bool = True
    ghost_show: bool = False
    background_post_keys: bool = False
    auto_mute_enabled: bool = False
    loot_vault_enabled: bool = True
    humanizer_enabled: bool = True
    coffee_break_enabled: bool = False
    auto_calibrate: bool = True
    stuck_timeout_min: float = 15.0
    rescue_remote_enabled: bool = True
    squad_check_enabled: bool = False
    rescue_listening: bool = False
    afk_mouse_look: bool = True
    jitter_enabled: bool = True
    wait_jitter_percent: float = 0.15
    pickaxe_afk_enabled: bool = True
    pickaxe_slot_key: str = '1'
    bus_drop_enabled: bool = True
    mode_fix_enabled: bool = True
    bus_dive_seconds: float = 8.0
    bus_drop_min: int = 15
    bus_drop_max: int = 25
    pickaxe_min_s: float = 10.0
    license_key: str = ''
    license_ok_at: float = 0.0
    license_ok_hwid: str = ''
    relay_fallback_urls: str = ''
    license_grace_until: float = 0.0
    license_grace_since: float = 0.0
    license_sig: str = ''
    pickaxe_max_s: float = 30.0

USER_SETTING_KEYS = ('discord_link_key', 'telemetry_enabled', 'alert_enabled', 'screenshot_enabled', 'telemetry_api_url', 'report_hours', 'remote_enabled', 'auto_update_check', 'reward_shot_enabled', 'background_mode', 'background_ghost', 'background_post_keys', 'lang', 'mode', 'wait_b', 'wait_c', 'threshold', 'afk_enabled', 'afk_interval', 'afk_hold', 'space_enabled', 'space_seconds', 'space_count', 'auto_mute_enabled', 'loot_vault_enabled', 'humanizer_enabled', 'coffee_break_enabled', 'auto_calibrate', 'stuck_timeout_min', 'rescue_remote_enabled', 'squad_check_enabled', 'afk_mouse_look', 'jitter_enabled', 'wait_jitter_percent', 'pickaxe_afk_enabled', 'pickaxe_slot_key', 'pickaxe_min_s', 'pickaxe_max_s', 'license_key', 'license_ok_at', 'license_ok_hwid', 'license_sig', 'license_grace_until', 'license_grace_since', 'relay_fallback_urls', 'bus_drop_enabled', 'mode_fix_enabled', 'bus_dive_seconds', 'bus_drop_min', 'bus_drop_max')
NUMBER_RANGES = {'report_hours': (0.0, 24.0), 'wait_b': (10.0, 600.0), 'wait_c': (10.0, 600.0), 'threshold': (0.3, 0.99), 'afk_interval': (1.0, 600.0), 'afk_hold': (0.5, 30.0), 'space_seconds': (1.0, 3600.0), 'space_count': (1, 20), 'stuck_timeout_min': (0.0, 240.0), 'wait_jitter_percent': (0.0, 0.5), 'pickaxe_min_s': (1.0, 3600.0), 'pickaxe_max_s': (1.0, 3600.0), 'bus_dive_seconds': (1.0, 60.0), 'bus_drop_min': (1, 60), 'bus_drop_max': (1, 60)}
PICKAXE_SLOT_KEYS = tuple('1234567890')

def jitter_range(base_seconds: float, s: 'Settings | None'=None) -> tuple:
    base = float(base_seconds)
    if s is None:
        s = Settings()
    if not getattr(s, 'jitter_enabled', True) or base <= 0:
        return base, base
    pct = max(0.0, min(0.5, float(getattr(s, 'wait_jitter_percent', 0.15))))
    return base * (1.0 - pct), base * (1.0 + pct)

def get_jittered_wait(base_seconds: float, s: 'Settings | None'=None, rng=random) -> float:
    lo, hi = jitter_range(base_seconds, s)
    if hi <= lo:
        return lo
    return rng.uniform(lo, hi)

def user_settings_path() -> str:
    return os.path.join(base_dir(), 'pk-auto_settings.json')

def load_user_settings(s: 'Settings', path: str='') -> None:
    try:
        with open(path or user_settings_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for k in USER_SETTING_KEYS:
            if k not in data:
                continue
            v, want = data[k], type(getattr(s, k))
            if want is float and isinstance(v, int) and not isinstance(v, bool):
                v = float(v)
            if not isinstance(v, want):
                continue
            if k == 'telemetry_api_url':
                if not v.strip() or 'your-worker' in v.lower():
                    continue
            if k in NUMBER_RANGES:
                if not NUMBER_RANGES[k][0] <= v <= NUMBER_RANGES[k][1]:
                    continue
            if k == 'pickaxe_slot_key' and v not in PICKAXE_SLOT_KEYS:
                continue
            if k == 'lang' and v not in LANGS:
                continue
            if k == 'mode':
                if v not in MODES:
                    continue
            setattr(s, k, v)
    except Exception:
        return

def save_user_settings(s: 'Settings', path: str='') -> bool:
    try:
        pass
    except Exception:
        return False
    try:
        data = {k: getattr(s, k) for k in USER_SETTING_KEYS}
        if data['telemetry_api_url'] == DEFAULT_TELEMETRY_URL:
            del data['telemetry_api_url']
        with open(path or user_settings_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

