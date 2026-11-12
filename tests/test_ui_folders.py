"""The "Open folder" buttons: a missing folder is created, a failure is reported, the logs folder is one click away."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from maxondroid.core import paths  # noqa: E402
from maxondroid.ui import common  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402


@pytest.fixture
def opened(monkeypatch):
    seen = {"urls": [], "warnings": [], "result": True}

    def fake_open(url):
        seen["urls"].append(url.toLocalFile())
        return seen["result"]

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(fake_open))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: seen["warnings"].append(args)))
    return seen


def test_missing_folder_is_created_then_opened(qtbot, tmp_path, opened):
    target = tmp_path / "Pictures" / "MaxOnDroid"
    assert not target.exists()
    assert common.open_folder(target) is True
    assert target.is_dir()
    assert opened["urls"] == [str(target)] and opened["warnings"] == []


def test_failed_open_is_reported(qtbot, tmp_path, opened):
    opened["result"] = False
    assert common.open_folder(tmp_path / "x") is False
    (args,) = opened["warnings"]
    assert str(tmp_path / "x") in args[2]


def test_folder_that_cannot_be_created_is_reported(qtbot, tmp_path, opened):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    assert common.open_folder(blocker / "sub") is False
    assert opened["urls"] == [] and len(opened["warnings"]) == 1


def test_screen_folder_button_and_logs_menu(qtbot, fake_adb, tmp_path, opened):
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": "List of devices attached\n\n"}])
    app = QApplication.instance()
    w = create_window(app)
    qtbot.addWidget(w)
    w.ctx.settings.settings.auto_reconnect = False
    w.ctx.settings.settings.capture_dir = str(tmp_path / "never used yet")
    w.show()
    w.setup_adb(fake_adb.runner)
    try:
        w.screen.folder_open.click()
        assert (tmp_path / "never used yet").is_dir()
        assert opened["urls"][-1] == str(tmp_path / "never used yet")
        assert w.act_logs in w.menu_help.actions() and w.act_logs.text()
        w.act_logs.trigger()
        assert opened["urls"][-1] == str(paths.log_dir())
        assert paths.log_dir().is_dir()
    finally:
        w.timer.stop()
        w.ctx.tasks.shutdown()
