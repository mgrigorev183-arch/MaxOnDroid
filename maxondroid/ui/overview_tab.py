"""Overview tab: what the selected device is and how it is doing."""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import actions, connection
from maxondroid.core.devices import State, Transport
from maxondroid.core.info import BatteryStatus, DeviceInfo, InfoError, read_info
from maxondroid.core.manager import DeviceView
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import Banner, format_kb, kind_name, label, state_name, transport_name
from maxondroid.ui.context import AppContext
from maxondroid.ui.device_list import device_accessible_text
from maxondroid.ui.tokens import TokenWidget, style_for

FIELD_KEYS = {
    "device": ["name", "manufacturer", "model", "kind", "android", "patch", "build", "abi", "serial"],
    "power": ["battery", "status", "temperature"],
    "memory": ["storage", "storage_bar", "ram"],
    "screen_network": ["resolution", "density", "ip", "connection", "wireless", "legacy"],
}


class Card(QFrame):
    def __init__(self, section: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.section = section
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        self.heading = label("", role="section")
        self.heading.setFont(theme.token_font(11.5))
        layout.addWidget(self.heading)
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(7)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)
        layout.addStretch(1)
        self.names: dict[str, QLabel] = {}
        self.values: dict[str, QWidget] = {}
        for key in FIELD_KEYS[section]:
            name = label("", role="muted")
            if key == "storage_bar":
                value: QWidget = QProgressBar()
                value.setTextVisible(False)
                value.setFixedHeight(6)
                value.setRange(0, 1000)
            else:
                value = label("", role="value", wrap=True, selectable=True)
            self.names[key] = name
            self.values[key] = value
            self.form.addRow(name, value)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def retranslate(self) -> None:
        self.heading.setText(tr(f"overview.section.{self.section}"))
        for key, name in self.names.items():
            name.setText(tr(f"overview.field.{key}") if key != "storage_bar" else "")

    def set_value(self, key: str, text: str | None) -> None:
        widget = self.values[key]
        visible = bool(text)
        if isinstance(widget, QLabel):
            widget.setText(text or "")
        self.form.setRowVisible(widget, visible)

    def set_bar(self, fraction: float | None) -> None:
        bar = self.values["storage_bar"]
        if fraction is None:
            self.form.setRowVisible(bar, False)
            return
        bar.setValue(int(max(0.0, min(1.0, fraction)) * 1000))  # type: ignore[attr-defined]
        bar.setAccessibleName(tr("overview.storage_used", percent=round(fraction * 100)))
        self.form.setRowVisible(bar, True)


class OverviewTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self.info: DeviceInfo | None = None
        self._info_for: tuple[str, str] | None = None  # (key, serial) the info belongs to
        self._loading = False
        self._error: str | None = None
        self._action_note: tuple[str, str] | None = None  # (kind, text) after an action
        self._busy_actions = False
        self._risk_expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        # empty page
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.setContentsMargins(40, 40, 40, 40)
        empty_layout.addStretch(1)
        self.empty_title = label("", role="title")
        self.empty_title.setFont(theme.token_font(16))
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body = label("", role="muted", wrap=True)
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_button = QPushButton()
        self.empty_button.setObjectName("Primary")
        self.empty_button.clicked.connect(lambda: self.ctx.open_connect(None))
        empty_layout.addWidget(self.empty_title)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(self.empty_body)
        empty_layout.addSpacing(16)
        empty_layout.addWidget(self.empty_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(2)
        self.stack.addWidget(self.empty)

        # device page
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        scroll.setWidget(page)
        self.page_layout = QVBoxLayout(page)
        self.page_layout.setContentsMargins(24, 20, 24, 24)
        self.page_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.token = TokenWidget(52)
        header.addWidget(self.token, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label("", role="title", wrap=True, selectable=True)
        self.title.setFont(theme.token_font(17))
        self.subtitle = label("", role="muted", wrap=True, selectable=True)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        actions_row.setContentsMargins(0, 8, 0, 0)
        titles.addLayout(actions_row)
        header.addLayout(titles, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.reload)
        self.rename_button = QPushButton()
        self.rename_button.clicked.connect(self.rename)
        self.reboot_button = QPushButton()
        self.reboot_button.setProperty("menu", True)
        self.reboot_menu = QMenu(self)
        self.reboot_button.setMenu(self.reboot_menu)
        self.more_button = QPushButton()
        self.more_button.setProperty("menu", True)
        self.more_menu = QMenu(self)
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_button.setMenu(self.more_menu)
        for button in (self.refresh_button, self.rename_button, self.reboot_button, self.more_button):
            actions_row.addWidget(button)
        actions_row.addStretch(1)
        self.page_layout.addLayout(header)

        self.security_banner = Banner("warning")
        self.state_banner = Banner("info")
        self.note_banner = Banner("info")
        for banner in (self.security_banner, self.state_banner, self.note_banner):
            self.page_layout.addWidget(banner)

        self.status_line = label("", role="muted")
        self.page_layout.addWidget(self.status_line)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        self.cards = {name: Card(name) for name in FIELD_KEYS}
        grid.addWidget(self.cards["device"], 0, 0, 2, 1)
        grid.addWidget(self.cards["power"], 0, 1)
        grid.addWidget(self.cards["memory"], 1, 1)
        grid.addWidget(self.cards["screen_network"], 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.page_layout.addLayout(grid)
        self.page_layout.addStretch(1)
        self.stack.addWidget(scroll)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_status_line)
        self._loaded_at: float | None = None
        self.retranslate()
        self.apply_palette()

    # -- language and theme ---------------------------------------------------
    def retranslate(self) -> None:
        self.refresh_button.setText(tr("overview.refresh"))
        self.rename_button.setText(tr("overview.rename"))
        self.reboot_button.setText(tr("overview.reboot"))
        self.more_button.setText(tr("overview.more"))
        self.empty_button.setText(tr("rail.connect"))
        self.reboot_menu.clear()
        self.reboot_menu.addAction(tr("overview.reboot.system"), lambda: self.reboot("system"))
        self.reboot_menu.addSeparator()
        self.reboot_menu.addAction(tr("overview.reboot.recovery"), lambda: self.reboot("recovery"))
        self.reboot_menu.addAction(tr("overview.reboot.bootloader"), lambda: self.reboot("bootloader"))
        for card in self.cards.values():
            card.retranslate()
        self.render()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.refresh_button.setIcon(icons.icon("refresh", p.text))
        self.render()

    # -- data -----------------------------------------------------------------
    def set_device(self, view: DeviceView | None, empty_list: bool = False) -> None:
        previous = self.view
        self.view = view
        self._empty_list = empty_list
        if view is None:
            self.info = None
            self._info_for = None
            self.render()
            return
        if previous is None or previous.key != view.key:
            self._action_note = None
            self._error = None
            self._risk_expanded = False
            if self._info_for and self._info_for[0] != view.key:
                self.info = None
        wanted = (view.key, view.serial) if view.online else None
        if wanted and wanted != self._info_for and not self._loading:
            self.reload()
            return
        if previous == view:
            return  # nothing changed since the last poll; keep text selections intact
        self.render()

    def reload(self) -> None:
        view = self.view
        if view is None or not view.online or self.ctx.runner is None or self._loading:
            return
        runner = self.ctx.runner
        serial = view.serial
        key = view.key
        self._loading = True
        self._error = None
        self.render()

        def done(info: DeviceInfo) -> None:
            self._loading = False
            if self.view is None or self.view.key != key:
                if self.view is not None:
                    self.set_device(self.view)  # another device was picked meanwhile
                return
            self.info = info
            self._info_for = (key, serial)
            self._loaded_at = time.monotonic()
            if info.identity.legacy_network_open != self.view.legacy_network_open and self.ctx.manager:
                for item in self.view.serials:  # the device list is out of date: read identity again
                    self.ctx.manager.invalidate(item)
                self.ctx.request_refresh()
            self.render()

        def failed(exc: BaseException) -> None:
            self._loading = False
            if self.view is None or self.view.key != key:
                if self.view is not None:
                    self.set_device(self.view)  # another device was picked meanwhile
                return
            self._info_for = (key, serial)
            self._error = exc.result.display_output() if isinstance(exc, InfoError) else str(exc)
            self.render()

        self.ctx.tasks.submit(lambda: read_info(runner, serial), done, failed)

    # -- rendering ------------------------------------------------------------
    def render(self) -> None:
        view = self.view
        if view is None:
            self.stack.setCurrentIndex(0)
            if getattr(self, "_empty_list", True):
                self.empty_title.setText(tr("overview.empty.title"))
                self.empty_body.setText(tr("overview.empty.body"))
                self.empty_button.show()
            else:
                self.empty_title.setText(tr("overview.pick.title"))
                self.empty_body.setText(tr("overview.pick.body"))
                self.empty_button.hide()
            self._tick.stop()
            return
        self.stack.setCurrentIndex(1)
        p = self.ctx.palette
        self.token.set_token(view.token, style_for(view.state), view.legacy_network_open, p)
        self.token.setAccessibleName(device_accessible_text(view))
        self.title.setText(view.name)
        info = self.info if self._info_for and self._info_for[0] == view.key else None
        sub = [kind_name(view.kind)]
        if view.model and view.model != view.name:
            sub.append(view.model)
        if info and info.android_version:
            sub.append(tr("overview.android_short", version=info.android_version))
        sub.append(transport_name(view.transport) if view.online else state_name(view.state))
        self.subtitle.setText(" · ".join(s for s in sub if s))

        online = view.online
        self.refresh_button.setEnabled(online and not self._loading)
        self.reboot_button.setEnabled(online and not self._busy_actions)
        self.rename_button.setEnabled(view.saved)
        self.more_button.setEnabled(not self._busy_actions)

        self._render_banners(view, p)
        self._render_cards(view, info)
        self._update_status_line()
        if online and not self._tick.isActive():
            self._tick.start()
        elif not online:
            self._tick.stop()

    def _render_banners(self, view: DeviceView, p: theme.Palette) -> None:
        if view.legacy_network_open and view.online:
            port = self.info.identity.legacy_tcp_port if self.info and self._info_for and self._info_for[0] == view.key else None
            port = port or connection.LEGACY_PORT
            if view.risk_accepted and not self._risk_expanded:
                self.security_banner.show_message(
                    "warning", tr("overview.legacy.accepted", port=port), "", tr("overview.legacy.details"), self._expand_risk, p
                )
            else:
                body = tr("overview.legacy.body", port=port)
                if view.transport is Transport.WIFI_LEGACY:
                    body += " " + tr("overview.legacy.body_wifi")
                if view.risk_accepted:
                    second, handler2 = tr("overview.legacy.revoke"), lambda: self._set_risk(False)
                elif view.saved:
                    second, handler2 = tr("overview.legacy.accept"), lambda: self._set_risk(True)
                else:
                    second, handler2 = None, None
                self.security_banner.show_message(
                    "warning", tr("overview.legacy.title"), body, tr("overview.legacy.action"), self.disable_network_adb, p, second, handler2
                )
        else:
            self.security_banner.hide()

        if view.state is State.UNAUTHORIZED:
            self.state_banner.show_message("info", tr("overview.unauthorized.title"), tr("overview.unauthorized.body"), palette=p)
        elif view.state is State.NO_PERMISSIONS:
            self.state_banner.show_message("info", tr("overview.no_permissions.title"), view.state_detail, palette=p)
        elif view.state is State.OFFLINE:
            self.state_banner.show_message("info", tr("overview.offline.title"), tr("overview.offline.body"), palette=p)
        elif view.state is State.UNKNOWN:
            self.state_banner.show_message("info", tr("overview.unknown.title"), tr("overview.unknown.body", state=view.state_detail or "?"), palette=p)
        elif view.state is State.DISCONNECTED:
            if view.network:
                body = tr("overview.disconnected.body_network", address=f"{view.network.host}:{view.network.port}")
                self.state_banner.show_message(
                    "info", tr("overview.disconnected.title"), body, tr("overview.disconnected.action"), self.connect_now, p
                )
            else:
                self.state_banner.show_message("info", tr("overview.disconnected.title"), tr("overview.disconnected.body_usb"), palette=p)
        elif view.state in (State.RECOVERY, State.SIDELOAD, State.BOOTLOADER, State.RESCUE):
            self.state_banner.show_message("info", tr("overview.special_mode.title", mode=state_name(view.state)), tr("overview.special_mode.body"), palette=p)
        elif self._error and view.online:
            self.state_banner.show_message("error", tr("overview.error.title"), self._error, tr("overview.refresh"), self.reload, p)
        else:
            self.state_banner.hide()

        if self._action_note:
            kind, text = self._action_note
            self.note_banner.show_message(kind, "", text, palette=p)
        else:
            self.note_banner.hide()

    def _render_cards(self, view: DeviceView, info: DeviceInfo | None) -> None:
        device = self.cards["device"]
        device.set_value("name", (info.identity.device_name if info else None) or view.alias or None)
        device.set_value("manufacturer", (info.identity.manufacturer if info else None) or view.manufacturer)
        device.set_value("model", (info.identity.model if info else None) or view.model)
        device.set_value("kind", kind_name(view.kind))
        if info:
            android = info.android_version or ""
            if info.sdk:
                android = tr("overview.android_api", version=android, sdk=info.sdk) if android else f"API {info.sdk}"
            device.set_value("android", android or None)
            device.set_value("patch", info.security_patch)
            device.set_value("build", info.build)
            device.set_value("abi", info.abi)
            device.set_value("serial", info.identity.serialno)
        else:
            for key in ("android", "patch", "build", "abi"):
                device.set_value(key, None)
            device.set_value("serial", view.key if view.saved else None)

        show_live = info is not None and view.online
        for name in ("power", "memory", "screen_network"):
            self.cards[name].setVisible(show_live or (name == "screen_network" and view.network is not None))
        if show_live:
            self._render_power(info)
            self._render_memory(info)
        self._render_screen_network(view, info if show_live else None)

    def _render_power(self, info: DeviceInfo) -> None:
        card = self.cards["power"]
        battery = info.battery
        if battery is None or not battery.present:
            card.set_value("battery", tr("overview.battery.none"))
            card.set_value("status", tr("overview.battery.mains") if battery else None)
            card.set_value("temperature", None)
            return
        card.set_value("battery", tr("overview.battery.level", level=battery.level) if battery.level is not None else None)
        status = tr(f"overview.battery.{battery.status.value}")
        if battery.powered_by and battery.status in (BatteryStatus.CHARGING, BatteryStatus.FULL, BatteryStatus.NOT_CHARGING):
            sources = ", ".join(tr(f"overview.power.{s}") for s in battery.powered_by)
            status = tr("overview.battery.from", status=status, sources=sources)
        card.set_value("status", status)
        if battery.temperature_c is not None:
            card.set_value("temperature", tr("unit.celsius", value=f"{battery.temperature_c:.1f}".replace(".", tr("unit.decimal"))))
        else:
            card.set_value("temperature", None)

    def _render_memory(self, info: DeviceInfo) -> None:
        card = self.cards["memory"]
        if info.storage and info.storage.total_kb:
            card.set_value("storage", tr("overview.storage.free", free=format_kb(info.storage.free_kb), total=format_kb(info.storage.total_kb)))
            card.set_bar(info.storage.used_kb / info.storage.total_kb)
        else:
            card.set_value("storage", tr("overview.unknown"))
            card.set_bar(None)
        if info.memory:
            if info.memory.available_kb is not None:
                card.set_value("ram", tr("overview.ram.available", free=format_kb(info.memory.available_kb), total=format_kb(info.memory.total_kb)))
            else:
                card.set_value("ram", format_kb(info.memory.total_kb))
        else:
            card.set_value("ram", None)

    def _render_screen_network(self, view: DeviceView, info: DeviceInfo | None) -> None:
        card = self.cards["screen_network"]
        if info:
            card.set_value("resolution", info.screen_size.replace("x", " × ") if info.screen_size else None)
            card.set_value("density", tr("overview.density", dpi=info.screen_density) if info.screen_density else None)
            if info.addresses:
                card.set_value("ip", "\n".join(f"{addr}  ({iface})" for iface, addr in info.addresses))
            else:
                card.set_value("ip", tr("overview.no_network"))
            card.set_value("wireless", tr("overview.on") if info.wireless_debugging else tr("overview.off"))
            port = info.identity.legacy_tcp_port
            card.set_value("legacy", tr("overview.legacy.open", port=port) if port else tr("overview.legacy.closed"))
        else:
            for key in ("resolution", "density", "ip", "wireless", "legacy"):
                card.set_value(key, None)
        if view.online:
            card.set_value("connection", transport_name(view.transport))
        elif view.network:
            mode = tr("overview.mode.legacy") if view.network.mode == "legacy" else tr("overview.mode.paired")
            card.set_value("connection", tr("overview.last_address", address=f"{view.network.host}:{view.network.port}", mode=mode))
        else:
            card.set_value("connection", None)

    def _update_status_line(self) -> None:
        if self.view is None or not self.view.online:
            self.status_line.hide()
            return
        if self._loading:
            text = tr("overview.loading")
        elif self._loaded_at is not None and self.info is not None:
            seconds = int(time.monotonic() - self._loaded_at)
            text = tr("overview.updated_now") if seconds < 5 else tr("overview.updated_ago", seconds=seconds) if seconds < 60 else tr("overview.updated_min", minutes=seconds // 60)
        else:
            text = ""
        self.status_line.setText(text)
        self.status_line.setVisible(bool(text))

    # -- actions --------------------------------------------------------------
    def _confirm(self, title: str, text: str, ok_text: str, danger: bool = False) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(text)
        ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(QMessageBox.StandardButton.NoButton)
        box.exec()
        return box.clickedButton() is ok

    def _run_action(self, fn, success_text, after=None) -> None:
        self._busy_actions = True
        self.render()

        def done(result) -> None:
            self._busy_actions = False
            ok = getattr(result, "ok", True)
            if ok:
                self._action_note = ("info", success_text)
            else:
                message = getattr(result, "message", None) or getattr(result, "output", "") or ""
                self._action_note = ("error", tr("overview.action_failed", details=message.strip() or "—"))
            if self.view and self.view.serial and self.ctx.manager:
                for serial in self.view.serials:
                    self.ctx.manager.invalidate(serial)
            self._info_for = None
            self.render()
            if after:
                after(result)
            self.ctx.request_refresh()

        def failed(exc: BaseException) -> None:
            self._busy_actions = False
            self._action_note = ("error", tr("overview.action_failed", details=str(exc)))
            self.render()

        self.ctx.tasks.submit(fn, done, failed)

    def reboot(self, target: str) -> None:
        view = self.view
        if view is None or not view.online or self.ctx.runner is None:
            return
        text = tr(f"overview.reboot.confirm.{target}", name=view.name)
        if not self._confirm(tr("overview.reboot"), text, tr(f"overview.reboot.do.{target}"), danger=target != "system"):
            return
        runner, serial = self.ctx.runner, view.serial
        self._run_action(lambda: actions.reboot(runner, serial, target), tr("overview.reboot.sent", name=view.name))

    def _expand_risk(self) -> None:
        self._risk_expanded = True
        self.render()

    def _set_risk(self, accepted: bool) -> None:
        view = self.view
        if view is None or not view.saved:
            return
        self.ctx.registry.set_risk_accepted(view.key, accepted)
        self._risk_expanded = False
        self.view = replace(view, risk_accepted=accepted)
        self.render()
        self.ctx.request_refresh()

    def rename(self) -> None:
        view = self.view
        if view is None or not view.saved:
            return
        text, ok = QInputDialog.getText(self, tr("overview.rename"), tr("overview.rename.prompt"), text=view.alias or view.name)
        if ok:
            self.ctx.registry.rename(view.key, text)
            self.ctx.request_refresh()

    def connect_now(self) -> None:
        view = self.view
        if view is None or view.network is None or self.ctx.runner is None:
            return
        runner, net = self.ctx.runner, view.network
        self._run_action(lambda: connection.connect(runner, net.host, net.port), tr("overview.connected"))

    def disable_network_adb(self) -> None:
        view = self.view
        if view is None or not view.online or self.ctx.runner is None:
            return
        body = tr("overview.disable_legacy.confirm")
        if view.transport is Transport.WIFI_LEGACY:
            body += "\n\n" + tr("overview.disable_legacy.confirm_wifi")
        if not self._confirm(tr("overview.disable_legacy"), body, tr("overview.disable_legacy.do")):
            return
        runner, serial = self.ctx.runner, view.serial
        self._run_action(lambda: connection.disable_network_adb(runner, serial), tr("overview.disable_legacy.done"))

    def enable_legacy(self) -> None:
        view = self.view
        if view is None or not view.online or self.ctx.runner is None:
            return
        if not self._confirm(tr("overview.enable_legacy"), tr("overview.enable_legacy.confirm"), tr("overview.enable_legacy.do"), danger=True):
            return
        runner, serial = self.ctx.runner, view.serial
        address = next((addr for _, addr in self.info.addresses), None) if self.info else None

        def work():
            step = connection.enable_legacy_tcpip(runner, serial)
            if step.ok and address:
                time.sleep(2.0)
                return connection.connect(runner, address, connection.LEGACY_PORT)
            return step

        self._run_action(work, tr("overview.enable_legacy.done", address=f"{address}:{connection.LEGACY_PORT}" if address else "—"))

    def disconnect_network(self) -> None:
        view = self.view
        if view is None or self.ctx.runner is None:
            return
        runner = self.ctx.runner
        targets = [s for s in view.serials if ":" in s or "._adb-tls-connect" in s]

        def work():
            last = None
            for serial in targets:
                last = connection.disconnect(runner, serial)
            return last

        self._run_action(work, tr("overview.disconnected_note"))

    def forget(self) -> None:
        view = self.view
        if view is None or not view.saved or self.ctx.manager is None:
            return
        if not self._confirm(tr("overview.forget"), tr("overview.forget.confirm", name=view.name), tr("overview.forget.do"), danger=True):
            return
        manager = self.ctx.manager
        self._run_action(lambda: manager.forget(view), tr("overview.forget.done", name=view.name))

    def _fill_more_menu(self) -> None:
        menu = self.more_menu
        menu.clear()
        view = self.view
        if view is None:
            return
        online = view.online
        network_serials = [s for s in view.serials if ":" in s or "._adb-tls-connect" in s]
        if online and view.legacy_network_open:
            menu.addAction(tr("overview.disable_legacy") + "…", self.disable_network_adb)
        elif online:
            menu.addAction(tr("overview.enable_legacy") + "…", self.enable_legacy)
        if network_serials:
            menu.addAction(tr("overview.disconnect"), self.disconnect_network)
        if not online and view.network:
            menu.addAction(tr("overview.disconnected.action"), self.connect_now)
        if view.saved:
            menu.addSeparator()
            menu.addAction(tr("overview.forget") + "…", self.forget)
        if menu.isEmpty():
            action = menu.addAction(tr("overview.no_actions"))
            action.setEnabled(False)
