"""Small widgets shared by several screens."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from maxondroid.core.devices import State, Transport
from maxondroid.core.info import Kind
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def label(text: str = "", role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    return lbl


class IconLabel(QWidget):
    """An icon drawn with the current theme colour, for banners."""

    def __init__(self, name: str, color: str, size: int = 18, parent: QWidget | None = None):
        super().__init__(parent)
        self.name, self.color, self._size = name, color, size
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self.color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        icons.paint(painter, self.name, QRectF(0, 0, self._size, self._size), self.color, 1.6)
        painter.end()


class Banner(QFrame):
    """A message strip with an optional action button. kind: warning, info, error."""

    def __init__(self, kind: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("kind", kind)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)
        self.icon = IconLabel("warning", "#000000")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.title = label("", wrap=True)
        font = self.title.font()
        font.setWeight(font.Weight.DemiBold)
        self.title.setFont(font)
        self.body = label("", wrap=True, selectable=True)
        text_box.addWidget(self.title)
        text_box.addWidget(self.body)
        layout.addLayout(text_box, 1)
        self.button = QPushButton()
        self.button.hide()
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._handler: Callable[[], None] | None = None
        self.button.clicked.connect(self._clicked)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.hide()

    def _clicked(self) -> None:
        if self._handler:
            self._handler()

    def show_message(
        self,
        kind: str,
        title: str,
        body: str = "",
        action: str | None = None,
        handler: Callable[[], None] | None = None,
        palette: theme.Palette | None = None,
    ) -> None:
        self.setProperty("kind", kind)
        repolish(self)
        for child in (self.title, self.body):
            repolish(child)
        p = palette or theme.LIGHT
        self.icon.name = "warning"
        self.icon.set_color({"warning": p.warning_text, "error": p.danger_text}.get(kind, p.info_text))
        self.title.setText(title)
        self.title.setVisible(bool(title))
        self.body.setText(body)
        self.body.setVisible(bool(body))
        self._handler = handler
        if action and handler:
            self.button.setText(action)
            self.button.show()
        else:
            self.button.hide()
        self.show()


def kind_name(kind: Kind) -> str:
    return tr(f"kind.{kind.value}")


def transport_name(transport: Transport | None) -> str:
    if transport is None:
        return ""
    return tr(f"transport.{transport.value}")


def state_name(state: State) -> str:
    key = "state." + state.value.replace(" ", "_")
    return tr(key)


def kind_icon(kind: Kind) -> str:
    return {Kind.TV: "tv", Kind.TABLET: "tablet", Kind.WATCH: "watch"}.get(kind, "phone")


def transport_icon(transport: Transport | None) -> str | None:
    if transport is None:
        return None
    return "usb" if transport in (Transport.USB, Transport.EMULATOR) else "wifi"


def format_kb(kb: int) -> str:
    gb = kb / (1024 * 1024)
    if gb >= 10:
        return tr("unit.gb", value=f"{gb:.0f}")
    if gb >= 1:
        return tr("unit.gb", value=f"{gb:.1f}".replace(".", tr("unit.decimal")))
    mb = kb / 1024
    return tr("unit.mb", value=f"{mb:.0f}")
