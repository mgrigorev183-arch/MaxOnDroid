import json
import threading
import time

import pytest

from maxondroid.core import console
from maxondroid.core.console import Command, ConsoleError, ConsoleStore, Run, build, tokenize

S = "R58M12ABCDE"


def test_tokenize_like_a_windows_user_types():
    assert tokenize('install "C:\\Users\\Мария\\Загрузки\\a b.apk"') == ["install", "C:\\Users\\Мария\\Загрузки\\a b.apk"]
    assert tokenize("push 'C:\\x y\\file.txt' /sdcard/") == ["push", "C:\\x y\\file.txt", "/sdcard/"]
    assert tokenize('  shell   echo ""  ') == ["shell", "echo", ""]
    assert tokenize('a"b c"d') == ["ab cd"]
    with pytest.raises(ConsoleError) as unterminated:
        tokenize('install "C:\\a b.apk')
    assert unterminated.value.code == "quote"


def test_adb_mode_adds_the_selected_device_only_where_it_belongs():
    assert build("adb", "logcat -d", S).args == ("-s", S, "logcat", "-d")  # logcat's -d is not adb's -d
    assert build("adb", "adb shell pm list packages", S).args == ("-s", S, "shell", "pm", "list", "packages")
    assert build("adb", "-s OTHER reboot", S).args == ("-s", "OTHER", "reboot")
    assert build("adb", "-d shell ls", S).args == ("-d", "shell", "ls")
    assert build("adb", "devices -l", S).args == ("devices", "-l")
    assert build("adb", "connect 192.168.1.40:5555", S).args == ("connect", "192.168.1.40:5555")
    assert build("adb", "adb.exe version", None).args == ("version",)
    assert build("adb", "reboot", None).args == ("reboot",)  # no device selected: adb decides


def test_shell_mode_sends_one_line_to_the_device_shell():
    command = build("shell", "ls -l /sdcard | grep DCIM; echo $HOME", S)
    assert command.args == ("-s", S, "shell", "ls -l /sdcard | grep DCIM; echo $HOME")
    assert build("shell", "adb shell  pm list packages", S).args == ("-s", S, "shell", "pm list packages")
    assert build("shell", "shell ls", S).args == ("-s", S, "shell", "ls")
    with pytest.raises(ConsoleError) as no_device:
        build("shell", "ls", None)
    assert no_device.value.code == "no_device"


@pytest.mark.parametrize("mode,text,code", [
    ("adb", "", "empty"), ("adb", "   ", "empty"), ("adb", "adb", "empty"),
    ("adb", "shell", "interactive"), ("adb", "-s X shell", "interactive"), ("shell", "adb shell", "interactive"),
    ("adb", "x" * 5000, "too_long"), ("shell", "ls\nreboot", "bad_char"), ("adb", "shell ls\x00", "bad_char"),
])
def test_refused_commands(mode, text, code):
    with pytest.raises(ConsoleError) as refused:
        build(mode, text, S)
    assert refused.value.code == code


def test_pairing_code_is_masked():
    command = build("adb", "pair 192.168.1.23:37159 482913", S)
    assert command.args == ("pair", "192.168.1.23:37159", "482913")
    assert command.secrets == ("482913",)
    assert "482913" not in command.display() and "adb pair 192.168.1.23:37159" in command.display()
    assert build("adb", 'push "C:\\a b.txt" /sdcard/', S).display() == 'adb -s R58M12ABCDE push "C:\\a b.txt" /sdcard/'


def collect(runner, command):
    chunks, done = [], threading.Event()
    run = Run(runner, command, chunks.append, lambda _r: done.set())
    return run, chunks, done


def test_run_streams_output_and_exit_code(fake_adb):
    fake_adb.set_rules([{"args": ["-s", S, "logcat", "-d"], "stream": [
        {"data": "первая строка\r\n", "sleep": 0.2}, {"data": "second\n"}], "rc": 0},
        {"args": ["-s", S, "bad"], "stdout": "", "stderr": "adb: unknown command bad\n", "rc": 1}])
    run, chunks, done = collect(fake_adb.runner, build("adb", "logcat -d", S))
    assert done.wait(10)
    assert "".join(chunks) == "первая строка\nsecond\n"
    assert run.returncode == 0 and not run.running and not run.stopped
    run, chunks, done = collect(fake_adb.runner, build("adb", "bad", S))
    assert done.wait(10) and run.returncode == 1 and "unknown command" in run.output_tail()


def test_stop_ends_a_long_command(fake_adb):
    fake_adb.set_rules([{"args": ["-s", S, "logcat"], "stream": [{"data": "line\n", "sleep": 60}]}])
    run, chunks, done = collect(fake_adb.runner, build("adb", "logcat", S))
    deadline = time.monotonic() + 5
    while not chunks and time.monotonic() < deadline:
        time.sleep(0.05)
    assert chunks == ["line\n"] and run.running
    run.stop()
    assert done.wait(5)
    assert run.stopped and not run.running and run.returncode != 0


def test_store_history_and_saved_commands_persist(tmp_path):
    path = tmp_path / "console.json"
    store = ConsoleStore.load(path)
    for i in range(console.MAX_HISTORY + 20):
        store.remember("adb", f"shell echo {i}")
    store.remember("adb", f"shell echo {console.MAX_HISTORY + 19}")  # repeated: kept once
    store.remember("shell", "  ")
    store.add_saved("Список пакетов", "shell", "pm list packages")
    store.add_saved("Логи", "adb", "logcat -d")
    store.add_saved("Логи", "adb", "logcat -d -v time")  # same name replaces
    store.save()
    again = ConsoleStore.load(path)
    assert len(again.history) == console.MAX_HISTORY
    assert again.history[-1] == ("adb", f"shell echo {console.MAX_HISTORY + 19}")
    assert [(s.name, s.text) for s in again.saved] == [("Логи", "logcat -d -v time"), ("Список пакетов", "pm list packages")]
    again.remove_saved("Логи")
    assert [s.name for s in again.saved] == ["Список пакетов"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "maxondroid.console"


def test_store_survives_damaged_or_foreign_files(tmp_path):
    path = tmp_path / "console.json"
    path.write_text("{not json", encoding="utf-8")
    assert ConsoleStore.load(path).history == []
    path.write_text(json.dumps({"format": "maxondroid.console", "history": [{"mode": "evil", "text": "x"}, 5, {"mode": "adb", "text": "devices"}],
                                "saved": [{"name": "", "mode": "adb", "text": "x"}, {"name": "ok", "mode": "shell", "text": "id"}, "junk"]}), encoding="utf-8")
    store = ConsoleStore.load(path)
    assert store.history == [("adb", "devices")]
    assert [(s.name, s.mode, s.text) for s in store.saved] == [("ok", "shell", "id")]


def test_saved_commands_have_a_limit(tmp_path):
    store = ConsoleStore.load(tmp_path / "c.json")
    for i in range(console.MAX_SAVED):
        store.add_saved(f"n{i}", "adb", "devices")
    with pytest.raises(ConsoleError):
        store.add_saved("one more", "adb", "devices")
    assert len(store.saved) == console.MAX_SAVED
    store.add_saved("n5", "adb", "version")  # replacing an existing one is fine
    assert Command("adb", "x", ("devices",)).display() == "adb devices"
