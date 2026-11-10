"""Application start-up."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from maxondroid import APP_ID, APP_NAME, __version__, i18n
from maxondroid.core import paths
from maxondroid.core.journal import Journal
from maxondroid.core.registry import Registry
from maxondroid.core.settings import SettingsStore
from maxondroid.ui import theme
from maxondroid.ui.context import AppContext
from maxondroid.ui.main_window import MainWindow
from maxondroid.ui.tokens import TokenStyle, paint_token
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
    retranslate = window.retranslate
    i18n.on_change(retranslate)
    window.destroyed.connect(lambda *_: i18n.remove_listener(retranslate))

    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: settings.settings.theme == "system" and apply_theme("system"))
    return window


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.desktop")
        except Exception:
            pass
    app = QApplication(argv if argv is not None else sys.argv)
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
