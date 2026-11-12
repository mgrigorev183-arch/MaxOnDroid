"""Files tab: browse a device folder, copy files both ways, create, rename, delete.

Every action is one adb command shown in the journal: listing and changes run
a short fixed script on the device with the path as its argument (see
core/files.py), copies are ``adb push`` and ``adb pull``. One copy runs at a
time and can be cancelled; browsing stays possible meanwhile.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import files
from maxondroid.core.adb import AdbResult
from maxondroid.core.files import FilesError, RemoteEntry
from maxondroid.core.manager import DeviceView
from maxondroid.i18n import tr
from maxondroid.ui import icons
from maxondroid.ui.common import FlowLayout, Placeholder, breakable, label, open_folder
from maxondroid.ui.context import AppContext
from maxondroid.ui.package_support import confirm

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
SORT_ROLE = Qt.ItemDataRole.UserRole + 2
LISTED_IN_CONFIRM = 10


def human_size(size: int) -> str:
    sep = tr("unit.decimal")
    if size < 1024:
        return tr("unit.bytes", value=size)
    for key, power in (("unit.kb", 1), ("unit.mb", 2), ("unit.gb", 3)):
        value = size / 1024**power
        if value < 1024 or key == "unit.gb":
            text = f"{value:.1f}".replace(".", sep) if value < 100 else f"{value:.0f}"
            return tr(key, value=text)
    return str(size)


class _DirsFirst(QSortFilterProxyModel):
    """Sorts by the clicked column, but folders always stay above files."""

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        a = self.sourceModel().index(left.row(), 0).data(ENTRY_ROLE)
        b = self.sourceModel().index(right.row(), 0).data(ENTRY_ROLE)
        if a is not None and b is not None and a.is_dir != b.is_dir:
            return a.is_dir if self.sortOrder() == Qt.SortOrder.AscendingOrder else b.is_dir
        return super().lessThan(left, right)


class FileList(QTableView):
    """The folder listing; files dropped from Explorer are handed to ``on_drop``."""

    def __init__(self, on_drop):
        super().__init__()
        self.on_drop = on_drop
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    @staticmethod
    def local_paths(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.local_paths(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self.local_paths(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self.local_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.on_drop(paths)


class FilesTab(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.view: DeviceView | None = None
        self.folder = files.HOME
        self.entries: list[RemoteEntry] = []
        self._folders: dict[str, str] = {}  # device key -> last folder
        self._loading = False
        self._load_id = 0
        self._transfer: threading.Event | None = None  # the running copy's cancel switch
        self.last_download: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.placeholder = Placeholder()
        self.stack.addWidget(self.placeholder)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(10)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.up_button = QToolButton()
        self.up_button.clicked.connect(self.go_up)
        self.home_button = QToolButton()
        self.home_button.clicked.connect(lambda: self.open_folder_path(files.HOME))
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(lambda: self.open_folder_path(self.path_edit.text()))
        self.refresh_button = QToolButton()
        self.refresh_button.clicked.connect(self.reload)
        # "new folder" is an icon beside the path, as in Explorer: the action row must fit a narrow window
        self.new_folder_button = QToolButton()
        self.new_folder_button.clicked.connect(self.new_folder)
        for button in (self.up_button, self.home_button, self.refresh_button, self.new_folder_button):
            button.setAutoRaise(True)
        nav.addWidget(self.up_button)
        nav.addWidget(self.home_button)
        nav.addWidget(self.path_edit, 1)
        nav.addWidget(self.refresh_button)
        nav.addWidget(self.new_folder_button)
        layout.addLayout(nav)

        actions = FlowLayout(spacing=8)  # wraps on narrow windows and long translations
        self.upload_button = QPushButton()
        self.upload_button.setObjectName("Primary")
        self.upload_menu = QMenu(self)
        self.act_upload_files = self.upload_menu.addAction("", self.upload_files)
        self.act_upload_folder = self.upload_menu.addAction("", self.upload_folder)
        self.upload_button.setMenu(self.upload_menu)
        self.download_button = QPushButton()
        self.download_button.clicked.connect(self.download)
        self.rename_button = QPushButton()
        self.rename_button.clicked.connect(self.rename)
        self.delete_button = QPushButton()
        self.delete_button.clicked.connect(self.delete)
        for button in (self.upload_button, self.download_button, self.rename_button, self.delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)

        self.model = QStandardItemModel(0, 3, self)
        self.proxy = _DirsFirst(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = FileList(self.upload)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        head.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.doubleClicked.connect(self._activated)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.table, 1)

        transfer = QHBoxLayout()
        transfer.setSpacing(8)
        self.transfer_label = label("", role="muted", wrap=True)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self.cancel_transfer)
        self.result_open = QPushButton()
        self.result_open.clicked.connect(lambda: self.last_download and open_folder(self.last_download, self))
        transfer.addWidget(self.transfer_label, 1)
        transfer.addWidget(self.cancel_button)
        transfer.addWidget(self.result_open)
        layout.addLayout(transfer)
        self.status = label("", role="muted")
        self.hint = label("", role="muted", wrap=True)
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(self.status)
        bottom.addWidget(self.hint, 1)
        layout.addLayout(bottom)
        self.stack.addWidget(page)

        for keys, handler in (
            (QKeySequence(Qt.Key.Key_Backspace), self.go_up),
            (QKeySequence(Qt.Key.Key_Delete), self.delete),
            (QKeySequence(Qt.Key.Key_F2), self.rename),
            (QKeySequence(Qt.Key.Key_Return), self._enter_selected),
        ):
            shortcut = QShortcut(keys, self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(handler)

        self.cancel_button.hide()
        self.result_open.hide()
        self.retranslate()
        self.render()

    # -- device ----------------------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        old = self.view
        self.view = view
        if view is None or old is None or view.key != old.key or view.online != old.online:
            if old is not None:
                self._folders[old.key] = self.folder
            self.render()
            if view is not None and view.online and (old is None or old.key != view.key or not old.online):
                self.folder = self._folders.get(view.key, files.HOME)
                self.entries = []
                self.model.removeRows(0, self.model.rowCount())
                self.reload()

    def render(self) -> None:
        if self.view is None or not self.view.online:
            self.placeholder.set_message(tr("files.offline"))
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self._update_buttons()

    # -- texts and look --------------------------------------------------------------
    def retranslate(self) -> None:
        self.model.setHorizontalHeaderLabels([tr("files.col.name"), tr("files.col.size"), tr("files.col.modified")])
        self.up_button.setToolTip(tr("files.up"))
        self.home_button.setToolTip(tr("files.home", path=files.HOME))
        self.refresh_button.setToolTip(tr("files.refresh"))
        self.path_edit.setPlaceholderText(tr("files.path.placeholder"))
        self.path_edit.setToolTip(tr("files.path.tip"))
        self.upload_button.setText(tr("files.upload"))
        self.act_upload_files.setText(tr("files.upload.files"))
        self.act_upload_folder.setText(tr("files.upload.folder"))
        self.download_button.setText(tr("files.download"))
        self.new_folder_button.setToolTip(tr("files.new_folder"))
        self.rename_button.setText(tr("files.rename"))
        self.delete_button.setText(tr("files.delete"))
        self.cancel_button.setText(tr("common.cancel"))
        self.result_open.setText(tr("files.open_download"))
        self.hint.setText(tr("files.hint"))
        metrics = self.table.fontMetrics()
        head = self.table.horizontalHeader()
        head.resizeSection(1, max(metrics.horizontalAdvance(t) for t in (human_size(999 * 1024**2), tr("files.col.size"))) + 32)
        head.resizeSection(2, max(metrics.horizontalAdvance(t) for t in ("30.12.2026 23:59", tr("files.col.modified"))) + 32)
        self._fill()
        self.apply_palette()
        if self.view is None or not self.view.online:
            self.render()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.up_button.setIcon(icons.icon("up", p.text))
        self.home_button.setIcon(icons.icon("home", p.text))
        self.refresh_button.setIcon(icons.icon("refresh", p.text))
        self.download_button.setIcon(icons.icon("download", p.text))
        self.new_folder_button.setIcon(icons.icon("new_folder", p.text))
        self.rename_button.setIcon(icons.icon("rename", p.text))
        self.delete_button.setIcon(icons.icon("trash", p.danger))
        self._fill()

    # -- listing ---------------------------------------------------------------------
    def reload(self) -> None:
        self.open_folder_path(self.folder)

    def go_up(self) -> None:
        if self.folder != "/":
            self.open_folder_path(files.parent(self.folder), select=self.folder)

    def open_folder_path(self, path: str, select: str | None = None) -> None:
        view = self.view
        runner = self.ctx.runner
        if view is None or not view.online or runner is None:
            return
        target = files.normalize(path)
        serial = view.serial
        self._load_id += 1
        load_id = self._load_id
        self._loading = True
        self.path_edit.setText(target)
        self.status.setText(tr("files.loading"))
        self._update_buttons()

        def done(entries: list[RemoteEntry]) -> None:
            if load_id != self._load_id:
                return  # an older listing arrived late
            self._loading = False
            self.folder = target
            self.entries = entries
            self._fill(select)
            self.status.setText(tr("files.count", count=len(entries)) if entries else tr("files.empty"))
            self._update_buttons()

        def failed(exc: BaseException) -> None:
            if load_id != self._load_id:
                return
            self._loading = False
            self.path_edit.setText(self.folder)  # stay where we were
            self.status.setText(tr("files.count", count=len(self.entries)))
            if isinstance(exc, FilesError) and exc.code == "denied":
                self._say(tr("files.denied", path=target))
            else:
                self._say(tr("files.failed", details=str(exc)))
            self._update_buttons()

        self.ctx.tasks.submit(lambda: files.list_folder(runner, serial, target), done, failed)

    def _fill(self, select: str | None = None) -> None:
        p = self.ctx.palette
        folder_icon = icons.icon("folder", p.brass_text)
        file_icon = icons.icon("file", p.text_muted)
        keep = {select} if select else {e.path for e in self.selected()}  # a reload keeps the selection
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        for entry in self.entries:
            name = QStandardItem(folder_icon if entry.is_dir else file_icon, entry.name)
            name.setData(entry, ENTRY_ROLE)
            name.setData(entry.name.casefold(), SORT_ROLE)
            name.setToolTip(entry.path)
            size = QStandardItem("" if entry.is_dir else human_size(entry.size))
            size.setData(-1 if entry.is_dir else entry.size, SORT_ROLE)
            size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            when = QStandardItem(datetime.fromtimestamp(entry.modified).strftime("%d.%m.%Y %H:%M") if entry.modified else "")
            when.setData(entry.modified, SORT_ROLE)
            self.model.appendRow([name, size, when])
        self.table.setSortingEnabled(True)
        selection = self.table.selectionModel()
        first = None
        for row in range(self.proxy.rowCount()):
            entry = self.proxy.index(row, 0).data(ENTRY_ROLE)
            if entry is not None and entry.path in keep:
                selection.select(self.proxy.index(row, 0), selection.SelectionFlag.Select | selection.SelectionFlag.Rows)
                first = first if first is not None else row
        if first is not None:
            self.table.scrollTo(self.proxy.index(first, 0))

    def selected(self) -> list[RemoteEntry]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [e for e in (self.proxy.index(r, 0).data(ENTRY_ROLE) for r in rows) if e is not None]

    def _activated(self, index: QModelIndex) -> None:
        entry = self.proxy.index(index.row(), 0).data(ENTRY_ROLE)
        if entry is not None and entry.is_dir:
            self.open_folder_path(entry.path)

    def _enter_selected(self) -> None:
        chosen = self.selected()
        if len(chosen) == 1 and chosen[0].is_dir:
            self.open_folder_path(chosen[0].path)

    # -- changes ---------------------------------------------------------------------
    def _run(self, work, done_text) -> None:
        """Run a change in the background, then reload and report."""
        def done(result) -> None:
            self._say(done_text(result))
            self.reload_after(result)

        def failed(exc: BaseException) -> None:
            self._say(self._error_text(exc))
            self._update_buttons()

        self.ctx.tasks.submit(work, done, failed)

    def reload_after(self, result) -> None:
        self.open_folder_path(self.folder, select=result if isinstance(result, str) else None)

    def _error_text(self, exc: BaseException) -> str:
        if isinstance(exc, FilesError):
            return tr(f"files.error.{exc.code}", details=exc.details or str(exc))
        return tr("files.failed", details=str(exc))

    def new_folder(self) -> None:
        if not self._ready():
            return
        name, ok = QInputDialog.getText(self, tr("files.new_folder.title"), tr("files.new_folder.prompt", folder=self.folder), text=tr("files.new_folder.default"))
        if not ok or not name.strip():
            return
        runner, serial, folder = self.ctx.runner, self.view.serial, self.folder
        self._run(lambda: files.make_folder(runner, serial, folder, name), lambda path: tr("files.created", path=path))

    def rename(self) -> None:
        chosen = self.selected()
        if not self._ready() or len(chosen) != 1:
            return
        entry = chosen[0]
        name, ok = QInputDialog.getText(self, tr("files.rename.title"), tr("files.rename.prompt", name=entry.name), text=entry.name)
        if not ok or not name.strip() or name.strip() == entry.name:
            return
        runner, serial = self.ctx.runner, self.view.serial
        self._run(lambda: files.rename(runner, serial, entry.path, name), lambda path: tr("files.renamed", path=path))

    def delete(self) -> None:
        chosen = self.selected()
        if not self._ready() or not chosen:
            return
        blocked = [e.path for e in chosen if files.is_protected(e.path)]
        if blocked:
            QMessageBox.warning(self, tr("files.delete.title"), tr("files.error.protected", details=", ".join(blocked)))
            return
        names = [e.name + ("/" if e.is_dir else "") for e in chosen]
        listed = "\n".join(names[:LISTED_IN_CONFIRM])
        if len(names) > LISTED_IN_CONFIRM:
            listed += "\n" + tr("files.delete.more", count=len(names) - LISTED_IN_CONFIRM)
        has_folders = any(e.is_dir for e in chosen)
        ok, _ = confirm(
            self,
            tr("files.delete.title"),
            tr("files.delete.body_folders" if has_folders else "files.delete.body", folder=self.folder) + "\n\n" + listed,
            tr("files.delete.do", count=len(chosen)),
            danger=True,
        )
        if not ok:
            return
        runner, serial, paths = self.ctx.runner, self.view.serial, [e.path for e in chosen]
        self._run(lambda: files.remove(runner, serial, paths), lambda _r: tr("files.deleted", count=len(paths)))

    # -- copies ----------------------------------------------------------------------
    def upload_files(self) -> None:
        if not self._ready():
            return
        chosen, _ = QFileDialog.getOpenFileNames(self, tr("files.upload.files.title", folder=self.folder))
        if chosen:
            self.upload([Path(p) for p in chosen])

    def upload_folder(self) -> None:
        if not self._ready():
            return
        chosen = QFileDialog.getExistingDirectory(self, tr("files.upload.folder.title", folder=self.folder))
        if chosen:
            self.upload([Path(chosen)])

    def upload(self, paths: list[Path]) -> None:
        """Copy files and folders from the computer into the open folder (buttons and drag and drop)."""
        if not self._ready() or not paths:
            return
        if self._transfer is not None:
            self._say(tr("files.busy"))
            return
        runner, serial, folder = self.ctx.runner, self.view.serial, self.folder
        names = ", ".join(p.name for p in paths[:3]) + ("…" if len(paths) > 3 else "")
        self._start_transfer(
            tr("files.uploading", what=names, folder=folder),
            lambda cancel: files.push(runner, serial, paths, folder, cancel=cancel),
            lambda result: tr("files.uploaded", folder=folder, summary=files.transfer_summary(result)),
            reload=True,
        )

    def download(self) -> None:
        chosen = self.selected()
        if not self._ready() or not chosen:
            return
        if self._transfer is not None:
            self._say(tr("files.busy"))
            return
        settings = self.ctx.settings.settings
        start = settings.files_download_dir or str(Path.home() / "Downloads")
        target = QFileDialog.getExistingDirectory(self, tr("files.download.title"), start)
        if not target:
            return
        settings.files_download_dir = target
        try:
            self.ctx.settings.save()
        except OSError:
            pass
        runner, serial, paths, local = self.ctx.runner, self.view.serial, [e.path for e in chosen], Path(target)
        names = ", ".join(e.name for e in chosen[:3]) + ("…" if len(chosen) > 3 else "")

        def finished(result: AdbResult) -> str:
            self.last_download = local
            self.result_open.show()
            return tr("files.downloaded", folder=breakable(local), summary=files.transfer_summary(result))

        self._start_transfer(tr("files.downloading", what=names), lambda cancel: files.pull(runner, serial, paths, local, cancel=cancel), finished)

    def _start_transfer(self, text: str, work, finished, reload: bool = False) -> None:
        cancel = threading.Event()
        self._transfer = cancel
        self.result_open.hide()
        self.cancel_button.show()
        self._say(text)
        self._update_buttons()

        def done(result: AdbResult) -> None:
            self._transfer = None
            self.cancel_button.hide()
            if result.cancelled:
                self._say(tr("files.cancelled"))
            elif not result.ok:
                self._say(tr("files.transfer_failed", details=result.output or "—"))
            else:
                self._say(finished(result))
            self._update_buttons()
            if reload and self.view is not None and self.view.online:
                self.reload_after(None)

        def failed(exc: BaseException) -> None:
            self._transfer = None
            self.cancel_button.hide()
            self._say(self._error_text(exc))
            self._update_buttons()

        self.ctx.tasks.submit(lambda: work(cancel), done, failed)

    def cancel_transfer(self) -> None:
        if self._transfer is not None:
            self._transfer.set()

    def shutdown(self) -> None:
        self.cancel_transfer()

    # -- helpers ---------------------------------------------------------------------
    def _ready(self) -> bool:
        return self.view is not None and self.view.online and self.ctx.runner is not None

    def _say(self, text: str) -> None:
        self.transfer_label.setText(text)

    def _update_buttons(self) -> None:
        chosen = self.selected() if self.stack.currentIndex() == 1 else []
        ready = self._ready()
        busy = self._transfer is not None
        self.up_button.setEnabled(ready and self.folder != "/")
        self.upload_button.setEnabled(ready and not busy)
        self.download_button.setEnabled(ready and not busy and bool(chosen))
        self.new_folder_button.setEnabled(ready)
        self.rename_button.setEnabled(ready and len(chosen) == 1)
        self.delete_button.setEnabled(ready and bool(chosen))
