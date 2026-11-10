"""Connecting a device: pairing by code or QR, by address, found on the network, USB help."""

from __future__ import annotations

import threading

import segno
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import connection, mdns, validate
from maxondroid.core.connection import Outcome, StepResult
from maxondroid.i18n import tr
from maxondroid.ui import icons
from maxondroid.ui.common import label, repolish
from maxondroid.ui.context import AppContext

TABS = ("code", "qr", "address", "found", "usb")
GOOGLE_USB_DRIVER = "https://developer.android.com/studio/run/win-usb"
OEM_DRIVERS = "https://developer.android.com/studio/run/oem-usb"


class QrWidget(QWidget):
    """Draws a QR code; always dark on white so every phone camera can read it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._matrix: list[list[bool]] = []
        self.setFixedSize(232, 232)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(232, 232)

    def set_payload(self, payload: str | None) -> None:
        if payload:
            code = segno.make(payload, error="m", micro=False)
            self._matrix = [[bool(v) for v in row] for row in code.matrix]
        else:
            self._matrix = []
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        if self._matrix:
            quiet = 4
            count = len(self._matrix) + 2 * quiet
            cell = min(self.width(), self.height()) / count
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#111111"))
            for y, row in enumerate(self._matrix):
                for x, dark in enumerate(row):
                    if dark:
                        painter.drawRect(QRectF((x + quiet) * cell, (y + quiet) * cell, cell + 0.3, cell + 0.3))
        painter.end()


def outcome_text(step: StepResult | None, stage: str) -> str:
    if step is None:
        return ""
    key = f"connect.result.{stage}.{step.outcome.value}"
    text = tr(key)
    if text == key:
        text = tr(f"connect.result.{step.outcome.value}")
    if step.message and not step.ok:
        text += "\n" + step.message
    return text


class ConnectDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None, initial_tab: str | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setMinimumSize(660, 540)
        self._qr_cancel: threading.Event | None = None
        self._qr_session: connection.QrSession | None = None
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        self.status = label("", wrap=True, selectable=True)
        self.status.hide()
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        self._build_code_tab()
        self._build_qr_tab()
        self._build_address_tab()
        self._build_found_tab()
        self._build_usb_tab()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.retranslate()
        if initial_tab in TABS:
            self.tabs.setCurrentIndex(TABS.index(initial_tab))

    # -- building -------------------------------------------------------------
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(4, 14, 4, 4)
        box.setSpacing(12)
        return page, box

    def _build_code_tab(self) -> None:
        page, box = self._page()
        self.code_steps = label("", wrap=True)
        box.addWidget(self.code_steps)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.code_host = QLineEdit()
        self.code_host.setPlaceholderText("192.168.1.23")
        self.code_port = QLineEdit()
        self.code_port.setPlaceholderText("41231")
        self.code_port.setMaxLength(5)
        self.code_value = QLineEdit()
        self.code_value.setPlaceholderText("123456")
        self.code_value.setMaxLength(7)
        self.code_connect_port = QLineEdit()
        self.code_connect_port.setMaxLength(5)
        self.code_labels = [label(), label(), label(), label()]
        form.addRow(self.code_labels[0], self.code_host)
        form.addRow(self.code_labels[1], self.code_port)
        form.addRow(self.code_labels[2], self.code_value)
        form.addRow(self.code_labels[3], self.code_connect_port)
        box.addLayout(form)
        self.code_button = QPushButton()
        self.code_button.setObjectName("Primary")
        self.code_button.clicked.connect(self.pair_with_code)
        self.code_value.returnPressed.connect(self.pair_with_code)
        box.addWidget(self.code_button, 0, Qt.AlignmentFlag.AlignLeft)
        box.addStretch(1)
        self.tabs.addTab(page, "")

    def _build_qr_tab(self) -> None:
        page, box = self._page()
        row = QHBoxLayout()
        row.setSpacing(18)
        self.qr = QrWidget()
        row.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        self.qr_steps = label("", wrap=True)
        right.addWidget(self.qr_steps)
        self.qr_state = label("", role="muted", wrap=True)
        right.addWidget(self.qr_state)
        self.qr_new = QPushButton()
        self.qr_new.clicked.connect(self.start_qr)
        right.addWidget(self.qr_new, 0, Qt.AlignmentFlag.AlignLeft)
        right.addStretch(1)
        row.addLayout(right, 1)
        box.addLayout(row)
        self.qr_note = label("", role="muted", wrap=True)
        box.addWidget(self.qr_note)
        box.addStretch(1)
        self.tabs.addTab(page, "")

    def _build_address_tab(self) -> None:
        page, box = self._page()
        self.address_text = label("", wrap=True)
        box.addWidget(self.address_text)
        form = QFormLayout()
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("192.168.1.40:5555")
        self.address_label = label()
        form.addRow(self.address_label, self.address_edit)
        box.addLayout(form)
        self.address_button = QPushButton()
        self.address_button.setObjectName("Primary")
        self.address_button.clicked.connect(self.connect_address)
        self.address_edit.returnPressed.connect(self.connect_address)
        box.addWidget(self.address_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.address_warning = label("", role="muted", wrap=True)
        box.addWidget(self.address_warning)
        box.addStretch(1)
        self.tabs.addTab(page, "")

    def _build_found_tab(self) -> None:
        page, box = self._page()
        self.found_text = label("", wrap=True)
        box.addWidget(self.found_text)
        self.found_list = QListWidget()
        self.found_list.itemDoubleClicked.connect(lambda item: self.use_found())
        self.found_list.currentItemChanged.connect(lambda *_: self._update_found_button())
        box.addWidget(self.found_list, 1)
        row = QHBoxLayout()
        self.found_refresh = QPushButton()
        self.found_refresh.clicked.connect(self.discover)
        self.found_use = QPushButton()
        self.found_use.setObjectName("Primary")
        self.found_use.clicked.connect(self.use_found)
        row.addWidget(self.found_refresh)
        row.addStretch(1)
        row.addWidget(self.found_use)
        box.addLayout(row)
        self.tabs.addTab(page, "")

    def _build_usb_tab(self) -> None:
        page, box = self._page()
        self.usb_text = label("", wrap=True)
        self.usb_text.setOpenExternalLinks(True)
        self.usb_text.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.usb_text)
        box.addStretch(1)
        self.tabs.addTab(page, "")

    def retranslate(self) -> None:
        self.setWindowTitle(tr("connect.title"))
        for index, name in enumerate(TABS):
            self.tabs.setTabText(index, tr(f"connect.tab.{name}"))
        self.code_steps.setText(tr("connect.code.steps"))
        for lbl, key in zip(self.code_labels, ("host", "pair_port", "code", "connect_port"), strict=True):
            lbl.setText(tr(f"connect.field.{key}"))
        self.code_connect_port.setPlaceholderText(tr("connect.field.connect_port_hint"))
        self.code_button.setText(tr("connect.code.button"))
        self.qr_steps.setText(tr("connect.qr.steps"))
        self.qr_new.setText(tr("connect.qr.new"))
        self.qr_note.setText(tr("connect.qr.note"))
        self.address_text.setText(tr("connect.address.text"))
        self.address_label.setText(tr("connect.field.address"))
        self.address_button.setText(tr("connect.address.button"))
        self.address_warning.setText(tr("connect.address.warning"))
        self.found_text.setText(tr("connect.found.text"))
        self.found_refresh.setText(tr("connect.found.refresh"))
        self.found_refresh.setIcon(icons.icon("refresh", self.ctx.palette.text))
        self._update_found_button()
        self.usb_text.setText(tr("connect.usb.text", google=GOOGLE_USB_DRIVER, oem=OEM_DRIVERS))

    # -- helpers --------------------------------------------------------------
    def _set_status(self, text: str, kind: str = "info") -> None:
        self.status.setProperty("role", {"error": "error", "ok": "success"}.get(kind, "muted"))
        repolish(self.status)
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.code_button, self.address_button, self.found_use, self.found_refresh):
            widget.setEnabled(not busy)
        if not busy:
            self._update_found_button()

    def _validation_message(self, err: validate.ValidationError) -> str:
        return tr(f"validate.{err.code}")

    def _finish(self, pair_step: StepResult | None, connect_step: StepResult | None) -> None:
        self._set_busy(False)
        if pair_step is not None and not pair_step.ok:
            self._set_status(outcome_text(pair_step, "pair"), "error")
            return
        if connect_step is None:
            self._set_status(tr("connect.result.paired_only"), "info")
            return
        if connect_step.ok:
            self._set_status(tr("connect.result.connected", endpoint=connect_step.endpoint or ""), "ok")
            self.ctx.request_refresh()
        elif connect_step.outcome is Outcome.NOT_FOUND and pair_step is not None:
            self._set_status(tr("connect.result.need_connect_port"), "error")
            self.code_connect_port.setFocus()
        else:
            self._set_status(outcome_text(connect_step, "connect"), "error")

    def _failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._set_status(tr("connect.result.exception", details=str(exc)), "error")

    # -- pairing by code ------------------------------------------------------
    def pair_with_code(self) -> None:
        if self._busy or self.ctx.runner is None:
            return
        try:
            host = validate.host(self.code_host.text())
            port = validate.port(self.code_port.text())
            code = validate.pair_code(self.code_value.text())
            connect_port_text = self.code_connect_port.text().strip()
            connect_port = validate.port(connect_port_text) if connect_port_text else None
        except validate.ValidationError as err:
            self._set_status(self._validation_message(err), "error")
            return
        runner = self.ctx.runner
        self._set_busy(True)
        self._set_status(tr("connect.code.working"))
        self.ctx.tasks.submit(
            lambda: connection.pair_and_connect(runner, host, port, code, connect_port),
            lambda steps: self._finish(*steps),
            self._failed,
        )

    def prefill_pairing(self, host: str, port: int) -> None:
        self.code_host.setText(host)
        self.code_port.setText(str(port))
        self.tabs.setCurrentIndex(TABS.index("code"))
        self.code_value.setFocus()

    # -- QR -------------------------------------------------------------------
    def _tab_changed(self, index: int) -> None:
        self._set_status("")
        name = TABS[index]
        if name == "qr":
            self.start_qr()
        else:
            self.stop_qr()
        if name == "found" and self.found_list.count() == 0:
            self.discover()

    def stop_qr(self) -> None:
        if self._qr_cancel is not None:
            self._qr_cancel.set()
            self._qr_cancel = None

    def start_qr(self) -> None:
        self.stop_qr()
        if self.ctx.runner is None:
            return
        session = connection.new_qr_session()
        self._qr_session = session
        self.qr.set_payload(session.payload)
        self.qr_state.setText(tr("connect.qr.waiting"))
        cancel = threading.Event()
        self._qr_cancel = cancel
        runner = self.ctx.runner

        def done(steps) -> None:
            if cancel.is_set() or self._qr_session is not session:
                return
            pair_step, connect_step = steps
            if pair_step.outcome is Outcome.NOT_FOUND:
                self.qr_state.setText(tr("connect.qr.expired"))
                return
            self.qr_state.setText("")
            self._finish(pair_step, connect_step)

        self.ctx.tasks.submit(
            lambda: connection.qr_pair_and_connect(runner, session, timeout=180, cancelled=cancel.is_set),
            done,
            self._failed,
        )

    # -- by address -----------------------------------------------------------
    def connect_address(self) -> None:
        if self._busy or self.ctx.runner is None:
            return
        try:
            host, port = validate.split_endpoint(self.address_edit.text(), connection.LEGACY_PORT)
        except validate.ValidationError as err:
            self._set_status(self._validation_message(err), "error")
            return
        runner = self.ctx.runner
        self._set_busy(True)
        self._set_status(tr("connect.address.working", endpoint=validate.endpoint(host, port)))
        self.ctx.tasks.submit(lambda: connection.connect(runner, host, port), lambda step: self._finish(None, step), self._failed)

    # -- found on the network -------------------------------------------------
    def discover(self) -> None:
        if self.ctx.runner is None:
            return
        runner = self.ctx.runner
        self.found_refresh.setEnabled(False)
        self.found_list.clear()
        placeholder = QListWidgetItem(tr("connect.found.searching"))
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.found_list.addItem(placeholder)

        def done(services: list[mdns.MdnsService]) -> None:
            self.found_refresh.setEnabled(not self._busy)
            self.found_list.clear()
            useful = [s for s in services if s.kind is not mdns.ServiceKind.OTHER]
            if not useful:
                empty = QListWidgetItem(tr("connect.found.none"))
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self.found_list.addItem(empty)
            for service in useful:
                text = tr(f"connect.found.kind.{service.kind.value}", name=service.name, address=validate.endpoint(service.host, service.port))
                item = QListWidgetItem(icons.icon("wifi", self.ctx.palette.text), text)
                item.setData(Qt.ItemDataRole.UserRole, service)
                self.found_list.addItem(item)
            self._update_found_button()

        self.ctx.tasks.submit(lambda: mdns.discover(runner, log=True), done, self._failed)

    def _update_found_button(self) -> None:
        item = self.found_list.currentItem()
        service: mdns.MdnsService | None = item.data(Qt.ItemDataRole.UserRole) if item else None
        if service is None:
            self.found_use.setText(tr("connect.found.use"))
            self.found_use.setEnabled(False)
            return
        key = "connect.found.pair" if service.kind is mdns.ServiceKind.PAIRING else "connect.found.use"
        self.found_use.setText(tr(key))
        self.found_use.setEnabled(not self._busy)

    def use_found(self) -> None:
        item = self.found_list.currentItem()
        service: mdns.MdnsService | None = item.data(Qt.ItemDataRole.UserRole) if item else None
        if service is None or self.ctx.runner is None or self._busy:
            return
        if service.kind is mdns.ServiceKind.PAIRING:
            self.prefill_pairing(service.host, service.port)
            return
        runner = self.ctx.runner
        self._set_busy(True)
        self._set_status(tr("connect.address.working", endpoint=validate.endpoint(service.host, service.port)))
        self.ctx.tasks.submit(lambda: connection.connect(runner, service.host, service.port), lambda step: self._finish(None, step), self._failed)

    # -- lifecycle ------------------------------------------------------------
    def done(self, result: int) -> None:  # noqa: D401 (Qt API)
        self.stop_qr()
        super().done(result)
