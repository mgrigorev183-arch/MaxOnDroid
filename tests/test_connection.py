import pytest

from maxondroid.core import connection, validate
from maxondroid.core.connection import Outcome
from tests import fixtures as fx


def test_connect_reads_text_not_exit_code(fake_adb):
    fake_adb.set_rules([
        {"args": ["connect", "192.168.1.23:37159"], "stdout": fx.CONNECT_OK},
        {"args": ["connect", "192.168.1.40:5555"], "stdout": fx.CONNECT_ALREADY},
        {"args": ["connect", "192.168.1.99:5555"], "stdout": fx.CONNECT_REFUSED, "rc": 0},
    ])
    assert connection.connect(fake_adb.runner, "192.168.1.23", 37159).outcome is Outcome.OK
    assert connection.connect(fake_adb.runner, "192.168.1.40", 5555).outcome is Outcome.ALREADY
    refused = connection.connect(fake_adb.runner, "192.168.1.99", 5555)
    assert refused.outcome is Outcome.REFUSED and not refused.ok


def test_connect_validates_before_running(fake_adb):
    with pytest.raises(validate.ValidationError) as err:
        connection.connect(fake_adb.runner, "-s evil", 5555)
    assert err.value.code == "host_invalid"
    with pytest.raises(validate.ValidationError):
        connection.connect(fake_adb.runner, "192.168.1.5", 70000)
    assert fake_adb.calls() == []


def test_pair_and_connect_with_code_finds_connect_port(fake_adb):
    fake_adb.set_rules([
        {"args": ["pair", "192.168.1.23:41231", "482913"], "stdout": fx.PAIR_OK},
        {"args": ["mdns", "services"], "stdout": fx.MDNS_SERVICES},
        {"args": ["connect", "192.168.1.23:37159"], "stdout": fx.CONNECT_OK},
    ])
    seen = []
    fake_adb.runner.add_listener(seen.append)
    paired, connected = connection.pair_and_connect(fake_adb.runner, "192.168.1.23", 41231, "482913", sleep=lambda s: None)
    assert paired.outcome is Outcome.OK and paired.guid == "adb-R58M12ABCDE-Xy12Ab"
    assert connected is not None and connected.outcome is Outcome.OK
    assert connected.endpoint == "192.168.1.23:37159"
    assert all("482913" not in r.display_command() and "482913" not in r.display_output() for r in seen)


def test_pair_wrong_code(fake_adb):
    fake_adb.set_rules([{"args": ["pair", "*"], "stdout": fx.PAIR_BAD, "rc": 1}])
    paired, connected = connection.pair_and_connect(fake_adb.runner, "192.168.1.23", 41231, "000000")
    assert paired.outcome is Outcome.BAD_CODE and connected is None


def test_pair_then_no_connect_service(fake_adb):
    fake_adb.set_rules([
        {"args": ["pair", "*"], "stdout": fx.PAIR_OK},
        {"args": ["mdns", "services"], "stdout": "List of discovered mdns services\n"},
    ])
    clock = iter(range(0, 1000, 5))
    paired, connected = connection.pair_and_connect(
        fake_adb.runner, "192.168.1.23", 41231, "482913", sleep=lambda s: None, clock=lambda: next(clock)
    )
    assert paired.ok and connected.outcome is Outcome.NOT_FOUND


def test_explicit_connect_port_skips_discovery(fake_adb):
    fake_adb.set_rules([
        {"args": ["pair", "*"], "stdout": fx.PAIR_OK},
        {"args": ["connect", "192.168.1.23:40000"], "stdout": "connected to 192.168.1.23:40000\n"},
    ])
    _, connected = connection.pair_and_connect(fake_adb.runner, "192.168.1.23", 41231, "482913", connect_port=40000)
    assert connected.ok
    assert ["mdns", "services"] not in fake_adb.calls()


def test_qr_session_payload_and_flow(fake_adb):
    session = connection.new_qr_session()
    assert session.payload == f"WIFI:T:ADB;S:{session.name};P:{session.password};;"
    assert session.name.startswith("maxondroid-") and len(session.password) == 12
    assert session.password.isalnum() and session.name.replace("-", "").isalnum()
    services_after_scan = fx.MDNS_SERVICES.replace("maxondroid-AbCdEfGh", session.name)
    fake_adb.set_rules([
        {"args": ["mdns", "services"], "responses": [
            {"stdout": "List of discovered mdns services\n"},
            {"stdout": services_after_scan},
        ]},
        {"args": ["pair", "192.168.1.23:41231", session.password], "stdout": fx.PAIR_OK},
        {"args": ["connect", "192.168.1.23:37159"], "stdout": fx.CONNECT_OK},
    ])
    paired, connected = connection.qr_pair_and_connect(fake_adb.runner, session, timeout=60, sleep=lambda s: None)
    assert paired.ok and connected.ok


def test_qr_flow_can_be_cancelled(fake_adb):
    fake_adb.set_rules([{"args": ["mdns", "services"], "stdout": "List of discovered mdns services\n"}])
    paired, connected = connection.qr_pair_and_connect(
        fake_adb.runner, connection.new_qr_session(), timeout=60, sleep=lambda s: None, cancelled=lambda: True
    )
    assert paired.outcome is Outcome.NOT_FOUND and connected is None


def test_legacy_mode_toggles(fake_adb):
    fake_adb.set_rules([
        {"args": ["-s", "R58M", "tcpip", "5555"], "stdout": "restarting in TCP mode port: 5555\n"},
        {"args": ["-s", "192.168.1.40:5555", "usb"], "stdout": "restarting in USB mode\n"},
    ])
    assert connection.enable_legacy_tcpip(fake_adb.runner, "R58M").ok
    assert connection.disable_network_adb(fake_adb.runner, "192.168.1.40:5555").ok


@pytest.mark.parametrize("text, expected", [
    ("192.168.1.5", ("192.168.1.5", 5555)),
    ("192.168.1.5:41000", ("192.168.1.5", 41000)),
    ("[fe80::1]:5555", ("fe80::1", 5555)),
    ("my-tv.local", ("my-tv.local", 5555)),
])
def test_split_endpoint(text, expected):
    assert validate.split_endpoint(text, 5555) == expected


@pytest.mark.parametrize("bad", ["", "-s", "a b", "999.1.1.1", "host:0", "host:abc", "1.2.3.4:5:6"])
def test_split_endpoint_rejects(bad):
    with pytest.raises(validate.ValidationError):
        validate.split_endpoint(bad, 5555)


def test_pair_code_validation():
    assert validate.pair_code(" 482 913 ") == "482913"
    for bad in ("12345", "abcdef", "1234567"):
        with pytest.raises(validate.ValidationError):
            validate.pair_code(bad)
