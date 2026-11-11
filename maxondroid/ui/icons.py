"""A small set of line icons drawn in code: one stroke weight, one grid (16x16)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

Drawer = Callable[[QPainter], None]


def _path(points: list[tuple[float, float]], closed: bool = False) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    if closed:
        path.closeSubpath()
    return path


def _warning(p: QPainter) -> None:
    p.drawPath(_path([(8, 1.8), (14.8, 13.8), (1.2, 13.8)], closed=True))
    p.drawLine(QPointF(8, 6), QPointF(8, 9.6))
    p.drawPoint(QPointF(8, 11.7))


def _refresh(p: QPainter) -> None:
    p.drawArc(QRectF(2.5, 2.5, 11, 11), 60 * 16, 270 * 16)
    p.drawPath(_path([(10.2, 1.6), (13.1, 3.4), (10.9, 6.0)]))


def _plus(p: QPainter) -> None:
    p.drawLine(QPointF(8, 2.5), QPointF(8, 13.5))
    p.drawLine(QPointF(2.5, 8), QPointF(13.5, 8))


def _sliders(p: QPainter) -> None:
    for y, knob in ((3.5, 10.5), (8, 5), (12.5, 9)):
        p.drawLine(QPointF(2, y), QPointF(14, y))
        p.save()
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(knob, y), 1.6, 1.6)
        p.restore()


def _phone(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4.5, 1.5, 7, 13), 1.5, 1.5)
    p.drawLine(QPointF(7, 12.3), QPointF(9, 12.3))


def _tv(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(1.5, 2.5, 13, 8.5), 1, 1)
    p.drawLine(QPointF(5, 14), QPointF(11, 14))
    p.drawLine(QPointF(8, 11), QPointF(8, 14))


def _wifi(p: QPainter) -> None:
    p.drawArc(QRectF(1.5, 4, 13, 13), 45 * 16, 90 * 16)
    p.drawArc(QRectF(4, 6.8, 8, 8), 45 * 16, 90 * 16)
    p.save()
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(8, 12.8), 1.1, 1.1)
    p.restore()


def _usb(p: QPainter) -> None:
    p.drawLine(QPointF(8, 1.8), QPointF(8, 14.2))
    p.drawPath(_path([(8, 10.5), (4.5, 8), (4.5, 6)]))
    p.drawPath(_path([(8, 9), (11.5, 6.8), (11.5, 5)]))
    p.drawEllipse(QPointF(4.5, 5), 1.1, 1.1)
    p.drawRect(QRectF(10.6, 3.2, 1.8, 1.8))
    p.drawPath(_path([(6.5, 3.3), (8, 1.6), (9.5, 3.3)]))


def _chevron_down(p: QPainter) -> None:
    p.drawPath(_path([(4, 6), (8, 10), (12, 6)]))


def _trash(p: QPainter) -> None:
    p.drawLine(QPointF(2.5, 4), QPointF(13.5, 4))
    p.drawPath(_path([(6, 4), (6, 2.2), (10, 2.2), (10, 4)]))
    p.drawPath(_path([(4, 4), (4.8, 14), (11.2, 14), (12, 4)]))


def _copy(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(5, 5, 9, 9), 1, 1)
    p.drawPath(_path([(3, 10.5), (2, 10.5), (2, 2), (10.5, 2), (10.5, 3)]))


def _hide(p: QPainter) -> None:
    p.drawPath(_path([(4, 6.5), (8, 10.5), (12, 6.5)]))


def _show(p: QPainter) -> None:
    p.drawPath(_path([(4, 10), (8, 6), (12, 10)]))


def _link(p: QPainter) -> None:
    p.drawPath(_path([(9, 2), (14, 2), (14, 7)]))
    p.drawLine(QPointF(14, 2), QPointF(7.5, 8.5))
    p.drawPath(_path([(12, 9.5), (12, 14), (2, 14), (2, 4), (6.5, 4)]))


def _arrow(direction: str):
    def draw(p: QPainter) -> None:
        pts = {"up": [(3.5, 10.5), (8, 6), (12.5, 10.5)], "down": [(3.5, 5.5), (8, 10), (12.5, 5.5)],
               "left": [(10.5, 3.5), (6, 8), (10.5, 12.5)], "right": [(5.5, 3.5), (10, 8), (5.5, 12.5)]}[direction]
        p.drawPath(_path(pts))
    return draw


def _back(p: QPainter) -> None:
    p.drawPath(_path([(6, 3), (2.5, 6.5), (6, 10)]))
    path = QPainterPath(QPointF(2.5, 6.5))
    path.lineTo(10, 6.5)
    path.cubicTo(15, 6.5, 15, 13.5, 10, 13.5)
    path.lineTo(6.5, 13.5)
    p.drawPath(path)


def _home(p: QPainter) -> None:
    p.drawPath(_path([(2, 8), (8, 2.5), (14, 8)]))
    p.drawPath(_path([(3.8, 6.5), (3.8, 13.5), (12.2, 13.5), (12.2, 6.5)]))
    p.drawPath(_path([(6.5, 13.5), (6.5, 9.5), (9.5, 9.5), (9.5, 13.5)]))


def _menu(p: QPainter) -> None:
    for y in (4, 8, 12):
        p.drawLine(QPointF(2.5, y), QPointF(13.5, y))


def _recents(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2.5, 4.5, 8, 9), 1, 1)
    p.drawPath(_path([(5, 2.5), (13.5, 2.5), (13.5, 11)]))


def _power(p: QPainter) -> None:
    p.drawArc(QRectF(2.5, 3, 11, 11), 125 * 16, 290 * 16)
    p.drawLine(QPointF(8, 1.8), QPointF(8, 7.5))


def _speaker(p: QPainter) -> None:
    p.drawPath(_path([(2, 6), (4.5, 6), (8, 3), (8, 13), (4.5, 10), (2, 10)], closed=True))


def _volume_up(p: QPainter) -> None:
    _speaker(p)
    p.drawLine(QPointF(10.5, 8), QPointF(14.5, 8))
    p.drawLine(QPointF(12.5, 6), QPointF(12.5, 10))


def _volume_down(p: QPainter) -> None:
    _speaker(p)
    p.drawLine(QPointF(10.5, 8), QPointF(14.5, 8))


def _mute(p: QPainter) -> None:
    _speaker(p)
    p.drawLine(QPointF(10.5, 6), QPointF(14.5, 10))
    p.drawLine(QPointF(14.5, 6), QPointF(10.5, 10))


def _play_pause(p: QPainter) -> None:
    p.drawPath(_path([(2.5, 3), (8, 8), (2.5, 13)], closed=True))
    p.drawLine(QPointF(10.5, 3.5), QPointF(10.5, 12.5))
    p.drawLine(QPointF(13.5, 3.5), QPointF(13.5, 12.5))


def _stop(p: QPainter) -> None:
    p.drawRect(QRectF(4, 4, 8, 8))


def _previous(p: QPainter) -> None:
    p.drawLine(QPointF(3.5, 3.5), QPointF(3.5, 12.5))
    p.drawPath(_path([(12.5, 3.5), (5.5, 8), (12.5, 12.5)], closed=True))


def _next(p: QPainter) -> None:
    p.drawLine(QPointF(12.5, 3.5), QPointF(12.5, 12.5))
    p.drawPath(_path([(3.5, 3.5), (10.5, 8), (3.5, 12.5)], closed=True))


def _rewind(p: QPainter) -> None:
    p.drawPath(_path([(8, 4), (2.5, 8), (8, 12)], closed=True))
    p.drawPath(_path([(14, 4), (8.5, 8), (14, 12)], closed=True))


def _fast_forward(p: QPainter) -> None:
    p.drawPath(_path([(2, 4), (7.5, 8), (2, 12)], closed=True))
    p.drawPath(_path([(8, 4), (13.5, 8), (8, 12)], closed=True))


def _search(p: QPainter) -> None:
    p.drawEllipse(QRectF(2.5, 2.5, 8, 8))
    p.drawLine(QPointF(9.5, 9.5), QPointF(13.8, 13.8))


def _camera(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(1.5, 4.5, 13, 9), 1.5, 1.5)
    p.drawPath(_path([(5, 4.5), (6.2, 2.5), (9.8, 2.5), (11, 4.5)]))
    p.drawEllipse(QPointF(8, 9), 2.4, 2.4)


def _record(p: QPainter) -> None:
    p.drawEllipse(QPointF(8, 8), 5.5, 5.5)
    p.save()
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(8, 8), 2.6, 2.6)
    p.restore()


def _screen(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(1.5, 2.5, 13, 9), 1, 1)
    p.drawLine(QPointF(5.5, 14), QPointF(10.5, 14))
    p.drawLine(QPointF(8, 11.5), QPointF(8, 14))


def _channel_up(p: QPainter) -> None:
    p.drawPath(_path([(4, 9.5), (8, 5.5), (12, 9.5)]))
    p.drawLine(QPointF(4, 12.5), QPointF(12, 12.5))


def _channel_down(p: QPainter) -> None:
    p.drawPath(_path([(4, 6.5), (8, 10.5), (12, 6.5)]))
    p.drawLine(QPointF(4, 3.5), QPointF(12, 3.5))


def _enter(p: QPainter) -> None:
    p.drawPath(_path([(13.5, 3), (13.5, 9), (3, 9)]))
    p.drawPath(_path([(6, 6), (3, 9), (6, 12)]))


def _delete(p: QPainter) -> None:
    p.drawPath(_path([(5.5, 3.5), (14, 3.5), (14, 12.5), (5.5, 12.5), (1.5, 8)], closed=True))
    p.drawLine(QPointF(7.5, 6), QPointF(11.5, 10))
    p.drawLine(QPointF(11.5, 6), QPointF(7.5, 10))


def _input(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(1.5, 3, 13, 9), 1, 1)
    p.drawPath(_path([(6, 13.8), (8, 12), (10, 13.8)]))
    p.drawPath(_path([(5.5, 7.5), (10, 7.5)]))
    p.drawPath(_path([(8.5, 5.8), (10.2, 7.5), (8.5, 9.2)]))


DRAWERS: dict[str, Drawer] = {
    "warning": _warning,
    "refresh": _refresh,
    "plus": _plus,
    "settings": _sliders,
    "phone": _phone,
    "tablet": _phone,
    "watch": _phone,
    "tv": _tv,
    "wifi": _wifi,
    "usb": _usb,
    "chevron": _chevron_down,
    "trash": _trash,
    "copy": _copy,
    "hide": _hide,
    "show": _show,
    "link": _link,
    "up": _arrow("up"),
    "down": _arrow("down"),
    "left": _arrow("left"),
    "right": _arrow("right"),
    "back": _back,
    "home": _home,
    "menu": _menu,
    "recents": _recents,
    "power": _power,
    "volume_up": _volume_up,
    "volume_down": _volume_down,
    "mute": _mute,
    "play_pause": _play_pause,
    "stop": _stop,
    "previous": _previous,
    "next": _next,
    "rewind": _rewind,
    "fast_forward": _fast_forward,
    "search": _search,
    "camera": _camera,
    "record": _record,
    "screen": _screen,
    "channel_up": _channel_up,
    "channel_down": _channel_down,
    "enter": _enter,
    "delete": _delete,
    "input": _input,
}


def paint(painter: QPainter, name: str, rect: QRectF, color: str | QColor, stroke: float = 1.4) -> None:
    drawer = DRAWERS.get(name)
    if drawer is None:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / 16.0, rect.height() / 16.0)
    pen = QPen(QColor(color), stroke * 16.0 / max(rect.width(), 1.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    drawer(painter)
    painter.restore()


def icon(name: str, color: str | QColor, size: int = 16) -> QIcon:
    result = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(scale)
        painter = QPainter(pixmap)
        paint(painter, name, QRectF(0, 0, size, size), color)
        painter.end()
        result.addPixmap(pixmap)
    return result
