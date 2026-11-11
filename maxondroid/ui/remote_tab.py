"""Remote tab: a TV remote on screen, plus the PC keyboard while the pad has focus."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import remote
from maxondroid.core.manager import DeviceView
from maxondroid.i18n import tr
from maxondroid.ui import icons
from maxondroid.ui.common import Placeholder, label
from maxondroid.ui.context import AppContext
from maxondroid.ui.workers import TaskRunner

LONG_PRESS_MS = 600

#: PC keyboard → remote key while the pad has focus.
SHORTCUTS: dict[int, str] = {
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Return: "ok",
    Qt.Key.Key_Enter: "ok",
    Qt.Key.Key_Escape: "back",
    Qt.Key.Key_Backspace: "back",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_Menu: "menu",
    Qt.Key.Key_Space: "play_pause",
    Qt.Key.Key_MediaPlay: "play_pause",
    Qt.Key.Key_MediaTogglePlayPause: "play_pause",
    Qt.Key.Key_MediaNext: "next",
    Qt.Key.Key_MediaPrevious: "previous",
    Qt.Key.Key_Plus: "volume_up",
    Qt.Key.Key_Equal: "volume_up",
    Qt.Key.Key_Minus: "volume_down",
    Qt.Key.Key_VolumeUp: "volume_up",
    Qt.Key.Key_VolumeDown: "volume_down",
    Qt.Key.Key_VolumeMute: "mute",
    Qt.Key.Key_M: "mute",
    Qt.Key.Key_PageUp: "channel_up",
    Qt.Key.Key_PageDown: "channel_down",
    Qt.Key.Key_BracketLeft: "rewind",
    Qt.Key.Key_BracketRight: "fast_forward",
}


#: Keys that may repeat while a PC key is held down.
REPEATABLE = {"up", "down", "left", "right", "volume_up", "volume_down", "channel_up", "channel_down", "rewind", "fast_forward"}


class KeySender(QObject):
    """Sends keys one after another, in the order they were pressed."""

    sent = Signal(str, bool, str)  # key, ok, error text

    def __init__(self, ctx: AppContext, parent: QObject | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.tasks = TaskRunner(self, max_threads=1)

    def send(self, serial: str, key: str, long: bool = False) -> None:
        runner = self.ctx.runner
        if runner is None:
            return

        def work():
            return remote.press(runner, serial, key, long)

        def done(result) -> None:
            self.sent.emit(key, result.ok, "" if result.ok else result.display_output())

        self.tasks.submit(work, done, lambda exc: self.sent.emit(key, False, str(exc)))

    def type_text(self, serial: str, text: str, on_done: Callable[[bool, str], None]) -> None:
        runner = self.ctx.runner
        if runner is None:
            return

        def done(result: remote.TextResult) -> None:
            last = result.results[-1].display_output() if result.results else ""
            on_done(result.ok, "" if result.ok else last)

        self.tasks.submit(lambda: remote.type_text(runner, serial, text), done, lambda exc: on_done(False, str(exc)))


class RemoteButton(QToolButton):
    """A remote key: click for a press, hold for a long press. Never takes focus from the pad."""

    def __init__(self, key: str, icon_name: str, with_text: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.icon_name = icon_name
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setProperty("remote", True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if with_text else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(20, 20))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(56, 52 if with_text else 44)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(LONG_PRESS_MS)
        self._timer.timeout.connect(self._long)
        self._long_fired = False
        self.on_press: Callable[[str, bool], None] = lambda key, long: None
        self.pressed.connect(self._start)
        self.released.connect(self._end)

    def _start(self) -> None:
        self._long_fired = False
        self._timer.start()

    def _long(self) -> None:
        self._long_fired = True
        self.on_press(self.key, True)

    def _end(self) -> None:
        self._timer.stop()
        if not self._long_fired:
            self.on_press(self.key, False)


class RemotePad(QFrame):
    """Takes the PC keyboard when focused."""

    key_pressed = Signal(str)
    focus_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("RemotePad")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = SHORTCUTS.get(Qt.Key(event.key()))
        if key and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            if not event.isAutoRepeat() or key in REPEATABLE:  # a held Enter must not press OK twenty times
                self.key_pressed.emit(key)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.focus_changed.emit(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.focus_changed.emit(False)
        super().focusOutEvent(event)


class RemoteTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self.sender_ = KeySender(ctx, self)
        self.sender_.sent.connect(self._sent)
        self.buttons: dict[str, RemoteButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.placeholder = Placeholder()
        self.stack.addWidget(self.placeholder)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 16, 20, 14)
        page_layout.setSpacing(12)

        self.pad = RemotePad()
        self.pad.key_pressed.connect(lambda key: self.press(key, False))
        self.pad.focus_changed.connect(self._focus_changed)
        pad_layout = QHBoxLayout(self.pad)
        pad_layout.setContentsMargins(18, 16, 18, 16)
        pad_layout.setSpacing(28)

        # navigation: d-pad and the keys under it
        nav = QVBoxLayout()
        nav.setSpacing(10)
        dpad = QGridLayout()
        dpad.setSpacing(6)
        dpad.addWidget(self._button("up", "up", with_text=False), 0, 1)
        dpad.addWidget(self._button("left", "left", with_text=False), 1, 0)
        ok = self._button("ok", None, with_text=True)
        ok.setObjectName("RemoteOk")
        ok.setMinimumSize(72, 56)
        dpad.addWidget(ok, 1, 1)
        dpad.addWidget(self._button("right", "right", with_text=False), 1, 2)
        dpad.addWidget(self._button("down", "down", with_text=False), 2, 1)
        nav.addLayout(dpad)
        row = QHBoxLayout()
        row.setSpacing(6)
        for key in ("back", "home", "menu", "recents"):
            row.addWidget(self._button(key, key))
        nav.addLayout(row)
        pad_layout.addLayout(nav, 3)

        # sound, power, channels
        side = QGridLayout()
        side.setSpacing(6)
        side.addWidget(self._button("power", "power"), 0, 0)
        side.addWidget(self._button("mute", "mute"), 0, 1)
        side.addWidget(self._button("volume_up", "volume_up"), 1, 0)
        side.addWidget(self._button("channel_up", "channel_up"), 1, 1)
        side.addWidget(self._button("volume_down", "volume_down"), 2, 0)
        side.addWidget(self._button("channel_down", "channel_down"), 2, 1)
        side.addWidget(self._button("settings", "settings"), 3, 0)
        side.addWidget(self._button("input", "input"), 3, 1)
        pad_layout.addLayout(side, 2)
        page_layout.addWidget(self.pad)

        media = QHBoxLayout()
        media.setSpacing(6)
        for key in ("previous", "rewind", "play_pause", "fast_forward", "next", "search"):
            media.addWidget(self._button(key, key))
        page_layout.addLayout(media)

        text_row = QHBoxLayout()
        text_row.setSpacing(8)
        self.text = QLineEdit()
        self.text.setClearButtonEnabled(True)
        self.text.returnPressed.connect(self.send_text)
        self.send_button = QPushButton()
        self.send_button.clicked.connect(self.send_text)
        text_row.addWidget(self.text, 1)
        text_row.addWidget(self.send_button)
        for key in ("delete", "enter"):
            button = self._button(key, key, with_text=False)
            button.setMinimumSize(40, 34)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            text_row.addWidget(button)
        page_layout.addLayout(text_row)

        self.hint = label("", role="muted", wrap=True)
        self.status = label("", role="muted", wrap=True, selectable=True)
        page_layout.addWidget(self.hint)
        page_layout.addWidget(self.status)
        page_layout.addStretch(1)
        self.stack.addWidget(page)
        self.retranslate()

    def _button(self, key: str, icon_name: str | None, with_text: bool = True) -> RemoteButton:
        button = RemoteButton(key, icon_name or "", with_text)
        button.on_press = self.press
        self.buttons[key] = button
        return button

    # -- language and theme ----------------------------------------------------
    def retranslate(self) -> None:
        for key, button in self.buttons.items():
            name = tr(f"remote.key.{key}")
            button.setText(name if button.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly else "")
            button.setToolTip(name + " — " + tr("remote.hold_hint"))
            button.setAccessibleName(name)
        self.text.setPlaceholderText(tr("remote.text.placeholder"))
        self.send_button.setText(tr("remote.text.send"))
        self._focus_changed(self.pad.hasFocus())
        self.apply_palette()
        self.render()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        for button in self.buttons.values():
            if button.icon_name:
                color = p.brass_on if button.objectName() == "RemoteOk" else p.text
                button.setIcon(icons.icon(button.icon_name, color, 20))

    def _focus_changed(self, focused: bool) -> None:
        self.hint.setText(tr("remote.keyboard.on") if focused else tr("remote.keyboard.off"))

    # -- device ----------------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        changed = self.view is None or view is None or self.view.key != view.key or self.view.online != view.online
        self.view = view
        if changed:
            self.status.setText("")
            self.render()

    def render(self) -> None:
        if self.view is None or not self.view.online:
            self.placeholder.set_message(tr("remote.offline"))
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.stack.currentIndex() == 1:
            self.pad.setFocus(Qt.FocusReason.OtherFocusReason)

    # -- actions -----------------------------------------------------------------
    def press(self, key: str, long: bool = False) -> None:
        if self.view is None or not self.view.online:
            return
        self.sender_.send(self.view.serial, key, long)

    def _sent(self, key: str, ok: bool, error: str) -> None:
        name = tr(f"remote.key.{key}")
        if ok:
            self.status.setText(tr("remote.sent", key=name))
        else:
            self.status.setText(tr("remote.failed", key=name, details=error or "—"))

    def send_text(self) -> None:
        text = self.text.text()
        if not text or self.view is None or not self.view.online:
            return
        bad = remote.unsupported_characters(text)
        if bad:
            self.status.setText(tr("remote.text.unsupported", chars=bad[:12]))
            return
        self.send_button.setEnabled(False)

        def done(ok: bool, error: str) -> None:
            self.send_button.setEnabled(True)
            if ok:
                self.text.clear()
                self.status.setText(tr("remote.text.sent"))
            else:
                self.status.setText(tr("remote.text.failed", details=error or "—"))

        self.sender_.type_text(self.view.serial, text, done)

