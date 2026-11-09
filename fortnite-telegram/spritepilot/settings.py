from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile


def resource_root() -> Path:
    # PyInstaller also gives bundled modules a usable __file__. Package data
    # stays next to the package in both wheels and frozen builds.
    return Path(__file__).resolve().parent


def data_root() -> Path:
    explicit = os.environ.get("SPRITEPILOT_DATA")
    base = Path(explicit) if explicit else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "SpritePilot"
    base.mkdir(parents=True, exist_ok=True)
    return base


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class Settings:
    mode: str = "A"
    lang: str = "en"
    wait_b: float = 90.0
    threshold: float = 0.82
    afk_enabled: bool = False
    afk_interval: float = 10.0
    afk_hold: float = 3.0
    poll_interval: float = 1.0
    capture_interval: float = 0.3
    click_cooldown: float = 3.0
    delay_min: float = 0.05
    delay_max: float = 0.15
    jitter_px: int = 0
    scales: tuple = (0.65, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4)
    telegram_enabled: bool = False
    telegram_user_id: int = 0
    remote_control: bool = False
    remote_screenshots: bool = False
    notify_rewards: bool = True
    notify_unknown: bool = True
    summary_minutes: int = 60
    stuck_minutes: int = 10
    favorites: list[str] = field(default_factory=list)
    pause_on_favorite: bool = False
    variants: dict[str, str] = field(default_factory=lambda: {f"gizmo_{i}": f"Вариант {i}" for i in range(1, 6)})
    # Anchor/icon rectangles are pixel rectangles in the reference image.
    calibration: dict = field(default_factory=dict)

    def apply(self, values: dict) -> None:
        allowed = {item.name for item in fields(self)}
        ranges = {"wait_b": (10, 600), "threshold": (.3, .99), "afk_interval": (1, 600),
                  "afk_hold": (.1, 30), "capture_interval": (.1, 2), "poll_interval": (.2, 5),
                  "summary_minutes": (0, 1440), "stuck_minutes": (1, 240), "telegram_user_id": (0, 2**53)}
        for name, value in values.items():
            if name not in allowed or name == "scales":
                continue
            current = getattr(self, name)
            if isinstance(current, bool):
                if type(value) is not bool:
                    continue
            elif isinstance(current, (int, float)):
                if type(value) not in (int, float) or not math.isfinite(value):
                    continue
                if name in ranges and not ranges[name][0] <= value <= ranges[name][1]:
                    continue
                value = type(current)(value)
            elif not isinstance(value, type(current)):
                continue
            if name == "mode" and value not in ("A", "B"):
                continue
            if name == "lang" and value not in ("ja", "en", "ru", "es", "pt"):
                continue
            if name == "variants":
                value = {k: str(value.get(k, current[k]))[:60] for k in current}
            if name == "favorites":
                value = [k for k in value if k in self.variants]
            if name == "calibration" and value:
                if not valid_calibration(value):
                    continue
            setattr(self, name, value)

    @classmethod
    def load(cls, root: Path) -> Settings:
        result = cls()
        try:
            result.apply(json.loads((root / "settings.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return result

    def save(self, root: Path) -> None:
        atomic_json(root / "settings.json", asdict(self))

    def export_profile(self, path: Path) -> None:
        values = asdict(self)
        for key in ("telegram_enabled", "telegram_user_id", "remote_control", "remote_screenshots", "calibration"):
            values.pop(key, None)
        atomic_json(path, values)


def valid_calibration(value: dict) -> bool:
    for name in ("anchor", "icon"):
        rect = value.get(name)
        if not isinstance(rect, list) or len(rect) != 4:
            return False
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in rect):
            return False
        if min(rect) < 0 or rect[2] < 12 or rect[3] < 12:
            return False
    return True


def read_token() -> str:
    token = os.environ.get("SPRITEPILOT_TELEGRAM_TOKEN", "").strip()
    if token:
        return token
    try:
        import keyring
        return keyring.get_password("SpritePilot", "telegram") or ""
    except Exception:
        return ""


def save_token(token: str) -> None:
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("Проверьте формат токена BotFather")
    import keyring
    keyring.set_password("SpritePilot", "telegram", token)
