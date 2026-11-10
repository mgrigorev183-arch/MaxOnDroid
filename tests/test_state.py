import json

from maxondroid.core import paths
from maxondroid.core.devices import State, Transport
from maxondroid.core.info import Kind
from maxondroid.core.journal import Journal
from maxondroid.core.manager import DeviceManager
from maxondroid.core.registry import Registry
from maxondroid.core.settings import Settings, SettingsStore
from tests import fixtures as fx


def _phone_identity():
    return fx.identity_output(fx.PHONE_PROPS, fx.FEATURES_PHONE)


def _tv_identity():
    return fx.identity_output(fx.TV_PROPS, fx.FEATURES_TV, "Телевизор в зале")


def make_manager(fake_adb, tmp_path):
    return DeviceManager(fake_adb.runner, Registry(tmp_path / "devices.json"))


def test_tokens_follow_devices_and_merge_usb_with_wifi(fake_adb, tmp_path):
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": fx.DEVICES_MIXED},
        {"args": ["-s", "R58M12ABCDE", "shell", "*"], "stdout": _phone_identity()},
        {"args": ["-s", "adb-R58M12ABCDE-Xy12Ab._adb-tls-connect._tcp", "shell", "*"], "stdout": _phone_identity()},
        {"args": ["-s", "192.168.1.40:5555", "shell", "*"], "stdout": _tv_identity()},
    ])
    manager = make_manager(fake_adb, tmp_path)
    views = {v.key: v for v in manager.refresh()}
    phone = views["R58M12ABCDE"]
    assert phone.state is State.ONLINE and phone.transport is Transport.USB
    assert phone.serial == "R58M12ABCDE" and len(phone.serials) == 2
    assert phone.token == 1 and phone.kind is Kind.PHONE
    assert phone.name == "Samsung SM-G973F"
    tv = views["28041SKV0123"]
    assert tv.token == 2 and tv.transport is Transport.WIFI_LEGACY
    assert tv.legacy_network_open and tv.name == "Телевизор в зале"
    assert views["ZY22BXYZ12"].state is State.UNAUTHORIZED and views["ZY22BXYZ12"].token is None
    assert all(v.key != "emulator-5554" or v.token is None for v in views.values())

    # second refresh uses the identity cache: no extra shell calls
    before = len([c for c in fake_adb.calls() if "shell" in c])
    manager.refresh()
    assert len([c for c in fake_adb.calls() if "shell" in c]) == before

    # tokens survive a restart and the TV shows as disconnected when gone
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": fx.DEVICES_EMPTY}])
    again = {v.key: v for v in make_manager(fake_adb, tmp_path).refresh()}
    assert again["28041SKV0123"].token == 2
    assert again["28041SKV0123"].state is State.DISCONNECTED
    assert again["28041SKV0123"].network.host == "192.168.1.40"
    assert again["28041SKV0123"].network.mode == "legacy"


def test_smallest_free_token_is_reused(tmp_path):
    registry = Registry(tmp_path / "devices.json")
    assert registry.remember("a").token == 1
    assert registry.remember("b").token == 2
    assert registry.remember("c").token == 3
    registry.forget("b")
    assert registry.remember("d").token == 2
    registry.rename("d", "  Планшет  ")
    reloaded = Registry(tmp_path / "devices.json")
    assert reloaded.get("d").alias == "Планшет"
    assert [d.token for d in reloaded.all()] == [1, 2, 3]


def test_registry_survives_corrupt_and_hostile_files(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text("{not json", encoding="utf-8")
    assert Registry(path).all() == []
    path.write_text(json.dumps({"format": "maxondroid.devices", "version": 1, "devices": [
        {"key": "a", "token": 1}, {"key": "b", "token": 1}, {"key": "c", "token": 500}, "junk", {"token": 3},
    ]}), encoding="utf-8")
    assert [d.key for d in Registry(path).all()] == ["a"]


def test_reconnect_uses_mdns_port_and_backs_off(fake_adb, tmp_path):
    registry = Registry(tmp_path / "devices.json")
    from maxondroid.core.registry import NetworkAddress

    registry.remember("R58M12ABCDE", model="SM-G973F", network=NetworkAddress("192.168.1.23", 30000, "paired"))
    registry.remember("28041SKV0123", model="MiTV", network=NetworkAddress("192.168.1.40", 5555, "legacy"))
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": fx.DEVICES_EMPTY},
        {"args": ["mdns", "services"], "stdout": fx.MDNS_SERVICES},
        {"args": ["connect", "192.168.1.23:37159"], "stdout": fx.CONNECT_OK},
        {"args": ["connect", "192.168.1.40:5555"], "stdout": fx.CONNECT_REFUSED},
    ])
    manager = DeviceManager(fake_adb.runner, registry)
    views = manager.refresh()
    tried = manager.reconnect(views, now=1000.0)
    assert set(tried) == {"R58M12ABCDE", "28041SKV0123"}
    assert ["connect", "192.168.1.23:37159"] in fake_adb.calls()
    # the TV failed: not retried before its backoff, the phone succeeded and has none
    assert manager.reconnect(views, now=1005.0) == ["R58M12ABCDE"]
    assert manager.reconnect(views, now=1000.0 + 21) == ["R58M12ABCDE", "28041SKV0123"]


def test_journal_records_with_tokens_and_files(fake_adb, tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    old = folder / "commands-2000-01-01.jsonl"
    old.write_text("{}\n")
    journal = Journal(folder, token_lookup=lambda serial: 7 if serial == "S" else None)
    assert not old.exists()
    fake_adb.set_rules([{"args": ["-s", "S", "reboot"], "stdout": ""}, {"args": ["pair", "*"], "stdout": "x 654321 y"}])
    fake_adb.runner.add_listener(journal.record)
    fake_adb.runner.run(["reboot"], serial="S")
    fake_adb.runner.run(["pair", "1.2.3.4:5", "654321"], secrets=["654321"])
    assert [e.token for e in journal.entries] == [7, None]
    assert journal.entries[0].command == "adb -s S reboot"
    lines = [json.loads(line) for f in folder.glob("commands-*.jsonl") for line in f.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2 and lines[0]["format"] == "maxondroid.command"
    assert all("654321" not in json.dumps(line) for line in lines)


def test_settings_roundtrip_and_bad_values(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.settings == Settings()
    store.settings.language = "en"
    store.settings.theme = "dark"
    store.save()
    assert SettingsStore(tmp_path / "settings.json").settings.theme == "dark"
    (tmp_path / "settings.json").write_text(json.dumps({"format": "maxondroid.settings", "settings": {
        "language": "klingon", "theme": 5, "journal_visible": "yes"}}), encoding="utf-8")
    loaded = SettingsStore(tmp_path / "settings.json").settings
    assert loaded.language == "system" and loaded.theme == "system" and loaded.journal_visible is True


def test_paths_honour_override(isolated_home):
    assert paths.config_dir() == isolated_home / "config"
    assert paths.log_dir() == isolated_home / "logs"
