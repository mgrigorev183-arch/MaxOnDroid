"""Debloat tab: packages known to the UAD-ng list, with safety levels, presets and undo."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
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
    QTableView,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import paths, presets, safety, uad
from maxondroid.core.changes import Change
from maxondroid.core.manager import DeviceView
from maxondroid.core.packages import Action, Package, PkgState, Snapshot
from maxondroid.core.presets import PlanStatus, Preset, PresetAction
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.apps_tab import state_text
from maxondroid.ui.common import Banner, Placeholder, label, refilter
from maxondroid.ui.context import AppContext
from maxondroid.ui.package_support import confirm, confirm_destructive, describe_reasons, make_ops, summarize

COLUMNS = ("check", "package", "removal", "list", "state")
LEVELS = (uad.Removal.RECOMMENDED, uad.Removal.ADVANCED, uad.Removal.EXPERT, uad.Removal.UNSAFE)
GROUPS = ("Oem", "Google", "Aosp", "Carrier", "Misc")
RowRole = Qt.ItemDataRole.UserRole + 20


def presets_dir() -> Path:
    folder = paths.config_dir() / "presets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class DebloatModel(QAbstractTableModel):
    def __init__(self, ctx: AppContext, parent: QObject | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.rows: list[tuple[Package, uad.Entry | None]] = []
        self.checked: set[str] = set()

    def refresh_all(self) -> None:
        """Repaint every cell after a language or theme change (the rows themselves did not change)."""
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, self.columnCount() - 1))

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal and section > 0:
            return tr(f"debloat.col.{COLUMNS[section]}")
        return None

    def set_rows(self, rows: list[tuple[Package, uad.Entry | None]]) -> None:
        self.beginResetModel()
        self.rows = rows
        names = {p.name for p, _ in rows}
        self.checked &= names
        self.endResetModel()

    def flags(self, index):
        base = super().flags(index)
        if index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pkg, entry = self.rows[index.row()]
        column = COLUMNS[index.column()]
        removal = entry.removal if entry else uad.Removal.UNLISTED
        if role == RowRole:
            return pkg, entry
        if role == Qt.ItemDataRole.CheckStateRole and column == "check":
            return Qt.CheckState.Checked if pkg.name in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.AccessibleTextRole and column == "check":
            return pkg.name
        if role == Qt.ItemDataRole.DisplayRole:
            if column == "package":
                return pkg.name
            if column == "removal":
                return tr(f"removal.{removal.value}")
            if column == "list":
                return tr(f"uadlist.{entry.list}") if entry and tr(f"uadlist.{entry.list}") != f"uadlist.{entry.list}" else (entry.list if entry else "—")
            if column == "state":
                return state_text(pkg.state)
        if role == Qt.ItemDataRole.ForegroundRole:
            p = self.ctx.palette
            if column == "removal":
                if removal is uad.Removal.UNSAFE:
                    return QColor(p.danger_text)
                if removal is uad.Removal.EXPERT:
                    return QColor(p.brass_text)
                if removal is uad.Removal.UNLISTED:
                    return QColor(p.text_muted)
            if column in ("package", "state") and pkg.state is not PkgState.ENABLED:
                return QColor(p.text_muted)
        if role == Qt.ItemDataRole.FontRole and column == "package":
            return theme.mono_font(9)
        if role == Qt.ItemDataRole.ToolTipRole and column == "package":
            return pkg.name + ("\n" + entry.summary if entry and entry.summary else "")
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if index.isValid() and role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            name = self.rows[index.row()][0].name
            checked = Qt.CheckState(value) == Qt.CheckState.Checked
            (self.checked.add if checked else self.checked.discard)(name)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def set_checked(self, names: set[str], checked: bool) -> None:
        if checked:
            self.checked |= names
        else:
            self.checked -= names
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0))


class DebloatFilter(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.text = ""
        self.levels: set[uad.Removal] = {uad.Removal.RECOMMENDED, uad.Removal.ADVANCED}
        self.group = "all"
        self.state = "installed"
        self.unlisted = False
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def refilter(self) -> None:
        refilter(self)

    def filterAcceptsRow(self, row: int, parent) -> bool:  # noqa: N802
        pkg, entry = self.sourceModel().rows[row]
        if entry is None:
            if not self.unlisted:
                return False
        elif entry.removal not in self.levels:
            return False
        if self.group != "all" and (entry is None or entry.list != self.group):
            return False
        if self.state == "installed" and pkg.state is PkgState.REMOVED:
            return False
        if self.state == "changed" and pkg.state is PkgState.ENABLED:
            return False
        if self.text:
            haystack = pkg.name.lower() + " " + (entry.description.lower() if entry else "")
            if self.text not in haystack:
                return False
        return True

    def lessThan(self, left, right) -> bool:  # noqa: N802
        if left.column() == 2:
            order = {lvl: i for i, lvl in enumerate(uad.REMOVAL_ORDER)}
            le = left.data(RowRole)[1]
            ri = right.data(RowRole)[1]
            return order[le.removal if le else uad.Removal.UNLISTED] < order[ri.removal if ri else uad.Removal.UNLISTED]
        return super().lessThan(left, right)


class DebloatTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self._busy = False

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
        self.group = QComboBox()
        self.state = QComboBox()
        for combo in (self.group, self.state):
            combo.currentIndexChanged.connect(self._filter)
            filters.addWidget(combo)
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
            button.setChecked(level in (uad.Removal.RECOMMENDED, uad.Removal.ADVANCED))
            button.toggled.connect(self._filter)
            self.level_buttons[level] = button
            levels.addWidget(button)
        levels.addSpacing(12)
        self.unlisted = QCheckBox()
        self.unlisted.toggled.connect(self._filter)
        levels.addWidget(self.unlisted)
        levels.addStretch(1)
        layout.addLayout(levels)

        self.banner = Banner("info")
        layout.addWidget(self.banner)

        self.model = DebloatModel(ctx, self)
        self.model.dataChanged.connect(lambda *_: self._update_buttons())
        self.proxy = DebloatFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        head_view = self.table.horizontalHeader()
        head_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        head_view.resizeSection(0, 30)
        head_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            head_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self._show_details())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setMinimumWidth(240)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
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
        self.uncheck_button.clicked.connect(lambda: self.model.set_checked(set(self.model.checked), False))
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
        self.refresh_button.setToolTip(tr("debloat.refresh"))
        self.refresh_button.setAccessibleName(tr("debloat.refresh"))
        self.update_button.setToolTip(tr("debloat.update_db.tip", url=uad.UAD_URL))
        self.presets_button.setText(tr("debloat.presets"))
        for level, button in self.level_buttons.items():
            button.setText(tr(f"removal.{level.value}"))
            button.setToolTip(tr(f"removal.desc.{level.value}"))
        for combo, values, prefix in ((self.group, ("all",) + GROUPS, "uadlist"), (self.state, ("installed", "changed", "all"), "debloat.state")):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for value in values:
                combo.addItem(tr(f"{prefix}.{value}"), value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
        self.unlisted.setText(tr("debloat.unlisted"))
        self.levels_label.setText(tr("debloat.levels"))
        self.check_visible.setText(tr("debloat.check_selected"))
        self.uncheck_button.setText(tr("debloat.uncheck"))
        self.restore_button.setText(tr("pkg.action.restore"))
        self.disable_button.setText(tr("pkg.action.disable"))
        self.remove_button.setText(tr("pkg.action.remove"))
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        self.model.refresh_all()
        self.apply_palette()
        self.render()

    def apply_palette(self) -> None:
        self.update_button.setIcon(icons.icon("refresh", self.ctx.palette.text))
        self.refresh_button.setIcon(icons.icon("refresh", self.ctx.palette.text_muted))
        self._show_details()

    # -- data ------------------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        new_device = self.view is None or view is None or self.view.key != view.key
        came_online = not new_device and view is not None and view.online and not self.view.online
        changed = new_device or came_online or (view is not None and self.view is not None and self.view.online != view.online)
        if self.view is not None and view is not None and self.view.key != view.key:
            self.model.checked.clear()
        self.view = view
        if changed:
            self.banner.hide()
            if came_online:
                self.ctx.packages.load(view)
            else:
                self.ctx.packages.ensure(view)
            self.render()

    def snapshot(self) -> Snapshot | None:
        return self.ctx.packages.get(self.view.key) if self.view else None

    def reload(self) -> None:
        if self.view is not None and self.view.online:
            self.ctx.packages.load(self.view)

    def _cache_changed(self, key: str) -> None:
        if self.view is not None and key == self.view.key:
            self.render()

    def render(self) -> None:
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
        db = self.ctx.uad
        rows = [(pkg, db.get(pkg.name) if db else None) for pkg in snapshot.packages.values()]
        if rows != self.model.rows:
            self.model.set_rows(rows)
        self._update_counts()
        self._update_buttons()
        self._show_details()

    def _render_db_label(self) -> None:
        db = self.ctx.uad
        if db is None:
            self.db_label.setText(tr("debloat.db.missing"))
            return
        source = tr(f"debloat.db.{db.source.value}")
        self.db_label.setText(tr("debloat.db.info", count=f"{len(db.entries):,}".replace(",", " "), source=source, date=db.date or "—"))

    def _filter(self, *_args) -> None:
        self.proxy.text = self.search.text().strip().lower()
        self.proxy.levels = {lvl for lvl, b in self.level_buttons.items() if b.isChecked()}
        self.proxy.group = self.group.currentData() or "all"
        self.proxy.state = self.state.currentData() or "installed"
        self.proxy.unlisted = self.unlisted.isChecked()
        self.proxy.refilter()
        self._update_counts()

    def _update_counts(self) -> None:
        self.count_label.setText(tr("debloat.count", shown=self.proxy.rowCount(), checked=len(self.model.checked)))
        if self.view:
            pending = len(self.ctx.changes.pending(self.view.key)) if self.ctx.changes else 0
            self.history_button.setText(tr("debloat.history", count=pending))

    def checked_packages(self) -> list[Package]:
        return [p for p, _ in self.model.rows if p.name in self.model.checked]

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

    def _check_selection(self, checked: bool) -> None:
        names = {index.data(RowRole)[0].name for index in self.table.selectionModel().selectedRows()}
        if names:
            self.model.set_checked(names, checked)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("debloat.check_selected"), lambda: self._check_selection(True))
        menu.addAction(tr("debloat.uncheck_selected"), lambda: self._check_selection(False))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_details(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            self.details.setHtml(f"<p style='color:{self.ctx.palette.text_muted}'>{html.escape(tr('debloat.details.empty'))}</p>")
            return
        pkg, entry = index.data(RowRole)
        p = self.ctx.palette
        removal = entry.removal if entry else uad.Removal.UNLISTED
        verdict = safety.classify(pkg.name, entry, self.snapshot())
        parts = [f"<p style='font-family:Consolas,monospace;font-size:10pt'><b>{html.escape(pkg.name)}</b></p>"]
        parts.append(
            f"<p><b>{html.escape(tr(f'removal.{removal.value}'))}</b> — {html.escape(tr(f'removal.desc.{removal.value}'))}</p>"
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
            self.model.set_checked({r.package for r in results if r.ok}, False)
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
        save.setEnabled(bool(self.model.checked))
        self.presets_menu.addAction(tr("debloat.preset.apply") + "…", self.pick_preset)
        self.presets_menu.addSeparator()
        self.presets_menu.addAction(tr("debloat.preset.folder"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(presets_dir()))))

    def save_preset(self) -> None:
        names = sorted(self.model.checked)
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
