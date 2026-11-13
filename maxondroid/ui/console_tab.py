"""Console tab: type an adb command or a device shell line, see the output as it comes.

The exact adb command is shown before it runs (the preview line under the
input), and every run goes to the journal like any button. Nothing goes
through cmd.exe: see core/console.py for how the text becomes arguments.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import console, paths
from maxondroid.core.console import Command, ConsoleError, ConsoleStore, Run
from maxondroid.core.manager import DeviceView
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import label
from maxondroid.ui.context import AppContext
from maxondroid.ui.tokens import token_label

MAX_BLOCKS = 5000  # lines kept in the output; logcat would fill memory otherwise
FLUSH_MS = 60


class _Bridge(QObject):
    output = Signal(str)
    exited = Signal(object)


class ConsoleTab(QWidget):
    def __init__(self, ctx: AppContext, store: ConsoleStore | None = None):
        super().__init__()
        self.ctx = ctx
        self.view: DeviceView | None = None
        self.store = store or ConsoleStore.load(paths.config_dir() / "console.json")
        self.run: Run | None = None
        self._history_pos: int | None = None
        self._draft = ""
        self._pending: list[str] = []
        self._bridge = _Bridge(self)
        self._bridge.output.connect(self._queue, Qt.ConnectionType.QueuedConnection)
        self._bridge.exited.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.mode_adb = QRadioButton()
        self.mode_shell = QRadioButton()
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_adb)
        self.mode_group.addButton(self.mode_shell)
        (self.mode_shell if ctx.settings.settings.console_mode == "shell" else self.mode_adb).setChecked(True)
        self.mode_adb.toggled.connect(self._mode_changed)
        self.device_label = label("", role="muted")
        top.addWidget(self.mode_adb)
        top.addWidget(self.mode_shell)
        top.addStretch(1)
        top.addWidget(self.device_label)
        layout.addLayout(top)

        entry = QHBoxLayout()
        entry.setSpacing(8)
        self.input = QLineEdit()
        self.input.setFont(theme.mono_font(10))
        self.input.textChanged.connect(self._update_preview)
        self.input.returnPressed.connect(self.execute)
        self.input.installEventFilter(self)
        self.run_button = QPushButton()
        self.run_button.setObjectName("Primary")
        self.run_button.clicked.connect(self.execute)
        self.stop_button = QPushButton()
        self.stop_button.clicked.connect(self.stop)
        entry.addWidget(self.input, 1)
        entry.addWidget(self.run_button)
        entry.addWidget(self.stop_button)
        layout.addLayout(entry)
        self.preview = label("", role="muted", wrap=True, selectable=True)
        self.preview.setFont(theme.mono_font(9))
        layout.addWidget(self.preview)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(theme.mono_font(9.5))
        self.output.setMaximumBlockCount(MAX_BLOCKS)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        split.addWidget(self.output)
        saved_box = QWidget()
        saved = QVBoxLayout(saved_box)
        saved.setContentsMargins(8, 0, 0, 0)
        saved.setSpacing(6)
        self.saved_title = label("", role="section")
        saved.addWidget(self.saved_title)
        self.saved_list = QListWidget()
        self.saved_list.itemDoubleClicked.connect(self._load_saved)
        self.saved_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        saved.addWidget(self.saved_list, 1)
        self.saved_empty = label("", role="muted", wrap=True)
        saved.addWidget(self.saved_empty)
        saved_buttons = QHBoxLayout()
        saved_buttons.setSpacing(6)
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self.save_current)
        self.run_saved_button = QPushButton()
        self.run_saved_button.clicked.connect(self.run_saved)
        self.delete_saved_button = QPushButton()
        self.delete_saved_button.clicked.connect(self.delete_saved)
        saved_buttons.addWidget(self.run_saved_button)
        saved_buttons.addWidget(self.delete_saved_button)
        saved.addWidget(self.save_button)  # on its own row: the column stays narrow
        saved.addLayout(saved_buttons)
        split.addWidget(saved_box)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([720, 240])  # the output gets the room, the saved list a column
        layout.addWidget(split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.status = label("", role="muted")
        self.clear_button = QPushButton()
        self.clear_button.clicked.connect(self.output.clear)
        self.copy_button = QPushButton()
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.output.toPlainText()))
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.clear_button)
        bottom.addWidget(self.copy_button)
        layout.addLayout(bottom)

        self.retranslate()

    # -- state -----------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return "shell" if self.mode_shell.isChecked() else "adb"

    def serial(self) -> str | None:
        return self.view.serial if self.view is not None and self.view.online else None

    def set_device(self, view: DeviceView | None) -> None:
        self.view = view
        self._update_device()
        self._update_preview()

    def _update_device(self) -> None:
        view = self.view
        if view is not None and view.online:
            self.device_label.setText(tr("console.device", token=token_label(view.token), name=view.name))
        else:
            self.device_label.setText(tr("console.no_device"))

    def command(self) -> Command:
        return console.build(self.mode, self.input.text(), self.serial())

    def _update_preview(self, *_args) -> None:
        if not self.input.text().strip():
            self.preview.setText(tr(f"console.example.{self.mode}"))
            self.preview.setProperty("role", "muted")
        else:
            try:
                self.preview.setText(tr("console.preview", command=self.command().display()))
                self.preview.setProperty("role", "muted")
            except ConsoleError as exc:
                self.preview.setText(tr(f"console.error.{exc.code}"))
                self.preview.setProperty("role", "error")
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
        self._update_buttons()

    def _update_buttons(self) -> None:
        running = self.run is not None and self.run.running
        try:
            valid = bool(self.input.text().strip()) and self.command() is not None
        except ConsoleError:
            valid = False
        self.run_button.setEnabled(valid and not running)
        self.stop_button.setEnabled(running)
        self.run_saved_button.setEnabled(self.saved_list.currentItem() is not None and not running)
        self.delete_saved_button.setEnabled(self.saved_list.currentItem() is not None)
        self.save_button.setEnabled(bool(self.input.text().strip()))

    def _mode_changed(self, *_args) -> None:
        self.ctx.settings.settings.console_mode = self.mode
        try:
            self.ctx.settings.save()
        except OSError:
            pass
        self.input.setPlaceholderText(tr(f"console.placeholder.{self.mode}"))
        self._update_preview()

    # -- texts and look --------------------------------------------------------------
    def retranslate(self) -> None:
        self.mode_adb.setText(tr("console.mode.adb"))
        self.mode_adb.setToolTip(tr("console.mode.adb.tip"))
        self.mode_shell.setText(tr("console.mode.shell"))
        self.mode_shell.setToolTip(tr("console.mode.shell.tip"))
        self.input.setPlaceholderText(tr(f"console.placeholder.{self.mode}"))
        self.input.setToolTip(tr("console.input.tip"))
        self.run_button.setText(tr("console.run"))
        self.stop_button.setText(tr("console.stop"))
        self.saved_title.setText(tr("console.saved"))
        self.save_button.setText(tr("console.save"))
        self.run_saved_button.setText(tr("console.run_saved"))
        self.delete_saved_button.setText(tr("console.delete_saved"))
        self.clear_button.setText(tr("console.clear"))
        self.copy_button.setText(tr("console.copy"))
        self.saved_list.setToolTip(tr("console.saved.tip"))
        self.saved_empty.setText(tr("console.saved.empty"))
        self._fill_saved()
        self._update_device()
        self._update_preview()
        self.apply_palette()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.stop_button.setIcon(icons.icon("stop", p.danger))
        self.clear_button.setIcon(icons.icon("trash", p.text_muted))
        self.copy_button.setIcon(icons.icon("copy", p.text_muted))

    def _fill_saved(self, select: str | None = None) -> None:
        current = select or (self.saved_list.currentItem().data(Qt.ItemDataRole.UserRole).name if self.saved_list.currentItem() else None)
        self.saved_list.clear()
        for item in self.store.saved:
            row = QListWidgetItem(f"{item.name}")
            row.setToolTip(f"{tr('console.mode.' + item.mode)}: {item.text}")
            row.setData(Qt.ItemDataRole.UserRole, item)
            self.saved_list.addItem(row)
            if item.name == current:
                self.saved_list.setCurrentItem(row)
        self.saved_empty.setVisible(not self.store.saved)

    # -- running ---------------------------------------------------------------------
    def execute(self) -> None:
        if self.run is not None and self.run.running:
            return
        try:
            command = self.command()
        except ConsoleError as exc:
            self.status.setText(tr(f"console.error.{exc.code}"))
            return
        runner = self.ctx.runner
        if runner is None:
            self.status.setText(tr("console.no_adb"))
            return
        self.store.remember(self.mode, self.input.text(), command.secrets)
        try:
            self.store.save()
        except OSError:
            pass
        self._history_pos = None
        self._append(("\n" if self.output.toPlainText() else "") + "> " + command.display() + "\n")
        self.status.setText(tr("console.running"))
        try:
            self.run = Run(runner, command, self._bridge.output.emit, self._bridge.exited.emit)
        except Exception as exc:  # adb missing or refused
            self.run = None
            self.status.setText(tr("console.failed", details=str(exc)))
            return
        self._flush_timer.start()
        self._update_buttons()

    def stop(self) -> None:
        if self.run is not None:
            self.run.stop()

    def shutdown(self) -> None:
        self.stop()

    def _queue(self, text: str) -> None:
        self._pending.append(text)

    def _flush(self) -> None:
        if self._pending:
            text = "".join(self._pending)
            self._pending.clear()
            self._append(text)

    def _append(self, text: str) -> None:
        bar = self.output.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if at_end:
            bar.setValue(bar.maximum())

    def _finished(self, run: Run) -> None:
        self._flush()
        self._flush_timer.stop()
        seconds = f"{run.duration:.1f}".replace(".", tr("unit.decimal"))
        if run.stopped:
            self.status.setText(tr("console.stopped", seconds=seconds))
        elif run.returncode == 1 and not run.output_tail().strip():
            self.status.setText(tr("console.done_quiet", seconds=seconds))
        else:
            self.status.setText(tr("console.done", code=run.returncode, seconds=seconds))
        serial = next((run.command.args[i + 1] for i, a in enumerate(run.command.args[:-1]) if a == "-s"), None)
        self.ctx.journal.note(run.command.display(), serial, run.output_tail(), run.returncode == 0 and not run.stopped, duration=run.duration)
        if self.run is run:
            self._update_buttons()

    # -- history ---------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._walk_history(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(obj, event)

    def _walk_history(self, step: int) -> None:
        history = self.store.history
        if not history:
            return
        if self._history_pos is None:
            if step > 0:
                return
            self._draft = self.input.text()
            self._history_pos = len(history)
        position = self._history_pos + step
        if position >= len(history):
            self._history_pos = None
            self.input.setText(self._draft)
            return
        self._history_pos = max(0, position)
        mode, text = history[self._history_pos]
        (self.mode_shell if mode == "shell" else self.mode_adb).setChecked(True)
        self.input.setText(text)

    # -- saved -----------------------------------------------------------------------
    def save_current(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        name, ok = QInputDialog.getText(self, tr("console.save.title"), tr("console.save.prompt"), text=text[:40])
        if not ok or not name.strip():
            return
        try:
            item = self.store.add_saved(name, self.mode, text)
            self.store.save()
        except (ConsoleError, OSError) as exc:
            self.status.setText(tr("console.save.failed", details=str(exc)))
            return
        self._fill_saved(select=item.name)
        self.status.setText(tr("console.saved_one", name=item.name))
        self._update_buttons()

    def _load_saved(self, row: QListWidgetItem | None = None) -> None:
        row = row or self.saved_list.currentItem()
        if row is None:
            return
        item = row.data(Qt.ItemDataRole.UserRole)
        (self.mode_shell if item.mode == "shell" else self.mode_adb).setChecked(True)
        self.input.setText(item.text)
        self.input.setFocus()

    def run_saved(self) -> None:
        self._load_saved()
        self.execute()

    def delete_saved(self) -> None:
        row = self.saved_list.currentItem()
        if row is None:
            return
        self.store.remove_saved(row.data(Qt.ItemDataRole.UserRole).name)
        try:
            self.store.save()
        except OSError:
            pass
        self._fill_saved()
        self._update_buttons()

