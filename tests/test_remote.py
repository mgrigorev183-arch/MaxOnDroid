import pytest

from maxondroid.core import remote

SERIAL = "192.168.1.40:5555"


def test_press_sends_whitelisted_keycode(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stdout": ""}])
    remote.press(fake_adb.runner, SERIAL, "up")
    remote.press(fake_adb.runner, SERIAL, "home", long=True)
    assert [c[3] for c in fake_adb.calls()] == ["input keyevent KEYCODE_DPAD_UP", "input keyevent --longpress KEYCODE_HOME"]


@pytest.mark.parametrize("key", ["KEYCODE_HOME", "reboot", "up; reboot", ""])
def test_unknown_keys_never_reach_adb(fake_adb, key):
    with pytest.raises(remote.UnknownKeyError):
        remote.press(fake_adb.runner, SERIAL, key)
    assert fake_adb.calls() == []


def test_every_key_maps_to_a_keycode_name():
    assert all(code.startswith("KEYCODE_") and code.replace("_", "").isalnum() for code in remote.KEYS.values())
    assert len(remote.KEYS) >= 25


def test_text_spaces_and_quoting(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stdout": ""}])
    assert remote.type_text(fake_adb.runner, SERIAL, "it's 50% off; reboot").ok
    assert fake_adb.calls()[0][3] == "input text 'it'\"'\"'s%s50%%soff;%sreboot'"


def test_long_text_is_split():
    text = "a" * 200
    chunks = remote.text_chunks(text)
    assert [len(c) for c in chunks] == [80, 80, 40]


@pytest.mark.parametrize("text, bad", [("Привет", "Привет"), ("ok 👍", "👍"), ("tab\there", "\t")])
def test_non_latin_text_is_refused(fake_adb, text, bad):
    with pytest.raises(remote.TextNotSupportedError) as err:
        remote.type_text(fake_adb.runner, SERIAL, text)
    assert err.value.characters == bad
    assert fake_adb.calls() == []


def test_text_stops_at_first_failure(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stderr": "error: closed", "rc": 1}])
    result = remote.type_text(fake_adb.runner, SERIAL, "b" * 170)
    assert not result.ok and len(result.results) == 1
