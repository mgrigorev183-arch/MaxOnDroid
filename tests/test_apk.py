import zipfile

import pytest

from maxondroid.core import apk
from maxondroid.core.apk import BundleError
from tests import fixtures as fx

SERIAL = "R58M12ABCDE"
BUNDLETOOL = ["base-master.apk", "base-arm64_v8a.apk", "base-armeabi_v7a.apk", "base-x86.apk", "base-mdpi.apk", "base-xhdpi.apk", "base-xxhdpi.apk", "base-ru.apk", "base-en.apk"]
SAI = ["base.apk", "split_config.arm64_v8a.apk", "split_config.armeabi_v7a.apk", "split_config.xxhdpi.apk", "split_config.ru.apk"]


def test_choose_splits_bundletool_layout():
    chosen = apk.choose_splits(BUNDLETOOL, ("arm64-v8a", "armeabi-v7a"), 420)
    assert set(chosen) == {"base-master.apk", "base-arm64_v8a.apk", "base-xxhdpi.apk", "base-ru.apk", "base-en.apk"}


def test_choose_splits_falls_back_to_next_abi_and_largest_density():
    chosen = apk.choose_splits(SAI[:1] + SAI[2:], ("arm64-v8a", "armeabi-v7a"), 640)
    assert "split_config.armeabi_v7a.apk" in chosen and "split_config.xxhdpi.apk" in chosen


def test_choose_splits_no_matching_abi():
    with pytest.raises(BundleError) as err:
        apk.choose_splits(["base.apk", "split_config.x86.apk"], ("arm64-v8a",), 320)
    assert err.value.code == "no_matching_abi"


def test_choose_splits_needs_a_base():
    with pytest.raises(BundleError) as err:
        apk.choose_splits(["split_config.arm64_v8a.apk"], ("arm64-v8a",), 320)
    assert err.value.code == "no_base"


def make_bundle(path, names, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, b"PK-apk-" + name.encode())
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_extract_bundle_ignores_paths_from_the_archive(tmp_path):
    bundle = make_bundle(tmp_path / "evil.apks", ["../../outside.apk", "splits/base.apk", "C:\\Windows\\x.apk", "dup/base.apk"], {"manifest.json": "{}", "Android/obb/a.obb": "x"})
    out = tmp_path / "out"
    out.mkdir()
    files = apk.extract_bundle(bundle, out)
    assert sorted(p.name for p in files) == ["base-1.apk", "base.apk", "outside.apk", "x.apk"]
    assert all(p.parent == out for p in files)
    assert not (tmp_path / "outside.apk").exists()


def test_extract_bundle_rejects_non_zip_and_empty(tmp_path):
    bad = tmp_path / "bad.xapk"
    bad.write_bytes(b"not a zip")
    with pytest.raises(BundleError) as err:
        apk.extract_bundle(bad, tmp_path)
    assert err.value.code == "bad_bundle"
    empty = make_bundle(tmp_path / "empty.apks", [], {"readme.txt": "x"})
    with pytest.raises(BundleError) as err:
        apk.extract_bundle(empty, tmp_path)
    assert err.value.code == "no_apks"


@pytest.mark.parametrize(
    "text, ok, code",
    [
        ("Performing Streamed Install\nSuccess\n", True, None),
        ("adb: failed to install x.apk: Failure [INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected]\n", False, "INSTALL_FAILED_VERSION_DOWNGRADE"),
        ("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package signatures do not match]", False, "INSTALL_FAILED_UPDATE_INCOMPATIBLE"),
        ("adb: failed to install: something odd", False, "UNKNOWN"),
    ],
)
def test_parse_install_output(text, ok, code):
    assert apk.parse_install_output(text) == (ok, code)


def test_install_single_apk(fake_adb, tmp_path):
    file = tmp_path / "My App.apk"
    file.write_bytes(b"x")
    fake_adb.set_rules([{"args": ["-s", SERIAL, "install", "-r", str(file)], "stdout": "Performing Streamed Install\nSuccess\n"}])
    result = apk.install(fake_adb.runner, SERIAL, file)
    assert result.ok and result.error_code is None


def test_install_bundle_uses_install_multiple_with_chosen_splits(fake_adb, tmp_path):
    bundle = make_bundle(tmp_path / "app.apks", ["splits/" + n for n in BUNDLETOOL])
    fake_adb.set_rules([{"args": ["-s", SERIAL, "install-multiple", "-r", "*"], "stdout": "Success\n"}])
    result = apk.install(fake_adb.runner, SERIAL, bundle, ("arm64-v8a",), 480, temp_root=tmp_path)
    assert result.ok
    call = fake_adb.calls()[0]
    names = sorted(p.replace("\\", "/").rsplit("/", 1)[-1] for p in call[4:])
    assert names == sorted(["base-master.apk", "base-arm64_v8a.apk", "base-xxhdpi.apk", "base-ru.apk", "base-en.apk"])
    assert [p for p in tmp_path.iterdir() if p.name.startswith("maxondroid-")] == []  # temp folder cleaned


def test_install_reports_bundle_errors_without_calling_adb(fake_adb, tmp_path):
    bundle = make_bundle(tmp_path / "x86only.apks", ["base.apk", "split_config.x86.apk"])
    result = apk.install(fake_adb.runner, SERIAL, bundle, ("arm64-v8a",), 320, temp_root=tmp_path)
    assert not result.ok and result.error_code == "no_matching_abi"
    assert fake_adb.calls() == []
    other = tmp_path / "notes.txt"
    other.write_text("x")
    assert apk.install(fake_adb.runner, SERIAL, other).error_code == "unsupported_file"


def test_install_failure_code(fake_adb, tmp_path):
    file = tmp_path / "a.apk"
    file.write_bytes(b"x")
    fake_adb.set_rules([{"args": ["-s", SERIAL, "install", "*"], "stdout": "Performing Streamed Install\n", "stderr": "adb: failed to install a.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]\n", "rc": 1}])
    result = apk.install(fake_adb.runner, SERIAL, file)
    assert not result.ok and result.error_code == "INSTALL_FAILED_INSUFFICIENT_STORAGE"


def _pull_rules(tmp_path, paths):
    """fake adb cannot create files, so pull is emulated by a tiny helper script per path."""
    return [{"args": ["-s", SERIAL, "shell", "pm path org.videolan.vlc"], "stdout": paths}]


def test_extract_split_app_packs_apks(fake_adb, tmp_path, monkeypatch):
    fake_adb.set_rules(_pull_rules(tmp_path, fx.PM_PATH_SPLIT) + [{"args": ["-s", SERIAL, "pull", "*"], "stdout": "1 file pulled.\n"}])
    real_run = fake_adb.runner.run

    def run(args, serial=None, timeout=None, **kw):
        result = real_run(args, serial=serial, timeout=timeout, **kw)
        if args and args[0] == "pull":
            from pathlib import Path

            Path(args[2]).write_bytes(b"apk:" + args[1].encode())
        return result

    monkeypatch.setattr(fake_adb.runner, "run", run)
    out = tmp_path / "saved"
    result = apk.extract_apk(fake_adb.runner, SERIAL, "org.videolan.vlc", out, "3.5.4")
    assert result.ok and result.file.name == "org.videolan.vlc-3.5.4.apks"
    with zipfile.ZipFile(result.file) as z:
        assert sorted(z.namelist()) == ["base.apk", "split_config.arm64_v8a.apk", "split_config.xhdpi.apk"]
    assert [p.name for p in out.iterdir()] == ["org.videolan.vlc-3.5.4.apks"]
    again = apk.extract_apk(fake_adb.runner, SERIAL, "org.videolan.vlc", out, "3.5.4")
    assert again.file.name == "org.videolan.vlc-3.5.4 (2).apks"


def test_extract_single_apk_and_missing_package(fake_adb, tmp_path, monkeypatch):
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "shell", "pm path com.x.y"], "stdout": "package:/data/app/com.x.y/base.apk\n"},
        {"args": ["-s", SERIAL, "shell", "pm path com.gone.app"], "stdout": ""},
        {"args": ["-s", SERIAL, "pull", "*"], "stdout": "1 file pulled.\n"},
    ])
    real_run = fake_adb.runner.run

    def run(args, serial=None, timeout=None, **kw):
        result = real_run(args, serial=serial, timeout=timeout, **kw)
        if args and args[0] == "pull":
            from pathlib import Path

            Path(args[2]).write_bytes(b"apk")
        return result

    monkeypatch.setattr(fake_adb.runner, "run", run)
    result = apk.extract_apk(fake_adb.runner, SERIAL, "com.x.y", tmp_path / "o")
    assert result.ok and result.file.name == "com.x.y.apk"
    assert not apk.extract_apk(fake_adb.runner, SERIAL, "com.gone.app", tmp_path / "o").ok


def test_pull_failure_leaves_no_partial_files(fake_adb, tmp_path):
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "shell", "pm path org.videolan.vlc"], "stdout": fx.PM_PATH_SPLIT},
        {"args": ["-s", SERIAL, "pull", "*"], "stderr": "adb: error: failed to stat remote object", "rc": 1},
    ])
    out = tmp_path / "o"
    result = apk.extract_apk(fake_adb.runner, SERIAL, "org.videolan.vlc", out)
    assert not result.ok and "failed to stat" in result.message
    assert list(out.iterdir()) == []
