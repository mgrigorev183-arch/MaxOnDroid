"""Application start-up."""

from __future__ import annotations

import sys

import shiboken6
from PySide6.QtCore import QLocale, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from maxondroid import APP_ID, APP_NAME, __version__, i18n
from maxondroid.core import paths, uad
from maxondroid.core.changes import ChangeJournal
from maxondroid.core.diag import Diagnostics
from maxondroid.core.journal import Journal
from maxondroid.core.registry import Registry
from maxondroid.core.settings import SettingsStore
from maxondroid.ui import theme
from maxondroid.ui.context import AppContext
from maxondroid.ui.main_window import MainWindow
from maxondroid.ui.tokens import TokenStyle, paint_token
from maxondroid.ui.watchdog import StallWatchdog
from maxondroid.ui.workers import TaskRunner


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        from PySide6.QtCore import QRectF

        paint_token(painter, QRectF(0, 0, size, size), None, TokenStyle.CONNECTED, theme.LIGHT)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def create_window(app: QApplication) -> MainWindow:
    settings = SettingsStore(paths.config_dir() / "settings.json")
    registry = Registry(paths.config_dir() / "devices.json")
    journal = Journal(paths.log_dir())
    ctx = AppContext(settings=settings, registry=registry, journal=journal, tasks=TaskRunner(app))
    ctx.changes = ChangeJournal(paths.config_dir() / "changes.json")
    ctx.diag = Diagnostics(paths.log_dir())
    try:
        ctx.uad = uad.load(paths.package_data_dir() / "uad", paths.data_dir())
    except (OSError, uad.DatabaseError):
        ctx.uad = None  # the Debloat tab says the database is missing

    def apply_language(setting: str) -> None:
        i18n.set_language(i18n.resolve(setting, QLocale.system().uiLanguages()))

    def apply_theme(setting: str) -> None:
        ctx.palette = theme.resolve(setting)
        theme.apply(app, ctx.palette)
        if window is not None:
            window.theme_changed()

    window: MainWindow | None = None
    apply_language(settings.settings.language)
    apply_theme(settings.settings.theme)
    window = MainWindow(ctx, apply_theme, apply_language)
    def retranslate() -> None:
        if shiboken6.isValid(window) and shiboken6.isValid(window.apps):
            window.retranslate()
        else:  # the window is gone: stop listening
            i18n.remove_listener(retranslate)

    i18n.on_change(retranslate)
    window.watchdog = StallWatchdog(ctx.diag, window)
    QTimer.singleShot(0, window.watchdog.start)  # once the event loop runs: startup work is not a freeze
    window.i18n_listener = retranslate  # removed in closeEvent
    window.destroyed.connect(lambda *_: i18n.remove_listener(retranslate))

    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: settings.settings.theme == "system" and apply_theme("system"))
    return window


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    from maxondroid import selftest

    self_test = selftest.parse_args(args[1:])
    if self_test is not None:  # the release build checks itself; see maxondroid/selftest.py
        return selftest.main(*self_test)
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.desktop")
        except Exception:
            pass
    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(theme.font(theme.UI_FAMILIES, 9.5))
    app.setWindowIcon(app_icon())
    window = create_window(app)
    window.show()
    window.setup_adb()
    return app.exec()
