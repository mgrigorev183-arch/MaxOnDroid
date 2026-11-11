import pytest

from maxondroid.core import packages
from maxondroid.core.packages import Action, InvalidPackageError, PkgState
from tests import fixtures as fx

SERIAL = "192.168.1.40:5555"


def shell_rule(command, stdout, rc=0):
    return {"args": ["-s", SERIAL, "shell", command], "stdout": stdout, "rc": rc}


def test_snapshot_states_versions_and_device_facts():
    snap = packages.parse_snapshot(fx.PACKAGES_OUTPUT)
    assert "not a package" not in " ".join(snap.packages)
    yt = snap.get("com.google.android.youtube.tv")
    assert yt.system and yt.state is PkgState.ENABLED and yt.version_name == "4.01.345" and yt.version_code == 4012345
    assert snap.get("com.google.android.tvrecommendations").state is PkgState.REMOVED
    assert snap.get("com.netflix.ninja").state is PkgState.DISABLED
    vlc = snap.get("org.videolan.vlc")
    assert not vlc.system and vlc.version_name == "3.5.4"
    assert snap.home == "com.google.android.apps.tv.launcherx"
    assert snap.ime == "com.google.android.inputmethod.latin"
    assert snap.abis == ("arm64-v8a", "armeabi-v7a", "armeabi")
    assert snap.density == 320 and snap.sdk == 31 and snap.leanback


def test_read_snapshot_uses_one_shell_call(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stdout": fx.PACKAGES_OUTPUT}])
    snap = packages.read_snapshot(fake_adb.runner, SERIAL)
    assert len(snap.packages) == 9
    assert len(fake_adb.calls()) == 1


def test_read_snapshot_raises_on_failure(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stderr": "error: device offline", "rc": 1}])
    with pytest.raises(packages.PackageError):
        packages.read_snapshot(fake_adb.runner, SERIAL)


@pytest.mark.parametrize("name", ["com.example.app", "a.b", "org.videolan.vlc", "android", "com.A_b.c9"])
def test_valid_package_names(name):
    assert packages.check_package(name) == name


@pytest.mark.parametrize("name", ["", "com", "com.example;reboot", "com.example app", "-s", "com..x", "1com.x", "com.x/y", "$(id).x"])
def test_invalid_package_names(name):
    with pytest.raises(InvalidPackageError):
        packages.check_package(name)


def test_hostile_name_never_reaches_adb(fake_adb):
    with pytest.raises(InvalidPackageError):
        packages.disable(fake_adb.runner, SERIAL, "com.x; reboot")
    assert fake_adb.calls() == []


@pytest.mark.parametrize(
    "fn, command, stdout, ok, action",
    [
        (packages.remove_for_user, "pm uninstall -k --user 0 com.x.y", "Success\n", True, Action.REMOVE_FOR_USER),
        (packages.remove_for_user, "pm uninstall -k --user 0 com.x.y", "Failure [not installed for 0]\n", False, Action.REMOVE_FOR_USER),
        (packages.uninstall, "pm uninstall com.x.y", "Success\n", True, Action.UNINSTALL),
        (packages.disable, "pm disable-user --user 0 com.x.y", "Package com.x.y new state: disabled-user\n", True, Action.DISABLE),
        (packages.disable, "pm disable-user --user 0 com.x.y", "Error: java.lang.SecurityException: Cannot disable a protected package\n", False, Action.DISABLE),
        (packages.enable, "pm enable --user 0 com.x.y", "Package com.x.y new state: enabled\n", True, Action.ENABLE),
        (packages.clear_data, "pm clear --user 0 com.x.y", "Success\n", True, Action.CLEAR),
        (packages.clear_data, "pm clear --user 0 com.x.y", "Failed\n", False, Action.CLEAR),
        (packages.force_stop, "am force-stop com.x.y", "", True, Action.FORCE_STOP),
    ],
)
def test_actions(fake_adb, fn, command, stdout, ok, action):
    fake_adb.set_rules([shell_rule(command, stdout)])
    result = fn(fake_adb.runner, SERIAL, "com.x.y")
    assert result.ok is ok and result.action is action and result.package == "com.x.y"
    assert fake_adb.calls() == [["-s", SERIAL, "shell", command]]


def test_restore_uses_cmd_package_then_falls_back(fake_adb):
    fake_adb.set_rules([
        shell_rule("cmd package install-existing --user 0 com.x.y", "Exception occurred while executing: unknown command\n", 0),
        shell_rule("pm install-existing --user 0 com.x.y", "Package com.x.y installed for user: 0\n"),
    ])
    assert packages.restore(fake_adb.runner, SERIAL, "com.x.y", sdk=31).ok
    assert [c[3] for c in fake_adb.calls()] == ["cmd package install-existing --user 0 com.x.y", "pm install-existing --user 0 com.x.y"]


def test_restore_on_old_android_uses_pm(fake_adb):
    fake_adb.set_rules([shell_rule("pm install-existing --user 0 com.x.y", "Package com.x.y installed for user: 0\n")])
    assert packages.restore(fake_adb.runner, SERIAL, "com.x.y", sdk=24).ok
    assert len(fake_adb.calls()) == 1


def test_launch_prefers_tv_launcher_on_tv(fake_adb):
    fake_adb.set_rules([
        shell_rule("monkey -p com.x.y -c android.intent.category.LEANBACK_LAUNCHER 1", "  bash arg: -p\nEvents injected: 1\n"),
    ])
    assert packages.launch(fake_adb.runner, SERIAL, "com.x.y", leanback=True).ok
    assert len(fake_adb.calls()) == 1


def test_launch_tries_both_categories(fake_adb):
    fake_adb.set_rules([
        shell_rule("monkey -p com.x.y -c android.intent.category.LAUNCHER 1", "** No activities found to run, monkey aborted.\n"),
        shell_rule("monkey -p com.x.y -c android.intent.category.LEANBACK_LAUNCHER 1", "** No activities found to run, monkey aborted.\n"),
    ])
    result = packages.launch(fake_adb.runner, SERIAL, "com.x.y")
    assert not result.ok and "No activities" in result.message
    assert len(fake_adb.calls()) == 2


def test_apk_paths_filters_garbage(fake_adb):
    fake_adb.set_rules([shell_rule("pm path org.videolan.vlc", fx.PM_PATH_SPLIT + "package:../../etc/passwd\npackage:/x/../y.apk\n")])
    paths = packages.apk_paths(fake_adb.runner, SERIAL, "org.videolan.vlc")
    assert len(paths) == 3 and all(p.startswith("/data/app/") for p in paths)
