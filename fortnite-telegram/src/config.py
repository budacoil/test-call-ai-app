import os
import sys
from dataclasses import dataclass

TEMPLATE_NAMES = {
    "play": "play_btn.png",
    "continue": "continue_btn.png",
    "skip": "skip_btn.png",
    "return_lobby": "return_lobby_btn.png",

    "claim": "claim_btn.png",
    "claim_single": "claim_single_btn.png",
    "popup": "popup_btn.png",

    "hud": "hud_btn.png",
    "menu_btn": "menu_btn.png",
    "menu_return": "menu_return_btn.png",
}

MODES = {"A": "A: 通常ループ (続行→スキップ→ロビーへ)", "B": "B: 待機島で待ってEscから退出"}

OPTIONAL_TEMPLATES = {"popup", "claim", "claim_single"}

LANGS = {
    "ja": "日本語",
    "en": "English",
    "es": "Español (beta)",
    "pt": "Português (beta)",
    "ru": "Русский (beta)",
}
PLATE_LANGS = ("es", "pt", "ru")

LANG_INDEPENDENT = {"continue", "skip", "hud", "menu_btn", "menu_return"}

PLATES = {
    "play": {"roi": (0.0, 0.70, 0.40, 1.0), "threshold": 0.92},
    "return_lobby": {"roi": (0.55, 0.30, 1.0, 0.52), "threshold": 0.80},
    "claim": {"roi": (0.503, 0.80, 1.0, 1.0), "threshold": 0.93},

    "hud": {"roi": (0.0, 0.85, 0.30, 1.0), "threshold": 0.90},
    "menu_btn": {"roi": (0.70, 0.0, 1.0, 0.18), "threshold": 0.85},
    "menu_return": {"roi": (0.55, 0.0, 1.0, 0.36), "threshold": 0.85},
}

PLATE_UNUSED = {"claim_single"}

def plate_filename(key):
    return TEMPLATE_NAMES[key].replace(".png", "_plate.png")

def uses_template(key, lang):
    return not (lang in PLATE_LANGS and key in PLATE_UNUSED)

def template_filename(key, lang = "ja"):
    name = TEMPLATE_NAMES[key]
    if key in LANG_INDEPENDENT:
        return name
    if lang in PLATE_LANGS and key in PLATES:
        return plate_filename(key)
    if lang == "ja" or lang in PLATE_LANGS:
        return name
    return name.replace(".png", f"_{lang}.png")

def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def assets_dir():
    return os.path.join(base_dir(), "assets")

def bundled_assets_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", base_dir()), "assets_default")
    return assets_dir()

def external_template_path(key, lang = "ja"):
    return os.path.join(assets_dir(), template_filename(key, lang))

def template_path(key, lang = "ja"):
    ext = external_template_path(key, lang)
    if os.path.isfile(ext):
        return ext
    bundled = os.path.join(bundled_assets_dir(), template_filename(key, lang))
    return bundled if os.path.isfile(bundled) else ext

@dataclass
class Settings:
    threshold: float = 0.82
    lang: str = "ja"
    mode: str = "A"
    wait_b: float = 90.0
    poll_interval: float = 2.0

    scales: tuple = tuple(round(0.6 + 0.1 * i, 2) for i in range(9))
    jitter_px: int = 5
    delay_min: float = 0.15
    delay_max: float = 0.45
    click_cooldown: float = 3.0
    monitor_index: int = 1

    afk_enabled: bool = True
    afk_interval: float = 10.0
    afk_hold: float = 3.0
    afk_keys: tuple = ("w", "a", "s", "d")
