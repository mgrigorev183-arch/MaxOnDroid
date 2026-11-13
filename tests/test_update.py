import io
import json
from datetime import date

import pytest

from maxondroid.core import net, update
from maxondroid.core.update import Release, UpdateError


def answer(payload, status_bytes=None):
    raw = status_bytes if status_bytes is not None else json.dumps(payload).encode()
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        return io.BytesIO(raw)

    return opener, seen


def test_versions_compare_as_numbers():
    assert update.parse_version("v0.10.0") == (0, 10, 0) and update.parse_version("1.2.3") == (1, 2, 3)
    for bad in ("", "v1", "1.2", "1.2.3-beta", "latest", "v1.2.3.4", "1.2.x"):
        assert update.parse_version(bad) is None, bad
    assert Release("0.10.0", "x").newer_than("0.9.0")
    assert not Release("0.9.0", "x").newer_than("0.9.0")
    assert not Release("0.8.9", "x").newer_than("0.9.0")
    assert not Release("1.0.0", "x").newer_than("garbage")


def test_latest_release_and_the_link_is_always_ours():
    opener, seen = answer({"tag_name": "v0.9.3", "html_url": "https://evil.example/download.exe", "draft": False, "prerelease": False})
    release = update.latest(opener=opener)
    assert release == Release("0.9.3", "https://github.com/mgrigorev183-arch/MaxOnDroid/releases/tag/v0.9.3")
    assert seen["url"] == "https://api.github.com/repos/mgrigorev183-arch/MaxOnDroid/releases/latest"
    assert seen["headers"]["User-agent"].startswith("MaxOnDroid/")
    assert set(seen["headers"]) <= {"User-agent", "Accept"}  # nothing about the user or the devices


@pytest.mark.parametrize("payload", [
    b"not json", b"\xff\xfe", b"[]", b"null",
    json.dumps({"tag_name": "<script>"}).encode(),
    json.dumps({"tag_name": 5}).encode(),
    json.dumps({"tag_name": "v1.0.0", "draft": True}).encode(),
    json.dumps({"tag_name": "v1.0.0", "prerelease": True}).encode(),
])
def test_junk_answers_are_errors(payload):
    opener, _ = answer(None, payload)
    with pytest.raises(UpdateError) as error:
        update.latest(opener=opener)
    assert error.value.code == "bad_response"


def test_network_problems_are_errors(monkeypatch):
    def offline(request, timeout):
        raise OSError("getaddrinfo failed")

    with pytest.raises(UpdateError) as error:
        update.latest(opener=offline)
    assert error.value.code == "network"
    huge, _ = answer(None, b"x" * (update.MAX_BYTES + 10))
    with pytest.raises(UpdateError):
        update.latest(opener=huge)
    with pytest.raises(UpdateError):  # the test suite's own guard: no real network
        update.latest()


def test_https_only_even_after_a_redirect():
    with pytest.raises(net.NetError) as plain:
        net.fetch("http://api.github.com/x", 10)
    assert plain.value.code == "insecure_url"
    handler = net._HttpsOnlyRedirects()
    import urllib.request

    request = urllib.request.Request("https://api.github.com/x")
    with pytest.raises(net.NetError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://evil.example/x")
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://objects.example/x") is not None


def test_once_a_day_and_never_when_off():
    today = date(2026, 11, 13)
    assert update.due(True, "", today)
    assert update.due(True, "2026-11-12", today)
    assert not update.due(True, "2026-11-13", today)
    assert not update.due(False, "", today)


def test_banner_only_for_newer_and_not_after_hiding_that_version():
    newer = Release("0.9.1", "u")
    assert update.should_announce(newer, current="0.9.0")
    assert not update.should_announce(newer, current="0.9.0", dismissed="0.9.1")
    assert update.should_announce(Release("0.9.2", "u"), current="0.9.0", dismissed="0.9.1")
    assert not update.should_announce(Release("0.9.0", "u"), current="0.9.0")


def test_update_module_has_no_download_or_run_code():
    import inspect

    source = inspect.getsource(update)
    for forbidden in ("subprocess", "os.startfile", "urlretrieve", "write_bytes", ".exe\"", "browser_download_url"):
        assert forbidden not in source, forbidden
