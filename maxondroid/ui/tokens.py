"""The cloakroom token: a round numbered disc that stands for one device.

Its shape carries the connection state, so the state never depends on colour
alone:

* connected     solid brass disc, dark numeral
* offline       outline ring, light numeral
* unauthorized  solid muted disc with a notch cut out at the top right
* busy          dashed ring (connecting, authorizing)
* legacy network adb open: an extra amber ring around any of the above
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from maxondroid.core.devices import State
from maxondroid.ui import theme


class TokenStyle(StrEnum):
    CONNECTED = "connected"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    BUSY = "busy"


def style_for(state: State) -> TokenStyle:
    if state is State.ONLINE:
        return TokenStyle.CONNECTED
    if state in (State.UNAUTHORIZED, State.NO_PERMISSIONS):
        return TokenStyle.UNAUTHORIZED
    if state in (State.AUTHORIZING, State.CONNECTING):
        return TokenStyle.BUSY
    if state in (State.RECOVERY, State.SIDELOAD, State.BOOTLOADER, State.RESCUE):
        return TokenStyle.CONNECTED
    return TokenStyle.OFFLINE


def token_label(number: int | None) -> str:
    return f"{number:02d}" if number is not None else "—"


def paint_token(
    painter: QPainter,
    rect: QRectF,
    number: int | None,
    style: TokenStyle,
    palette: theme.Palette,
    *,
    warning: bool = False,
    on_dark: bool = True,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    ring_gap = max(2.0, side * 0.08) if warning else 0.0
    ring_width = max(2.0, side * 0.07) if warning else 0.0
    inner = side - 2 * (ring_gap + ring_width)
    center = rect.center()
    disc = QRectF(center.x() - inner / 2, center.y() - inner / 2, inner, inner)
    stroke = max(1.5, inner * 0.06)

    if warning:
        pen = QPen(QColor(palette.warning), ring_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer = side - ring_width
        painter.drawEllipse(QRectF(center.x() - outer / 2, center.y() - outer / 2, outer, outer))

    numeral = QColor(palette.brass_on)
    if style is TokenStyle.CONNECTED:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.brass))
        painter.drawEllipse(disc)
    elif style is TokenStyle.UNAUTHORIZED:
        path = QPainterPath()
        path.addEllipse(disc)
        notch = QPainterPath()
        r = inner * 0.24
        notch.addEllipse(QPointF(disc.right() - inner * 0.12, disc.top() + inner * 0.12), r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.token_off))
        painter.drawPath(path.subtracted(notch))
    else:
        pen = QPen(QColor(palette.brass if style is TokenStyle.BUSY else palette.token_off), stroke)
        if style is TokenStyle.BUSY:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = stroke / 2
        painter.drawEllipse(disc.adjusted(half, half, -half, -half))
        numeral = QColor(palette.rail_text if on_dark else palette.text)

    painter.setPen(numeral)
    painter.setFont(theme.token_font(max(6.0, inner * 0.30)))
    painter.drawText(disc, Qt.AlignmentFlag.AlignCenter, token_label(number))
    painter.restore()


class TokenWidget(QWidget):
    """A token outside the device list (Overview header)."""

    def __init__(self, size: int = 44, parent: QWidget | None = None, on_dark: bool = False):
        super().__init__(parent)
        self._size = size
        self._number: int | None = None
        self._style = TokenStyle.OFFLINE
        self._warning = False
        self._palette = theme.LIGHT
        self._on_dark = on_dark
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(self._size, self._size)

    def set_token(self, number: int | None, style: TokenStyle, warning: bool, palette: theme.Palette) -> None:
        self._number, self._style, self._warning, self._palette = number, style, warning, palette
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        paint_token(
            painter,
            QRectF(0, 0, self.width(), self.height()),
            self._number,
            self._style,
            self._palette,
            warning=self._warning,
            on_dark=self._on_dark,
        )
        painter.end()
