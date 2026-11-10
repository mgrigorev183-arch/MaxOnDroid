"""Where MaxOnDroid keeps its files.

Windows:
    settings and device registry  %APPDATA%\\MaxOnDroid
    command logs                  %LOCALAPPDATA%\\MaxOnDroid\\logs
Other systems follow the XDG base directories.

Setting the environment variable ``MAXONDROID_HOME`` puts everything under one
directory instead (used by tests and by portable setups).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from maxondroid import APP_ID, APP_NAME


def _home_override() -> Path | None:
    value = os.environ.get("MAXONDROID_HOME", "").strip()
    return Path(value) if value else None


def config_dir() -> Path:
    override = _home_override()
    if override:
        path = override / "config"
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    override = _home_override()
    if override:
        path = override / "logs"
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME / "logs"
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        path = Path(base) / APP_ID / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_root() -> Path:
    """Directory the application runs from (the install folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundled_tools_dir() -> Path:
    """Folder that ships adb and scrcpy with the installer."""
    return app_root() / "tools"
