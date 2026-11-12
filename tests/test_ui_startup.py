"""Startup and device changes: the list never waits for a reconnect, track-devices updates it at once."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from maxondroid.core import paths  # noqa: E402
from maxondroid.core.registry import NetworkAddress, Registry  # noqa: E402
from maxondroid.ui import main_window  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

TV = "192.168.1.40:5555"
TV_LINE = f"{TV}      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5\n"
TV_INFO = fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV, "Телевизор в зале")


def block(text: str) -> str:
    return f"{len(text.encode('utf-8')):04x}{text}"


def make_window(qtbot, fake_adb, auto_reconnect=True):
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w.ctx.settings.settings.auto_reconnect = auto_reconnect
    w.resize(1100, 760)
    w.show()
    w.setup_adb(fake_adb.runner)
    return w


def close(w):
    w.timer.stop()
    if w.watcher is not None:
        w.watcher.stop()
    w.ctx.tasks.shutdown(8000)


def test_list_shows_up_while_reconnect_still_hangs(qtbot, fake_adb):
    """The report: with nobody online the first start took 20-30 s, three saved devices tried one by one."""
    registry = Registry(paths.config_dir() / "devices.json")
    registry.remember("R58M12ABCDE", model="SM-G973F", kind="phone", network=NetworkAddress("192.168.1.23", 37159, "paired"))
    registry.remember("28041SKV0123", model="MiTV", kind="tv", network=NetworkAddress("192.168.1.40", 5555, "legacy"))
    registry.remember("ZY22BXYZ12", model="Xiaomi", kind="phone", network=NetworkAddress("192.168.1.31", 41000, "paired"))
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": fx.DEVICES_EMPTY},
        {"args": ["mdns", "services"], "stdout": "List of discovered mdns services\n", "sleep": 1},
        {"args": ["connect", "*"], "stdout": "", "sleep": 30},  # absent hosts: each attempt hangs until killed
    ])
    started = time.monotonic()
    w = make_window(qtbot, fake_adb)
    try:
        qtbot.waitUntil(lambda: len(w.views) == 3, timeout=5000)
        shown_after = time.monotonic() - started
        assert shown_after < 3, shown_after
        qtbot.waitUntil(lambda: w._reconnecting, timeout=3000)  # the reconnect runs, the list did not wait for it
        assert all(not v.online for v in w.views)
        assert w.device_list.model_.rowCount() == 3
        # the list keeps refreshing while the reconnect hangs
        polls = len([c for c in fake_adb.calls() if c == ["devices", "-l"]])
        w.refresh_now()
        qtbot.waitUntil(lambda: len([c for c in fake_adb.calls() if c == ["devices", "-l"]]) > polls, timeout=3000)
    finally:
        close(w)


def test_track_devices_updates_the_list_before_the_poll(qtbot, fake_adb, monkeypatch):
    monkeypatch.setattr(main_window, "POLL_MS", 600000)
    monkeypatch.setattr(main_window, "SLOW_POLL_MS", 600000)
    track = {"args": ["track-devices", "-l"], "stream": [{"data": block(""), "sleep": 3}, {"data": block(TV_LINE), "sleep": 60}]}
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": fx.DEVICES_EMPTY}, track])
    w = make_window(qtbot, fake_adb, auto_reconnect=False)
    try:
        qtbot.waitUntil(lambda: w.watcher is not None and w.watcher.alive, timeout=5000)
        qtbot.waitUntil(lambda: not w._refreshing and w.views == [], timeout=5000)
        # the TV appears: adb would now list it, and track-devices says so
        fake_adb.set_rules([
            {"args": ["devices", "-l"], "stdout": "List of devices attached\n" + TV_LINE + "\n"},
            {"args": ["-s", TV, "shell", "*"], "stdout": TV_INFO},
            track,
        ])
        qtbot.waitUntil(lambda: len(w.views) == 1 and w.views[0].online, timeout=8000)
        assert w.timer.interval() == 600000  # it was not the poll
    finally:
        close(w)


def test_poll_slows_down_while_track_devices_runs(qtbot, fake_adb):
    track = {"args": ["track-devices", "-l"], "stream": [{"data": block(""), "sleep": 60}]}
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": fx.DEVICES_EMPTY}, track])
    w = make_window(qtbot, fake_adb, auto_reconnect=False)
    try:
        qtbot.waitUntil(lambda: w.watcher is not None and w.watcher.alive, timeout=5000)
        w.refresh_now()
        qtbot.waitUntil(lambda: w.timer.interval() == main_window.SLOW_POLL_MS, timeout=5000)
        w.watcher.stop()
        w.refresh_now()
        qtbot.waitUntil(lambda: w.timer.interval() == main_window.POLL_MS, timeout=5000)
    finally:
        close(w)
