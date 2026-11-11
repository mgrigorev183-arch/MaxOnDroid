"""Apps tab: every package on the device, with install and per-app actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import apk, publishers
from maxondroid.core.manager import DeviceView
from maxondroid.core.packages import Action, Package, PkgState, Snapshot
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import Banner, Placeholder, label, open_folder, publisher_label, refilter
from maxondroid.ui.context import AppContext
from maxondroid.ui.package_support import (
    confirm,
    confirm_destructive,
    install_error_text,
    install_queue,
    make_ops,
    summarize,
)

COLUMNS = ("package", "publisher", "version", "type", "state", "description")
PackageRole = Qt.ItemDataRole.UserRole + 10


def state_text(state: PkgState) -> str:
    return tr(f"pkg.state.{state.value}")


class AppsModel(QAbstractTableModel):
    def __init__(self, ctx: AppContext, parent: QObject | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.rows: list[Package] = []
        self.publishers: dict[str, publishers.Publisher] = {}

    def refresh_all(self) -> None:
        """Repaint every cell after a language or theme change (the rows themselves did not change)."""
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, self.columnCount() - 1))

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(f"apps.col.{COLUMNS[section]}")
        return None

    def set_rows(self, rows: list[Package], pubs: dict[str, publishers.Publisher]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.publishers = pubs
        self.endResetModel()

    def publisher_name(self, pkg: Package) -> str:
        pub = self.publishers.get(pkg.name)
        return publisher_label(pub) if pub else ""

    def summary(self, pkg: Package) -> str:
        entry = self.ctx.uad.get(pkg.name) if self.ctx.uad else None
        return entry.summary if entry else ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pkg = self.rows[index.row()]
        column = COLUMNS[index.column()]
        if role == PackageRole:
            return pkg
        if role == Qt.ItemDataRole.DisplayRole:
            if column == "package":
                return pkg.name
            if column == "publisher":
                return self.publisher_name(pkg)
            if column == "version":
                return pkg.version_name or (str(pkg.version_code) if pkg.version_code else "")
            if column == "type":
                return tr("pkg.type.system") if pkg.system else tr("pkg.type.user")
            if column == "state":
                return state_text(pkg.state)
            if column == "description":
                return self.summary(pkg)
        if role == Qt.ItemDataRole.ToolTipRole and column == "description":
            entry = self.ctx.uad.get(pkg.name) if self.ctx.uad else None
            return entry.description if entry else None
        if role == Qt.ItemDataRole.ForegroundRole and pkg.state is not PkgState.ENABLED and column in ("package", "state"):
            return QColor(self.ctx.palette.text_muted)
        if role == Qt.ItemDataRole.FontRole and column == "package":
            return theme.mono_font(9)
        return None


class AppsFilter(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.text = ""
        self.kind = "all"  # all, user, system
        self.state = "installed"  # installed, enabled, disabled, removed, all
        self.publisher = "all"  # a publisher id
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def update(self, text: str, kind: str, state: str, publisher: str = "all") -> None:
        self.text, self.kind, self.state, self.publisher = text.strip().lower(), kind, state, publisher
        refilter(self)

    def filterAcceptsRow(self, row: int, parent) -> bool:  # noqa: N802
        model: AppsModel = self.sourceModel()
        pkg = model.rows[row]
        if self.kind == "user" and pkg.system or self.kind == "system" and not pkg.system:
            return False
        if self.state == "installed" and pkg.state is PkgState.REMOVED:
            return False
        if self.state in ("enabled", "disabled", "removed") and pkg.state.value != self.state:
            return False
        if self.publisher != "all":
            pub = model.publishers.get(pkg.name)
            if pub is None or pub.id != self.publisher:
                return False
        if self.text and self.text not in pkg.name.lower() and self.text not in model.summary(pkg).lower():
            return False
        return True


class _Bridge(QObject):
    progress = Signal(int, int, str)


class AppsTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self._busy = False
        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._install_progress, Qt.ConnectionType.QueuedConnection)
        self.setAcceptDrops(True)

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
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.kind = QComboBox()
        self.state = QComboBox()
        self.publisher = QComboBox()
        for combo in (self.kind, self.state, self.publisher):
            combo.currentIndexChanged.connect(self._filter)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.reload)
        self.install_button = QPushButton()
        self.install_button.setObjectName("Primary")
        self.install_button.clicked.connect(self.pick_files)
        top.addWidget(self.search, 1)
        top.addWidget(self.refresh_button)
        top.addWidget(self.install_button)
        layout.addLayout(top)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        for combo in (self.publisher, self.kind, self.state):
            filters.addWidget(combo)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.banner = Banner("info")
        layout.addWidget(self.banner)

        self.model = AppsModel(ctx, self)
        self.proxy = AppsFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setWordWrap(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.resizeSection(0, 270)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        head.resizeSection(1, 170)
        for column in (2, 3, 4):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        head.setMinimumSectionSize(60)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self.table.doubleClicked.connect(lambda *_: self.launch())
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.count_label = label("", role="muted")
        self.launch_button = QPushButton()
        self.launch_button.clicked.connect(self.launch)
        self.toggle_button = QPushButton()
        self.toggle_button.clicked.connect(self.toggle_enabled)
        self.remove_button = QPushButton()
        self.remove_button.clicked.connect(self.remove_or_restore)
        self.more_button = QPushButton()
        self.more_button.setProperty("menu", True)
        self.more_menu = QMenu(self)
        self.more_menu.aboutToShow.connect(lambda: self._fill_menu(self.more_menu, include_main=False))
        self.more_button.setMenu(self.more_menu)
        actions.addWidget(self.count_label, 1)
        for button in (self.launch_button, self.toggle_button, self.remove_button, self.more_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.stack.addWidget(page)

        ctx.packages.changed.connect(self._cache_changed)
        self.retranslate()

    # -- language and theme ----------------------------------------------------
    def retranslate(self) -> None:
        self.search.setPlaceholderText(tr("apps.search"))
        for combo, prefix, values in (
            (self.kind, "apps.kind", ("all", "user", "system")),
            (self.state, "apps.filter", ("installed", "enabled", "disabled", "removed", "all")),
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for value in values:
                combo.addItem(tr(f"{prefix}.{value}"), value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
        if self.model.rows:
            self._fill_publishers()
        self.refresh_button.setText(tr("overview.refresh"))
        self.install_button.setText(tr("apps.install"))
        self.launch_button.setText(tr("pkg.action.launch"))
        self.more_button.setText(tr("overview.more"))
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        self.model.refresh_all()
        self.apply_palette()
        self.render()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.refresh_button.setIcon(icons.icon("refresh", p.text))
        self.install_button.setIcon(icons.icon("plus", p.brass_on))

    # -- data ------------------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        new_device = self.view is None or view is None or self.view.key != view.key
        came_online = not new_device and view is not None and view.online and not self.view.online
        changed = new_device or came_online or (view is not None and self.view is not None and self.view.online != view.online)
        self.view = view
        if changed:
            self.banner.hide()
            if came_online:
                self.ctx.packages.load(view)  # it may have changed while it was away
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
        selected = {p.name for p in self.selected()}
        rows = list(snapshot.packages.values())
        if [p for p in self.model.rows] != rows:
            db = self.ctx.uad
            pubs = publishers.group_packages(
                [p.name for p in rows], {p.name: db.get(p.name) for p in rows} if db else {}, view.manufacturer
            )
            self.model.set_rows(rows, pubs)
            self._fill_publishers()
            self._reselect(selected)
        self.refresh_button.setEnabled(view.key not in cache.loading and not self._busy)
        self._update_count()
        self._update_buttons()

    def _reselect(self, names: set[str]) -> None:
        if not names:
            return
        selection = self.table.selectionModel()
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(PackageRole).name in names:
                selection.select(index, selection.SelectionFlag.Select | selection.SelectionFlag.Rows)

    def _fill_publishers(self) -> None:
        current = self.publisher.currentData() or "all"
        found = {pub.id: pub for pub in self.model.publishers.values()}
        self.publisher.blockSignals(True)
        self.publisher.clear()
        self.publisher.addItem(tr("apps.publisher.all"), "all")
        for pub in sorted(found.values(), key=publishers.sort_key):
            self.publisher.addItem(publisher_label(pub), pub.id)
        self.publisher.setCurrentIndex(max(0, self.publisher.findData(current)))
        self.publisher.blockSignals(False)
        self._filter()

    def _filter(self, *_args) -> None:
        self.proxy.update(
            self.search.text(), self.kind.currentData() or "all", self.state.currentData() or "installed", self.publisher.currentData() or "all"
        )
        self._update_count()

    def _update_count(self) -> None:
        self.count_label.setText(tr("apps.count", shown=self.proxy.rowCount(), total=self.model.rowCount()))

    def selected(self) -> list[Package]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return [index.data(PackageRole) for index in rows]

    def _update_buttons(self) -> None:
        items = self.selected()
        busy = self._busy
        any_removed = any(p.state is PkgState.REMOVED for p in items)
        all_removed = bool(items) and all(p.state is PkgState.REMOVED for p in items)
        all_disabled = bool(items) and all(p.state is PkgState.DISABLED for p in items)
        self.launch_button.setEnabled(len(items) == 1 and items[0].state is PkgState.ENABLED and not busy)
        self.toggle_button.setText(tr("pkg.action.enable") if all_disabled else tr("pkg.action.disable"))
        self.toggle_button.setEnabled(bool(items) and not any_removed and not busy)
        self.remove_button.setText(tr("pkg.action.restore") if all_removed else tr("pkg.action.remove"))
        self.remove_button.setEnabled(bool(items) and (all_removed or not any_removed) and not busy)
        self.more_button.setEnabled(bool(items) and not busy)
        self.install_button.setEnabled(not busy)

    # -- actions -----------------------------------------------------------------
    def _fill_menu(self, menu: QMenu, include_main: bool) -> None:
        menu.clear()
        items = self.selected()
        if not items:
            return
        single = items[0] if len(items) == 1 else None
        if include_main:
            menu.addAction(tr("pkg.action.launch"), self.launch).setEnabled(self.launch_button.isEnabled())
            menu.addAction(self.toggle_button.text(), self.toggle_enabled).setEnabled(self.toggle_button.isEnabled())
            menu.addAction(self.remove_button.text() + ("…" if self.remove_button.text() == tr("pkg.action.remove") else ""), self.remove_or_restore).setEnabled(self.remove_button.isEnabled())
            menu.addSeparator()
        installed = [p for p in items if p.state is not PkgState.REMOVED]
        menu.addAction(tr("pkg.action.force_stop"), self.force_stop).setEnabled(bool(installed) and not self._busy)
        menu.addAction(tr("pkg.action.clear") + "…", self.clear_data).setEnabled(bool(installed) and not self._busy)
        menu.addAction(tr("pkg.action.extract") + "…", self.extract).setEnabled(single is not None and single.state is not PkgState.REMOVED and not self._busy)
        menu.addSeparator()
        menu.addAction(tr("pkg.action.copy_name"), lambda: QGuiApplication.clipboard().setText("\n".join(p.name for p in items)))

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        self._fill_menu(menu, include_main=True)
        if not menu.isEmpty():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _run(self, work, done_text_fn=None) -> None:
        if self.view is None or self.ctx.runner is None:
            return
        self._busy = True
        self._update_buttons()
        self.banner.show_message("info", "", tr("pkg.working"), palette=self.ctx.palette)
        view = self.view

        def done(results) -> None:
            self._busy = False
            kind, text = done_text_fn(results) if done_text_fn else summarize(results)
            self.banner.show_message(kind, "", text, palette=self.ctx.palette)
            self.ctx.packages.load(view)
            self._update_buttons()

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.banner.show_message("error", "", tr("pkg.failed", details=str(exc)), palette=self.ctx.palette)
            self._update_buttons()

        self.ctx.tasks.submit(work, done, failed)

    def _ops(self):
        return make_ops(self.ctx, self.view, self.snapshot())

    def launch(self) -> None:
        items = self.selected()
        if len(items) != 1 or items[0].state is not PkgState.ENABLED or self._busy:
            return
        from maxondroid.core import packages

        runner, serial, leanback = self.ctx.runner, self.view.serial, bool(self.snapshot() and self.snapshot().leanback)
        name = items[0].name

        def work():
            result = packages.launch(runner, serial, name, leanback)
            from maxondroid.core.ops import OpResult

            return [OpResult(result.ok, name, Action.LAUNCH, result.message, None if result.ok else "no_launcher")]

        self._run(work, lambda r: ("info", tr("pkg.launched", name=name)) if r[0].ok else summarize(r))

    def toggle_enabled(self) -> None:
        items = [p for p in self.selected() if p.state is not PkgState.REMOVED]
        if not items or self._busy:
            return
        ops = self._ops()
        if all(p.state is PkgState.DISABLED for p in items):
            self._run(lambda: [ops.enable(p) for p in items])
            return
        targets, _ = confirm_destructive(self, self.ctx, Action.DISABLE, [p for p in items if p.state is PkgState.ENABLED], self.snapshot())
        if targets:
            self._run(lambda: [ops.disable(p) for p in targets])

    def remove_or_restore(self) -> None:
        items = self.selected()
        if not items or self._busy:
            return
        ops = self._ops()
        if all(p.state is PkgState.REMOVED for p in items):
            self._run(lambda: [ops.restore(p) for p in items])
            return
        targets, backup = confirm_destructive(self, self.ctx, Action.REMOVE_FOR_USER, items, self.snapshot())
        if targets:
            self._run(lambda: [ops.remove(p, backup=backup) for p in targets])

    def force_stop(self) -> None:
        from maxondroid.core import packages
        from maxondroid.core.ops import OpResult

        items = [p for p in self.selected() if p.state is not PkgState.REMOVED]
        runner, serial = self.ctx.runner, self.view.serial

        def work():
            out = []
            for p in items:
                r = packages.force_stop(runner, serial, p.name)
                out.append(OpResult(r.ok, p.name, Action.FORCE_STOP, r.message))
            return out

        self._run(work)

    def clear_data(self) -> None:
        from maxondroid.core import packages
        from maxondroid.core.ops import OpResult

        items = [p for p in self.selected() if p.state is not PkgState.REMOVED]
        if not items:
            return
        names = "\n".join("• " + p.name for p in items[:12])
        ok, _ = confirm(self, tr("pkg.action.clear"), tr("pkg.confirm.clear", count=len(items)) + "\n\n" + names, tr("pkg.action.clear"), danger=True)
        if not ok:
            return
        runner, serial = self.ctx.runner, self.view.serial

        def work():
            out = []
            for p in items:
                r = packages.clear_data(runner, serial, p.name)
                out.append(OpResult(r.ok, p.name, Action.CLEAR, r.message))
            return out

        self._run(work)

    def extract(self) -> None:
        items = self.selected()
        if len(items) != 1:
            return
        pkg = items[0]
        default = Path.home() / "Documents" / "MaxOnDroid" / "APK"
        folder = QFileDialog.getExistingDirectory(self, tr("pkg.extract.pick"), str(default if default.exists() else Path.home()))
        if not folder:
            return
        runner, serial = self.ctx.runner, self.view.serial
        self._busy = True
        self._update_buttons()
        self.banner.show_message("info", "", tr("pkg.extract.working", name=pkg.name), palette=self.ctx.palette)

        def done(result: apk.ExtractResult) -> None:
            self._busy = False
            if result.ok and result.file:
                self.banner.show_message(
                    "info", "", tr("pkg.extract.done", path=str(result.file)), tr("pkg.extract.open"),
                    lambda: open_folder(result.file.parent), self.ctx.palette,
                )
            else:
                self.banner.show_message("error", "", tr("pkg.extract.failed", details=result.message), palette=self.ctx.palette)
            self._update_buttons()

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.banner.show_message("error", "", tr("pkg.extract.failed", details=str(exc)), palette=self.ctx.palette)
            self._update_buttons()

        self.ctx.tasks.submit(lambda: apk.extract_apk(runner, serial, pkg.name, Path(folder), pkg.version_name), done, failed)

    # -- install -------------------------------------------------------------------
    def pick_files(self) -> None:
        pattern = tr("apps.install.filter") + " (" + " ".join("*" + s for s in apk.INSTALLABLE_SUFFIXES) + ")"
        files, _ = QFileDialog.getOpenFileNames(self, tr("apps.install"), str(Path.home() / "Downloads"), pattern)
        if files:
            self.install([Path(f) for f in files])

    def install(self, files: list[Path]) -> None:
        files = [f for f in files if apk.is_installable(f)]
        if not files or self.view is None or not self.view.online or self.ctx.runner is None or self._busy:
            if files and (self.view is None or not self.view.online):
                self.banner.show_message("error", "", tr("pkg.offline"), palette=self.ctx.palette)
            return
        runner, serial, snapshot, view = self.ctx.runner, self.view.serial, self.snapshot(), self.view
        self._busy = True
        self._update_buttons()
        self.stack.setCurrentIndex(1 if snapshot else self.stack.currentIndex())
        self.banner.show_message("info", "", tr("apps.install.working", index=1, total=len(files), name=files[0].name), palette=self.ctx.palette)
        emit = self._bridge.progress.emit

        def done(results: list[apk.InstallResult]) -> None:
            self._busy = False
            ok = [r for r in results if r.ok]
            failed = [r for r in results if not r.ok]
            if not failed:
                self.banner.show_message("info", "", tr("apps.install.done", count=len(ok)), palette=self.ctx.palette)
            else:
                lines = [f"{r.file.name}: {install_error_text(r.error_code)}" + (f"\n{r.message}" if r.message and r.error_code == 'UNKNOWN' else "") for r in failed]
                self.banner.show_message("error", tr("apps.install.partial", ok=len(ok), failed=len(failed)), "\n".join(lines), palette=self.ctx.palette)
            self.ctx.packages.load(view)
            self._update_buttons()

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.banner.show_message("error", "", tr("pkg.failed", details=str(exc)), palette=self.ctx.palette)
            self._update_buttons()

        self.ctx.tasks.submit(lambda: install_queue(runner, serial, files, snapshot, emit), done, failed)

    def _install_progress(self, index: int, total: int, name: str) -> None:
        if self._busy:
            self.banner.show_message("info", "", tr("apps.install.working", index=index, total=total, name=name), palette=self.ctx.palette)

    # -- drag and drop -------------------------------------------------------------
    @staticmethod
    def dropped_files(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and apk.is_installable(Path(u.toLocalFile()))]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = self.dropped_files(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.install(files)
