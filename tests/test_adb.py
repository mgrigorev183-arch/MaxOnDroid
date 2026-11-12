import subprocess

import pytest

from maxondroid.core import adb as adb_module
from maxondroid.core.adb import AdbNotFoundError, AdbRunner, find_adb, mask_secrets, sh_quote


def test_runs_with_argument_list_and_serial(fake_adb):
    fake_adb.set_rules([{"args": ["-s", "R58M", "get-state"], "stdout": "device\n"}])
    result = fake_adb.runner.run(["get-state"], serial="R58M")
    assert result.ok
    assert result.stdout == "device\n"
    assert fake_adb.calls() == [["-s", "R58M", "get-state"]]


def test_hostile_serial_stays_one_argument(fake_adb):
    hostile = "x; del C:\\Windows & calc"
    fake_adb.set_rules([{"args": ["-s", hostile, "get-state"], "stdout": "device\n"}])
    result = fake_adb.runner.run(["get-state"], serial=hostile)
    assert result.ok, result.output
    assert fake_adb.calls() == [["-s", hostile, "get-state"]]


def test_never_uses_a_host_shell(monkeypatch):
    seen = {}

    class Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["shell"] = kwargs.get("shell")
        return Proc()

    monkeypatch.setattr(adb_module.subprocess, "Popen", fake_popen)
    AdbRunner("adb").run(["devices"])
    assert isinstance(seen["cmd"], list)
    assert seen["shell"] is False


def test_rejects_non_string_and_nul_arguments(fake_adb):
    with pytest.raises(TypeError):
        fake_adb.runner.run(["shell", 5])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        fake_adb.runner.run(["shell", "a\x00b"])


def test_shell_quotes_every_argument_for_the_device(fake_adb):
    fake_adb.set_rules([{"args": ["-s", "S", "shell", "*"], "stdout": "ok\n"}])
    fake_adb.runner.shell("S", "ls", "/sdcard/My Files; reboot")
    assert fake_adb.calls()[-1] == ["-s", "S", "shell", "ls '/sdcard/My Files; reboot'"]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("com.example.app", "com.example.app"),
        ("", "''"),
        ("a b", "'a b'"),
        ("it's", "'it'\"'\"'s'"),
        ("$(reboot)", "'$(reboot)'"),
        ("a;b", "'a;b'"),
    ],
)
def test_sh_quote(value, expected):
    assert sh_quote(value) == expected


def test_timeout_kills_and_reports(fake_adb):
    fake_adb.set_rules([{"args": ["wait"], "sleep": 5, "stdout": "late"}])
    result = fake_adb.runner.run(["wait"], timeout=0.5)
    assert result.timed_out
    assert not result.ok


def test_missing_executable_raises():
    with pytest.raises(AdbNotFoundError):
        AdbRunner("/definitely/not/here/adb").run(["devices"])


def test_listener_receives_results_and_secrets_are_masked(fake_adb):
    fake_adb.set_rules([{"args": ["pair", "*"], "stdout": "Failed: code 123456 rejected\n", "rc": 1}])
    seen = []
    fake_adb.runner.add_listener(seen.append)
    fake_adb.runner.run(["pair", "192.168.1.5:41000", "123456"], secrets=["123456"])
    fake_adb.runner.run(["pair", "192.168.1.5:41000", "123456"], log=False, secrets=["123456"])
    assert len(seen) == 1
    assert "123456" not in seen[0].display_command()
    assert "123456" not in seen[0].display_output()
    assert "••••••" in seen[0].display_command()


def test_broken_listener_does_not_break_calls(fake_adb):
    fake_adb.set_rules([{"args": ["version"], "stdout": "Android Debug Bridge version 1.0.41\n"}])

    def boom(_):
        raise RuntimeError("listener bug")

    fake_adb.runner.add_listener(boom)
    assert fake_adb.runner.version() == "Android Debug Bridge version 1.0.41"


def test_mask_secrets_ignores_empty():
    assert mask_secrets("abc", ["", "b"]) == "a•c"


def test_find_adb_prefers_custom_path(tmp_path):
    custom = tmp_path / "adb.exe"
    custom.write_text("")
    assert find_adb(str(custom)) == str(custom)
    assert find_adb(str(tmp_path / "missing.exe")) is None


def test_windows_flag_constant_is_create_no_window():
    assert adb_module._CREATE_NO_WINDOW == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def test_timeout_does_not_hang_when_another_process_holds_the_pipes(fake_adb, monkeypatch):
    """On Windows an adb server started by the client can keep its pipes open; the call must still return."""
    monkeypatch.setattr(adb_module, "AFTER_KILL_WAIT", 1.0)
    fake_adb.set_rules([{"args": ["hang"], "holder": 20, "sleep": 20}])
    import time

    started = time.monotonic()
    result = fake_adb.runner.run(["hang"], timeout=0.5)
    elapsed = time.monotonic() - started
    assert result.timed_out and not result.ok
    assert elapsed < 6, elapsed  # 0.5 s timeout + 1 s grace + reaping, not the holder's 20 s
    assert "held by another process" in result.stderr


def test_holder_control_old_behaviour_would_wait(fake_adb):
    """Positive control: without the bound, communicate() after kill waits for the holder."""
    fake_adb.set_rules([{"args": ["hang"], "holder": 3, "sleep": 20}])
    import sys
    import time

    proc = subprocess.Popen([sys.executable, str(adb_module.Path(__file__).with_name("fake_adb.py")), "hang"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    time.sleep(0.8)
    proc.kill()
    started = time.monotonic()
    proc.communicate()
    assert time.monotonic() - started > 1.0


def test_tracer_sees_quiet_commands_with_duration(fake_adb):
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": "List of devices attached\n\n", "sleep": 0.2}])
    traced, logged = [], []
    fake_adb.runner.add_tracer(traced.append)
    fake_adb.runner.add_listener(logged.append)
    fake_adb.runner.run(["devices", "-l"], log=False)
    assert logged == []
    assert len(traced) == 1 and traced[0].duration >= 0.2


def test_open_stream_reads_as_it_comes(fake_adb):
    fake_adb.set_rules([{"args": ["track-devices", "-l"], "stream": [{"data": "0000", "sleep": 0.1}, {"data": "0005hello"}]}])
    proc = fake_adb.runner.open_stream(["track-devices", "-l"])
    try:
        assert proc.stdout.read(4) == b"0000"
        assert proc.stdout.read(9) == b"0005hello"
    finally:
        proc.kill()
        proc.wait(5)
    assert ["track-devices", "-l"] in fake_adb.calls()
