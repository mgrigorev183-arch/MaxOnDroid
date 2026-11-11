import io
import json
from pathlib import Path

import pytest

from maxondroid.core import paths, presets, safety, uad
from maxondroid.core.changes import ChangeJournal
from maxondroid.core.ops import PackageOps
from maxondroid.core.packages import Action, Package, PkgState, parse_snapshot
from maxondroid.core.presets import PlanStatus, Preset, PresetAction
from tests import fixtures as fx

SERIAL = "192.168.1.40:5555"
BUNDLED = paths.package_data_dir() / "uad"


def test_bundled_database_loads_with_provenance(tmp_path):
    db = uad.load(BUNDLED, tmp_path)
    assert db.source is uad.Source.BUNDLED and len(db.entries) > 5000
    assert db.date == "2026-11-11"
    source = json.loads((BUNDLED / "SOURCE.json").read_text())
    assert db.sha256 == source["sha256"]
    yt = db.get("com.google.android.youtube.tv")
    assert yt.removal is uad.Removal.RECOMMENDED and yt.summary == "YouTube app"
    assert db.get("com.android.systemui").removal is uad.Removal.UNSAFE


def test_download_validates_and_is_preferred(tmp_path):
    raw = (BUNDLED / "uad_lists.json").read_bytes()

    def opener(request, timeout):
        assert request.full_url == uad.UAD_URL and timeout == 30.0
        return io.BytesIO(raw)

    db = uad.download(tmp_path, opener=opener)
    assert db.source is uad.Source.DOWNLOADED and len(db.entries) > 5000
    assert uad.load(BUNDLED, tmp_path).source is uad.Source.DOWNLOADED
    (tmp_path / "uad_lists.json").write_text("{}")  # tampered after download: checksum no longer matches
    assert uad.load(BUNDLED, tmp_path).source is uad.Source.BUNDLED


@pytest.mark.parametrize("payload, code", [(b"<html>rate limited</html>", "invalid_json"), (b"[]", "invalid_format"), (b'{"a.b": {"list": "Oem", "description": "x", "removal": "Recommended"}}', "too_small")])
def test_download_rejects_bad_payloads_and_keeps_old_copy(tmp_path, payload, code):
    with pytest.raises(uad.DatabaseError) as err:
        uad.download(tmp_path, opener=lambda r, t: io.BytesIO(payload))
    assert err.value.code == code
    assert not (tmp_path / "uad_lists.json").exists()


def test_download_network_error_and_insecure_url(tmp_path):
    def broken(request, timeout):
        raise OSError("no route to host")

    with pytest.raises(uad.DatabaseError) as err:
        uad.download(tmp_path, opener=broken)
    assert err.value.code == "network"
    with pytest.raises(uad.DatabaseError) as err:
        uad.download(tmp_path, url="http://example.com/list.json")
    assert err.value.code == "insecure_url"


def test_safety_levels():
    db = uad.load(BUNDLED, Path("/nonexistent"))
    snap = parse_snapshot(fx.PACKAGES_OUTPUT)
    assert safety.classify("com.android.shell", db.get("com.android.shell"), snap).level is safety.Level.BLOCKED
    launcher = safety.classify("com.google.android.apps.tv.launcherx", db.get("com.google.android.apps.tv.launcherx"), snap)
    assert launcher.level is safety.Level.CRITICAL and safety.Reason.LAUNCHER in launcher.reasons
    keyboard = safety.classify("com.google.android.inputmethod.latin", None, snap)
    assert safety.Reason.KEYBOARD in keyboard.reasons
    assert safety.Reason.UPDATER in safety.classify("com.xiaomi.mitv.upgrade", None, snap).reasons
    assert safety.Reason.CORE in safety.classify("com.google.android.gms", db.get("com.google.android.gms"), snap).reasons
    assert safety.classify("com.google.android.youtube.tv", db.get("com.google.android.youtube.tv"), snap).level is safety.Level.NORMAL


def test_presets_roundtrip_and_plan(tmp_path):
    preset = Preset("Мой телевизор", "реклама", (("com.google.android.youtube.tv", PresetAction.REMOVE), ("com.netflix.ninja", PresetAction.DISABLE), ("com.google.android.tvrecommendations", PresetAction.REMOVE), ("com.absent.app", PresetAction.REMOVE)))
    path = tmp_path / "tv.json"
    presets.save(preset, path)
    loaded = presets.load(path)
    assert loaded.name == "Мой телевизор" and loaded.items == preset.items
    plan = {i.package: i.status for i in presets.plan(loaded, parse_snapshot(fx.PACKAGES_OUTPUT))}
    assert plan == {
        "com.google.android.youtube.tv": PlanStatus.TODO,
        "com.netflix.ninja": PlanStatus.DONE,
        "com.google.android.tvrecommendations": PlanStatus.DONE,
        "com.absent.app": PlanStatus.MISSING,
    }


def test_preset_loading_is_defensive(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"format": "maxondroid.preset", "packages": [
        {"package": "com.ok.app", "action": "remove"}, {"package": "com.ok.app", "action": "disable"},
        {"package": "bad;name", "action": "remove"}, {"package": "com.x.y", "action": "explode"}, "junk",
    ]}), encoding="utf-8")
    loaded = presets.load(path)
    assert loaded.items == (("com.ok.app", PresetAction.REMOVE),) and loaded.name == "p"
    path.write_text('{"format": "something.else"}')
    with pytest.raises(presets.PresetError):
        presets.load(path)


def make_ops(fake_adb, tmp_path):
    journal = ChangeJournal(tmp_path / "changes.json")
    return PackageOps(fake_adb.runner, SERIAL, "28041SKV0123", journal, tmp_path / "backups", parse_snapshot(fx.PACKAGES_OUTPUT)), journal


def test_remove_disable_then_undo_all_in_reverse(fake_adb, tmp_path):
    ops, journal = make_ops(fake_adb, tmp_path)
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "shell", "pm uninstall -k --user 0 com.google.android.youtube.tv"], "stdout": "Success\n"},
        {"args": ["-s", SERIAL, "shell", "pm disable-user --user 0 com.netflix.ninja"], "stdout": "Package com.netflix.ninja new state: disabled-user\n"},
        {"args": ["-s", SERIAL, "shell", "cmd package install-existing --user 0 com.google.android.youtube.tv"], "stdout": "Package com.google.android.youtube.tv installed for user: 0\n"},
        {"args": ["-s", SERIAL, "shell", "pm enable --user 0 com.netflix.ninja"], "stdout": "Package com.netflix.ninja new state: enabled\n"},
    ])
    yt = Package("com.google.android.youtube.tv", True, PkgState.ENABLED, "4.01.345")
    nf = Package("com.netflix.ninja", True, PkgState.ENABLED)
    assert ops.remove(yt).ok and ops.disable(nf).ok
    assert [c.package for c in journal.pending("28041SKV0123")] == ["com.netflix.ninja", "com.google.android.youtube.tv"]
    reloaded = ChangeJournal(tmp_path / "changes.json")
    assert len(reloaded.pending("28041SKV0123")) == 2
    results = ops.undo_all()
    assert [r.ok for r in results] == [True, True]
    commands = [c[3] for c in fake_adb.calls()]
    assert commands[-2:] == ["pm enable --user 0 com.netflix.ninja", "cmd package install-existing --user 0 com.google.android.youtube.tv"]
    assert journal.pending("28041SKV0123") == [] and len(journal.for_device("28041SKV0123")) == 2


def test_blocked_package_is_refused_without_adb(fake_adb, tmp_path):
    ops, journal = make_ops(fake_adb, tmp_path)
    result = ops.remove(Package("com.android.shell", True, PkgState.ENABLED))
    assert not result.ok and result.code == "blocked"
    assert ops.disable(Package("com.android.systemui", True, PkgState.ENABLED)).code == "blocked"
    assert fake_adb.calls() == [] and journal.pending("28041SKV0123") == []


def test_user_app_is_backed_up_before_uninstall_and_reinstalled_on_undo(fake_adb, tmp_path, monkeypatch):
    ops, journal = make_ops(fake_adb, tmp_path)
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "shell", "pm path org.videolan.vlc"], "stdout": "package:/data/app/org.videolan.vlc/base.apk\n"},
        {"args": ["-s", SERIAL, "pull", "*"], "stdout": "1 file pulled.\n"},
        {"args": ["-s", SERIAL, "shell", "pm uninstall org.videolan.vlc"], "stdout": "Success\n"},
        {"args": ["-s", SERIAL, "install", "-r", "*"], "stdout": "Success\n"},
    ])
    real_run = fake_adb.runner.run

    def run(args, serial=None, timeout=None, **kw):
        result = real_run(args, serial=serial, timeout=timeout, **kw)
        if args and args[0] == "pull":
            Path(args[2]).write_bytes(b"apk")
        return result

    monkeypatch.setattr(fake_adb.runner, "run", run)
    vlc = Package("org.videolan.vlc", False, PkgState.ENABLED, "3.5.4")
    result = ops.remove(vlc)
    assert result.ok and result.action is Action.UNINSTALL
    change = journal.pending("28041SKV0123")[0]
    assert change.backup and Path(change.backup).name == "org.videolan.vlc-3.5.4.apk"
    assert ops.undo(change).ok
    assert fake_adb.calls()[-1][:4] == ["-s", SERIAL, "install", "-r"]
    assert journal.pending("28041SKV0123") == []


def test_failed_backup_stops_the_uninstall(fake_adb, tmp_path):
    ops, journal = make_ops(fake_adb, tmp_path)
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "pm path org.videolan.vlc"], "stdout": ""}])
    result = ops.remove(Package("org.videolan.vlc", False, PkgState.ENABLED))
    assert not result.ok and result.code == "backup_failed"
    assert all("uninstall" not in " ".join(c) for c in fake_adb.calls())


def test_enable_and_restore_settle_the_journal(fake_adb, tmp_path):
    ops, journal = make_ops(fake_adb, tmp_path)
    journal.record("28041SKV0123", "com.netflix.ninja", Action.DISABLE)
    journal.record("28041SKV0123", "com.google.android.tvrecommendations", Action.REMOVE_FOR_USER)
    fake_adb.set_rules([
        {"args": ["-s", SERIAL, "shell", "pm enable --user 0 com.netflix.ninja"], "stdout": "Package com.netflix.ninja new state: enabled\n"},
        {"args": ["-s", SERIAL, "shell", "cmd package install-existing --user 0 com.google.android.tvrecommendations"], "stdout": "Package com.google.android.tvrecommendations installed for user: 0\n"},
    ])
    assert ops.restore(Package("com.netflix.ninja", True, PkgState.DISABLED)).ok
    assert ops.restore(Package("com.google.android.tvrecommendations", True, PkgState.REMOVED)).ok
    assert journal.pending("28041SKV0123") == []


def test_undo_without_backup_reports_it(fake_adb, tmp_path):
    ops, journal = make_ops(fake_adb, tmp_path)
    change = journal.record("28041SKV0123", "org.videolan.vlc", Action.UNINSTALL, backup=str(tmp_path / "gone.apk"))
    result = ops.undo(change)
    assert not result.ok and result.code == "no_backup" and change.pending


def test_change_journal_rejects_bad_entries(tmp_path):
    path = tmp_path / "changes.json"
    path.write_text(json.dumps({"format": "maxondroid.changes", "changes": [
        {"id": "1", "device": "d", "package": "com.ok.x", "action": "disable", "time": "t"},
        {"id": "2", "device": "d", "package": "bad;x", "action": "disable"},
        {"id": "3", "device": "d", "package": "com.ok.y", "action": "launch"},
        {"id": "4", "device": "d", "package": "com.ok.z", "action": "nonsense"},
    ]}), encoding="utf-8")
    journal = ChangeJournal(path)
    assert [c.id for c in journal.pending("d")] == ["1"]
    with pytest.raises(ValueError):
        journal.record("d", "com.ok.x", Action.LAUNCH)
