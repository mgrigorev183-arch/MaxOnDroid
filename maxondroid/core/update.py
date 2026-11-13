"""Is there a newer MaxOnDroid? Only tells and links; never downloads or installs anything.

One HTTPS request to GitHub's public API for the latest release of this
repository, at most once a day and only while "check for updates" is on in
the settings (and whenever the user asks from the Help menu). The answer is
treated as untrusted: the version must look like a version, and the link
shown is always this repository's release page, whatever the answer says.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from maxondroid import __version__
from maxondroid.core import net

REPOSITORY = "mgrigorev183-arch/MaxOnDroid"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
MAX_BYTES = 512 * 1024
_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


class UpdateError(RuntimeError):
    """``code``: network, bad_response."""

    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(text.strip())
    return tuple(int(g) for g in match.groups()) if match else None  # type: ignore[return-value]


@dataclass(frozen=True)
class Release:
    version: str  # "0.9.1"
    url: str  # always under RELEASES_PAGE

    def newer_than(self, current: str) -> bool:
        mine, theirs = parse_version(current), parse_version(self.version)
        return bool(mine and theirs and theirs > mine)


def parse_release(raw: bytes) -> Release:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("bad_response", "not JSON") from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("bad_response", "no published release")
    tag = data.get("tag_name")
    version = parse_version(tag) if isinstance(tag, str) else None
    if version is None:
        raise UpdateError("bad_response", f"unexpected tag {str(tag)[:40]!r}")
    text = ".".join(map(str, version))
    # the link is built here, never taken from the answer
    return Release(text, f"{RELEASES_PAGE}/tag/v{text}")


def latest(opener=None, timeout: float = 15.0) -> Release:
    try:
        raw = net.fetch(API_URL, MAX_BYTES, timeout=timeout, headers={"Accept": "application/vnd.github+json"}, opener=opener)
    except net.NetError as exc:
        raise UpdateError("network", exc.details or exc.code) from exc
    return parse_release(raw)


def due(enabled: bool, last_check: str, today: date | None = None) -> bool:
    """The automatic check runs once a day, and never when turned off."""
    today = today or date.today()
    return enabled and last_check != today.isoformat()


def should_announce(release: Release, current: str = __version__, dismissed: str = "") -> bool:
    """A banner for a newer version, unless the user hid the banner for exactly that version."""
    return release.newer_than(current) and release.version != dismissed
