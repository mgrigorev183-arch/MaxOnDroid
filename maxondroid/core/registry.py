"""Saved devices: the numbered "cloakroom tokens", names and last addresses.

File: ``devices.json`` in the config folder. Format (documented in
docs/formats.md)::

    {
      "format": "maxondroid.devices",
      "version": 1,
      "devices": [
        {"key": "R58M12345", "token": 1, "alias": "Телефон Маши",
         "model": "SM-G973F", "manufacturer": "samsung", "kind": "phone",
         "network": {"host": "192.168.1.23", "port": 37159, "mode": "paired"},
         "mdns_name": "adb-R58M12345-AbCdEf",
         "first_seen": "2026-11-10T20:00:00+00:00",
         "last_seen": "2026-11-10T21:00:00+00:00"}
      ]
    }
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from maxondroid.core.jsonstore import read_json, write_json_atomic

FORMAT = "maxondroid.devices"
VERSION = 1
MAX_TOKEN = 99


@dataclass
class NetworkAddress:
    host: str
    port: int
    mode: str  # "paired" (wireless debugging) or "legacy" (adb tcpip)


@dataclass
class SavedDevice:
    key: str
    token: int
    alias: str = ""
    model: str | None = None
    manufacturer: str | None = None
    kind: str = "unknown"
    network: NetworkAddress | None = None
    mdns_name: str | None = None
    legacy_risk_accepted: bool = False  # the owner accepted open network adb on this device
    first_seen: str = ""
    last_seen: str = ""
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        data = asdict(self)
        extra = data.pop("extra")
        data.update({k: v for k, v in extra.items() if k not in data})
        return data

    @classmethod
    def from_json(cls, data: dict) -> SavedDevice | None:
        try:
            key = str(data["key"])
            token = int(data["token"])
        except (KeyError, TypeError, ValueError):
            return None
        if not key or not 1 <= token <= MAX_TOKEN:
            return None
        network = None
        raw_net = data.get("network")
        if isinstance(raw_net, dict):
            try:
                network = NetworkAddress(str(raw_net["host"]), int(raw_net["port"]), str(raw_net.get("mode", "paired")))
            except (KeyError, TypeError, ValueError):
                network = None
        known = {"key", "token", "alias", "model", "manufacturer", "kind", "network", "mdns_name", "legacy_risk_accepted", "first_seen", "last_seen"}
        return cls(
            key=key,
            token=token,
            alias=str(data.get("alias") or ""),
            model=data.get("model"),
            manufacturer=data.get("manufacturer"),
            kind=str(data.get("kind") or "unknown"),
            network=network,
            mdns_name=data.get("mdns_name"),
            legacy_risk_accepted=data.get("legacy_risk_accepted") is True,
            first_seen=str(data.get("first_seen") or ""),
            last_seen=str(data.get("last_seen") or ""),
            extra={k: v for k, v in data.items() if k not in known},
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._devices: dict[str, SavedDevice] = {}
        self.load()

    def load(self) -> None:
        data = read_json(self.path)
        devices: dict[str, SavedDevice] = {}
        used: set[int] = set()
        if isinstance(data, dict) and data.get("format") == FORMAT and isinstance(data.get("devices"), list):
            for raw in data["devices"]:
                if not isinstance(raw, dict):
                    continue
                saved = SavedDevice.from_json(raw)
                if saved and saved.key not in devices and saved.token not in used:
                    devices[saved.key] = saved
                    used.add(saved.token)
        with self._lock:
            self._devices = devices

    def save(self) -> None:
        with self._lock:
            payload = {
                "format": FORMAT,
                "version": VERSION,
                "devices": [d.to_json() for d in sorted(self._devices.values(), key=lambda d: d.token)],
            }
        write_json_atomic(self.path, payload)

    def all(self) -> list[SavedDevice]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: d.token)

    def get(self, key: str) -> SavedDevice | None:
        with self._lock:
            return self._devices.get(key)

    def next_token(self) -> int | None:
        with self._lock:
            used = {d.token for d in self._devices.values()}
        for number in range(1, MAX_TOKEN + 1):
            if number not in used:
                return number
        return None

    def remember(self, key: str, **fields) -> SavedDevice | None:
        """Add a device (giving it the smallest free token) or update it. Saves to disk."""
        with self._lock:
            saved = self._devices.get(key)
            changed = saved is None
            if saved is None:
                token = self.next_token()
                if token is None:
                    return None
                saved = SavedDevice(key=key, token=token, first_seen=_now())
                self._devices[key] = saved
            for name, value in fields.items():
                if value is None or not hasattr(saved, name):
                    continue
                if getattr(saved, name) != value:
                    setattr(saved, name, value)
                    changed = True
            saved.last_seen = _now()
            if changed:
                self.save()
            return saved

    def touch(self, key: str) -> None:
        with self._lock:
            saved = self._devices.get(key)
            if saved:
                saved.last_seen = _now()

    def rename(self, key: str, alias: str) -> None:
        with self._lock:
            saved = self._devices.get(key)
            if saved is None:
                return
            saved.alias = alias.strip()[:60]
        self.save()

    def set_risk_accepted(self, key: str, accepted: bool) -> None:
        with self._lock:
            saved = self._devices.get(key)
            if saved is None:
                return
            saved.legacy_risk_accepted = accepted
        self.save()

    def forget(self, key: str) -> None:
        with self._lock:
            self._devices.pop(key, None)
        self.save()
