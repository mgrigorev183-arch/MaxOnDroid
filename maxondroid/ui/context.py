"""Objects shared by the windows and tabs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from maxondroid.core.adb import AdbRunner
from maxondroid.core.changes import ChangeJournal
from maxondroid.core.diag import Diagnostics
from maxondroid.core.journal import Journal
from maxondroid.core.manager import DeviceManager
from maxondroid.core.registry import Registry
from maxondroid.core.settings import SettingsStore
from maxondroid.core.uad import Database
from maxondroid.ui import theme
from maxondroid.ui.workers import TaskRunner


@dataclass
class AppContext:
    settings: SettingsStore
    registry: Registry
    journal: Journal
    tasks: TaskRunner
    runner: AdbRunner | None = None
    manager: DeviceManager | None = None
    palette: theme.Palette = theme.LIGHT
    changes: ChangeJournal | None = None
    uad: Database | None = None
    packages: object | None = None  # ui.package_support.PackageCache, set by the main window
    diag: Diagnostics | None = None  # slow commands and window stalls (core/diag.py)
    request_refresh: Callable[[], None] = field(default=lambda: None)
    open_connect: Callable[[str | None], None] = field(default=lambda tab=None: None)
    open_settings: Callable[[], None] = field(default=lambda: None)
