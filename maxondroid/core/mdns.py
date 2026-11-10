"""Devices that announce themselves on the local network (``adb mdns services``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from maxondroid.core.adb import AdbRunner


class ServiceKind(StrEnum):
    CONNECT = "connect"  # _adb-tls-connect: paired device ready to connect
    PAIRING = "pairing"  # _adb-tls-pairing: "pair with code/QR" screen is open
    LEGACY = "legacy"  # _adb: adb tcpip mode
    OTHER = "other"


_TYPES = {
    "_adb-tls-connect._tcp": ServiceKind.CONNECT,
    "_adb-tls-pairing._tcp": ServiceKind.PAIRING,
    "_adb._tcp": ServiceKind.LEGACY,
}
_ADDR = re.compile(r"^(.*):(\d{1,5})$")


@dataclass(frozen=True)
class MdnsService:
    name: str
    kind: ServiceKind
    host: str
    port: int

    @property
    def device_serial(self) -> str | None:
        """``adb-<serialno>-<random>`` -> ``<serialno>`` when the name has that shape."""
        if self.name.startswith("adb-") and self.name.count("-") >= 2:
            return self.name[4:].rsplit("-", 1)[0]
        return None


def parse_services(output: str) -> list[MdnsService]:
    services: list[MdnsService] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("list of discovered"):
            continue
        fields = line.split("\t") if "\t" in line else line.split()
        fields = [f.strip() for f in fields if f.strip()]
        if len(fields) < 3:
            continue
        name, service_type, address = fields[0], fields[1].rstrip("."), fields[-1]
        match = _ADDR.match(address)
        if not match:
            continue
        host = match.group(1).strip("[]")
        port = int(match.group(2))
        if not 0 < port < 65536:
            continue
        services.append(MdnsService(name, _TYPES.get(service_type, ServiceKind.OTHER), host, port))
    return services


def discover(runner: AdbRunner, log: bool = False) -> list[MdnsService]:
    result = runner.run(["mdns", "services"], timeout=10, log=log)
    if not result.ok:
        return []
    return parse_services(result.stdout)
