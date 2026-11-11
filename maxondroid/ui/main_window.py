"""The main window: device rail on the left, tabs on the right, journal below."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from maxondroid import APP_NAME, __version__
from maxondroid.core.adb import AdbNotFoundError, AdbRunner, find_adb
from maxondroid.core.manager import DeviceManager, DeviceView, ManagerError
from maxondroid.core.settings import THEMES
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.apps_tab import AppsTab
from maxondroid.ui.common import Banner, label
from maxondroid.ui.connect_dialog import ConnectDialog
from maxondroid.ui.context import AppContext
from maxondroid.ui.debloat_tab import DebloatTab
from maxondroid.ui.device_list import DeviceListView
from maxondroid.ui.journal_panel import JournalPanel
from maxondroid.ui.overview_tab import OverviewTab
from maxondroid.ui.package_support import PackageCache
from maxondroid.ui.remote_tab import RemoteTab
from maxondroid.ui.screen_tab import ScreenTab
from maxondroid.ui.settings_dialog import SettingsDialog

POLL_MS = 2500
RECONNECT_EVERY = 8  # polls (about 20 s)
REPO_URL = "https://github.com/mgrigorev183-arch/MaxOnDroid"


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, apply_theme, apply_language):
        super().__init__()
        self.ctx = ctx
        self._apply_theme = apply_theme
        self._apply_language = apply_language
        self.views: list[DeviceView] = []
        self._refreshing = False
        self._poll_count = 0
        self._adb_error: str | None = None
        self._connect_dialog: ConnectDialog | None = None
        ctx.request_refresh = self.refresh_now
        ctx.open_connect = self.open_connect
        ctx.open_settings = self.open_settings

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(880, 560)

        # rail -----------------------------------------------------------------
        self.rail = QFrame()
        self.rail.setObjectName("Rail")
        self.rail.setMinimumWidth(240)
        self.rail.setMaximumWidth(360)
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(0, 14, 0, 0)
        rail_layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(18, 0, 10, 4)
        self.app_title = QLabel(APP_NAME)
        self.app_title.setObjectName("RailTitle")
        self.app_title.setFont(theme.token_font(15, theme.QFont.Weight.Bold))
        head.addWidget(self.app_title)
        head.addStretch(1)
        self.rail_refresh = QToolButton()
        self.rail_refresh.clicked.connect(self.refresh_now)
        self.rail_settings = QToolButton()
        self.rail_settings.clicked.connect(self.open_settings)
        for button in (self.rail_refresh, self.rail_settings):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # reachable by F5 and Ctrl+, instead
            button.setAutoRaise(True)
            head.addWidget(button)
        rail_layout.addLayout(head)
        self.rail_caption = label("", role="muted")
        self.rail_caption.setContentsMargins(18, 0, 18, 4)
        rail_layout.addWidget(self.rail_caption)

        self.rail_stack = QStackedWidget()
        self.device_list = DeviceListView()
        self.device_list.selection_changed_key.connect(self._selection_changed)
        self.device_list.customContextMenuRequested.connect(self._device_menu)
        self.rail_empty = label("", role="muted", wrap=True)
        self.rail_empty.setContentsMargins(18, 8, 18, 8)
        self.rail_empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.rail_stack.addWidget(self.device_list)
        self.rail_stack.addWidget(self.rail_empty)
        rail_layout.addWidget(self.rail_stack, 1)

        footer = QFrame()
        footer.setObjectName("RailFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 12, 14, 14)
        self.connect_button = QPushButton()
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(lambda: self.open_connect(None))
        footer_layout.addWidget(self.connect_button)
        rail_layout.addWidget(footer)

        # work area ------------------------------------------------------------
        work = QWidget()
        work_layout = QVBoxLayout(work)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)
        self.adb_banner = Banner("error")
        banner_box = QVBoxLayout()
        banner_box.setContentsMargins(16, 12, 16, 0)
        banner_box.addWidget(self.adb_banner)
        work_layout.addLayout(banner_box)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        ctx.packages = PackageCache(ctx, self)
        self.overview = OverviewTab(ctx)
        self.apps = AppsTab(ctx)
        self.debloat = DebloatTab(ctx)
        self.remote = RemoteTab(ctx)
        self.screen = ScreenTab(ctx)
        for tab in (self.overview, self.apps, self.debloat, self.remote, self.screen):
            self.tabs.addTab(tab, "")
        self.setAcceptDrops(True)
        work_layout.addWidget(self.tabs, 1)

        self.journal_panel = JournalPanel(ctx.journal)
        self.journal_panel.visibility_requested.connect(self._journal_toggled)
        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.addWidget(work)
        self.vsplit.addWidget(self.journal_panel)
        self.vsplit.setStretchFactor(0, 3)
        self.vsplit.setStretchFactor(1, 1)
        self.vsplit.setChildrenCollapsible(False)

        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.addWidget(self.rail)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([280, 900])
        self.hsplit.setChildrenCollapsible(False)
        self.setCentralWidget(self.hsplit)

        self.status_adb = label("")
        self.status_devices = label("")
        self.statusBar().addWidget(self.status_adb, 1)
        self.statusBar().addPermanentWidget(self.status_devices)

        self._build_menus()
        self._restore_layout()

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)

        self.retranslate()
        self.apply_palette()

    # -- menus ----------------------------------------------------------------
    def _build_menus(self) -> None:
        bar = self.menuBar()
        self.menu_file = QMenu(self)
        self.menu_device = QMenu(self)
        self.menu_view = QMenu(self)
        self.menu_help = QMenu(self)
        for menu in (self.menu_file, self.menu_device, self.menu_view, self.menu_help):
            bar.addMenu(menu)
        self.act_settings = QAction(self, triggered=self.open_settings)
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_quit = QAction(self, triggered=self.close)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.menu_file.addAction(self.act_settings)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_quit)
        self.act_connect = QAction(self, triggered=lambda: self.open_connect(None))
        self.act_connect.setShortcut(QKeySequence("Ctrl+N"))
        self.act_refresh = QAction(self, triggered=self.refresh_now)
        self.act_refresh.setShortcut(QKeySequence("F5"))
        self.menu_device.addAction(self.act_connect)
        self.menu_device.addAction(self.act_refresh)
        self.act_journal = QAction(self, checkable=True, triggered=self._journal_menu)
        self.act_journal.setShortcut(QKeySequence("Ctrl+J"))
        self.menu_view.addAction(self.act_journal)
        self.menu_theme = self.menu_view.addMenu("")
        self.theme_group = QActionGroup(self)
        self.theme_actions: dict[str, QAction] = {}
        for code in THEMES:
            action = QAction(self, checkable=True)
            action.triggered.connect(lambda checked=False, c=code: self._set_theme(c))
            self.theme_group.addAction(action)
            self.menu_theme.addAction(action)
            self.theme_actions[code] = action
        self.menu_language = self.menu_view.addMenu("")
        self.lang_group = QActionGroup(self)
        self.lang_actions: dict[str, QAction] = {}
        for code in ("system", "ru", "en"):
            action = QAction(self, checkable=True)
            action.triggered.connect(lambda checked=False, c=code: self._set_language(c))
            self.lang_group.addAction(action)
            self.menu_language.addAction(action)
            self.lang_actions[code] = action
        self.act_repo = QAction(self, triggered=lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        self.act_about = QAction(self, triggered=self._about)
        self.menu_help.addAction(self.act_repo)
        self.menu_help.addAction(self.act_about)

    def retranslate(self) -> None:
        self.menu_file.setTitle(tr("menu.file"))
        self.menu_device.setTitle(tr("menu.device"))
        self.menu_view.setTitle(tr("menu.view"))
        self.menu_help.setTitle(tr("menu.help"))
        self.act_settings.setText(tr("menu.settings"))
        self.act_quit.setText(tr("menu.quit"))
        self.act_connect.setText(tr("rail.connect") + "…")
        self.act_refresh.setText(tr("menu.refresh"))
        self.act_journal.setText(tr("menu.journal"))
        self.menu_theme.setTitle(tr("settings.theme"))
        for code, action in self.theme_actions.items():
            action.setText(tr(f"settings.theme.{code}"))
        self.menu_language.setTitle(tr("settings.language"))
        for code, action in self.lang_actions.items():
            action.setText(tr(f"settings.language.{code}"))
        self.act_repo.setText(tr("menu.repo"))
        self.act_about.setText(tr("menu.about"))
        self.tabs.setTabText(0, tr("tab.overview"))
        self.tabs.setTabText(1, tr("tab.apps"))
        self.tabs.setTabText(2, tr("tab.debloat"))
        self.tabs.setTabText(3, tr("tab.remote"))
        self.tabs.setTabText(4, tr("tab.screen"))
        self.apps.retranslate()
        self.debloat.retranslate()
        self.remote.retranslate()
        self.screen.retranslate()
        self.connect_button.setText(tr("rail.connect"))
        self.rail_caption.setText(tr("rail.caption"))
        for button, key in ((self.rail_refresh, "menu.refresh"), (self.rail_settings, "menu.settings")):
            button.setToolTip(tr(key))
            button.setAccessibleName(tr(key))
        self.overview.retranslate()
        self.journal_panel.retranslate()
        self.device_list.model_.refresh_texts()
        if self._connect_dialog is not None:
            self._connect_dialog.retranslate()
        self._sync_checks()
        self._update_status()
        self._render_rail()
        self._render_adb_banner()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.device_list.set_palette(p)
        self.rail_refresh.setIcon(icons.icon("refresh", p.rail_text))
        self.rail_settings.setIcon(icons.icon("settings", p.rail_text))
        self.connect_button.setIcon(icons.icon("plus", p.brass_on))
        self.journal_panel.set_palette(p)
        self.overview.apply_palette()
        self.apps.apply_palette()
        self.debloat.apply_palette()
        self.remote.apply_palette()
        self.screen.apply_palette()
        self.apps.model.refresh_all()
        self.debloat.refresh_texts()
        if self._connect_dialog is not None:
            self._connect_dialog.retranslate()  # re-tints its icons
        self._render_adb_banner()

    def _sync_checks(self) -> None:
        s = self.ctx.settings.settings
        self.theme_actions[s.theme].setChecked(True)
        self.lang_actions[s.language].setChecked(True)
        self.act_journal.setChecked(s.journal_visible)

    # -- layout persistence -------------------------------------------------
    def _restore_layout(self) -> None:
        s = self.ctx.settings.settings
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
        self.journal_panel.set_expanded(s.journal_visible)
        self._apply_journal_size(s.journal_visible)

    def _apply_journal_size(self, expanded: bool) -> None:
        total = max(self.vsplit.height(), 600)
        header = self.journal_panel.sizeHint().height() if not expanded else 0
        if expanded:
            self.journal_panel.setMinimumHeight(120)
            self.journal_panel.setMaximumHeight(16777215)
            self.vsplit.setSizes([int(total * 0.72), int(total * 0.28)])
        else:
            self.journal_panel.setMinimumHeight(0)
            self.journal_panel.setMaximumHeight(max(header, 34))
            self.vsplit.setSizes([total, 34])

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        from maxondroid import i18n

        i18n.remove_listener(getattr(self, "i18n_listener", None))
        s = self.ctx.settings.settings
        s.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        try:
            self.ctx.settings.save()
            self.ctx.registry.save()
        except OSError:
            pass
        if self._connect_dialog is not None:
            self._connect_dialog.stop_qr()
        self.screen.shutdown()
        self.ctx.tasks.shutdown(3000)
        super().closeEvent(event)

    # -- adb setup ------------------------------------------------------------
    def setup_adb(self, runner: AdbRunner | None = None) -> None:
        """Find adb and start polling. Tests pass their own runner."""
        path = runner.executable if runner is not None else find_adb(self.ctx.settings.settings.adb_path or None)
        self.ctx.runner = None
        self.ctx.manager = None
        if path is None:
            self._adb_error = "missing"
        else:
            runner = runner or AdbRunner(path)
            runner.add_listener(self.ctx.journal.record)
            manager = DeviceManager(runner, self.ctx.registry)
            self.ctx.journal.token_lookup = manager.token_for_serial
            self.ctx.runner = runner
            self.ctx.manager = manager
            self._adb_error = None
            self._adb_path = path
        self._render_adb_banner()
        self._update_status()
        self.screen.setup_tool()
        self.timer.start()
        self.refresh_now()
        self.device_list.setFocus()

    def _render_adb_banner(self) -> None:
        p = self.ctx.palette
        if self._adb_error == "missing":
            self.adb_banner.show_message("error", tr("adb.missing.title"), tr("adb.missing.body"), tr("adb.missing.action"), self.open_settings, p)
        elif self._adb_error:
            self.adb_banner.show_message("error", tr("adb.error.title"), self._adb_error, tr("menu.settings"), self.open_settings, p)
        else:
            self.adb_banner.hide()

    # -- polling --------------------------------------------------------------
    def refresh_now(self) -> None:
        self._poll(force=True)

    def _poll(self, force: bool = False) -> None:
        manager = self.ctx.manager
        if manager is None or self._refreshing:
            return
        self._refreshing = True
        self._poll_count += 1
        try_reconnect = self.ctx.settings.settings.auto_reconnect and (self._poll_count % RECONNECT_EVERY == 1)

        def work():
            views = manager.refresh()
            if try_reconnect and manager.reconnect(views):
                views = manager.refresh()
            return views

        self.ctx.tasks.submit(work, self._refreshed, self._refresh_failed)

    def _refreshed(self, views: list[DeviceView]) -> None:
        self._refreshing = False
        if self._adb_error and self._adb_error != "missing":
            self._adb_error = None
            self._render_adb_banner()
        self.views = views
        self.device_list.set_views(views)
        self._render_rail()
        self._update_status()

    def _refresh_failed(self, exc: BaseException) -> None:
        self._refreshing = False
        if isinstance(exc, AdbNotFoundError):
            self._adb_error = "missing"
        elif isinstance(exc, ManagerError):
            self._adb_error = str(exc) or tr("adb.error.generic")
        else:
            self._adb_error = f"{type(exc).__name__}: {exc}"
        self._render_adb_banner()

    def _render_rail(self) -> None:
        if self.views:
            self.rail_stack.setCurrentIndex(0)
        else:
            self.rail_empty.setText(tr("rail.empty"))
            self.rail_stack.setCurrentIndex(1)

    def _update_status(self) -> None:
        if self.ctx.runner is not None:
            self.status_adb.setText(tr("status.adb", path=getattr(self, "_adb_path", "")))
        else:
            self.status_adb.setText(tr("status.adb_missing"))
        online = sum(1 for v in self.views if v.online)
        self.status_devices.setText(tr("status.devices", online=online, total=len(self.views)))

    def _selection_changed(self, key: str | None) -> None:
        view = next((v for v in self.views if v.key == key), None)
        self.overview.set_device(view, empty_list=not self.views)
        self.apps.set_device(view)
        self.debloat.set_device(view)
        self.remote.set_device(view)
        self.screen.set_device(view)

    def _device_menu(self, pos) -> None:
        index = self.device_list.indexAt(pos)
        if not index.isValid():
            return
        self.device_list.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction(tr("overview.rename") + "…", self.overview.rename).setEnabled(bool(self.overview.view and self.overview.view.saved))
        menu.addSeparator()
        self.overview._fill_more_menu()
        for action in self.overview.more_menu.actions():
            menu.addAction(action)
        menu.exec(self.device_list.viewport().mapToGlobal(pos))

    # -- dialogs and settings -------------------------------------------------
    def open_connect(self, tab: str | None = None) -> None:
        if self._connect_dialog is None:
            self._connect_dialog = ConnectDialog(self.ctx, self, tab)
        elif tab:
            from maxondroid.ui.connect_dialog import TABS

            self._connect_dialog.tabs.setCurrentIndex(TABS.index(tab))
        self._connect_dialog.show()
        self._connect_dialog.raise_()
        self._connect_dialog.activateWindow()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.ctx, self)
        old_adb = self.ctx.settings.settings.adb_path
        old_scrcpy = self.ctx.settings.settings.scrcpy_path
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        s = dialog.result_settings()
        self.ctx.settings.save()
        self._apply_language(s.language)
        self._apply_theme(s.theme)
        self.journal_panel.set_expanded(s.journal_visible)
        self._apply_journal_size(s.journal_visible)
        self._sync_checks()
        if s.adb_path != old_adb or self.ctx.runner is None:
            self.setup_adb()
        elif s.scrcpy_path != old_scrcpy:
            self.screen.setup_tool()

    def _set_theme(self, code: str) -> None:
        self.ctx.settings.settings.theme = code
        self.ctx.settings.save()
        self._apply_theme(code)

    def _set_language(self, code: str) -> None:
        self.ctx.settings.settings.language = code
        self.ctx.settings.save()
        self._apply_language(code)

    def _journal_menu(self, checked: bool) -> None:
        self.journal_panel.set_expanded(checked)
        self._journal_toggled(checked)

    def _journal_toggled(self, expanded: bool) -> None:
        self.ctx.settings.settings.journal_visible = expanded
        self.ctx.settings.save()
        self._apply_journal_size(expanded)
        self.act_journal.setChecked(expanded)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if AppsTab.dropped_files(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = AppsTab.dropped_files(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.tabs.setCurrentWidget(self.apps)
            self.apps.install(files)

    def _about(self) -> None:
        QMessageBox.about(self, tr("menu.about"), tr("about.text", name=APP_NAME, version=__version__, url=REPO_URL))

    def theme_changed(self) -> None:
        self.apply_palette()
        app = QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                widget.update()
