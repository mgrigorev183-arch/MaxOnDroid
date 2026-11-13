"""Update check in the window: banner, Help menu, settings toggle. Never real network (see conftest)."""

from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from maxondroid.core import update  # noqa: E402
from maxondroid.core.update import Release, UpdateError  # noqa: E402
from maxondroid.ui import main_window  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402

NEWER = Release("0.9.5", "https://github.com/mgrigorev183-arch/MaxOnDroid/releases/tag/v0.9.5")


@pytest.fixture
def make(qtbot, fake_adb, monkeypatch):
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": "List of devices attached\n\n"}])
    monkeypatch.setattr(main_window, "UPDATE_DELAY_MS", 50)
    windows = []

    def build(answer, enabled=True, last="", dismissed=""):
        calls = []

        def fake_latest():
            calls.append(1)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        monkeypatch.setattr(update, "latest", fake_latest)
        app = QApplication.instance()
        w = create_window(app)
        qtbot.addWidget(w)
        w._set_language("ru")
        s = w.ctx.settings.settings
        s.auto_reconnect = False
        s.update_check, s.update_last_check, s.update_dismissed = enabled, last, dismissed
        w.show()
        w.setup_adb(fake_adb.runner)
        w.update_calls = calls
        windows.append(w)
        return w

    yield build
    for w in windows:
        w.timer.stop()
        w.ctx.tasks.shutdown()


def test_newer_release_shows_a_banner_with_the_link(make, qtbot, monkeypatch):
    w = make(NEWER)
    qtbot.waitUntil(lambda: w.update_banner.isVisible(), timeout=5000)
    assert "0.9.5" in w.update_banner.title.text()
    assert w.ctx.settings.settings.update_last_check == date.today().isoformat()
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    w.update_banner.button.click()
    assert opened == [NEWER.url]
    w.update_banner.button2.click()  # hide
    assert not w.update_banner.isVisible() and w.ctx.settings.settings.update_dismissed == "0.9.5"


def test_once_a_day_and_off_switch_and_hidden_version(make, qtbot):
    today = make(NEWER, last=date.today().isoformat())
    off = make(NEWER, enabled=False)
    hidden = make(NEWER, dismissed="0.9.5")
    qtbot.waitUntil(lambda: hidden.update_calls == [1] and not hidden._checking_update, timeout=5000)
    qtbot.wait(200)
    assert today.update_calls == [] and off.update_calls == []
    assert not hidden.update_banner.isVisible()


def test_same_version_and_errors_stay_quiet(make, qtbot):
    same = make(Release("0.9.0", NEWER.url))
    qtbot.waitUntil(lambda: same.update_calls == [1] and not same._checking_update, timeout=5000)
    broken = make(UpdateError("network", "offline"))
    qtbot.waitUntil(lambda: broken.update_calls == [1] and not broken._checking_update, timeout=5000)
    assert not same.update_banner.isVisible() and not broken.update_banner.isVisible()


@pytest.mark.parametrize("answer,title", [
    (NEWER, "Есть новая версия"),
    (Release("0.9.0", NEWER.url), "Обновлений нет"),
    (UpdateError("network", "offline"), "Не удалось проверить"),
])
def test_help_menu_check_reports_the_result(make, qtbot, monkeypatch, answer, title):
    w = make(answer, enabled=False)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append((box.windowTitle(), box.text())) or 0)
    assert w.act_update in w.menu_help.actions()
    w.act_update.trigger()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    assert shown[0][0] == title
    assert w.update_calls == [1]  # asked even with the daily check off: the user asked


def test_settings_dialog_has_the_toggle(make, qtbot):
    from maxondroid.ui.settings_dialog import SettingsDialog

    w = make(NEWER, enabled=False)
    dialog = SettingsDialog(w.ctx, w)
    assert not dialog.update_check.isChecked()
    dialog.update_check.setChecked(True)
    assert dialog.result_settings().update_check is True
    dialog.close()
