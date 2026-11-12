"""Screen tab: open the device screen with scrcpy, record it, take screenshots."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from maxondroid.core import screen
from maxondroid.core.manager import DeviceView
from maxondroid.core.screen import Scrcpy, ScrcpyError, ScrcpyOptions
from maxondroid.i18n import tr
from maxondroid.ui import icons, theme
from maxondroid.ui.common import Banner, Placeholder, label, open_folder
from maxondroid.ui.context import AppContext
from maxondroid.ui.tokens import token_label

SCRCPY_RELEASES = "https://github.com/Genymobile/scrcpy/releases"
SIZES = (0, 1920, 1280, 1024, 800)
RESTART_DELAY_MS = 700
FPS = (0, 60, 30, 15)


@dataclass
class ScrcpyStatus:
    tool: Scrcpy | None = None
    error: ScrcpyError | None = None
    version: tuple[int, int, int] | None = None
    checking: bool = False


def _rec_key(key: str) -> str:
    return "rec:" + key


class ScreenTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.view: DeviceView | None = None
        self.status_ = ScrcpyStatus()
        self.last_shot: Path | None = None
        self._busy_shot = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.placeholder = Placeholder()
        self.stack.addWidget(self.placeholder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # scroll, never cut off
        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        self.tool_banner = Banner("error")
        layout.addWidget(self.tool_banner)

        # -- mirror -----------------------------------------------------------------
        self.mirror_card = QFrame()
        self.mirror_card.setObjectName("Card")
        mirror = QVBoxLayout(self.mirror_card)
        mirror.setContentsMargins(16, 14, 16, 16)
        mirror.setSpacing(10)
        self.mirror_title = label("", role="section")
        self.mirror_title.setFont(theme.token_font(11.5))
        mirror.addWidget(self.mirror_title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.open_button = QPushButton()
        self.open_button.setObjectName("Primary")
        self.open_button.clicked.connect(self.open_screen)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(lambda: self._stop(self.view.key if self.view else ""))
        row.addWidget(self.open_button)
        row.addWidget(self.close_button)
        row.addSpacing(16)
        self.preset_quality = QRadioButton()
        self.preset_speed = QRadioButton()
        self.preset_group = QButtonGroup(self)
        self.preset_group.addButton(self.preset_quality)
        self.preset_group.addButton(self.preset_speed)
        self.preset_quality.toggled.connect(lambda on: on and self._apply_preset("quality"))
        self.preset_speed.toggled.connect(lambda on: on and self._apply_preset("speed"))
        row.addWidget(self.preset_quality)
        row.addWidget(self.preset_speed)
        row.addStretch(1)
        mirror.addLayout(row)
        self.mirror_state = label("", role="muted", wrap=True, selectable=True)
        mirror.addWidget(self.mirror_state)
        self.apply_note = label("", role="muted", wrap=True)
        self.apply_note.hide()
        mirror.addWidget(self.apply_note)
        self.tv_hint = label("", role="muted", wrap=True)
        self.tv_hint.hide()
        mirror.addWidget(self.tv_hint)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setAutoRaise(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        mirror.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(4, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.size = QComboBox()
        self.bit_rate = QSpinBox()
        self.bit_rate.setRange(1, screen.MAX_BIT_RATE)
        self.bit_rate.setSuffix(" Mbit/s")
        self.fps = QComboBox()
        self.audio = QCheckBox()
        self.turn_off = QCheckBox()
        self.on_top = QCheckBox()
        self.stay_awake = QCheckBox()
        self.view_only = QCheckBox()
        self.keyboard_uhid = QCheckBox()
        self.keyboard_settings = QPushButton()
        self.keyboard_settings.clicked.connect(self.open_keyboard_settings)
        self.keyboard_hint = label("", role="muted", wrap=True)
        self.bit_rate_hint = label("", role="muted", wrap=True)
        self.form_labels = [label(), label(), label()]
        form.addRow(self.form_labels[0], self.size)
        form.addRow(self.form_labels[1], self.bit_rate)
        form.addRow(label(""), self.bit_rate_hint)
        form.addRow(self.form_labels[2], self.fps)
        for box in (self.audio, self.turn_off, self.on_top, self.stay_awake, self.view_only):
            form.addRow(label(""), box)
        # the button sits under the option, not beside it: side by side they made the tab wider
        # than a half-screen window and the right edge was cut off
        form.addRow(label(""), self.keyboard_uhid)
        keyboard_row = QHBoxLayout()
        keyboard_row.addWidget(self.keyboard_settings)
        keyboard_row.addStretch(1)
        form.addRow(label(""), keyboard_row)
        form.addRow(label(""), self.keyboard_hint)
        for widget in (self.size, self.fps):
            widget.currentIndexChanged.connect(self._save_options)
        self.bit_rate.valueChanged.connect(self._save_options)
        for box in (self.audio, self.turn_off, self.on_top, self.stay_awake, self.view_only, self.keyboard_uhid):
            box.toggled.connect(self._save_options)
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(RESTART_DELAY_MS)  # spin boxes change on every click: wait for the last one
        self._restart_timer.timeout.connect(self._restart_mirror)
        self._restarting: str | None = None
        self._finishing: set[str] = set()  # recordings being closed: scrcpy is writing the end of the file
        self.advanced.hide()
        mirror.addWidget(self.advanced)
        layout.addWidget(self.mirror_card)

        # -- captures ------------------------------------------------------------------
        self.capture_card = QFrame()
        self.capture_card.setObjectName("Card")
        cap = QVBoxLayout(self.capture_card)
        cap.setContentsMargins(16, 14, 16, 16)
        cap.setSpacing(10)
        self.capture_title = label("", role="section")
        self.capture_title.setFont(theme.token_font(11.5))
        cap.addWidget(self.capture_title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.shot_button = QPushButton()
        self.shot_button.clicked.connect(self.take_screenshot)
        self.record_button = QPushButton()
        self.record_button.clicked.connect(self.toggle_recording)
        self.record_format = QComboBox()
        self.record_format.currentIndexChanged.connect(self._save_format)
        row.addWidget(self.shot_button)
        row.addWidget(self.record_button)
        row.addWidget(self.record_format)
        row.addStretch(1)
        cap.addLayout(row)
        self.capture_state = label("", role="muted", wrap=True, selectable=True)
        cap.addWidget(self.capture_state)
        self.folder_label = label("", role="muted", wrap=True, selectable=True)
        cap.addWidget(self.folder_label)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_change = QPushButton()
        self.folder_change.clicked.connect(self.pick_folder)
        self.folder_open = QPushButton()
        self.folder_open.clicked.connect(lambda: open_folder(self.capture_dir(), self))
        folder_row.addWidget(self.folder_change)
        folder_row.addWidget(self.folder_open)
        folder_row.addStretch(1)
        cap.addLayout(folder_row)
        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        self.preview = QLabel()
        self.preview.setFixedSize(320, 200)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("Preview")
        preview_row.addWidget(self.preview)
        preview_buttons = QVBoxLayout()
        self.copy_button = QPushButton()
        self.copy_button.clicked.connect(self.copy_screenshot)
        self.open_file_button = QPushButton()
        self.open_file_button.clicked.connect(lambda: self.last_shot and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_shot))))
        preview_buttons.addWidget(self.copy_button)
        preview_buttons.addWidget(self.open_file_button)
        preview_buttons.addStretch(1)
        preview_row.addLayout(preview_buttons)
        preview_row.addStretch(1)
        cap.addLayout(preview_row)
        layout.addWidget(self.capture_card)

        self.drm_note = label("", role="muted", wrap=True)
        layout.addWidget(self.drm_note)
        layout.addStretch(1)
        self.stack.addWidget(scroll)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_state)
        self._tick.start()
        self._loading = False
        self.retranslate()

    # -- scrcpy --------------------------------------------------------------------
    def setup_tool(self) -> None:
        """Find scrcpy and check its version in the background (after adb is known)."""
        settings = self.ctx.settings.settings
        adb = self.ctx.runner.executable if self.ctx.runner else None
        if self.status_.tool is not None:
            self.status_.tool.stop_all()
        path = screen.find_scrcpy(settings.scrcpy_path or None, adb)
        self.status_ = ScrcpyStatus()
        if path is None:
            self.status_.error = ScrcpyError("missing")
            self.render()
            return
        tool = Scrcpy(path, adb)
        tool.listeners.append(self._journal_start)
        self.status_.tool = tool
        self.status_.checking = True
        self.render()

        def done(version) -> None:
            self.status_.checking = False
            self.status_.version = version
            self.render()

        def failed(exc: BaseException) -> None:
            self.status_.checking = False
            self.status_.error = exc if isinstance(exc, ScrcpyError) else ScrcpyError("broken", str(exc))
            self.render()

        self.ctx.tasks.submit(tool.check, done, failed)

    def use_tool(self, tool: Scrcpy) -> None:
        """Tests and future front ends hand over a ready Scrcpy."""
        tool.listeners.append(self._journal_start)
        self.status_ = ScrcpyStatus(tool=tool, version=(3, 0, 0))
        self.render()

    def _journal_start(self, command: str) -> None:
        serial = self.view.serial if self.view else None
        self.ctx.journal.note(command, serial)

    def options(self) -> ScrcpyOptions:
        return ScrcpyOptions(
            preset="speed" if self.preset_speed.isChecked() else "quality",
            max_size=self.size.currentData() or 0,
            bit_rate_mbps=self.bit_rate.value(),
            max_fps=self.fps.currentData() or 0,
            audio=self.audio.isChecked(),
            turn_screen_off=self.turn_off.isChecked(),
            always_on_top=self.on_top.isChecked(),
            stay_awake=self.stay_awake.isChecked(),
            view_only=self.view_only.isChecked(),
            keyboard="uhid" if self.keyboard_uhid.isChecked() else "sdk",
        ).normalized()

    def last_used_options(self) -> ScrcpyOptions:
        s = self.ctx.settings.settings
        return ScrcpyOptions(
            preset=s.screen_preset, max_size=s.screen_max_size, bit_rate_mbps=s.screen_bit_rate, max_fps=s.screen_max_fps,
            audio=s.screen_audio, turn_screen_off=s.screen_turn_off, always_on_top=s.screen_on_top,
            stay_awake=s.screen_stay_awake, view_only=s.screen_view_only, keyboard=s.screen_keyboard,
        ).normalized()

    def options_for(self, view: DeviceView | None) -> ScrcpyOptions:
        """The options saved for this device, or a starting point for a device seen for the first time."""
        last = self.last_used_options()
        if view is None:
            return last
        saved = self.ctx.settings.settings.screen_devices.get(view.key)
        if saved is not None:
            return ScrcpyOptions.from_dict(saved, last)
        return screen.default_options(view.kind.value, last)

    def _show_options(self, opts: ScrcpyOptions) -> None:
        self._loading = True
        try:
            (self.preset_speed if opts.preset == "speed" else self.preset_quality).setChecked(True)
            self.size.setCurrentIndex(max(0, self.size.findData(opts.max_size)))
            self.bit_rate.setValue(opts.bit_rate_mbps)
            self.fps.setCurrentIndex(max(0, self.fps.findData(opts.max_fps)))
            self.audio.setChecked(opts.audio)
            self.turn_off.setChecked(opts.turn_screen_off)
            self.on_top.setChecked(opts.always_on_top)
            self.stay_awake.setChecked(opts.stay_awake)
            self.view_only.setChecked(opts.view_only)
            self.keyboard_uhid.setChecked(opts.keyboard == "uhid")
        finally:
            self._loading = False

    def _apply_preset(self, preset: str) -> None:
        if self._loading:
            return
        opts = ScrcpyOptions.for_preset(preset, self.options())
        self._loading = True
        self.size.setCurrentIndex(max(0, self.size.findData(opts.max_size)))
        self.bit_rate.setValue(opts.bit_rate_mbps)
        self.fps.setCurrentIndex(max(0, self.fps.findData(opts.max_fps)))
        self._loading = False
        self._save_options()

    def _save_options(self, *_args) -> None:
        if self._loading:
            return
        s = self.ctx.settings.settings
        o = self.options()
        s.screen_preset, s.screen_max_size, s.screen_bit_rate, s.screen_max_fps = o.preset, o.max_size, o.bit_rate_mbps, o.max_fps
        s.screen_audio, s.screen_turn_off, s.screen_on_top = o.audio, o.turn_screen_off, o.always_on_top
        s.screen_stay_awake, s.screen_view_only, s.screen_keyboard = o.stay_awake, o.view_only, o.keyboard
        if self.view is not None:
            s.screen_devices.pop(self.view.key, None)
            s.screen_devices[self.view.key] = o.to_dict()  # most recent last: the oldest are dropped first
        try:
            self.ctx.settings.save()
        except OSError:
            pass
        self._options_changed()

    def _options_changed(self) -> None:
        """scrcpy reads its options only at start: reopen an open window, explain it for a recording."""
        view = self.view
        tool = self.status_.tool
        if view is None or tool is None:
            return
        mirror = tool.get(view.key)
        if mirror is not None and mirror.running:
            self._restart_timer.start()
        recording = tool.get(_rec_key(view.key))
        _say(self.apply_note, tr("screen.apply.next_recording") if recording is not None and recording.running else "")

    def _restart_mirror(self) -> None:
        view = self.view
        tool = self.status_.tool
        if view is None or tool is None or not view.online or self._restarting:
            return
        mirror = tool.get(view.key)
        if mirror is None or not mirror.running:
            return
        key, serial, options, title = view.key, view.serial, self.options(), self._title()
        self._restarting = key
        self._update_state()

        def done(_session) -> None:
            self._restarting = None
            self._update_state()

        def failed(exc: BaseException) -> None:
            self._restarting = None
            self.mirror_state.setText(tr("screen.state.failed", details=str(exc)))

        self.ctx.tasks.submit(lambda: tool.restart(key, serial, options, title), done, failed)

    def serials_in_use(self) -> set[str]:
        """adb serials of open scrcpy windows and recordings (the device manager must not drop them)."""
        tool = self.status_.tool
        return tool.running_serials() if tool is not None else set()

    def open_keyboard_settings(self) -> None:
        """Android's physical keyboard settings, where the layout for the scrcpy keyboard is chosen."""
        view = self.view
        runner = self.ctx.runner
        if view is None or not view.online or runner is None:
            return
        serial = view.serial
        self.ctx.tasks.submit(
            lambda: runner.shell(serial, "am", "start", "-a", "android.settings.HARD_KEYBOARD_SETTINGS", timeout=15),
            lambda result: _say(self.keyboard_hint, tr("screen.keyboard.hint") if result.ok else tr("screen.keyboard.failed", output=result.output or "—")),
            lambda exc: _say(self.keyboard_hint, tr("screen.keyboard.failed", output=str(exc))),
        )

    def _toggle_advanced(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.advanced_toggle.setIcon(icons.icon("show" if shown else "chevron", self.ctx.palette.text))

    # -- language and theme ------------------------------------------------------
    def retranslate(self) -> None:
        self.mirror_title.setText(tr("screen.mirror.title"))
        self.open_button.setText(tr("screen.open"))
        self.close_button.setText(tr("screen.close"))
        self.preset_quality.setText(tr("screen.preset.quality"))
        self.preset_speed.setText(tr("screen.preset.speed"))
        self.preset_quality.setToolTip(tr("screen.preset.quality.tip"))
        self.preset_speed.setToolTip(tr("screen.preset.speed.tip"))
        self.advanced_toggle.setText(tr("screen.advanced"))
        for lbl, key in zip(self.form_labels, ("size", "bit_rate", "fps"), strict=True):
            lbl.setText(tr(f"screen.option.{key}"))
        first_time = self.size.count() == 0
        self._loading = True
        for combo, values, key in ((self.size, SIZES, "size"), (self.fps, FPS, "fps")):
            current = combo.currentData()
            combo.clear()
            for value in values:
                combo.addItem(tr(f"screen.{key}.any") if value == 0 else tr(f"screen.{key}.value", value=value), value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        self._loading = False
        if first_time:
            self._show_options(self.options_for(self.view))
        self.bit_rate.setSuffix(" " + tr("screen.mbps"))
        self.audio.setText(tr("screen.option.audio"))
        self.turn_off.setText(tr("screen.option.turn_off"))
        self.on_top.setText(tr("screen.option.on_top"))
        self.stay_awake.setText(tr("screen.option.stay_awake"))
        self.view_only.setText(tr("screen.option.view_only"))
        self.turn_off.setToolTip(tr("screen.option.turn_off.tip"))
        self.keyboard_uhid.setText(tr("screen.option.keyboard"))
        self.keyboard_uhid.setToolTip(tr("screen.option.keyboard.tip"))
        self.keyboard_settings.setText(tr("screen.keyboard.settings"))
        self.keyboard_settings.setToolTip(tr("screen.keyboard.settings.tip"))
        _say(self.keyboard_hint, tr("screen.keyboard.hint"))
        self.bit_rate_hint.setText(tr("screen.bit_rate.hint", max=screen.MAX_BIT_RATE))
        self.tv_hint.setText(tr("screen.tv_hint"))
        self.capture_title.setText(tr("screen.capture.title"))
        self.shot_button.setText(tr("screen.screenshot"))
        current = self.record_format.currentData() or self.ctx.settings.settings.capture_format
        self.record_format.blockSignals(True)
        self.record_format.clear()
        self.record_format.addItem(tr("screen.format.mp4"), "mp4")
        self.record_format.addItem(tr("screen.format.mkv"), "mkv")
        self.record_format.setCurrentIndex(max(0, self.record_format.findData(current)))
        self.record_format.blockSignals(False)
        self.record_format.setToolTip(tr("screen.format.tip"))
        self.folder_change.setText(tr("screen.folder.change"))
        self.folder_open.setText(tr("screen.folder.open"))
        self.copy_button.setText(tr("screen.copy"))
        self.open_file_button.setText(tr("screen.open_file"))
        self.drm_note.setText(tr("screen.drm_note"))
        self.apply_palette()
        self.render()

    def apply_palette(self) -> None:
        p = self.ctx.palette
        self.open_button.setIcon(icons.icon("screen", p.brass_on))
        self.shot_button.setIcon(icons.icon("camera", p.text))
        self.record_button.setIcon(icons.icon("record", p.danger_text))
        self._toggle_advanced(self.advanced_toggle.isChecked())
        self.preview.setStyleSheet(f"background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: 6px; color: {p.text_muted};")
        self.render()

    # -- device and state -----------------------------------------------------------
    def set_device(self, view: DeviceView | None) -> None:
        new_device = (self.view is None) != (view is None) or (view is not None and self.view is not None and self.view.key != view.key)
        changed = new_device or (view is not None and self.view is not None and self.view.online != view.online)
        self.view = view
        if new_device:
            self._restart_timer.stop()
            self._show_options(self.options_for(view))
            _say(self.apply_note, "")
            self.tv_hint.setVisible(view is not None and view.kind.value == "tv")
        if changed:
            _say(self.capture_state, "")
            self.render()

    def capture_dir(self) -> Path:
        custom = self.ctx.settings.settings.capture_dir
        return Path(custom) if custom else screen.default_capture_dir()

    def render(self) -> None:
        view = self.view
        if view is None or not view.online:
            self.placeholder.set_message(tr("screen.offline"))
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self._render_tool_banner()
        self.folder_label.setText(tr("screen.folder", path=str(self.capture_dir())))
        self._render_preview()
        self._update_state()

    def _render_tool_banner(self) -> None:
        st = self.status_
        p = self.ctx.palette
        if st.error is not None:
            code = st.error.code
            body = tr(f"screen.tool.{code}.body", detail=st.error.detail, url=SCRCPY_RELEASES)
            self.tool_banner.show_message(
                "error", tr(f"screen.tool.{code}.title"), body, tr("screen.tool.download"),
                lambda: QDesktopServices.openUrl(QUrl(SCRCPY_RELEASES)), p, tr("adb.missing.action"), self.ctx.open_settings,
            )
        else:
            self.tool_banner.hide()

    def _ready(self) -> bool:
        return self.status_.tool is not None and self.status_.error is None and not self.status_.checking

    def _update_state(self) -> None:
        view = self.view
        if view is None or not view.online or self.stack.currentIndex() != 1:
            return
        tool = self.status_.tool
        session = tool.get(view.key) if tool else None
        recording = tool.get(_rec_key(view.key)) if tool else None
        ready = self._ready()
        running = bool(session and session.running)
        self.open_button.setEnabled(ready and not running and self._restarting != view.key)
        self.close_button.setEnabled(running and self._restarting != view.key)
        version = self.status_.version
        keyboard_ok = version is None or version[:2] >= screen.KEYBOARD_VERSION
        self.keyboard_uhid.setEnabled(keyboard_ok and not self.view_only.isChecked())
        self.keyboard_settings.setEnabled(True)
        if not keyboard_ok:
            self.keyboard_uhid.setToolTip(tr("screen.option.keyboard.too_old", version=".".join(map(str, screen.KEYBOARD_VERSION))))
        if self.status_.checking:
            self.mirror_state.setText(tr("screen.tool.checking"))
        elif self._restarting == view.key:
            self.mirror_state.setText(tr("screen.state.restarting"))
        elif running:
            fps = session.fps
            if fps is None:
                self.mirror_state.setText(tr("screen.state.open", elapsed=_elapsed(session.started)))
            elif fps[1]:
                self.mirror_state.setText(tr("screen.state.open_fps_skipped", elapsed=_elapsed(session.started), fps=fps[0], skipped=fps[1]))
            else:
                self.mirror_state.setText(tr("screen.state.open_fps", elapsed=_elapsed(session.started), fps=fps[0]))
        elif session is not None and session.returncode not in (None, 0):
            self.mirror_state.setText(tr("screen.state.exited", code=session.returncode, output=session.tail() or "—"))
        elif self.status_.version:
            self.mirror_state.setText(tr("screen.state.ready", version=".".join(map(str, self.status_.version))))
        else:
            self.mirror_state.setText("")
        rec_running = bool(recording and recording.running)
        self.record_button.setText(tr("screen.record.stop") if rec_running else tr("screen.record.start"))
        self.record_button.setEnabled(ready or rec_running)
        self.shot_button.setEnabled(not self._busy_shot)
        rec_key = _rec_key(view.key)
        self.record_format.setEnabled(not rec_running)
        if rec_running and rec_key in self._finishing:
            self.record_button.setEnabled(False)
            _say(self.capture_state, tr("screen.record.finishing"))
        elif rec_running:
            _say(self.capture_state, tr("screen.record.running", elapsed=_elapsed(recording.started), path=str(recording.record)))
        elif recording is not None and recording.record and not recording.reported and rec_key not in self._finishing:
            recording.reported = True
            if recording.record.exists() and recording.graceful is False and recording.record.suffix.lower() == ".mp4":
                _say(self.capture_state, tr("screen.record.saved_forced", path=str(recording.record)))
            elif recording.record.exists():
                _say(self.capture_state, tr("screen.record.saved", path=str(recording.record)))
            else:
                _say(self.capture_state, tr("screen.record.failed", output=recording.tail() or "—"))

    # -- actions ---------------------------------------------------------------------
    def _title(self) -> str:
        view = self.view
        return f"{token_label(view.token)} {view.name}" if view else "MaxOnDroid"

    def open_screen(self) -> None:
        if self.view is None or not self.view.online or not self._ready():
            return
        try:
            self.status_.tool.start(self.view.key, self.view.serial, self.options(), self._title())
        except (ScrcpyError, OSError, ValueError) as exc:
            self.mirror_state.setText(tr("screen.state.failed", details=str(exc)))
            return
        self._update_state()

    def _stop(self, key: str) -> None:
        """Close a window or finish a recording in the background: scrcpy may take a moment to write the file."""
        tool = self.status_.tool
        if tool is None or not key:
            return
        if key == (self.view.key if self.view else None):
            self._restart_timer.stop()
        self._finishing.add(key)
        self._update_state()

        def finished(*_args) -> None:
            self._finishing.discard(key)
            self._update_state()

        self.ctx.tasks.submit(lambda: tool.stop(key), finished, finished)

    def _save_format(self, *_args) -> None:
        value = self.record_format.currentData()
        if value in ("mp4", "mkv") and value != self.ctx.settings.settings.capture_format:
            self.ctx.settings.settings.capture_format = value
            try:
                self.ctx.settings.save()
            except OSError:
                pass

    def toggle_recording(self) -> None:
        view = self.view
        tool = self.status_.tool
        if view is None or tool is None:
            return
        current = tool.get(_rec_key(view.key))
        if current is not None and current.running:
            self._stop(_rec_key(view.key))
            return
        if not self._ready():
            return
        target = self.capture_dir() / screen.capture_name(view.name, tr("screen.record.word"), self.ctx.settings.settings.capture_format)
        try:
            tool.start(_rec_key(view.key), view.serial, self.options(), self._title() + " — " + tr("screen.record.word"), record=target)
        except (ScrcpyError, OSError, ValueError) as exc:
            _say(self.capture_state, tr("screen.record.failed", output=str(exc)))
            return
        self._update_state()

    def take_screenshot(self) -> None:
        view = self.view
        runner = self.ctx.runner
        if view is None or not view.online or runner is None or self._busy_shot:
            return
        target = self.capture_dir() / screen.capture_name(view.name, tr("screen.screenshot.word"), "png")
        serial = view.serial
        self._busy_shot = True
        _say(self.capture_state, tr("screen.screenshot.working"))
        self._update_state()

        def done(path: Path) -> None:
            self._busy_shot = False
            self.last_shot = path
            _say(self.capture_state, tr("screen.screenshot.saved", path=str(path)))
            self._render_preview()
            self._update_state()

        def failed(exc: BaseException) -> None:
            self._busy_shot = False
            _say(self.capture_state, tr("screen.screenshot.failed", details=str(exc)))
            self._update_state()

        self.ctx.tasks.submit(lambda: screen.screenshot(runner, serial, target), done, failed)

    def _render_preview(self) -> None:
        has = self.last_shot is not None and self.last_shot.exists()
        self.copy_button.setEnabled(has)
        self.open_file_button.setEnabled(has)
        if not has:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(tr("screen.preview.empty"))
            return
        pixmap = QPixmap(str(self.last_shot))
        if pixmap.isNull():
            self.preview.setText(tr("screen.preview.empty"))
            return
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.preview.setAccessibleName(str(self.last_shot))

    def copy_screenshot(self) -> None:
        if self.last_shot and self.last_shot.exists():
            QGuiApplication.clipboard().setPixmap(QPixmap(str(self.last_shot)))
            _say(self.capture_state, tr("screen.copied"))

    def pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("screen.folder.change"), str(self.capture_dir()))
        if folder:
            self.ctx.settings.settings.capture_dir = folder
            try:
                self.ctx.settings.save()
            except OSError:
                pass
            self.render()

    def shutdown(self) -> None:
        if self.status_.tool is not None:
            self.status_.tool.stop_all()


def _elapsed(started: float) -> str:
    seconds = int(time.monotonic() - started)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _say(target: QLabel, text: str) -> None:
    """Set a status line and hide it while it has nothing to say (no empty gaps)."""
    target.setText(text)
    target.setVisible(bool(text))
