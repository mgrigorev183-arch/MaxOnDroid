"""User settings, stored as ``settings.json`` in the config folder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from maxondroid.core.jsonstore import read_json, write_json_atomic
from maxondroid.core.screen import KEYBOARDS, MAX_BIT_RATE, ScrcpyOptions

FORMAT = "maxondroid.settings"
MAX_SCREEN_DEVICES = 64
VERSION = 1

LANGUAGES = ("system", "ru", "en")
THEMES = ("system", "light", "dark")


@dataclass
class Settings:
    language: str = "system"
    theme: str = "system"
    adb_path: str = ""  # empty: bundled adb, then PATH
    journal_visible: bool = True
    auto_reconnect: bool = True
    window_geometry: str = ""  # base64 from Qt, opaque here
    window_state: str = ""
    # Screen tab (scrcpy)
    scrcpy_path: str = ""  # empty: next to adb, bundled, then PATH
    screen_preset: str = "quality"
    screen_max_size: int = 0
    screen_bit_rate: int = 8
    screen_max_fps: int = 0
    screen_audio: bool = True
    screen_turn_off: bool = False
    screen_on_top: bool = False
    screen_stay_awake: bool = False
    screen_view_only: bool = False
    screen_keyboard: str = "sdk"
    # options per device key (core.screen.ScrcpyOptions as a dict); the fields above are the
    # last used ones, the starting point for a device opened for the first time
    screen_devices: dict = field(default_factory=dict)
    capture_dir: str = ""  # empty: Pictures\MaxOnDroid

    def normalized(self) -> Settings:
        if self.language not in LANGUAGES:
            self.language = "system"
        if self.theme not in THEMES:
            self.theme = "system"
        self.adb_path = str(self.adb_path or "")
        if self.screen_preset not in ("quality", "speed"):
            self.screen_preset = "quality"
        self.screen_max_size = min(max(0, self.screen_max_size), 8192)
        self.screen_bit_rate = min(max(1, self.screen_bit_rate), MAX_BIT_RATE)
        self.screen_max_fps = min(max(0, self.screen_max_fps), 240)
        if self.screen_keyboard not in KEYBOARDS:
            self.screen_keyboard = "sdk"
        devices = {}
        for key, value in list(self.screen_devices.items())[-MAX_SCREEN_DEVICES:]:
            if isinstance(key, str) and key and isinstance(value, dict):
                devices[key] = ScrcpyOptions.from_dict(value).to_dict()
        self.screen_devices = devices
        return self


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.settings = self._load()

    def _load(self) -> Settings:
        data = read_json(self.path)
        settings = Settings()
        if isinstance(data, dict) and data.get("format") == FORMAT:
            values = data.get("settings", {})
            if isinstance(values, dict):
                for f in fields(Settings):
                    if f.name in values:
                        value = values[f.name]
                        expected = type(getattr(settings, f.name))
                        if isinstance(value, expected):
                            setattr(settings, f.name, value)
        return settings.normalized()

    def save(self) -> None:
        self.settings.normalized()
        write_json_atomic(self.path, {"format": FORMAT, "version": VERSION, "settings": asdict(self.settings)})
