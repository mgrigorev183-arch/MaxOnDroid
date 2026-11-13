"""Device files: listing, names, protected paths, and that paths can never become commands.

The scripts are also run for real with a local POSIX ``sh`` (skipped on
Windows): what the device shell would get is exactly what the local shell
runs here, in a temporary folder full of awkward names.
"""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from maxondroid.core import files
from maxondroid.core.adb import AdbResult, AdbRunner
from maxondroid.core.files import FilesError

SERIAL = "R58M12ABCDE"
NASTY = "a b; touch PWNED $(touch PWNED2) `touch PWNED3` 'q' \"d\" |x"


class LocalShell(AdbRunner):
    """Runs ``adb shell COMMAND`` as ``sh -c COMMAND`` on this machine, with device paths mapped into ``root``."""

    def __init__(self, root: Path, path_env: str | None = None, as_nobody: bool = False):
        super().__init__("adb")
        self.root = root
        self.path_env = path_env  # a PATH without stat, like an old Android
        self.as_nobody = as_nobody  # an ordinary user, like adb's shell user, so permissions apply
        self.commands: list[str] = []

    def run(self, args, serial=None, timeout=None, *, log=True, secrets=(), cancel=None):
        assert args[0] == "shell" and len(args) == 2
        command = args[1].replace("/dev/", "\x00DEV\x00").replace("/sdcard", str(self.root / "sdcard")).replace("\x00DEV\x00", "/dev/")
        self.commands.append(args[1])
        env = None if self.path_env is None else {"PATH": self.path_env}
        argv = ["/bin/sh" if env else "sh", "-c", command]
        if self.as_nobody:
            argv = ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", *argv]
        proc = subprocess.run(argv, capture_output=True, cwd=self.root, timeout=30, env=env)
        return AdbResult(("-s", serial, *args), proc.returncode, proc.stdout.decode(), proc.stderr.decode(), 0.01, serial=serial)


needs_sh = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX sh")


@pytest.fixture
def device(tmp_path):
    sdcard = tmp_path / "sdcard"
    (sdcard / "DCIM" / "Camera").mkdir(parents=True)
    (sdcard / "DCIM" / "Camera" / "IMG_1.jpg").write_bytes(b"x" * 1234)
    (sdcard / "Download").mkdir()
    (sdcard / "Download" / NASTY).write_text("nasty")
    (sdcard / ".hidden").write_text("h")
    (sdcard / "..dots").write_text("d")
    (sdcard / "notes.txt").write_text("hello")
    (sdcard / "link-to-dcim").symlink_to(sdcard / "DCIM")
    (sdcard / "broken-link").symlink_to(sdcard / "nowhere")
    return LocalShell(tmp_path)


def no_injection(root: Path):
    return not any((root / name).exists() or (root / "sdcard" / name).exists() for name in ("PWNED", "PWNED2", "PWNED3"))


@needs_sh
def test_list_folder_for_real(device):
    entries = files.list_folder(device, SERIAL, "/sdcard")
    names = [e.name for e in entries]
    assert names[:3] == ["DCIM", "Download", "link-to-dcim"]  # folders (and links to folders) first
    by_name = {e.name: e for e in entries}
    assert by_name["notes.txt"].kind == "file" and by_name["notes.txt"].size == 5
    assert by_name["link-to-dcim"].is_dir  # followed, like /sdcard itself
    assert by_name["broken-link"].kind == "link"
    assert {".hidden", "..dots"} <= set(names)
    assert by_name["notes.txt"].path == "/sdcard/notes.txt"
    assert by_name["notes.txt"].modified > 1_600_000_000


@needs_sh
def test_nasty_names_are_only_names(device):
    entries = files.list_folder(device, SERIAL, "/sdcard/Download")
    assert [e.name for e in entries] == [NASTY]
    renamed = files.rename(device, SERIAL, entries[0].path, NASTY + " (2)")
    assert renamed == "/sdcard/Download/" + NASTY + " (2)"
    made = files.make_folder(device, SERIAL, "/sdcard/Download", "$(touch PWNED) folder")
    assert (device.root / "sdcard" / "Download" / "$(touch PWNED) folder").is_dir()
    files.remove(device, SERIAL, [renamed, made])
    assert files.list_folder(device, SERIAL, "/sdcard/Download") == []
    assert no_injection(device.root)


@needs_sh
def test_empty_denied_and_existing(device):
    (device.root / "sdcard" / "empty").mkdir()
    assert files.list_folder(device, SERIAL, "/sdcard/empty") == []
    with pytest.raises(FilesError) as denied:
        files.list_folder(device, SERIAL, "/sdcard/no such folder")
    assert denied.value.code == "denied"
    with pytest.raises(FilesError) as exists:
        files.make_folder(device, SERIAL, "/sdcard", "DCIM")
    assert exists.value.code == "exists"
    with pytest.raises(FilesError) as taken:
        files.rename(device, SERIAL, "/sdcard/notes.txt", "Download")
    assert taken.value.code == "exists"
    assert (device.root / "sdcard" / "notes.txt").exists()


def test_parse_listing_handles_pipes_in_names_and_junk():
    text = "directory|4096|1700000000|Music\nregular file|10|1700000001|a|b.txt\nregular empty file|0|1700000002|zero\ngarbage\n?|0|0|odd\n@@end\n"
    entries = files.parse_listing(text, "/sdcard/")
    assert [(e.name, e.kind) for e in entries] == [("Music", "dir"), ("a|b.txt", "file"), ("odd", "other"), ("zero", "file")]
    assert entries[1].path == "/sdcard/a|b.txt"
    with pytest.raises(FilesError):
        files.parse_listing("@@denied\n", "/data")


def test_paths_and_names():
    assert files.normalize("") == "/sdcard"
    assert files.normalize("sdcard/../sdcard//DCIM/./") == "/sdcard/DCIM"
    assert files.normalize("\\sdcard\\Download") == "/sdcard/Download"
    assert files.parent("/sdcard/DCIM") == "/sdcard" and files.parent("/") == "/"
    for bad in ("", " ", ".", "..", "a/b", "x\x00", "line\nbreak", "я" * 200):
        with pytest.raises(FilesError):
            files.check_name(bad)
    assert files.check_name("  Новая папка ") == "Новая папка"


def test_storage_roots_are_never_deleted(fake_adb):
    for path in ("/", "/sdcard", "/sdcard/", "/storage/emulated/0", "/data", "/system", "/etc", "/sdcard/.."):
        assert files.is_protected(path), path
    assert not files.is_protected("/sdcard/DCIM")
    with pytest.raises(FilesError) as blocked:
        files.remove(fake_adb.runner, SERIAL, ["/sdcard/DCIM/a.jpg", "/sdcard"])
    assert blocked.value.code == "protected"
    with pytest.raises(FilesError):
        files.rename(fake_adb.runner, SERIAL, "/sdcard", "x")
    assert fake_adb.calls() == []  # refused before anything ran


def test_push_and_pull_are_argument_lists(fake_adb, tmp_path):
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "push", "*"], "stdout": "2 files pushed, 0 skipped. 12.0 MB/s (100 bytes in 0.001s)\n"},
        {"args": ["-s", SERIAL, "pull", "*"], "stdout": "1 file pulled, 0 skipped.\n"},
    ])
    a = tmp_path / "фото 1.jpg"
    a.write_bytes(b"1")
    folder = tmp_path / "папка"
    folder.mkdir()
    result = files.push(fake_adb.runner, SERIAL, [a, folder], "/sdcard/Download")
    assert result.ok and files.transfer_summary(result).startswith("2 files pushed")
    assert ["-s", SERIAL, "push", str(a), str(folder), "/sdcard/Download/"] in fake_adb.calls()
    out = tmp_path / "out"
    result = files.pull(fake_adb.runner, SERIAL, ["/sdcard/DCIM/Camera", "/sdcard/a;b.txt"], out)
    assert result.ok and out.is_dir()
    assert ["-s", SERIAL, "pull", "/sdcard/DCIM/Camera", "/sdcard/a;b.txt", str(out)] in fake_adb.calls()
    with pytest.raises(FilesError) as missing:
        files.push(fake_adb.runner, SERIAL, [tmp_path / "nope"], "/sdcard")
    assert missing.value.code == "missing"


def test_transfer_can_be_cancelled(fake_adb, tmp_path):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "pull", "*"], "stdout": "", "sleep": 30}])
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    result = files.pull(fake_adb.runner, SERIAL, ["/sdcard/DCIM"], tmp_path, cancel=cancel)
    assert result.cancelled


@needs_sh
def test_control_an_unquoted_name_would_run_commands(device):
    """Positive control for no_injection(): the same name pasted into a command unquoted does run them."""
    assert no_injection(device.root)
    device.run(["shell", f"ls /sdcard/Download/{NASTY}"])
    assert not no_injection(device.root)


@needs_sh
def test_listing_without_stat_falls_back_to_ls(device, tmp_path):
    import shutil

    bin_dir = tmp_path / "oldbin"
    bin_dir.mkdir()
    (bin_dir / "ls").symlink_to(shutil.which("ls"))
    (bin_dir / "sh").symlink_to(shutil.which("sh"))
    old = LocalShell(device.root, path_env=str(bin_dir))
    entries = files.list_folder(old, SERIAL, "/sdcard")
    by_name = {e.name: e for e in entries}
    assert by_name["DCIM"].is_dir and by_name["notes.txt"].kind == "file"
    assert ".hidden" in by_name
    assert by_name["notes.txt"].size == 0  # sizes come only from stat: this listing came from ls


def nobody_device():
    """A device tree an ordinary user can walk, with a folder like /data: enterable, not readable."""
    import os
    import shutil
    import tempfile

    if sys.platform == "win32" or os.geteuid() != 0 or not shutil.which("setpriv"):
        pytest.skip("needs root to switch to an ordinary user with setpriv")
    base = Path(tempfile.mkdtemp())
    base.chmod(0o755)
    (base / "sdcard" / "Pictures").mkdir(parents=True)
    (base / "sdcard" / "Pictures" / "a.jpg").write_text("x")
    locked = base / "sdcard" / "data"
    (locked / "inside").mkdir(parents=True)
    for folder in (base / "sdcard", base / "sdcard" / "Pictures", locked / "inside"):
        folder.chmod(0o755)
    (base / "sdcard" / "Pictures" / "a.jpg").chmod(0o644)
    locked.chmod(0o311)  # x without r, like /data for the shell user
    return LocalShell(base, as_nobody=True), base


def test_unreadable_folder_is_no_access_not_empty():
    import shutil

    device, base = nobody_device()
    try:
        with pytest.raises(FilesError) as denied:
            files.list_folder(device, SERIAL, "/sdcard/data")
        assert denied.value.code == "denied"
        assert [e.name for e in files.list_folder(device, SERIAL, "/sdcard/Pictures")] == ["a.jpg"]  # control
    finally:
        (base / "sdcard" / "data").chmod(0o755)
        shutil.rmtree(base)
