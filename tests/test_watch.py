import io
import threading
import time

from maxondroid.core import watch
from maxondroid.core.devices import parse_devices
from maxondroid.core.watch import DeviceWatcher, read_block

LIST = "R58M12ABCDE\tdevice usb:1-1 product:beyond1 model:SM_G973F device:beyond1 transport_id:3\n"


def block(text: str) -> str:
    return f"{len(text.encode('utf-8')):04x}{text}"


def test_read_block_parses_length_prefixed_lists():
    stream = io.BytesIO((block(LIST) + block("") + block("x")).encode())
    first = read_block(stream)
    assert first == LIST
    assert [d.serial for d in parse_devices(first)] == ["R58M12ABCDE"]
    assert read_block(stream) == ""
    assert read_block(stream) == "x"
    assert read_block(stream) is None  # end of stream


def test_read_block_rejects_garbage_and_truncation():
    assert read_block(io.BytesIO(b"zz12abc")) is None
    assert read_block(io.BytesIO(b"0010short")) is None
    assert read_block(io.BytesIO(b"ffffffff")) is None  # says 65535 bytes follow, only 4 do
    assert read_block(io.BytesIO(b"00")) is None


def test_watcher_delivers_changes_restarts_and_stops(fake_adb, monkeypatch):
    monkeypatch.setattr(watch, "RESTART_DELAYS", (0.2, 0.2, 0.2, 0.2))
    fake_adb.set_rules([
        {"args": ["track-devices", "-l"], "responses": [
            {"stream": [{"data": block(""), "sleep": 0.1}, {"data": block(LIST), "sleep": 0.1}]},  # then adb exits
            {"stream": [{"data": block(LIST), "sleep": 30}]},  # stays open until stopped
        ]},
    ])
    seen = []
    got_three = threading.Event()

    def on_change(text):
        seen.append(text)
        if len(seen) >= 3:
            got_three.set()

    watcher = DeviceWatcher(fake_adb.runner, on_change)
    watcher.start()
    try:
        assert got_three.wait(10), seen
        assert seen[:3] == ["", LIST, LIST]
        assert watcher.starts == 2  # restarted after the first adb exited
        deadline = time.monotonic() + 5
        while not watcher.alive and time.monotonic() < deadline:
            time.sleep(0.05)
        assert watcher.alive
    finally:
        started = time.monotonic()
        watcher.stop()
        assert time.monotonic() - started < 4
    assert not watcher.alive


def test_watcher_survives_missing_adb_and_broken_callback(tmp_path, monkeypatch):
    from maxondroid.core.adb import AdbRunner

    monkeypatch.setattr(watch, "RESTART_DELAYS", (0.05,))
    watcher = DeviceWatcher(AdbRunner(str(tmp_path / "no-adb")), lambda text: 1 / 0)
    watcher.start()
    time.sleep(0.3)
    watcher.stop()
    assert watcher.starts == 0 and not watcher.alive
