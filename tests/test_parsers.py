from maxondroid.core import info, mdns
from maxondroid.core.devices import State, Transport, parse_devices
from tests import fixtures as fx


def test_parse_devices_mixed_states():
    devices = {d.serial: d for d in parse_devices(fx.DEVICES_MIXED)}
    assert set(devices) == {
        "R58M12ABCDE",
        "192.168.1.40:5555",
        "adb-R58M12ABCDE-Xy12Ab._adb-tls-connect._tcp",
        "ZY22BXYZ12",
        "emulator-5554",
        "0123ABCD",
    }
    usb = devices["R58M12ABCDE"]
    assert usb.state is State.ONLINE and usb.transport is Transport.USB
    assert usb.model == "SM G973F" and usb.usb == "1-4" and usb.transport_id == "3"
    tv = devices["192.168.1.40:5555"]
    assert tv.transport is Transport.WIFI and tv.network_endpoint == ("192.168.1.40", 5555)
    tls = devices["adb-R58M12ABCDE-Xy12Ab._adb-tls-connect._tcp"]
    assert tls.transport is Transport.WIFI_PAIRED and tls.mdns_instance == "adb-R58M12ABCDE-Xy12Ab"
    assert devices["ZY22BXYZ12"].state is State.UNAUTHORIZED
    assert devices["emulator-5554"].transport is Transport.EMULATOR
    perm = devices["0123ABCD"]
    assert perm.state is State.NO_PERMISSIONS
    assert "plugdev" in perm.state_detail and perm.usb == "1-3"


def test_parse_devices_empty_and_daemon_noise():
    noise = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n" + fx.DEVICES_EMPTY
    assert parse_devices(noise) == []


def test_parse_mdns_services():
    services = mdns.parse_services(fx.MDNS_SERVICES)
    assert [(s.name, s.kind, s.host, s.port) for s in services] == [
        ("adb-R58M12ABCDE-Xy12Ab", mdns.ServiceKind.CONNECT, "192.168.1.23", 37159),
        ("maxondroid-AbCdEfGh", mdns.ServiceKind.PAIRING, "192.168.1.23", 41231),
        ("adb-28041SKV0123", mdns.ServiceKind.LEGACY, "192.168.1.40", 5555),
    ]
    assert services[0].device_serial == "R58M12ABCDE"


def test_parse_phone_info():
    data = info.parse_info(fx.info_output(fx.PHONE_PROPS, fx.PHONE_BATTERY, fx.FEATURES_PHONE, "Galaxy S10 Маши"))
    ident = data.identity
    assert ident.serialno == "R58M12ABCDE"
    assert ident.kind is info.Kind.PHONE
    assert ident.device_name == "Galaxy S10 Маши"
    assert ident.legacy_network_open is False
    assert data.android_version == "12" and data.sdk == 31
    assert data.security_patch == "2024-01-01"
    assert data.wireless_debugging is True
    assert data.props["ro.multiline.example"] == "first line\nsecond line"
    bat = data.battery
    assert bat.present and bat.level == 87 and bat.temperature_c == 29.6
    assert bat.status is info.BatteryStatus.CHARGING and bat.powered_by == ("usb",)
    assert data.storage == info.Storage(115266384, 28393856, 86741424)
    assert data.memory == info.Memory(7678772, 3456780)
    assert data.screen_size == "1080x2400" and data.screen_density == 420
    assert data.addresses[0] == ("wlan0", "192.168.1.23")
    assert ("lo", "127.0.0.1") not in data.addresses


def test_parse_tv_info_marks_legacy_network_and_no_battery():
    data = info.parse_info(fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV))
    assert data.identity.kind is info.Kind.TV
    assert data.identity.legacy_tcp_port == 5555
    assert data.identity.device_name is None
    assert data.battery.present is False and data.battery.level is None
    assert data.wireless_debugging is False


def test_tv_detected_from_features_alone():
    props = fx.TV_PROPS.replace("[ro.build.characteristics]: [tv]", "[ro.build.characteristics]: [default]")
    assert info.parse_info(fx.info_output(props, fx.TV_BATTERY, fx.FEATURES_TV)).identity.kind is info.Kind.TV


def test_df_variants():
    assert info.parse_df(fx.DF_TOYBOX_WRAPPED) == info.Storage(25196544, 9123456, 16073088)
    toolbox = info.parse_df(fx.DF_TOOLBOX)
    assert toolbox.total_kb == int(25.1 * 1024 * 1024)
    assert info.parse_df("") is None
    assert info.parse_df("df: /data: Permission denied") is None


def test_legacy_port_ignores_zero_and_minus_one():
    assert info.legacy_tcp_port({"service.adb.tcp.port": "0"}) is None
    assert info.legacy_tcp_port({"service.adb.tcp.port": "-1", "persist.adb.tcp.port": ""}) is None
    assert info.legacy_tcp_port({"persist.adb.tcp.port": "5555"}) == 5555


def test_placeholder_serial_is_ignored():
    props = "[ro.serialno]: [0123456789ABCDEF]\n[ro.product.model]: [Box]\n"
    assert info.parse_identity(info.split_sections(fx.identity_output(props, ""))).serialno is None


def test_scripts_are_single_line_constants():
    for script in (info.INFO_SCRIPT, info.IDENTITY_SCRIPT):
        assert "\n" not in script and script.endswith("echo @@end")
