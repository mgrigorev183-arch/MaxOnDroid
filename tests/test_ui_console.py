"""Console tab: preview, both modes, streaming, stop, history, saved commands, journal."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QWidget  # noqa: E402

from maxondroid.core import paths  # noqa: E402
from maxondroid.core.console import ConsoleStore  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

PHONE = "R58M12ABCDE"
DEVICES = f"List of devices attached\n{PHONE}\tdevice usb:1-1 product:beyond1 model:SM_G973F device:beyond1 transport_id:3\n\n"
RULES = [
    {"args": ["devices", "-l"], "stdout": DEVICES},
    {"args": ["-s", PHONE, "shell", "ls -l /sdcard | grep D"], "stdout": "drwxrws--- 2 u0 DCIM\ndrwxrws--- 2 u0 Download\n"},
    {"args": ["-s", PHONE, "logcat"], "stream": [{"data": "11-13 01:00:00 I/Tag: hello\n", "sleep": 60}]},
    {"args": ["-s", PHONE, "getprop", "x"], "stdout": "", "stderr": "adb: unknown command getprop\n", "rc": 1},
    {"args": ["pair", "192.168.1.23:37159", "482913"], "stdout": "Successfully paired to 192.168.1.23:37159\n"},
    {"args": ["-s", PHONE, "shell", "*"], "stdout": fx.info_output(fx.PHONE_PROPS, fx.PHONE_BATTERY, fx.FEATURES_PHONE)},
]


@pytest.fixture
def win(qtbot, fake_adb):
    fake_adb.set_rules(RULES)
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w._set_language("ru")
    w._set_theme("light")
    w.ctx.settings.settings.auto_reconnect = False
    w.resize(1180, 820)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 1 and w.views[0].online, timeout=10000)
    w.tabs.setCurrentWidget(w.console)
    yield w
    w.console.stop()
    w.timer.stop()
    w.ctx.tasks.shutdown()


def run(win, qtbot, mode, text):
    tab = win.console
    (tab.mode_shell if mode == "shell" else tab.mode_adb).setChecked(True)
    tab.input.setText(text)
    tab.run_button.click()
    qtbot.waitUntil(lambda: tab.run is not None and not tab.run.running and "Готово" in tab.status.text(), timeout=10000)


def test_adb_mode_previews_runs_and_journals(win, qtbot):
    tab = win.console
    assert "devices -l" in tab.preview.text()  # an example while empty
    tab.mode_adb.setChecked(True)
    tab.input.setText("devices -l")
    assert tab.preview.text() == "Будет выполнено: adb devices -l"
    tab.input.setText("shell pm list packages -3")
    assert tab.preview.text() == f"Будет выполнено: adb -s {PHONE} shell pm list packages -3"
    run(win, qtbot, "adb", "devices -l")
    text = tab.output.toPlainText()
    assert "> adb devices -l" in text and PHONE in text
    assert "код 0" in tab.status.text()
    assert any(e.command == "adb devices -l" for e in win.ctx.journal.entries)


def test_shell_mode_sends_the_line_to_the_device(win, qtbot):
    run(win, qtbot, "shell", "ls -l /sdcard | grep D")
    text = win.console.output.toPlainText()
    assert f'> adb -s {PHONE} shell "ls -l /sdcard | grep D"' in text
    assert "DCIM" in text and "Download" in text


def test_errors_show_in_the_preview_and_block_running(win):
    tab = win.console
    tab.mode_adb.setChecked(True)
    tab.input.setText('install "C:\\a b.apk')
    assert "кавычка" in tab.preview.text() and not tab.run_button.isEnabled()
    tab.input.setText("shell")
    assert "Интерактивная" in tab.preview.text() and not tab.run_button.isEnabled()
    win.console.set_device(None)
    tab.mode_shell.setChecked(True)
    tab.input.setText("ls")
    assert "выберите устройство" in tab.preview.text() and not tab.run_button.isEnabled()


def test_failed_command_shows_its_exit_code(win, qtbot):
    run(win, qtbot, "adb", "getprop x")
    assert "код 1" in win.console.status.text()
    assert "unknown command" in win.console.output.toPlainText()


def test_stop_a_streaming_command(win, qtbot):
    tab = win.console
    tab.mode_adb.setChecked(True)
    tab.input.setText("logcat")
    tab.run_button.click()
    qtbot.waitUntil(lambda: "I/Tag: hello" in tab.output.toPlainText(), timeout=10000)
    assert tab.stop_button.isEnabled() and not tab.run_button.isEnabled()
    tab.stop_button.click()
    qtbot.waitUntil(lambda: "Остановлено" in tab.status.text(), timeout=8000)
    assert tab.run_button.isEnabled() and not tab.stop_button.isEnabled()
    entry = [e for e in win.ctx.journal.entries if "logcat" in e.command][-1]
    assert not entry.ok and "hello" in entry.output


def test_history_walks_with_arrows_and_persists(win, qtbot):
    tab = win.console
    run(win, qtbot, "adb", "devices -l")
    run(win, qtbot, "shell", "ls -l /sdcard | grep D")
    tab.input.setText("черновик")

    def key(k):
        QApplication.sendEvent(tab.input, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))

    key(Qt.Key.Key_Up)
    assert tab.input.text() == "ls -l /sdcard | grep D" and tab.mode == "shell"
    key(Qt.Key.Key_Up)
    assert tab.input.text() == "devices -l" and tab.mode == "adb"
    key(Qt.Key.Key_Up)
    assert tab.input.text() == "devices -l"  # oldest stays
    key(Qt.Key.Key_Down)
    key(Qt.Key.Key_Down)
    assert tab.input.text() == "черновик"
    saved = ConsoleStore.load(paths.config_dir() / "console.json")
    assert saved.history[-2:] == [("adb", "devices -l"), ("shell", "ls -l /sdcard | grep D")]


def test_saved_commands(win, qtbot, monkeypatch):
    tab = win.console
    tab.mode_shell.setChecked(True)
    tab.input.setText("ls -l /sdcard | grep D")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Папки на карте", True)))
    tab.save_button.click()
    assert tab.saved_list.count() == 1 and tab.saved_list.item(0).text() == "Папки на карте"
    tab.mode_adb.setChecked(True)
    tab.input.clear()
    tab.saved_list.setCurrentRow(0)
    tab.run_saved_button.click()
    qtbot.waitUntil(lambda: "Download" in tab.output.toPlainText(), timeout=10000)
    assert tab.mode == "shell"
    assert [s.name for s in ConsoleStore.load(paths.config_dir() / "console.json").saved] == ["Папки на карте"]
    qtbot.waitUntil(lambda: not tab.run.running, timeout=5000)
    tab.delete_saved_button.click()
    assert tab.saved_list.count() == 0
    assert ConsoleStore.load(paths.config_dir() / "console.json").saved == []


def test_pairing_code_stays_out_of_screen_and_journal(win, qtbot):
    tab = win.console
    tab.mode_adb.setChecked(True)
    tab.input.setText("pair 192.168.1.23:37159 482913")
    assert "482913" not in tab.preview.text()
    tab.run_button.click()
    qtbot.waitUntil(lambda: "Successfully paired" in tab.output.toPlainText() and not tab.run.running, timeout=10000)
    assert "482913" not in tab.output.toPlainText().split("\n")[0]
    assert all("482913" not in e.command for e in win.ctx.journal.entries)


@pytest.mark.parametrize("language", ["ru", "en"])
def test_console_tab_fits_the_smallest_window(win, qtbot, language):
    win._set_language(language)
    win.resize(win.minimumWidth(), 700)
    qtbot.wait(200)
    tab = win.console
    widest = sorted(((w.minimumSizeHint().width(), type(w).__name__, getattr(w, "text", lambda: "")()[:30]) for w in tab.findChildren(QWidget) if w.isVisible()), reverse=True)[:6]
    assert tab.minimumSizeHint().width() <= tab.width(), (tab.minimumSizeHint().width(), tab.width(), widest)


def test_screenshots(win, qtbot):
    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("set SCREENSHOT_DIR to save screenshots")
    Path(folder).mkdir(parents=True, exist_ok=True)
    run(win, qtbot, "shell", "ls -l /sdcard | grep D")
    win.resize(960, 760)
    for theme in ("light", "dark"):
        win._set_theme(theme)
        qtbot.wait(150)
        win.grab().save(str(Path(folder) / f"stage4-console-{theme}.png"))
