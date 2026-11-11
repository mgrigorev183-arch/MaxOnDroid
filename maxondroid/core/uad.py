"""The Universal Android Debloater (UAD-ng) package database.

A snapshot ships with MaxOnDroid (``maxondroid/data/uad``). The user can
download the current file from the UAD-ng repository on GitHub; that copy is
kept in the local data folder and used when it is valid. This module holds the
only network code in MaxOnDroid, and it runs only when the user presses
"Update database".
"""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from maxondroid.core.jsonstore import read_json, write_json_atomic

UAD_URL = (
    "https://raw.githubusercontent.com/Universal-Debloater-Alliance/"
    "universal-android-debloater-next-generation/main/resources/assets/uad_lists.json"
)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MIN_ENTRIES = 500  # anything smaller is not the real list


class Removal(StrEnum):
    RECOMMENDED = "Recommended"
    ADVANCED = "Advanced"
    EXPERT = "Expert"
    UNSAFE = "Unsafe"
    UNLISTED = "Unlisted"  # not in the database


REMOVAL_ORDER = [Removal.RECOMMENDED, Removal.ADVANCED, Removal.EXPERT, Removal.UNSAFE, Removal.UNLISTED]


class Source(StrEnum):
    BUNDLED = "bundled"
    DOWNLOADED = "downloaded"


@dataclass(frozen=True)
class Entry:
    package: str
    list: str  # Oem, Google, Aosp, Carrier, Misc, ...
    description: str
    removal: Removal
    dependencies: tuple[str, ...] = ()
    needed_by: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """First line of the description, without links."""
        for line in self.description.splitlines():
            line = line.strip()
            if line and not line.startswith("http"):
                return line
        return ""


@dataclass(frozen=True)
class Database:
    entries: dict[str, Entry]
    source: Source
    date: str  # ISO date of the snapshot or download
    sha256: str

    def get(self, package: str) -> Entry | None:
        return self.entries.get(package)


class DatabaseError(RuntimeError):
    """``code`` is a stable key the UI translates."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _strings(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def parse(raw: bytes) -> dict[str, Entry]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DatabaseError("invalid_json", str(exc)) from exc
    if not isinstance(data, dict):
        raise DatabaseError("invalid_format")
    entries: dict[str, Entry] = {}
    for package, value in data.items():
        if not isinstance(package, str) or not isinstance(value, dict):
            continue
        description = value.get("description")
        removal = value.get("removal")
        group = value.get("list")
        if not isinstance(description, str) or not isinstance(group, str):
            continue
        try:
            level = Removal(removal)
        except ValueError:
            continue
        entries[package] = Entry(
            package=package,
            list=group,
            description=description.strip(),
            removal=level,
            dependencies=_strings(value.get("dependencies")),
            needed_by=_strings(value.get("neededBy")),
            labels=_strings(value.get("labels")),
        )
    if len(entries) < MIN_ENTRIES:
        raise DatabaseError("too_small", str(len(entries)))
    return entries


def _load_file(path: Path, source: Source, date: str) -> Database:
    raw = path.read_bytes()
    return Database(parse(raw), source, date, hashlib.sha256(raw).hexdigest())


def load(bundled_dir: Path, downloaded_dir: Path) -> Database:
    """The downloaded copy when it is valid, otherwise the bundled snapshot."""
    downloaded = downloaded_dir / "uad_lists.json"
    meta = read_json(downloaded_dir / "uad_lists.meta.json") or {}
    if downloaded.is_file():
        try:
            db = _load_file(downloaded, Source.DOWNLOADED, str(meta.get("date", "")))
            if not meta.get("sha256") or meta.get("sha256") == db.sha256:
                return db
        except (OSError, DatabaseError):
            pass
    source = read_json(bundled_dir / "SOURCE.json") or {}
    return _load_file(bundled_dir / "uad_lists.json", Source.BUNDLED, str(source.get("retrieved", "")))


def download(downloaded_dir: Path, url: str = UAD_URL, timeout: float = 30.0, opener=None) -> Database:
    """Fetch the current list over HTTPS, check it, and keep it next to its checksum."""
    if not url.startswith("https://"):
        raise DatabaseError("insecure_url", url)
    request = urllib.request.Request(url, headers={"User-Agent": "MaxOnDroid"})
    open_url = opener or (lambda req, t: urllib.request.urlopen(req, timeout=t, context=ssl.create_default_context()))
    try:
        with open_url(request, timeout) as response:
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except OSError as exc:  # URLError, HTTPError and socket errors are all OSError
        raise DatabaseError("network", str(exc)) from exc
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise DatabaseError("too_large")
    entries = parse(raw)
    downloaded_dir.mkdir(parents=True, exist_ok=True)
    target = downloaded_dir / "uad_lists.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    tmp.replace(target)
    digest = hashlib.sha256(raw).hexdigest()
    date = datetime.now(UTC).date().isoformat()
    write_json_atomic(downloaded_dir / "uad_lists.meta.json", {"url": url, "date": date, "sha256": digest, "entries": len(entries)})
    return Database(entries, Source.DOWNLOADED, date, digest)
