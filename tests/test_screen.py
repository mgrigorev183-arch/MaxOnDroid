import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from maxondroid.core import screen
from maxondroid.core.screen import Scrcpy, ScrcpyError, ScrcpyOptions

FAKE = Path(__file__).with_name("fake_scrcpy.py")
SERIAL = "192.168.1.40:5555"
PNG = screen.PNG_MAGIC + b"\x00\x00\x00\rIHDR" + b"\x00" * 40


@pytest.fixture
def scrcpy(tmp_path, monkeypatch):
    log = tmp_path / "scrcpy.jsonl"
    monkeypatch.setenv("FAKE_SCRCPY_LOG", str(log))
    monkeypatch.setenv("FAKE_SCRCPY_MODE", "run")
    tool = Scrcpy(str(FAKE), "C:/tools/adb.exe", [sys.executable, str(FAKE)])
    tool.log = log
    yield tool
    tool.stop_all()


def starts(tool):
    if not tool.log.exists():
        return []
    return [json.loads(line) for line in tool.log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_presets_and_arguments():
    quality = ScrcpyOptions.for_preset("quality")
    speed = ScrcpyOptions.for_preset("speed")
    assert screen.build_args(SERIAL, quality, "01 Телевизор") == [f"--serial={SERIAL}", "--window-title=01 Телевизор", "--video-bit-rate=8M"]
    assert screen.build_args(SERIAL, speed, "t") == [f"--serial={SERIAL}", "--window-title=t", "--max-size=1280", "--video-bit-rate=4M", "--max-fps=30"]
    every = ScrcpyOptions(max_size=1024, bit_rate_mbps=2, max_fps=15, audio=False, turn_screen_off=True, always_on_top=True, stay_awake=True, view_only=True)
    args = screen.build_args(SERIAL, every, "t", Path("C:/rec/a.mkv"))
    assert args[2:] == ["--max-size=1024", "--video-bit-rate=2M", "--max-fps=15", "--no-audio", "--turn-screen-off", "--always-on-top", "--stay-awake", "--no-control", f"--record={Path('C:/rec/a.mkv')}"]
    with pytest.raises(ValueError):
        screen.build_args(SERIAL, quality, "bad\ntitle")


@pytest.mark.parametrize("text, version", [("scrcpy 3.1 <https://github.com/Genymobile/scrcpy>", (3, 1, 0)), ("scrcpy v2.4.1", (2, 4, 1)), ("hello", None)])
def test_parse_version(text, version):
    assert screen.parse_version(text) == version


def test_version_check(scrcpy, monkeypatch):
    assert scrcpy.check() == (3, 1, 0)
    monkeypatch.setenv("FAKE_SCRCPY_MODE", "old")
    with pytest.raises(ScrcpyError) as err:
        scrcpy.check()
    assert err.value.code == "too_old" and err.value.detail == "1.25.0"
    missing = Scrcpy("/no/such/scrcpy", None)
    with pytest.raises(ScrcpyError) as err:
        missing.check()
    assert err.value.code == "missing"


def test_start_uses_our_adb_and_stops(scrcpy):
    seen = []
    scrcpy.listeners.append(seen.append)
    session = scrcpy.start("tv", SERIAL, ScrcpyOptions.for_preset("speed"), "02 Телевизор в зале")
    deadline = time.monotonic() + 10
    while not starts(scrcpy) and time.monotonic() < deadline:
        time.sleep(0.05)
    started = starts(scrcpy)[0]
    assert started["adb"] == "C:/tools/adb.exe"
    assert started["argv"][:2] == [f"--serial={SERIAL}", "--window-title=02 Телевизор в зале"]
    assert seen and seen[0].startswith("fake_scrcpy.py --serial=")
    assert session.running
    assert scrcpy.start("tv", SERIAL, ScrcpyOptions(), "again") is session  # one window per device
    scrcpy.stop("tv")
    assert not session.running


def test_early_exit_keeps_scrcpy_output(scrcpy, monkeypatch):
    monkeypatch.setenv("FAKE_SCRCPY_MODE", "fail")
    session = scrcpy.start("tv", SERIAL, ScrcpyOptions(), "t")
    session.proc.wait(timeout=10)
    assert session.returncode == 1
    assert "Could not find any ADB device" in session.tail()


def test_recording_writes_the_file(scrcpy, tmp_path):
    target = tmp_path / "captures" / "tv record.mkv"
    session = scrcpy.start("tv", SERIAL, ScrcpyOptions(), "t", record=target)
    deadline = time.monotonic() + 10
    while not target.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert target.exists() and session.record == target
    scrcpy.stop("tv")


def test_screenshot_saves_png(fake_adb, tmp_path):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "exec-out", "screencap", "-p"], "stdout_b64": base64.b64encode(PNG).decode()}])
    seen = []
    fake_adb.runner.add_listener(seen.append)
    target = screen.screenshot(fake_adb.runner, SERIAL, tmp_path / "shots" / "a.png")
    assert target.read_bytes() == PNG
    assert seen[0].display_output() == f"<{len(PNG)} bytes>"  # the journal never gets the image


def test_screenshot_error_has_adbs_words(fake_adb, tmp_path):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "exec-out", "*"], "stderr": "error: device offline", "rc": 1}])
    with pytest.raises(screen.ScreenshotError) as err:
        screen.screenshot(fake_adb.runner, SERIAL, tmp_path / "a.png")
    assert "device offline" in str(err.value)
    assert not (tmp_path / "a.png").exists()


def test_capture_names_are_windows_safe():
    when = datetime(2026, 11, 12, 1, 2, 3)
    assert screen.capture_name('TV: "Зал"/2', "скриншот", "png", when) == "TV_ _Зал__2 скриншот 2026-11-12 01-02-03.png"


def test_find_scrcpy_next_to_adb(tmp_path):
    exe = "scrcpy.exe" if sys.platform == "win32" else "scrcpy"
    (tmp_path / exe).write_text("")
    assert screen.find_scrcpy(None, str(tmp_path / "adb.exe")) == str(tmp_path / exe)
    assert screen.find_scrcpy(str(tmp_path / "missing.exe")) is None
    assert screen.find_scrcpy(str(tmp_path / exe)) == str(tmp_path / exe)


def test_keyboard_fps_and_bit_rate_cap_in_arguments():
    opts = ScrcpyOptions(keyboard="uhid", bit_rate_mbps=80)
    args = screen.build_args(SERIAL, opts, "t", print_fps=True)
    assert "--keyboard=uhid" in args and "--print-fps" in args
    assert "--video-bit-rate=50M" in args  # capped
    # view only sends no input, so no keyboard; recordings do not print fps
    assert "--keyboard=uhid" not in screen.build_args(SERIAL, ScrcpyOptions(keyboard="uhid", view_only=True), "t")
    assert "--print-fps" not in screen.build_args(SERIAL, ScrcpyOptions(), "t", Path("a.mkv"))
    assert "--keyboard=uhid" not in screen.build_args(SERIAL, ScrcpyOptions(), "t")


def test_options_from_saved_dict_are_sanitized():
    last = ScrcpyOptions(max_size=1024, audio=False)
    opts = ScrcpyOptions.from_dict({"bit_rate_mbps": 500, "max_fps": True, "keyboard": "evil", "preset": "speed", "junk": 1}, last)
    assert opts.bit_rate_mbps == 50 and opts.max_fps == 0 and opts.keyboard == "sdk"
    assert opts.preset == "speed" and opts.max_size == 1024 and opts.audio is False
    assert ScrcpyOptions.from_dict("not a dict", last) is last
    assert ScrcpyOptions.from_dict(opts.to_dict()) == opts


def test_tv_starts_on_the_light_preset():
    last = ScrcpyOptions(audio=False, max_size=0, bit_rate_mbps=12)
    tv = screen.default_options("tv", last)
    assert (tv.preset, tv.max_size, tv.bit_rate_mbps, tv.max_fps, tv.audio) == ("speed", 1280, 4, 30, False)
    assert screen.default_options("phone", last) is last


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


def test_session_reports_fps_and_keeps_them_out_of_the_tail(scrcpy):
    session = scrcpy.start("tv", SERIAL, ScrcpyOptions(), "t")
    assert "--print-fps" in session.command
    assert wait_for(lambda: session.fps is not None)
    assert session.fps in ((59, 0), (57, 2))
    assert "fps" not in session.tail(60)
    assert scrcpy.running_serials() == {SERIAL}
    scrcpy.stop("tv")
    assert session.fps is None and scrcpy.running_serials() == set()


def test_restart_reopens_with_new_options(scrcpy):
    first = scrcpy.start("tv", SERIAL, ScrcpyOptions(max_size=0), "t")
    assert wait_for(lambda: len(starts(scrcpy)) == 1)
    second = scrcpy.restart("tv", SERIAL, ScrcpyOptions(max_size=1024), "t")
    assert second is not first and not first.running and second.running
    assert wait_for(lambda: len(starts(scrcpy)) == 2)
    assert "--max-size=1024" in starts(scrcpy)[1]["argv"]
    assert "--max-size=1024" not in starts(scrcpy)[0]["argv"]
