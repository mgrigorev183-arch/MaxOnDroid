"""The command journal at the bottom of the window."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core.journal import Journal, JournalEntry
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import label
from maxondroid.ui.tokens import token_label

MAX_ROWS = 1000


class _Bridge(QObject):
    """Moves journal entries from worker threads to the UI thread."""

    entry = Signal(object)


def format_duration(ms: int) -> str:
    if ms < 1000:
        return tr("unit.ms", value=ms)
    return tr("unit.s", value=f"{ms / 1000:.1f}".replace(".", tr("unit.decimal")))


def result_text(entry: JournalEntry) -> str:
    if entry.timed_out:
        return tr("journal.timeout", duration=format_duration(entry.duration_ms))
    if entry.ok:
        return tr("journal.ok", duration=format_duration(entry.duration_ms))
    return tr("journal.failed", code=entry.exit_code, duration=format_duration(entry.duration_ms))


class JournalPanel(QWidget):
    visibility_requested = Signal(bool)

    def __init__(self, journal: Journal, parent: QWidget | None = None):
        super().__init__(parent)
        self.journal = journal
        self.palette_ = theme.LIGHT
        self._bridge = _Bridge(self)
        self._bridge.entry.connect(self._append, Qt.ConnectionType.QueuedConnection)
        journal.add_listener(self._bridge.entry.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("JournalHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 4, 6, 4)
        self.title = label("", role="section")
        title_font = theme.token_font(10.5)
        self.title.setFont(title_font)
        row.addWidget(self.title)
        self.hint = label("", role="muted")
        row.addWidget(self.hint)
        row.addStretch(1)
        self.copy_button = self._tool_button("copy", self.copy_selected)
        self.clear_button = self._tool_button("trash", self.clear)
        self.toggle_button = self._tool_button("hide", self._toggle)
        for button in (self.copy_button, self.clear_button, self.toggle_button):
            row.addWidget(button)
        layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setObjectName("Journal")
        self.tree.setColumnCount(4)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)
        self._expanded = True
        self.retranslate()
        for entry in list(journal.entries):
            self._append(entry)

    def _tool_button(self, icon_name: str, slot) -> QToolButton:
        button = QToolButton()
        button.setAutoRaise(True)
        button.setProperty("icon_name", icon_name)
        button.clicked.connect(slot)
        return button

    def set_palette(self, palette: theme.Palette) -> None:
        self.palette_ = palette
        for button in (self.copy_button, self.clear_button, self.toggle_button):
            button.setIcon(icons.icon(button.property("icon_name"), palette.text_muted))
        for i in range(self.tree.topLevelItemCount()):
            self._color_item(self.tree.topLevelItem(i))

    def retranslate(self) -> None:
        self.title.setText(tr("journal.title"))
        self.hint.setText(tr("journal.hint"))
        self.tree.setHeaderLabels([tr("journal.col.token"), tr("journal.col.time"), tr("journal.col.command"), tr("journal.col.result")])
        self.copy_button.setToolTip(tr("journal.copy"))
        self.copy_button.setAccessibleName(tr("journal.copy"))
        self.clear_button.setToolTip(tr("journal.clear"))
        self.clear_button.setAccessibleName(tr("journal.clear"))
        self._update_toggle()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                item.setText(3, result_text(entry))

    def _update_toggle(self) -> None:
        text = tr("journal.hide") if self._expanded else tr("journal.show")
        self.toggle_button.setToolTip(text)
        self.toggle_button.setAccessibleName(text)
        self.toggle_button.setProperty("icon_name", "hide" if self._expanded else "show")
        self.toggle_button.setIcon(icons.icon(self.toggle_button.property("icon_name"), self.palette_.text_muted))

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.tree.setVisible(expanded)
        self.copy_button.setVisible(expanded)
        self.clear_button.setVisible(expanded)
        self._update_toggle()

    def is_expanded(self) -> bool:
        return self._expanded

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)
        self.visibility_requested.emit(self._expanded)

    def _color_item(self, item: QTreeWidgetItem) -> None:
        entry: JournalEntry | None = item.data(0, Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        color = QColor(self.palette_.text if entry.ok else self.palette_.danger_text)
        item.setForeground(3, color)

    def _append(self, entry: JournalEntry) -> None:
        item = QTreeWidgetItem([
            token_label(entry.token) if entry.token is not None else "",
            entry.when.astimezone().strftime("%H:%M:%S"),
            entry.command,
            result_text(entry),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, entry)
        item.setFont(0, theme.token_font(9.5))
        item.setFont(2, theme.mono_font(9))
        item.setToolTip(2, entry.command)
        if entry.output:
            child = QTreeWidgetItem(["", "", entry.output, ""])
            child.setFont(2, theme.mono_font(9))
            child.setFirstColumnSpanned(False)
            item.addChild(child)
        self._color_item(item)
        self.tree.addTopLevelItem(item)
        if not entry.ok and entry.output:
            item.setExpanded(True)
        while self.tree.topLevelItemCount() > MAX_ROWS:
            self.tree.takeTopLevelItem(0)
        self.tree.scrollToItem(item)

    def clear(self) -> None:
        self.tree.clear()
        self.journal.clear()

    def _selected_entries(self) -> list[JournalEntry]:
        entries = []
        for item in self.tree.selectedItems():
            target = item if item.parent() is None else item.parent()
            entry = target.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None and entry not in entries:
                entries.append(entry)
        return entries

    def copy_selected(self) -> None:
        entries = self._selected_entries()
        if not entries and self.tree.topLevelItemCount():
            last = self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
            entries = [last.data(0, Qt.ItemDataRole.UserRole)]
        lines = []
        for entry in entries:
            lines.append(entry.command)
            if entry.output:
                lines.append(entry.output)
        if lines:
            QGuiApplication.clipboard().setText("\n".join(lines))

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy_cmd = menu.addAction(tr("journal.copy_command"))
        copy_all = menu.addAction(tr("journal.copy"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is copy_cmd:
            entries = self._selected_entries()
            if entries:
                QGuiApplication.clipboard().setText("\n".join(e.command for e in entries))
        elif chosen is copy_all:
            self.copy_selected()
