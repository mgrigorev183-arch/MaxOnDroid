"""The self-test mode the release workflow runs on the built and on the installed app."""

import json
import sys
from pathlib import Path

import pytest

from maxondroid import __version__, selftest
from maxondroid.core import adb, paths, screen
from maxondroid.ui import app as ui_app

HERE = Path(__file__).parent
FAKE_ADB = HERE / "fake_adb.py"
FAKE_SCRCPY = HERE / "fake_scrcpy.py"
EXE = ".exe" if sys.platform == "win32" else ""


@pytest.fixture
def bundle(tmp_path, monkeypatch, fake_adb):
    """A tools/scrcpy folder like the installer's, with the Python stand-ins behind the file names."""
    tools = tmp_path / "install" / "tools"
    (tools / "scrcpy").mkdir(parents=True)
    (tools / "scrcpy" / f"adb{EXE}").write_text("stand-in", encoding="utf-8")
    (tools / "scrcpy" / f"scrcpy{EXE}").write_text("stand-in", encoding="utf-8")
    for module in (paths, adb, screen):
        monkeypatch.setattr(module, "bundled_tools_dir", lambda: tools)

    def command(exe):
        name = Path(exe).name
        return [sys.executable, str(FAKE_ADB if name.startswith("adb") else FAKE_SCRCPY)]

    monkeypatch.setattr(selftest, "_command", command)
    fake_adb.set_rules([{"args": ["version"], "stdout": "Android Debug Bridge version 1.0.41\nVersion 36.0.0\n"}])
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))  # nothing else to find
    return tools


def checks(report):
    return {c["name"]: c for c in report["checks"]}


def test_all_checks_pass_on_a_complete_bundle(bundle, tmp_path, qapp, isolated_home):
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is True and report["version"] == __version__
    found = checks(report)
    assert list(found) == ["adb", "scrcpy", "uad", "i18n", "window"]
    assert all(c["ok"] for c in found.values()), found
    assert "Android Debug Bridge version 1.0.41" in found["adb"]["detail"]
    assert "3.1" in found["scrcpy"]["detail"]
    assert int(found["uad"]["detail"].split()[0]) >= selftest.MIN_UAD_ENTRIES
    # the user's own settings folder was not touched: everything went to a temporary home
    assert not (isolated_home / "config" / "settings.json").exists()


def test_missing_scrcpy_fails_and_says_which(bundle, tmp_path, qapp):
    (bundle / "scrcpy" / f"scrcpy{EXE}").unlink()
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is False
    found = checks(report)
    assert found["scrcpy"]["ok"] is False and "not found" in found["scrcpy"]["detail"]
    assert found["adb"]["ok"] is True  # one missing tool does not hide the others' results


def test_a_copy_on_path_does_not_count_as_bundled(bundle, tmp_path, monkeypatch, qapp):
    (bundle / "scrcpy" / f"adb{EXE}").unlink()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other = elsewhere / f"adb{EXE}"
    other.write_text("stand-in", encoding="utf-8")
    other.chmod(0o755)
    monkeypatch.setenv("PATH", str(elsewhere))
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    adb_check = checks(json.loads(out.read_text(encoding="utf-8")))["adb"]
    assert adb_check["ok"] is False and "not the bundled copy" in adb_check["detail"]
    # without --require-bundled the same copy is accepted (developer runs)
    assert selftest.main(out, require_bundled=False) == 0


def test_a_broken_adb_fails(bundle, fake_adb, tmp_path, qapp):
    fake_adb.set_rules([{"args": ["version"], "stdout": "", "rc": 1}])
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    assert checks(json.loads(out.read_text(encoding="utf-8")))["adb"]["ok"] is False


def test_a_damaged_package_list_fails(bundle, tmp_path, monkeypatch, qapp):
    data = tmp_path / "data"
    (data / "uad").mkdir(parents=True)
    (data / "uad" / "uad_lists.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "package_data_dir", lambda: data)
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    uad_check = checks(json.loads(out.read_text(encoding="utf-8")))["uad"]
    assert uad_check["ok"] is False


def test_incomplete_translations_fail(bundle, tmp_path, monkeypatch, qapp):
    from maxondroid.i18n import LANGUAGES

    monkeypatch.setitem(LANGUAGES, "ru", {k: v for k, v in LANGUAGES["ru"].items() if k != "menu.update"})
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    i18n_check = checks(json.loads(out.read_text(encoding="utf-8")))["i18n"]
    assert i18n_check["ok"] is False and "menu.update" in i18n_check["detail"]


def test_a_crashing_check_is_a_failure_not_a_pass(bundle, tmp_path, monkeypatch, qapp):
    def boom(_qt):
        raise RuntimeError("window exploded")

    monkeypatch.setattr(ui_app, "create_window", boom)
    out = tmp_path / "report.json"
    assert selftest.main(out, require_bundled=True) == 1
    window = checks(json.loads(out.read_text(encoding="utf-8")))["window"]
    assert window["ok"] is False and "window exploded" in window["detail"]


def test_the_switch_is_read_from_the_command_line(tmp_path, monkeypatch):
    assert selftest.parse_args([]) is None
    assert selftest.parse_args(["--self-test", "r.json"]) == (Path("r.json"), False)
    assert selftest.parse_args(["--self-test", "r.json", "--require-bundled"]) == (Path("r.json"), True)
    with pytest.raises(SystemExit):
        selftest.parse_args(["--self-test"])
    seen = []
    monkeypatch.setattr(selftest, "main", lambda report, require: seen.append((report, require)) or 7)
    assert ui_app.main(["MaxOnDroid.exe", "--self-test", str(tmp_path / "r.json"), "--require-bundled"]) == 7
    assert seen == [(tmp_path / "r.json", True)]
