"""Screen tab fixes: restart on change, options per device, physical keyboard, fps, bit rate cap."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from maxondroid.core.screen import Scrcpy  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

FAKE_SCRCPY = Path(__file__).with_name("fake_scrcpy.py")
TV = "192.168.1.40:5555"
TV_KEY = "28041SKV0123"
PHONE = "R58M12ABCDE"
DEVICES = (
    "List of devices attached\n"
    f"{PHONE}\tdevice usb:1-1 product:beyond1 model:SM_G973F device:beyond1 transport_id:3\n"
    f"{TV}      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5\n\n"
)
KEYBOARD_SETTINGS = "am start -a android.settings.HARD_KEYBOARD_SETTINGS"


@pytest.fixture
def win(qtbot, fake_adb, tmp_path, monkeypatch):
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": DEVICES},
        {"args": ["-s", PHONE, "shell", KEYBOARD_SETTINGS], "stdout": "Starting: Intent { act=android.settings.HARD_KEYBOARD_SETTINGS }\n"},
        {"args": ["-s", TV, "shell", "*"], "stdout": fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV, "Телевизор в зале")},
        {"args": ["-s", PHONE, "shell", "*"], "stdout": fx.info_output(fx.PHONE_PROPS, fx.PHONE_BATTERY, fx.FEATURES_PHONE)},
    ])
    monkeypatch.setenv("FAKE_SCRCPY_LOG", str(tmp_path / "scrcpy.jsonl"))
    monkeypatch.setenv("FAKE_SCRCPY_MODE", "run")
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w._set_language("ru")
    w._set_theme("light")
    w.ctx.settings.settings.auto_reconnect = False
    w.ctx.settings.settings.capture_dir = str(tmp_path / "captures")
    w.resize(1180, 860)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 2 and all(v.online for v in w.views), timeout=10000)
    w.scrcpy_log = tmp_path / "scrcpy.jsonl"
    tool = Scrcpy(str(FAKE_SCRCPY), w.ctx.runner.executable, [sys.executable, str(FAKE_SCRCPY)])
    w.screen.use_tool(tool)
    w.tool = tool
    w.tabs.setCurrentWidget(w.screen)
    w.screen.advanced_toggle.setChecked(True)
    yield w
    w.screen.shutdown()
    w.timer.stop()
    w.ctx.tasks.shutdown()


def starts(win):
    if not win.scrcpy_log.exists():
        return []
    return [json.loads(line)["argv"] for line in win.scrcpy_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def select(win, qtbot, key):
    win.device_list.select_key(key)
    qtbot.waitUntil(lambda: win.screen.view is not None and win.screen.view.key == key, timeout=5000)


def test_changing_an_option_reopens_the_window(win, qtbot):
    select(win, qtbot, PHONE)
    tab = win.screen
    tab.size.setCurrentIndex(tab.size.findData(0))
    tab.open_button.click()
    qtbot.waitUntil(lambda: len(starts(win)) == 1, timeout=10000)
    first = win.tool.get(PHONE)
    assert not any(a.startswith("--max-size") for a in starts(win)[0])
    tab.size.setCurrentIndex(tab.size.findData(1024))
    tab.bit_rate.setValue(6)  # a second change within the delay: one restart, with both
    qtbot.waitUntil(lambda: len(starts(win)) == 2, timeout=10000)
    assert "--max-size=1024" in starts(win)[1] and "--video-bit-rate=6M" in starts(win)[1]
    assert not first.running and win.tool.get(PHONE).running
    qtbot.waitUntil(lambda: tab.mirror_state.text().startswith("Окно открыто"), timeout=8000)
    qtbot.wait(1000)
    assert len(starts(win)) == 2  # no extra restarts


def test_recording_is_not_restarted(win, qtbot):
    select(win, qtbot, PHONE)
    tab = win.screen
    tab.record_button.click()
    qtbot.waitUntil(lambda: len(starts(win)) == 1, timeout=10000)
    tab.bit_rate.setValue(5)
    qtbot.waitUntil(lambda: tab.apply_note.isVisible(), timeout=3000)
    assert "следующей" in tab.apply_note.text()
    qtbot.wait(1200)
    assert len(starts(win)) == 1
    tab.record_button.click()
    qtbot.waitUntil(lambda: not win.tool.get("rec:" + PHONE).running, timeout=8000)


def test_options_are_kept_per_device_and_tv_starts_light(win, qtbot):
    tab = win.screen
    select(win, qtbot, TV_KEY)
    assert tab.preset_speed.isChecked() and tab.size.currentData() == 1280 and tab.fps.currentData() == 30
    assert tab.tv_hint.isVisible() and "4K" in tab.tv_hint.text()
    select(win, qtbot, PHONE)
    assert not tab.tv_hint.isVisible()
    tab.preset_quality.setChecked(True)
    tab.bit_rate.setValue(12)
    select(win, qtbot, TV_KEY)
    assert tab.bit_rate.value() == 4 and tab.preset_speed.isChecked()
    select(win, qtbot, PHONE)
    assert tab.bit_rate.value() == 12 and tab.size.currentData() == 0
    saved = win.ctx.settings.settings.screen_devices
    assert saved[PHONE]["bit_rate_mbps"] == 12
    reloaded = type(win.ctx.settings)(win.ctx.settings.path).settings.screen_devices
    assert reloaded[PHONE]["bit_rate_mbps"] == 12


def test_physical_keyboard_mode_and_layout_settings(win, qtbot, fake_adb):
    select(win, qtbot, PHONE)
    tab = win.screen
    assert tab.keyboard_uhid.isEnabled()
    tab.keyboard_uhid.setChecked(True)
    tab.open_button.click()
    qtbot.waitUntil(lambda: len(starts(win)) == 1, timeout=10000)
    assert "--keyboard=uhid" in starts(win)[0]
    tab.keyboard_settings.click()
    qtbot.waitUntil(lambda: ["-s", PHONE, "shell", KEYBOARD_SETTINGS] in fake_adb.calls(), timeout=5000)
    # visible in the journal (recorded when adb finishes, a moment after it starts)
    qtbot.waitUntil(lambda: any(KEYBOARD_SETTINGS in e.command for e in win.ctx.journal.entries), timeout=5000)
    assert "Ctrl+Пробел" in tab.keyboard_hint.text()
    # scrcpy older than 2.4 has no --keyboard: the option is off limits
    win.screen.status_.version = (2, 3, 0)
    tab._update_state()
    assert not tab.keyboard_uhid.isEnabled() and "2.4" in tab.keyboard_uhid.toolTip()


def test_frames_per_second_are_shown(win, qtbot):
    select(win, qtbot, PHONE)
    tab = win.screen
    tab.open_button.click()
    qtbot.waitUntil(lambda: "кадров/с" in tab.mirror_state.text(), timeout=10000)
    assert "59 кадров/с" in tab.mirror_state.text() or "пропущено 2" in tab.mirror_state.text()


def test_bit_rate_stops_at_50_with_guidance(win, qtbot):
    tab = win.screen
    assert tab.bit_rate.maximum() == 50
    tab.bit_rate.setValue(90)
    assert tab.bit_rate.value() == 50
    assert "USB" in tab.bit_rate_hint.text() and "50" in tab.bit_rate_hint.text()
    assert "Alt+O" in tab.turn_off.toolTip()


def test_the_manager_keeps_serials_of_open_windows(win, qtbot):
    select(win, qtbot, PHONE)
    win.screen.open_button.click()
    qtbot.waitUntil(lambda: PHONE in win.screen.serials_in_use(), timeout=10000)
