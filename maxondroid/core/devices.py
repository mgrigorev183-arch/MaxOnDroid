"""Parsing ``adb devices -l`` and describing how a device is connected."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class State(StrEnum):
    ONLINE = "device"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    AUTHORIZING = "authorizing"
    CONNECTING = "connecting"
    NO_PERMISSIONS = "no permissions"
    RECOVERY = "recovery"
    SIDELOAD = "sideload"
    BOOTLOADER = "bootloader"
    RESCUE = "rescue"
    HOST = "host"
    DISCONNECTED = "disconnected"  # saved device that adb does not see right now
    UNKNOWN = "unknown"


class Transport(StrEnum):
    USB = "usb"
    WIFI_PAIRED = "wifi-paired"  # Android 11+ wireless debugging (TLS, paired)
    WIFI_LEGACY = "wifi-legacy"  # adb tcpip: anyone on the network can connect
    WIFI = "wifi"  # network, mode not known yet
    EMULATOR = "emulator"


_KNOWN_STATES = sorted((s.value for s in State), key=len, reverse=True)
_KV = re.compile(r"^(usb|product|model|device|transport_id|features):(.*)$")
_IP_PORT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}|\[[0-9A-Fa-f:]+\]):(\d{1,5})$")
_TLS_SERVICE = re.compile(r"^(adb-.+)\._adb-tls-connect\._tcp\.?$")


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: State
    usb: str | None = None
    product: str | None = None
    model: str | None = None
    device: str | None = None
    transport_id: str | None = None
    state_detail: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def transport(self) -> Transport:
        return guess_transport(self.serial, self.usb)

    @property
    def network_endpoint(self) -> tuple[str, int] | None:
        match = _IP_PORT.match(self.serial)
        if not match:
            return None
        return match.group(1).strip("[]"), int(match.group(2))

    @property
    def mdns_instance(self) -> str | None:
        match = _TLS_SERVICE.match(self.serial)
        return match.group(1) if match else None


def guess_transport(serial: str, usb: str | None = None) -> Transport:
    if serial.startswith("emulator-"):
        return Transport.EMULATOR
    if _TLS_SERVICE.match(serial):
        return Transport.WIFI_PAIRED
    if _IP_PORT.match(serial):
        return Transport.WIFI
    return Transport.USB


def parse_devices(output: str) -> list[AdbDevice]:
    """Parse the text printed by ``adb devices -l``."""
    devices: list[AdbDevice] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        if line.startswith("adb server") or line.startswith("daemon"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        serial, rest = parts[0], parts[1].strip()
        state = State.UNKNOWN
        detail = ""
        for known in _KNOWN_STATES:
            if rest == known or rest.startswith(known + " ") or rest.startswith(known + "\t"):
                state = State(known)
                rest = rest[len(known) :].strip()
                break
        if state is State.UNKNOWN:
            # a state this code does not know (newer adb): keep its word for the user, parse the rest
            word, _, remainder = rest.partition(" ")
            if not _KV.match(word):
                detail, rest = word, remainder.strip()
        if state is State.NO_PERMISSIONS and rest.startswith("("):
            # "no permissions (user ... not in the plugdev group); see [http://...]"
            end = rest.find("]")
            end = rest.find(")") if end == -1 else end
            detail = rest[: end + 1] if end != -1 else rest
            rest = rest[end + 1 :].strip() if end != -1 else ""
        values: dict[str, str] = {}
        for token in rest.split():
            kv = _KV.match(token)
            if kv:
                values[kv.group(1)] = kv.group(2)
        devices.append(
            AdbDevice(
                serial=serial,
                state=state,
                usb=values.get("usb"),
                product=values.get("product"),
                model=(values.get("model") or "").replace("_", " ") or None,
                device=values.get("device"),
                transport_id=values.get("transport_id"),
                state_detail=detail,
            )
        )
    return devices
