"""The device rail: numbered tokens, names, how each device is connected."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from maxondroid.core.devices import State
from maxondroid.core.manager import DeviceView
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import kind_icon, kind_name, state_name, transport_icon, transport_name
from maxondroid.ui.tokens import paint_token, style_for, token_label

DeviceRole = Qt.ItemDataRole.UserRole + 1
KeyRole = Qt.ItemDataRole.UserRole + 2


def device_subtitle(view: DeviceView) -> str:
    parts = [kind_name(view.kind)]
    if view.state is State.ONLINE:
        parts.append(transport_name(view.transport))
    elif view.state is State.UNKNOWN and view.state_detail:
        parts.append(f"{state_name(view.state)} ({view.state_detail})")
    else:
        parts.append(state_name(view.state))
    return " · ".join(p for p in parts if p)


def device_accessible_text(view: DeviceView) -> str:
    text = f"{token_label(view.token)} {view.name}, {device_subtitle(view)}"
    if view.state is State.ONLINE:
        text += ", " + state_name(view.state)
    if view.legacy_network_open:
        text += ", " + tr("device.legacy_warning_short")
    return text


class DeviceModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.views: list[DeviceView] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.views)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.views):
            return None
        view = self.views[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return view.name
        if role in (Qt.ItemDataRole.AccessibleTextRole, Qt.ItemDataRole.ToolTipRole):
            return device_accessible_text(view)
        if role == DeviceRole:
            return view
        if role == KeyRole:
            return view.key
        return None

    def set_views(self, views: list[DeviceView]) -> None:
        if [v.key for v in views] == [v.key for v in self.views]:
            self.views = list(views)
            if views:
                self.dataChanged.emit(self.index(0), self.index(len(views) - 1))
            return
        self.beginResetModel()
        self.views = list(views)
        self.endResetModel()

    def row_of(self, key: str | None) -> int:
        for row, view in enumerate(self.views):
            if view.key == key:
                return row
        return -1

    def refresh_texts(self) -> None:
        if self.views:
            self.dataChanged.emit(self.index(0), self.index(len(self.views) - 1))


class DeviceDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 58
    TOKEN = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.palette = theme.LIGHT

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        view: DeviceView = index.data(DeviceRole)
        if view is None:
            return
        p = self.palette
        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.rail_selected if selected else p.rail_hover))
            painter.drawRoundedRect(rect.adjusted(6, 2, -6, -2), 5, 5)
        if option.state & QStyle.StateFlag.State_HasFocus and selected:
            painter.setPen(QColor(p.brass))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(6.5, 2.5, -6.5, -2.5), 5, 5)

        token_rect = QRectF(rect.left() + 16, rect.center().y() - self.TOKEN / 2, self.TOKEN, self.TOKEN)
        paint_token(painter, token_rect, view.token, style_for(view.state), p, warning=view.legacy_network_open)

        text_left = token_rect.right() + 12
        right_pad = 34 if view.legacy_network_open else 16
        text_width = rect.right() - text_left - right_pad

        name_font = QFont(option.font)
        name_font.setPointSizeF(option.font.pointSizeF() + 0.5)
        name_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(7.5, option.font.pointSizeF() - 0.5))

        name_metrics = QFontMetrics(name_font)
        sub_metrics = QFontMetrics(sub_font)
        total = name_metrics.height() + 3 + sub_metrics.height()
        top = rect.center().y() - total / 2

        painter.setFont(name_font)
        painter.setPen(QColor(p.rail_text))
        name = name_metrics.elidedText(view.name, Qt.TextElideMode.ElideRight, int(text_width))
        painter.drawText(QRectF(text_left, top, text_width, name_metrics.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        sub_top = top + name_metrics.height() + 3
        icon_x = text_left
        for icon_name in (kind_icon(view.kind), transport_icon(view.transport) if view.state is State.ONLINE else None):
            if icon_name:
                icons.paint(painter, icon_name, QRectF(icon_x, sub_top + (sub_metrics.height() - 12) / 2, 12, 12), p.rail_muted, 1.2)
                icon_x += 16
        painter.setFont(sub_font)
        painter.setPen(QColor(p.rail_muted))
        sub_width = rect.right() - right_pad - icon_x - 2
        sub = sub_metrics.elidedText(device_subtitle(view), Qt.TextElideMode.ElideRight, int(sub_width))
        painter.drawText(QRectF(icon_x + 2, sub_top, sub_width, sub_metrics.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)

        if view.legacy_network_open:
            icons.paint(painter, "warning", QRectF(rect.right() - 30, rect.center().y() - 8, 16, 16), p.warning, 1.5)
        painter.restore()


class DeviceListView(QListView):
    selection_changed_key = Signal(object)  # str | None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DeviceList")
        self.model_ = DeviceModel(self)
        self.delegate = DeviceDelegate(self)
        self.setModel(self.model_)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._selected_key: str | None = None
        self._updating = False
        self.selectionModel().currentChanged.connect(self._current_changed)

    def set_palette(self, palette: theme.Palette) -> None:
        self.delegate.palette = palette
        self.viewport().update()

    def _current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._updating:
            return
        key = current.data(KeyRole) if current.isValid() else None
        if key != self._selected_key:
            self._selected_key = key
            self.selection_changed_key.emit(key)

    def selected_key(self) -> str | None:
        return self._selected_key

    def selected_view(self) -> DeviceView | None:
        row = self.model_.row_of(self._selected_key)
        return self.model_.views[row] if row >= 0 else None

    def select_key(self, key: str | None) -> None:
        row = self.model_.row_of(key)
        if row >= 0:
            self.setCurrentIndex(self.model_.index(row))

    def set_views(self, views: list[DeviceView]) -> None:
        """Replace the list, keeping the selection on the same device when it is still there.

        Always emits ``selection_changed_key`` once, so the Overview can pick up a
        changed state of the selected device.
        """
        keep = self._selected_key
        self._updating = True
        try:
            self.model_.set_views(views)
            row = self.model_.row_of(keep)
            if row < 0 and views:
                row = 0
            if row >= 0:
                self.setCurrentIndex(self.model_.index(row))
        finally:
            self._updating = False
        self._selected_key = self.model_.views[row].key if views and row >= 0 else None
        self.selection_changed_key.emit(self._selected_key)
