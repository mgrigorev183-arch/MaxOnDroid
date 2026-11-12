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


A35 = "RFCX30397DJ"
A35_MDNS = f"adb-{A35}-i2nRnr._adb-tls-connect._tcp"
A35_PROPS = fx.PHONE_PROPS.replace("SM-G973F", "SM-A356E").replace("R58M12ABCDE", A35)


def test_old_address_and_unknown_state_fold_into_the_phone_and_get_dropped(fake_adb, tmp_path):
    """The report: a phone on wireless debugging showed twice, the second row "SM A356E · unknown"."""
    from maxondroid.core.registry import NetworkAddress

    registry = Registry(tmp_path / "devices.json")
    registry.remember(A35, model="SM-A356E", network=NetworkAddress("192.168.1.23", 37159, "paired"))
    listing = (
        "List of devices attached\n"
        f"{A35_MDNS} device product:a35x model:SM_A356E device:a35x transport_id:9\n"
        "192.168.1.23:41055      detached product:a35x model:SM_A356E device:a35x transport_id:7\n"
        "192.168.1.23:39999      offline transport_id:5\n\n"
    )
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": listing},
        {"args": ["-s", A35_MDNS, "shell", "*"], "stdout": fx.identity_output(A35_PROPS, fx.FEATURES_PHONE, "MaxonTelephone")},
        {"args": ["disconnect", "*"], "stdout": "disconnected\n"},
    ])
    manager = DeviceManager(fake_adb.runner, registry)
    views = manager.refresh()
    assert [v.key for v in views] == [A35]
    (phone,) = views
    assert phone.online and phone.serial == A35_MDNS and phone.name == "MaxonTelephone"
    assert set(phone.serials) == {A35_MDNS, "192.168.1.23:41055", "192.168.1.23:39999"}
    assert sorted(manager.prune()) == ["192.168.1.23:39999", "192.168.1.23:41055"]
    assert ["disconnect", "192.168.1.23:41055"] in fake_adb.calls()
    assert manager.prune() == []  # nothing left from that refresh


def test_unknown_entry_without_a_matching_device_still_shows_its_state(fake_adb, tmp_path):
    fake_adb.set_rules([{"args": ["devices", "-l"], "stdout": "List of devices attached\n10.0.0.9:5555 detached model:X1\n\n"}])
    (view,) = make_manager(fake_adb, tmp_path).refresh()
    assert view.state is State.UNKNOWN and view.state_detail == "detached"


def test_ip_duplicate_of_an_mdns_phone_is_dropped_unless_in_use(fake_adb, tmp_path):
    listing = (
        "List of devices attached\n"
        "192.168.1.23:37159      device product:a35x model:SM_A356E device:a35x transport_id:4\n"
        f"{A35_MDNS} device product:a35x model:SM_A356E device:a35x transport_id:9\n\n"
    )
    identity = fx.identity_output(A35_PROPS, fx.FEATURES_PHONE)
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": listing},
        {"args": ["-s", "*"], "stdout": identity},
        {"args": ["disconnect", "*"], "stdout": "disconnected\n"},
    ])
    manager = make_manager(fake_adb, tmp_path)
    (phone,) = manager.refresh()
    assert phone.serial == A35_MDNS  # the mDNS connection is the one commands use
    assert manager.prune(in_use={"192.168.1.23:37159"}) == []  # a scrcpy window uses it: keep
    manager.refresh()
    assert manager.prune() == ["192.168.1.23:37159"]


def test_failed_identity_is_not_retried_on_every_poll(fake_adb, tmp_path):
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": "List of devices attached\n192.168.1.40:5555 device product:x model:MiTV device:x transport_id:1\n\n"},
        {"args": ["-s", "192.168.1.40:5555", "shell", "*"], "stdout": "", "rc": 1},
    ])
    manager = make_manager(fake_adb, tmp_path)

    def shells():
        return len([c for c in fake_adb.calls() if "shell" in c])

    manager.refresh(now=100.0)
    assert shells() == 1
    manager.refresh(now=103.0)
    assert shells() == 1  # 5 s after the first failure
    manager.refresh(now=106.0)
    assert shells() == 2
    manager.refresh(now=115.0)
    assert shells() == 2  # 15 s after the second
    manager.refresh(now=122.0)
    assert shells() == 3
    for now in (130.0, 140.0, 150.0):
        manager.refresh(now=now)
    assert shells() == 3  # then every 30 s, not every 2.5 s poll
    manager.refresh(now=153.0)
    assert shells() == 4
    # the device drops and comes back: asked at once
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": "List of devices attached\n192.168.1.40:5555 offline\n\n"},
    ])
    manager.refresh(now=154.0)
    fake_adb.set_rules([
        {"args": ["devices", "-l"], "stdout": "List of devices attached\n192.168.1.40:5555 device product:x model:MiTV device:x transport_id:1\n\n"},
        {"args": ["-s", "192.168.1.40:5555", "shell", "*"], "stdout": "", "rc": 1},
    ])
    manager.refresh(now=155.0)
    assert shells() == 5


def test_reconnect_connect_timeout_is_short():
    assert DeviceManager.CONNECT_TIMEOUT <= 5 and DeviceManager.IDENTITY_TIMEOUT <= 10
    assert DeviceManager.IDENTITY_RETRY[-1] >= 30
