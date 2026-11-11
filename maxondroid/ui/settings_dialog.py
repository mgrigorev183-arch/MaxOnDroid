"""Settings: language, theme, which adb to use."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import paths
from maxondroid.core.adb import AdbRunner, find_adb
from maxondroid.core.settings import LANGUAGES, THEMES, Settings
from maxondroid.i18n import tr
from maxondroid.ui.common import label, open_folder
from maxondroid.ui.context import AppContext


class SettingsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setMinimumWidth(520)
        s = ctx.settings.settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(14)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        self.language = QComboBox()
        for code in LANGUAGES:
            self.language.addItem(tr(f"settings.language.{code}"), code)
        self.language.setCurrentIndex(LANGUAGES.index(s.language))
        self.theme = QComboBox()
        for code in THEMES:
            self.theme.addItem(tr(f"settings.theme.{code}"), code)
        self.theme.setCurrentIndex(THEMES.index(s.theme))
        form.addRow(label(tr("settings.language")), self.language)
        form.addRow(label(tr("settings.theme")), self.theme)

        adb_row = QHBoxLayout()
        self.adb_path = QLineEdit(s.adb_path)
        self.adb_path.setPlaceholderText(tr("settings.adb.auto"))
        self._adb_timer = QTimer(self)
        self._adb_timer.setSingleShot(True)
        self._adb_timer.setInterval(400)
        self._adb_timer.timeout.connect(self._update_adb_status)
        self.adb_path.textChanged.connect(lambda *_: self._adb_timer.start())
        browse = QPushButton(tr("settings.adb.browse"))
        browse.clicked.connect(self._browse)
        adb_row.addWidget(self.adb_path, 1)
        adb_row.addWidget(browse)
        form.addRow(label(tr("settings.adb")), adb_row)
        self.adb_status = label("", role="muted", wrap=True, selectable=True)
        form.addRow(label(""), self.adb_status)

        scrcpy_row = QHBoxLayout()
        self.scrcpy_path = QLineEdit(s.scrcpy_path)
        self.scrcpy_path.setPlaceholderText(tr("settings.scrcpy.auto"))
        browse_scrcpy = QPushButton(tr("settings.adb.browse"))
        browse_scrcpy.clicked.connect(self._browse_scrcpy)
        scrcpy_row.addWidget(self.scrcpy_path, 1)
        scrcpy_row.addWidget(browse_scrcpy)
        form.addRow(label(tr("settings.scrcpy")), scrcpy_row)

        self.auto_reconnect = QCheckBox(tr("settings.auto_reconnect"))
        self.auto_reconnect.setChecked(s.auto_reconnect)
        self.journal_visible = QCheckBox(tr("settings.journal_visible"))
        self.journal_visible.setChecked(s.journal_visible)
        form.addRow(label(""), self.auto_reconnect)
        form.addRow(label(""), self.journal_visible)
        layout.addLayout(form)

        folder_row = QHBoxLayout()
        open_config = QPushButton(tr("settings.open_config"))
        open_config.clicked.connect(lambda: open_folder(paths.config_dir()))
        open_logs = QPushButton(tr("settings.open_logs"))
        open_logs.clicked.connect(lambda: open_folder(paths.log_dir()))
        folder_row.addWidget(open_config)
        folder_row.addWidget(open_logs)
        folder_row.addStretch(1)
        layout.addLayout(folder_row)
        where = label(tr("settings.data_location", path=str(paths.explorer_path(paths.config_dir()))), role="muted", wrap=True, selectable=True)
        layout.addWidget(where)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setWindowTitle(tr("settings.title"))
        self._update_adb_status()

    def _browse(self) -> None:
        pattern = "adb.exe (adb.exe)" if sys.platform == "win32" else "adb (adb)"
        path, _ = QFileDialog.getOpenFileName(self, tr("settings.adb.pick"), self.adb_path.text(), pattern)
        if path:
            self.adb_path.setText(path)

    def _browse_scrcpy(self) -> None:
        pattern = "scrcpy.exe (scrcpy.exe)" if sys.platform == "win32" else "scrcpy (scrcpy)"
        path, _ = QFileDialog.getOpenFileName(self, tr("settings.scrcpy.pick"), self.scrcpy_path.text(), pattern)
        if path:
            self.scrcpy_path.setText(path)

    def _update_adb_status(self) -> None:
        custom = self.adb_path.text().strip()
        found = find_adb(custom or None)
        if not found:
            self.adb_status.setText(tr("settings.adb.missing"))
            return
        version = AdbRunner(found).version()
        if version:
            self.adb_status.setText(tr("settings.adb.found", path=found, version=version))
        else:
            self.adb_status.setText(tr("settings.adb.broken", path=found))

    def result_settings(self) -> Settings:
        s = self.ctx.settings.settings
        s.language = self.language.currentData()
        s.theme = self.theme.currentData()
        s.adb_path = self.adb_path.text().strip()
        s.scrcpy_path = self.scrcpy_path.text().strip()
        s.auto_reconnect = self.auto_reconnect.isChecked()
        s.journal_visible = self.journal_visible.isChecked()
        return s
