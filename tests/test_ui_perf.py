"""Freezes: theme and language switches with a big package list, the stall watchdog, the slow-command log."""

import json
import time
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QHeaderView  # noqa: E402

from maxondroid.core import paths  # noqa: E402
from maxondroid.core.diag import Diagnostics  # noqa: E402
from maxondroid.core.packages import LIST_SCRIPT  # noqa: E402
from maxondroid.ui import apps_tab  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from maxondroid.ui.watchdog import StallWatchdog  # noqa: E402
from tests import fixtures as fx  # noqa: E402

PHONE = "RFCX30397DJ"
DEVICES = f"List of devices attached\n{PHONE}\tdevice usb:1-1 product:a35x model:SM_A356E device:a35x transport_id:5\n\n"
UAD = Path(__file__).resolve().parents[1] / "maxondroid" / "data" / "uad" / "uad_lists.json"


def package_list(count: int) -> str:
    """A Samsung-sized list: real package names from the UAD database."""
    names = [n for n in json.loads(UAD.read_text(encoding="utf-8")) if n.startswith(("com.samsung", "com.sec", "com.google", "com.android"))][:count]
    body = "".join(f"package:{n}\n" for n in names)
    versions = "".join(f"  Package [{n}] (ab):\n    versionCode=1 minSdk=1 targetSdk=34\n    versionName=1.0.{i}\n" for i, n in enumerate(names))
    out = fx.PACKAGES_OUTPUT
    for section in ("@@all\n", "@@installed\n", "@@system\n"):
        out = out.replace(section, section + body, 1)
    return out.replace("@@versions\n", "@@versions\n" + versions, 1).replace("@@leanback\ntrue", "@@leanback\nfalse")


@pytest.fixture
def win(qtbot, fake_adb, monkeypatch):
    calls = {"data": 0}
    original = apps_tab.AppsModel.data

    class CountingModel(apps_tab.AppsModel):
        def data(self, index, role=0):
            calls["data"] += 1
            return original(self, index, role)

    monkeypatch.setattr(apps_tab, "AppsModel", CountingModel)
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": DEVICES},
        {"args": ["-s", PHONE, "shell", LIST_SCRIPT], "stdout": package_list(650)},
        {"args": ["-s", PHONE, "shell", "*"], "stdout": fx.info_output(fx.PHONE_PROPS.replace("R58M12ABCDE", PHONE), fx.PHONE_BATTERY, fx.FEATURES_PHONE)},
        {"args": ["slow"], "stdout": "", "sleep": 1.2},
    ])
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w._set_language("ru")
    w._set_theme("light")
    w.ctx.settings.settings.auto_reconnect = False
    w.resize(1280, 800)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 1 and w.ctx.packages.get(w.views[0].key) is not None, timeout=20000)
    w.tabs.setCurrentWidget(w.apps)
    qtbot.waitUntil(lambda: w.apps.model.rowCount() > 600, timeout=10000)
    w.data_calls = calls
    yield w
    w.timer.stop()
    w.ctx.tasks.shutdown()


def switch_theme_and_count(win) -> int:
    app = QApplication.instance()
    win.data_calls["data"] = 0
    win._set_theme("dark")
    app.processEvents()
    win._set_theme("light")
    app.processEvents()
    return win.data_calls["data"]


def test_theme_switch_does_not_measure_every_package(win):
    fixed = switch_theme_and_count(win)
    assert fixed < 20000, fixed
    # positive control: fitting the columns to their contents, as before the fix, measures every row
    head = win.apps.table.horizontalHeader()
    for column in (2, 3, 4):
        head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    fitted = switch_theme_and_count(win)
    assert fitted > 5 * max(fixed, 1000), (fixed, fitted)


def test_columns_still_fit_their_texts(win):
    head = win.apps.table.horizontalHeader()
    metrics = win.apps.table.fontMetrics()
    for column, text in ((3, "Системное"), (4, "Отключено")):
        assert head.sectionSize(column) >= metrics.horizontalAdvance(text), (column, text)


def test_language_switch_rebuilds_debloat_once_and_only_when_shown(win, qtbot):
    app = QApplication.instance()
    debloat = win.debloat
    win.tabs.setCurrentWidget(debloat)
    qtbot.waitUntil(lambda: debloat.model.rowCount() > 0, timeout=5000)
    before = debloat.rebuild_count
    win._set_language("en")
    app.processEvents()
    assert debloat.rebuild_count == before + 1
    before = debloat.rebuild_count
    win._set_theme("dark")
    app.processEvents()
    assert debloat.rebuild_count == before + 1
    # hidden: nothing now, one rebuild when it is shown
    win.tabs.setCurrentWidget(win.overview)
    before = debloat.rebuild_count
    win._set_language("ru")
    win._set_theme("light")
    app.processEvents()
    assert debloat.rebuild_count == before
    win.tabs.setCurrentWidget(debloat)
    app.processEvents()
    assert debloat.rebuild_count == before + 1
    assert debloat.model.horizontalHeaderItem(1).text() == "Риск удаления"


def _freeze_for_test(seconds: float) -> None:
    time.sleep(seconds)


def test_watchdog_writes_where_the_window_froze(qtbot, tmp_path):
    diag = Diagnostics(tmp_path)
    dog = StallWatchdog(diag, threshold=0.3)
    dog.start()
    try:
        qtbot.wait(300)
        _freeze_for_test(0.9)
        qtbot.waitUntil(lambda: bool(dog.stalls), timeout=3000)
    finally:
        dog.stop()
    seconds, stack = dog.stalls[0]
    assert 0.8 <= seconds < 3
    assert "_freeze_for_test" in stack
    text = diag.path_for(date.today()).read_text(encoding="utf-8")
    assert "window not responding for" in text and "_freeze_for_test" in text
    assert len(dog.stalls) == 1  # one freeze, one entry


def test_watchdog_runs_in_the_app_and_slow_commands_are_logged(win):
    assert win.watchdog is not None
    win.ctx.runner.run(["slow"], log=False)  # quiet, like the device poll: not in the journal
    win.ctx.runner.run(["devices", "-l"], log=False)  # quick: not logged
    text = (paths.log_dir() / f"diag-{date.today().isoformat()}.log").read_text(encoding="utf-8")
    assert "slow command" in text and "adb slow" in text
    assert "devices -l" not in text
