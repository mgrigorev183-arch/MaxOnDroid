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
