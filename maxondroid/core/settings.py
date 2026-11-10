"""User settings, stored as ``settings.json`` in the config folder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

from maxondroid.core.jsonstore import read_json, write_json_atomic

FORMAT = "maxondroid.settings"
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

    def normalized(self) -> Settings:
        if self.language not in LANGUAGES:
            self.language = "system"
        if self.theme not in THEMES:
            self.theme = "system"
        self.adb_path = str(self.adb_path or "")
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
