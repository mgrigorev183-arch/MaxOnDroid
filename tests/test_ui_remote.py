"""Stage 3 in the window: Remote tab and Screen tab."""

import base64
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from maxondroid.core.screen import Scrcpy  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

TV = "192.168.1.40:5555"
TV_KEY = "28041SKV0123"
TV_INFO = fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV, "Телевизор в зале")
DEVICES = "List of devices attached\n192.168.1.40:5555      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5\n\n"
FAKE_SCRCPY = Path(__file__).with_name("fake_scrcpy.py")


def png_bytes() -> bytes:
    image = QImage(160, 90, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def win(qtbot, fake_adb, tmp_path, monkeypatch):
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": DEVICES},
        {"args": ["-s", TV, "exec-out", "screencap", "-p"], "stdout_b64": base64.b64encode(png_bytes()).decode()},
        {"args": ["-s", TV, "shell", "*"], "stdout": TV_INFO},
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
    w.resize(1180, 820)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 1 and w.views[0].online, timeout=10000)
    w.scrcpy_log = tmp_path / "scrcpy.jsonl"
    yield w
    w.screen.shutdown()
    w.timer.stop()
    w.ctx.tasks.shutdown()


def key_calls(fake_adb):
    return [c[3] for c in fake_adb.calls() if len(c) > 3 and c[3].startswith("input ")]


def test_remote_buttons_send_keys_in_order(win, qtbot, fake_adb):
    win.tabs.setCurrentWidget(win.remote)
    tab = win.remote
    assert tab.stack.currentIndex() == 1
    for key in ("up", "up", "right", "ok", "back"):
        QTest.mouseClick(tab.buttons[key], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(key_calls(fake_adb)) == 5, timeout=10000)
    assert key_calls(fake_adb) == [
        "input keyevent KEYCODE_DPAD_UP",
        "input keyevent KEYCODE_DPAD_UP",
        "input keyevent KEYCODE_DPAD_RIGHT",
        "input keyevent KEYCODE_DPAD_CENTER",
        "input keyevent KEYCODE_BACK",
    ]
    qtbot.waitUntil(lambda: tab.status.text() == "Нажато: Назад", timeout=5000)
    entry = next(e for e in win.ctx.journal.entries if "KEYCODE_BACK" in e.command)
    assert entry.token == 1


def test_long_press(win, qtbot, fake_adb):
    win.tabs.setCurrentWidget(win.remote)
    button = win.remote.buttons["home"]
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    qtbot.wait(800)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: key_calls(fake_adb) == ["input keyevent --longpress KEYCODE_HOME"], timeout=5000)


def test_keyboard_shortcuts_only_when_pad_has_focus(win, qtbot, fake_adb):
    win.tabs.setCurrentWidget(win.remote)
    pad = win.remote.pad
    win.activateWindow()
    pad.setFocus()
    qtbot.waitUntil(pad.hasFocus, timeout=3000)
    assert "Клавиатура управляет устройством" in win.remote.hint.text()
    for key in (Qt.Key.Key_Down, Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_PageUp):
        QTest.keyClick(pad, key)
    QTest.keyClick(pad, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier)  # not a remote key
    qtbot.waitUntil(lambda: len(key_calls(fake_adb)) == 4, timeout=5000)
    assert key_calls(fake_adb) == [
        "input keyevent KEYCODE_DPAD_DOWN",
        "input keyevent KEYCODE_BACK",
        "input keyevent KEYCODE_MEDIA_PLAY_PAUSE",
        "input keyevent KEYCODE_CHANNEL_UP",
    ]
    from PySide6.QtGui import QKeyEvent

    for key in (Qt.Key.Key_Return, Qt.Key.Key_Up):
        for repeat in range(3):  # a held key: one press, then auto-repeats
            QApplication.sendEvent(pad, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, "", repeat > 0))
    qtbot.waitUntil(lambda: len(key_calls(fake_adb)) == 8, timeout=5000)
    assert key_calls(fake_adb)[4:] == ["input keyevent KEYCODE_DPAD_CENTER"] + ["input keyevent KEYCODE_DPAD_UP"] * 3  # Enter once, Up three times
    win.remote.text.setFocus()
    QTest.keyClick(win.remote.text, Qt.Key.Key_Down)  # typing in the text field is not a remote key
    qtbot.wait(300)
    assert len(key_calls(fake_adb)) == 8


def test_text_input(win, qtbot, fake_adb):
    win.tabs.setCurrentWidget(win.remote)
    tab = win.remote
    tab.text.setText("Привет")
    tab.send_text()
    assert "латиницу" in tab.status.text() and "Привет" in tab.status.text()
    tab.text.setText("hello world")
    tab.send_text()
    qtbot.waitUntil(lambda: tab.status.text() == "Текст отправлен.", timeout=5000)
    assert "input text hello%sworld" in key_calls(fake_adb)
    assert tab.text.text() == ""


def test_screen_tab_without_scrcpy_explains(win, qtbot, tmp_path):
    win.ctx.settings.settings.scrcpy_path = str(tmp_path / "nowhere" / "scrcpy.exe")
    win.screen.setup_tool()
    win.tabs.setCurrentWidget(win.screen)
    banner = win.screen.tool_banner
    assert banner.isVisible() and banner.title.text() == "Не найден scrcpy"
    assert "github.com/Genymobile/scrcpy/releases" in banner.body.text()
    assert banner.button.text() == "Скачать scrcpy" and banner.button2.text() == "Указать путь"
    assert not win.screen.open_button.isEnabled()
    assert win.screen.shot_button.isEnabled()  # screenshots need only adb


def use_fake_scrcpy(win):
    tool = Scrcpy(str(FAKE_SCRCPY), win.ctx.runner.executable, [sys.executable, str(FAKE_SCRCPY)])
    win.screen.use_tool(tool)
    return tool


def scrcpy_starts(win):
    if not win.scrcpy_log.exists():
        return []
    return [json.loads(line) for line in win.scrcpy_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_open_and_close_screen(win, qtbot):
    tool = use_fake_scrcpy(win)
    win.tabs.setCurrentWidget(win.screen)
    tab = win.screen
    tab.preset_speed.setChecked(True)
    assert tab.size.currentData() == 1280 and tab.bit_rate.value() == 4 and tab.fps.currentData() == 30
    assert win.ctx.settings.settings.screen_preset == "speed"
    tab.open_button.click()
    qtbot.waitUntil(lambda: bool(scrcpy_starts(win)), timeout=10000)
    argv = scrcpy_starts(win)[0]["argv"]
    assert argv[:2] == [f"--serial={TV}", "--window-title=01 Телевизор в зале"]
    assert "--max-size=1280" in argv and "--video-bit-rate=4M" in argv and "--max-fps=30" in argv
    qtbot.waitUntil(lambda: tab.mirror_state.text().startswith("Окно открыто"), timeout=5000)
    assert not tab.open_button.isEnabled() and tab.close_button.isEnabled()
    note = next(e for e in win.ctx.journal.entries if "fake_scrcpy.py --serial=" in e.command)
    assert note.token == 1
    tab.close_button.click()
    assert not tool.get(TV_KEY).running
    qtbot.waitUntil(lambda: tab.open_button.isEnabled(), timeout=5000)


def test_record_and_screenshot(win, qtbot, tmp_path):
    use_fake_scrcpy(win)
    win.tabs.setCurrentWidget(win.screen)
    tab = win.screen
    tab.record_button.click()
    qtbot.waitUntil(lambda: tab.record_button.text() == "Остановить запись", timeout=5000)
    qtbot.waitUntil(lambda: any(p.suffix == ".mkv" for p in (tmp_path / "captures").glob("*")), timeout=10000)
    tab.record_button.click()
    qtbot.waitUntil(lambda: tab.capture_state.text().startswith("Запись сохранена"), timeout=5000)
    assert "Телевизор в зале запись" in tab.capture_state.text()

    tab.shot_button.click()
    qtbot.waitUntil(lambda: tab.capture_state.text().startswith("Сохранено"), timeout=5000)
    shot = tab.last_shot
    assert shot.suffix == ".png" and shot.parent == tmp_path / "captures"
    assert shot.read_bytes().startswith(b"\x89PNG")
    assert not tab.preview.pixmap().isNull() and tab.copy_button.isEnabled()
    tab.copy_screenshot()
    assert not QApplication.clipboard().image().isNull()


def test_offline_device(win):
    from dataclasses import replace

    from maxondroid.core.devices import State

    view = replace(win.views[0], state=State.DISCONNECTED, serial=None)
    for tab in (win.remote, win.screen):
        tab.set_device(view)
        assert tab.stack.currentIndex() == 0


def test_stage3_screenshots(win, qtbot):
    import os

    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("SCREENSHOT_DIR not set")
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    use_fake_scrcpy(win)
    for code in ("light", "dark"):
        win._set_theme(code)
        win.tabs.setCurrentWidget(win.remote)
        win.remote.pad.setFocus()
        qtbot.wait(150)
        win.grab().save(str(out / f"stage3-remote-{code}.png"))
        win.tabs.setCurrentWidget(win.screen)
        win.screen.advanced_toggle.setChecked(True)
        qtbot.wait(150)
        win.grab().save(str(out / f"stage3-screen-{code}.png"))
    win._set_theme("light")
