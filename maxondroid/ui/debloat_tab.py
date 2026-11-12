"""Debloat tab: the device's packages grouped by publisher, with removal risk, presets and undo."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import paths, presets, publishers, safety, uad
from maxondroid.core.changes import Change
from maxondroid.core.manager import DeviceView
from maxondroid.core.packages import Action, Package, PkgState, Snapshot
from maxondroid.core.presets import PlanStatus, Preset, PresetAction
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.apps_tab import state_text
from maxondroid.ui.common import Banner, Placeholder, label, open_folder, publisher_label
from maxondroid.ui.context import AppContext
from maxondroid.ui.package_support import confirm, confirm_destructive, describe_reasons, make_ops, summarize

COLUMNS = ("package", "risk", "state")
LEVELS = (uad.Removal.RECOMMENDED, uad.Removal.ADVANCED, uad.Removal.EXPERT, uad.Removal.UNSAFE)
RISK_NUMBER = {uad.Removal.RECOMMENDED: "1", uad.Removal.ADVANCED: "2", uad.Removal.EXPERT: "3", uad.Removal.UNSAFE: "4", uad.Removal.UNLISTED: "?"}
PackageRole = Qt.ItemDataRole.UserRole + 20  # (Package, Entry | None) on package rows
GroupRole = Qt.ItemDataRole.UserRole + 21  # publisher id on group rows


def presets_dir() -> Path:
    folder = paths.config_dir() / "presets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def risk_of(entry: uad.Entry | None) -> uad.Removal:
    return entry.removal if entry else uad.Removal.UNLISTED


class DebloatTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self._busy = False
        self.checked: set[str] = set()
        self._collapsed: set[str] = set()  # publisher ids the user folded
        self._building = False
        self._shown = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.placeholder = Placeholder()
        self.stack.addWidget(self.placeholder)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.db_label = label("", role="muted", wrap=True)
        self.update_button = QPushButton()
        self.update_button.clicked.connect(self.update_database)
        self.presets_button = QPushButton()
        self.presets_button.setProperty("menu", True)
        self.presets_menu = QMenu(self)
        self.presets_menu.aboutToShow.connect(self._fill_presets_menu)
        self.presets_button.setMenu(self.presets_menu)
        self.history_button = QPushButton()
        self.history_button.clicked.connect(self.open_history)
        self.refresh_button = QToolButton()
        self.refresh_button.setAutoRaise(True)
        self.refresh_button.clicked.connect(self.reload)
        head.addWidget(self.db_label, 1)
        for button in (self.refresh_button, self.update_button, self.presets_button, self.history_button):
            head.addWidget(button)
        layout.addLayout(head)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        filters.addWidget(self.search, 1)
        self.state = QComboBox()
        self.state.currentIndexChanged.connect(self._filter)
        filters.addWidget(self.state)
        layout.addLayout(filters)

        levels = QHBoxLayout()
        levels.setSpacing(6)
        self.levels_label = label("", role="muted")
        levels.addWidget(self.levels_label)
        self.level_buttons: dict[uad.Removal, QToolButton] = {}
        for level in LEVELS:
            button = QToolButton()
            button.setProperty("filter", True)
            button.setCheckable(True)
            button.setChecked(level is not uad.Removal.UNSAFE)
            button.toggled.connect(self._filter)
            self.level_buttons[level] = button
            levels.addWidget(button)
        levels.addSpacing(12)
        self.unlisted = QCheckBox()
        self.unlisted.setChecked(True)
        self.unlisted.toggled.connect(self._filter)
        levels.addWidget(self.unlisted)
        levels.addStretch(1)
        self.expand_button = QToolButton()
        self.expand_button.setAutoRaise(True)
        self.expand_button.clicked.connect(lambda: self._set_all_expanded(True))
        self.collapse_button = QToolButton()
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.clicked.connect(lambda: self._set_all_expanded(False))
        levels.addWidget(self.expand_button)
        levels.addWidget(self.collapse_button)
        layout.addLayout(levels)

        self.banner = Banner("info")
        layout.addWidget(self.banner)

        self.model = QStandardItemModel(self)
        self.model.itemChanged.connect(self._item_changed)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.expanded.connect(lambda index: self._collapsed.discard(index.data(GroupRole)))
        self.tree.collapsed.connect(lambda index: self._collapsed.add(index.data(GroupRole)))
        self.tree.selectionModel().currentRowChanged.connect(lambda *_: self._show_details())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setMinimumWidth(240)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.tree)
        split.addWidget(self.details)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 1)
        split.setSizes([620, 300])
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.count_label = label("", role="muted")
        self.check_visible = QPushButton()
        self.check_visible.clicked.connect(lambda: self._check_selection(True))
        self.uncheck_button = QPushButton()
        self.uncheck_button.clicked.connect(lambda: self.set_checked(set(self.checked), False))
        self.restore_button = QPushButton()
        self.restore_button.clicked.connect(self.restore_checked)
        self.disable_button = QPushButton()
        self.disable_button.clicked.connect(self.disable_checked)
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("Primary")
        self.remove_button.clicked.connect(self.remove_checked)
        bottom.addWidget(self.count_label, 1)
        for button in (self.check_visible, self.uncheck_button, self.restore_button, self.disable_button, self.remove_button):
            bottom.addWidget(button)
        layout.addLayout(bottom)
        self.stack.addWidget(page)

        ctx.packages.changed.connect(self._cache_changed)
        self.retranslate()

    # -- language and theme ----------------------------------------------------
    def retranslate(self) -> None:
        self.search.setPlaceholderText(tr("debloat.search"))
        self.update_button.setText(tr("debloat.update_db"))
        self.update_button.setToolTip(tr("debloat.update_db.tip", url=uad.UAD_URL))
        self.refresh_button.setToolTip(tr("debloat.refresh"))
        self.refresh_button.setAccessibleName(tr("debloat.refresh"))
        self.presets_button.setText(tr("debloat.presets"))
        self.levels_label.setText(tr("debloat.levels"))
        for level, button in self.level_buttons.items():
            button.setText(RISK_NUMBER[level])
            button.setToolTip(tr(f"removal.{level.value}") + " — " + tr(f"removal.desc.{level.value}"))
            button.setAccessibleName(tr("debloat.level_button", level=RISK_NUMBER[level]) + ": " + tr(f"removal.desc.{level.value}"))
        current = self.state.currentData()
        self.state.blockSignals(True)
        self.state.clear()
        for value in ("installed", "changed", "all"):
            self.state.addItem(tr(f"debloat.state.{value}"), value)
        self.state.setCurrentIndex(max(0, self.state.findData(current)))
        self.state.blockSignals(False)
        self.unlisted.setText(tr("debloat.unlisted"))
        self.expand_button.setText(tr("debloat.expand_all"))
        self.collapse_button.setText(tr("debloat.collapse_all"))
        self.check_visible.setText(tr("debloat.check_selected"))
        self.uncheck_button.setText(tr("debloat.uncheck"))
        self.restore_button.setText(tr("pkg.action.restore"))
        self.disable_button.setText(tr("pkg.action.disable"))
        self.remove_button.setText(tr("pkg.action.remove"))
        self._apply_icons()
        self.render(force=True)  # the one rebuild for the new texts

    def _apply_icons(self) -> None:
        self.update_button.setIcon(icons.icon("refresh", self.ctx.palette.text))
        self.refresh_button.setIcon(icons.icon("refresh", self.ctx.palette.text_muted))

    def apply_palette(self) -> None:
        self._apply_icons()
        self.rebuild()

    def refresh_texts(self) -> None:
        self.rebuild()

    # -- data ------------------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        new_device = self.view is None or view is None or self.view.key != view.key
        came_online = not new_device and view is not None and view.online and not self.view.online
        changed = new_device or came_online or (view is not None and self.view is not None and self.view.online != view.online)
        if new_device:
            self.checked.clear()
        self.view = view
        if changed:
            self.banner.hide()
            if came_online:
                self.ctx.packages.load(view)
            else:
                self.ctx.packages.ensure(view)
            self.render(force=True)

    def snapshot(self) -> Snapshot | None:
        return self.ctx.packages.get(self.view.key) if self.view else None

    def reload(self) -> None:
        if self.view is not None and self.view.online:
            self.ctx.packages.load(self.view)

    def _cache_changed(self, key: str) -> None:
        if self.view is not None and key == self.view.key:
            self.render(force=True)

    def render(self, force: bool = False) -> None:
        self._render_db_label()
        view = self.view
        cache = self.ctx.packages
        if view is None or not view.online:
            self.placeholder.set_message(tr("pkg.offline"))
            self.stack.setCurrentIndex(0)
            return
        snapshot = cache.get(view.key)
        if snapshot is None:
            if view.key in cache.errors:
                self.placeholder.set_message(tr("pkg.load_failed", details=cache.errors[view.key]), tr("pkg.retry"), self.reload)
            else:
                self.placeholder.set_message(tr("pkg.loading"))
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        if force:
            self.rebuild()
        self._update_buttons()

    def _render_db_label(self) -> None:
        db = self.ctx.uad
        if db is None:
            self.db_label.setText(tr("debloat.db.missing"))
            return
        source = tr(f"debloat.db.{db.source.value}")
        self.db_label.setText(tr("debloat.db.info", count=f"{len(db.entries):,}".replace(",", " "), source=source, date=db.date or "—"))

    def publishers(self) -> dict[str, publishers.Publisher]:
        snapshot = self.snapshot()
        if snapshot is None:
            return {}
        db = self.ctx.uad
        names = list(snapshot.packages)
        entries = {n: db.get(n) for n in names} if db else {}
        return publishers.group_packages(names, entries, self.view.manufacturer if self.view else None)

    def _visible(self, pkg: Package, entry: uad.Entry | None) -> bool:
        if entry is None:
            if not self.unlisted.isChecked():
                return False
        else:
            button = self.level_buttons.get(entry.removal)
            if button is not None and not button.isChecked():
                return False
        state = self.state.currentData() or "installed"
        if state == "installed" and pkg.state is PkgState.REMOVED:
            return False
        if state == "changed" and pkg.state is PkgState.ENABLED:
            return False
        text = self.search.text().strip().lower()
        if text and text not in pkg.name.lower() and (entry is None or text not in entry.description.lower()):
            return False
        return True

    # -- the tree ---------------------------------------------------------------
    def rebuild(self) -> None:
        """Rebuild the tree now if the tab is on screen, otherwise when it is shown next.

        A language or theme switch, a filter click and a package change all ask
        for a rebuild; doing it for a hidden tab with hundreds of packages only
        makes the window freeze.
        """
        if not self.isVisible():
            self._dirty = True
            return
        self._rebuild_now()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._rebuild_now()

    def _rebuild_now(self) -> None:
        """Rebuild the grouped tree from the snapshot and the filters, keeping ticks, folds and the cursor."""
        self._dirty = False
        self.rebuild_count = getattr(self, "rebuild_count", 0) + 1
        snapshot = self.snapshot()
        current = self.tree.currentIndex().data(PackageRole) if hasattr(self, "tree") else None
        current_name = current[0].name if current else None
        self._building = True
        try:
            self.model.clear()
            self.model.setHorizontalHeaderLabels([tr(f"debloat.col.{c}") for c in COLUMNS])
            self._shown = 0
            if snapshot is None:
                return
            db = self.ctx.uad
            pubs = self.publishers()
            groups: dict[str, tuple[publishers.Publisher, list[tuple[Package, uad.Entry | None]]]] = {}
            for name, pkg in snapshot.packages.items():
                entry = db.get(name) if db else None
                if not self._visible(pkg, entry):
                    continue
                pub = pubs.get(name, publishers.OTHERS)
                groups.setdefault(pub.id, (pub, []))[1].append((pkg, entry))
            p = self.ctx.palette
            bold = QFont(self.font())
            bold.setWeight(QFont.Weight.DemiBold)
            mono = theme.mono_font(9)
            current_index = None
            for pub, rows in sorted(groups.values(), key=lambda g: publishers.sort_key(g[0])):
                rows.sort(key=lambda r: r[0].name)
                head = QStandardItem(tr("debloat.group", name=publisher_label(pub), count=len(rows)))
                head.setData(pub.id, GroupRole)
                head.setFont(bold)
                head.setCheckable(True)
                head.setAccessibleText(publisher_label(pub))
                filler = [QStandardItem(""), QStandardItem("")]
                for item in [head, *filler]:
                    item.setEditable(False)
                for pkg, entry in rows:
                    risk = risk_of(entry)
                    name_item = QStandardItem(pkg.name)
                    name_item.setData((pkg, entry), PackageRole)
                    name_item.setCheckable(True)
                    name_item.setCheckState(Qt.CheckState.Checked if pkg.name in self.checked else Qt.CheckState.Unchecked)
                    name_item.setFont(mono)
                    name_item.setToolTip(pkg.name + (f"\n{entry.summary}" if entry and entry.summary else ""))
                    risk_item = QStandardItem(tr(f"removal.{risk.value}"))
                    risk_item.setToolTip(tr(f"removal.desc.{risk.value}"))
                    state_item = QStandardItem(state_text(pkg.state))
                    if risk is uad.Removal.UNSAFE:
                        risk_item.setForeground(QColor(p.danger_text))
                    elif risk is uad.Removal.EXPERT:
                        risk_item.setForeground(QColor(p.brass_text))
                    elif risk is uad.Removal.UNLISTED:
                        risk_item.setForeground(QColor(p.text_muted))
                    if pkg.state is not PkgState.ENABLED:
                        name_item.setForeground(QColor(p.text_muted))
                        state_item.setForeground(QColor(p.text_muted))
                    for item in (name_item, risk_item, state_item):
                        item.setEditable(False)
                    head.appendRow([name_item, risk_item, state_item])
                    if pkg.name == current_name:
                        current_index = name_item
                    self._shown += 1
                self._sync_group(head)
                self.model.appendRow([head, *filler])
            for row in range(self.model.rowCount()):
                index = self.model.index(row, 0)
                self.tree.setExpanded(index, index.data(GroupRole) not in self._collapsed)
            header = self.tree.header()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
            metrics = self.tree.fontMetrics()
            for column, texts in (
                (1, [tr(f"removal.{r.value}") for r in uad.Removal] + [tr("debloat.col.risk")]),
                (2, [state_text(st) for st in PkgState] + [tr("debloat.col.state")]),
            ):
                header.resizeSection(column, max(metrics.horizontalAdvance(t) for t in texts) + 28)
            header.setStretchLastSection(False)
            if current_index is not None:
                self.tree.setCurrentIndex(current_index.index())
        finally:
            self._building = False
        self._update_counts()
        self._show_details()

    def _sync_group(self, head: QStandardItem) -> None:
        children = [head.child(r, 0) for r in range(head.rowCount())]
        ticked = sum(1 for c in children if c.checkState() == Qt.CheckState.Checked)
        if ticked == 0:
            state = Qt.CheckState.Unchecked
        elif ticked == len(children):
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        head.setCheckState(state)

    def _item_changed(self, item: QStandardItem) -> None:
        if self._building:
            return
        self._building = True
        try:
            data = item.data(PackageRole)
            if data is not None:
                name = data[0].name
                (self.checked.add if item.checkState() == Qt.CheckState.Checked else self.checked.discard)(name)
                if item.parent() is not None:
                    self._sync_group(item.parent())
            elif item.data(GroupRole) is not None:
                tick = item.checkState() != Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.PartiallyChecked:
                    item.setCheckState(Qt.CheckState.Checked)
                for row in range(item.rowCount()):
                    child = item.child(row, 0)
                    child.setCheckState(Qt.CheckState.Checked if tick else Qt.CheckState.Unchecked)
                    (self.checked.add if tick else self.checked.discard)(child.data(PackageRole)[0].name)
        finally:
            self._building = False
        self._update_buttons()

    def set_checked(self, names: set[str], checked: bool) -> None:
        if checked:
            self.checked |= names
        else:
            self.checked -= names
        self._building = True
        try:
            for row in range(self.model.rowCount()):
                head = self.model.item(row, 0)
                for child_row in range(head.rowCount()):
                    child = head.child(child_row, 0)
                    if child.data(PackageRole)[0].name in names:
                        child.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self._sync_group(head)
        finally:
            self._building = False
        self._update_buttons()

    def _set_all_expanded(self, expanded: bool) -> None:
        for row in range(self.model.rowCount()):
            self.tree.setExpanded(self.model.index(row, 0), expanded)

    def _filter(self, *_args) -> None:
        self.rebuild()

    def _update_counts(self) -> None:
        self.count_label.setText(tr("debloat.count", shown=self._shown, checked=len(self.checked)))
        if self.view:
            pending = len(self.ctx.changes.pending(self.view.key)) if self.ctx.changes else 0
            self.history_button.setText(tr("debloat.history", count=pending))

    def checked_packages(self) -> list[Package]:
        snapshot = self.snapshot()
        if snapshot is None:
            return []
        return [pkg for name, pkg in snapshot.packages.items() if name in self.checked]

    def _update_buttons(self) -> None:
        items = self.checked_packages()
        busy = self._busy
        active = [p for p in items if p.state is not PkgState.REMOVED]
        self.remove_button.setEnabled(bool(active) and not busy)
        self.disable_button.setEnabled(any(p.state is PkgState.ENABLED for p in items) and not busy)
        self.restore_button.setEnabled(any(p.state is not PkgState.ENABLED for p in items) and not busy)
        self.uncheck_button.setEnabled(bool(items))
        self.update_button.setEnabled(not busy)
        self._update_counts()

    def _selected_names(self) -> set[str]:
        names = set()
        for index in self.tree.selectionModel().selectedRows():
            data = index.data(PackageRole)
            if data is not None:
                names.add(data[0].name)
            else:  # a group row: everything shown under it
                head = self.model.itemFromIndex(index)
                for row in range(head.rowCount()):
                    names.add(head.child(row, 0).data(PackageRole)[0].name)
        return names

    def _check_selection(self, checked: bool) -> None:
        names = self._selected_names()
        if names:
            self.set_checked(names, checked)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("debloat.check_selected"), lambda: self._check_selection(True))
        menu.addAction(tr("debloat.uncheck_selected"), lambda: self._check_selection(False))
        menu.addSeparator()
        menu.addAction(tr("debloat.expand_all"), lambda: self._set_all_expanded(True))
        menu.addAction(tr("debloat.collapse_all"), lambda: self._set_all_expanded(False))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_details(self) -> None:
        index: QModelIndex = self.tree.currentIndex()
        data = index.sibling(index.row(), 0).data(PackageRole) if index.isValid() else None
        p = self.ctx.palette
        if data is None:
            self.details.setHtml(f"<p style='color:{p.text_muted}'>{html.escape(tr('debloat.details.empty'))}</p>")
            return
        pkg, entry = data
        removal = risk_of(entry)
        verdict = safety.classify(pkg.name, entry, self.snapshot())
        pub = self.publishers().get(pkg.name)
        parts = [f"<p style='font-family:Consolas,monospace;font-size:10pt'><b>{html.escape(pkg.name)}</b></p>"]
        if pub is not None:
            parts.append(f"<p style='color:{p.text_muted}'>{html.escape(tr('debloat.details.publisher', name=publisher_label(pub)))}</p>")
        parts.append(
            f"<p><b>{html.escape(tr('debloat.details.risk', level=RISK_NUMBER[removal]))}</b> — {html.escape(tr(f'removal.desc.{removal.value}'))}</p>"
        )
        if verdict.level is safety.Level.BLOCKED:
            parts.append(f"<p style='color:{p.danger_text}'>{html.escape(tr('pkg.blocked.body'))}</p>")
        elif verdict.level is safety.Level.CRITICAL:
            parts.append(f"<p style='color:{p.danger_text}'>{html.escape(tr('debloat.details.critical', reasons=describe_reasons(verdict)))}</p>")
        meta = [state_text(pkg.state), tr("pkg.type.system") if pkg.system else tr("pkg.type.user")]
        if pkg.version_name:
            meta.append(pkg.version_name)
        parts.append(f"<p style='color:{p.text_muted}'>{html.escape(' · '.join(meta))}</p>")
        if entry:
            text = html.escape(entry.description)
            text = re.sub(r"(https?://[^\s<]+)", r"<a href='\1'>\1</a>", text).replace("\n", "<br>")
            parts.append(f"<p>{text}</p>")
            for title, values in (("debloat.details.dependencies", entry.dependencies), ("debloat.details.needed_by", entry.needed_by), ("debloat.details.labels", entry.labels)):
                if values:
                    parts.append(f"<p><b>{html.escape(tr(title))}</b><br>{html.escape(', '.join(values))}</p>")
            parts.append(f"<p style='color:{p.text_muted}'>{html.escape(tr('debloat.details.source'))}</p>")
        else:
            parts.append(f"<p style='color:{p.text_muted}'>{html.escape(tr('debloat.details.unlisted'))}</p>")
        self.details.setHtml("".join(parts))

    # -- changes ---------------------------------------------------------------
    def _run(self, work) -> None:
        if self.view is None or self.ctx.runner is None:
            return
        self._busy = True
        self._update_buttons()
        self.banner.show_message("info", "", tr("pkg.working"), palette=self.ctx.palette)
        view = self.view

        def done(results) -> None:
            self._busy = False
            kind, text = summarize(results)
            self.banner.show_message(kind, "", text, palette=self.ctx.palette)
            self.set_checked({r.package for r in results if r.ok}, False)
            self.ctx.packages.load(view)
            self._update_buttons()

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.banner.show_message("error", "", tr("pkg.failed", details=str(exc)), palette=self.ctx.palette)
            self._update_buttons()

        self.ctx.tasks.submit(work, done, failed)

    def remove_checked(self) -> None:
        items = [p for p in self.checked_packages() if p.state is not PkgState.REMOVED]
        if not items or self._busy:
            return
        targets, backup = confirm_destructive(self, self.ctx, Action.REMOVE_FOR_USER, items, self.snapshot())
        if targets:
            ops = make_ops(self.ctx, self.view, self.snapshot())
            self._run(lambda: [ops.remove(p, backup=backup) for p in targets])

    def disable_checked(self) -> None:
        items = [p for p in self.checked_packages() if p.state is PkgState.ENABLED]
        if not items or self._busy:
            return
        targets, _ = confirm_destructive(self, self.ctx, Action.DISABLE, items, self.snapshot())
        if targets:
            ops = make_ops(self.ctx, self.view, self.snapshot())
            self._run(lambda: [ops.disable(p) for p in targets])

    def restore_checked(self) -> None:
        items = [p for p in self.checked_packages() if p.state is not PkgState.ENABLED]
        if not items or self._busy:
            return
        ops = make_ops(self.ctx, self.view, self.snapshot())
        self._run(lambda: [ops.restore(p) for p in items])

    # -- database --------------------------------------------------------------
    def update_database(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_buttons()
        self.banner.show_message("info", "", tr("debloat.db.updating"), palette=self.ctx.palette)
        target = paths.data_dir()

        def done(db: uad.Database) -> None:
            self._busy = False
            self.ctx.uad = db
            self.banner.show_message("info", "", tr("debloat.db.updated", count=len(db.entries)), palette=self.ctx.palette)
            self.render()

        def failed(exc: BaseException) -> None:
            self._busy = False
            code = exc.code if isinstance(exc, uad.DatabaseError) else "network"
            self.banner.show_message("error", tr("debloat.db.update_failed"), tr(f"debloat.db.error.{code}") + "\n" + str(exc), palette=self.ctx.palette)
            self._update_buttons()

        self.ctx.tasks.submit(lambda: uad.download(target), done, failed)

    # -- presets ---------------------------------------------------------------
    def _fill_presets_menu(self) -> None:
        self.presets_menu.clear()
        save = self.presets_menu.addAction(tr("debloat.preset.save") + "…", self.save_preset)
        save.setEnabled(bool(self.checked))
        self.presets_menu.addAction(tr("debloat.preset.apply") + "…", self.pick_preset)
        self.presets_menu.addSeparator()
        self.presets_menu.addAction(tr("debloat.preset.folder"), lambda: open_folder(presets_dir(), self))

    def save_preset(self) -> None:
        names = sorted(self.checked)
        if not names:
            return
        name, ok = QInputDialog.getText(self, tr("debloat.preset.save"), tr("debloat.preset.name"), text=self.view.name if self.view else "")
        if not ok or not name.strip():
            return
        actions = [tr("pkg.action.remove"), tr("pkg.action.disable")]
        choice, ok = QInputDialog.getItem(self, tr("debloat.preset.save"), tr("debloat.preset.action"), actions, 0, False)
        if not ok:
            return
        action = PresetAction.REMOVE if choice == actions[0] else PresetAction.DISABLE
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())[:60] or "preset"
        path, _ = QFileDialog.getSaveFileName(self, tr("debloat.preset.save"), str(presets_dir() / f"{safe}.json"), "JSON (*.json)")
        if not path:
            return
        preset = Preset(name.strip(), "", tuple((n, action) for n in names))
        try:
            presets.save(preset, Path(path))
        except OSError as exc:
            self.banner.show_message("error", "", tr("pkg.failed", details=str(exc)), palette=self.ctx.palette)
            return
        self.banner.show_message("info", "", tr("debloat.preset.saved", count=len(names), path=path), palette=self.ctx.palette)

    def pick_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("debloat.preset.apply"), str(presets_dir()), "JSON (*.json)")
        if path:
            self.apply_preset(Path(path))

    def apply_preset(self, path: Path) -> None:
        snapshot = self.snapshot()
        if snapshot is None or self._busy:
            return
        try:
            preset = presets.load(path)
        except presets.PresetError as err:
            self.banner.show_message("error", "", tr(f"debloat.preset.error.{err.code}") + (f"\n{err.detail}" if err.detail else ""), palette=self.ctx.palette)
            return
        plan = presets.plan(preset, snapshot)
        todo = [i for i in plan if i.status is PlanStatus.TODO]
        done = sum(1 for i in plan if i.status is PlanStatus.DONE)
        missing = sum(1 for i in plan if i.status is PlanStatus.MISSING)
        summary = tr("debloat.preset.plan", name=preset.name, todo=len(todo), done=done, missing=missing)
        if not todo:
            QMessageBox.information(self, tr("debloat.preset.apply"), summary)
            return
        ok, _ = confirm(self, tr("debloat.preset.apply"), summary, tr("debloat.preset.continue"))
        if not ok:
            return
        removes = [snapshot.get(i.package) for i in todo if i.action is PresetAction.REMOVE]
        disables = [snapshot.get(i.package) for i in todo if i.action is PresetAction.DISABLE and snapshot.get(i.package).state is PkgState.ENABLED]
        remove_targets, backup = confirm_destructive(self, self.ctx, Action.REMOVE_FOR_USER, removes, snapshot) if removes else ([], False)
        disable_targets, _ = confirm_destructive(self, self.ctx, Action.DISABLE, disables, snapshot) if disables else ([], False)
        if not remove_targets and not disable_targets:
            return
        ops = make_ops(self.ctx, self.view, snapshot)
        self._run(lambda: [ops.remove(p, backup=backup) for p in remove_targets] + [ops.disable(p) for p in disable_targets])

    # -- history -----------------------------------------------------------------
    def open_history(self) -> None:
        if self.view is None or self.ctx.changes is None:
            return
        dialog = HistoryDialog(self.ctx, self.view, self.snapshot(), self)
        dialog.exec()
        if dialog.changed:
            self.ctx.packages.load(self.view)
        self._update_counts()


class HistoryDialog(QDialog):
    """Every change MaxOnDroid made on this device, with undo."""

    def __init__(self, ctx: AppContext, view: DeviceView, snapshot: Snapshot | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx, self.view, self.snapshot = ctx, view, snapshot
        self.changed = False
        self.setWindowTitle(tr("history.title", name=view.name))
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        self.hint = label(tr("history.hint"), role="muted", wrap=True)
        layout.addWidget(self.hint)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("history.col.time"), tr("history.col.package"), tr("history.col.action"), tr("history.col.status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.tree, 1)
        self.status = label("", wrap=True, selectable=True)
        self.status.hide()
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.undo_button = QPushButton(tr("history.undo"))
        self.undo_button.clicked.connect(self.undo_selected)
        self.undo_all_button = QPushButton(tr("history.undo_all"))
        self.undo_all_button.setObjectName("Primary")
        self.undo_all_button.clicked.connect(self.undo_all)
        row.addWidget(self.undo_button)
        row.addStretch(1)
        row.addWidget(self.undo_all_button)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._busy = False
        self.fill()

    def fill(self) -> None:
        self.tree.clear()
        for change in self.ctx.changes.for_device(self.view.key):
            try:
                when = datetime.fromisoformat(change.time).astimezone().strftime("%d.%m.%Y %H:%M")
            except ValueError:
                when = change.time
            status = tr("history.status.active") if change.pending else tr("history.status.undone")
            item = QTreeWidgetItem([when, change.package, tr(f"history.action.{change.action}"), status])
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            item.setFont(1, theme.mono_font(9))
            if not change.pending:
                for column in range(4):
                    item.setForeground(column, QColor(self.ctx.palette.text_muted))
            self.tree.addTopLevelItem(item)
        if self.tree.topLevelItemCount() == 0:
            empty = QTreeWidgetItem([tr("history.empty"), "", "", ""])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        self._update_buttons()

    def _selected(self) -> list[Change]:
        out = []
        for item in self.tree.selectedItems():
            change = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(change, Change) and change.pending:
                out.append(change)
        return out

    def _update_buttons(self) -> None:
        online = self.view.online and self.ctx.runner is not None
        self.undo_button.setEnabled(bool(self._selected()) and online and not self._busy)
        self.undo_all_button.setEnabled(bool(self.ctx.changes.pending(self.view.key)) and online and not self._busy)

    def _run(self, work) -> None:
        self._busy = True
        self._update_buttons()
        self.status.setText(tr("pkg.working"))
        self.status.show()

        def done(results) -> None:
            self._busy = False
            self.changed = True
            kind, text = summarize(results)
            self.status.setProperty("role", "error" if kind == "error" else "muted")
            self.status.setText(text)
            self.fill()

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.status.setText(tr("pkg.failed", details=str(exc)))
            self._update_buttons()

        self.ctx.tasks.submit(work, done, failed)

    def undo_selected(self) -> None:
        changes = self._selected()
        if changes:
            ops = make_ops(self.ctx, self.view, self.snapshot)
            self._run(lambda: [ops.undo(c) for c in changes])

    def undo_all(self) -> None:
        pending = self.ctx.changes.pending(self.view.key)
        if not pending:
            return
        ok, _ = confirm(self, tr("history.undo_all"), tr("history.undo_all.confirm", count=len(pending)), tr("history.undo_all"))
        if ok:
            ops = make_ops(self.ctx, self.view, self.snapshot)
            self._run(ops.undo_all)
