"""Reading a device's state for the Overview tab, in one adb round trip."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from maxondroid.core.adb import AdbResult, AdbRunner


class Kind(StrEnum):
    PHONE = "phone"
    TABLET = "tablet"
    TV = "tv"
    WATCH = "watch"
    UNKNOWN = "unknown"


class BatteryStatus(StrEnum):
    CHARGING = "charging"
    DISCHARGING = "discharging"
    NOT_CHARGING = "not_charging"
    FULL = "full"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Battery:
    present: bool
    level: int | None = None
    temperature_c: float | None = None
    status: BatteryStatus = BatteryStatus.UNKNOWN
    powered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class Storage:
    total_kb: int
    used_kb: int
    free_kb: int


@dataclass(frozen=True)
class Memory:
    total_kb: int
    available_kb: int | None


@dataclass(frozen=True)
class Identity:
    """The few properties needed to recognise a device across connections."""

    serialno: str | None
    model: str | None
    manufacturer: str | None
    kind: Kind
    device_name: str | None
    legacy_tcp_port: int | None  # adb tcpip port if network adb is open to everyone

    @property
    def legacy_network_open(self) -> bool:
        return self.legacy_tcp_port is not None


@dataclass(frozen=True)
class DeviceInfo:
    identity: Identity
    android_version: str | None
    sdk: int | None
    security_patch: str | None
    brand: str | None
    abi: str | None
    build: str | None
    battery: Battery | None
    storage: Storage | None
    memory: Memory | None
    screen_size: str | None
    screen_density: int | None
    addresses: tuple[tuple[str, str], ...] = ()  # (interface, ipv4)
    wireless_debugging: bool = False
    props: dict = field(default_factory=dict, repr=False)


# One line, fixed text, no user input: safe to hand to the device shell.
IDENTITY_SCRIPT = (
    "echo @@props; getprop; "
    "echo @@name; settings get global device_name 2>/dev/null; "
    "echo @@features; pm list features 2>/dev/null; "
    "echo @@end"
)

INFO_SCRIPT = (
    "echo @@props; getprop; "
    "echo @@name; settings get global device_name 2>/dev/null; "
    "echo @@features; pm list features 2>/dev/null; "
    "echo @@battery; dumpsys battery 2>/dev/null; "
    "echo @@df; df -k /data 2>/dev/null || df /data 2>/dev/null; "
    "echo @@mem; cat /proc/meminfo 2>/dev/null; "
    "echo @@wm; wm size 2>/dev/null; wm density 2>/dev/null; "
    "echo @@ip; ip -f inet addr show 2>/dev/null; "
    "echo @@end"
)

_PROP = re.compile(r"^\[(?P<key>[^\]]+)\]: \[(?P<value>.*)\]$")


def split_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("@@") and stripped[2:].isalpha():
            current = stripped[2:]
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def parse_props(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    pending_key: str | None = None
    pending_value: list[str] = []
    for line in text.splitlines():
        if pending_key is not None:  # a value that spans lines
            if line.endswith("]"):
                pending_value.append(line[:-1])
                props[pending_key] = "\n".join(pending_value)
                pending_key = None
            else:
                pending_value.append(line)
            continue
        match = _PROP.match(line.strip())
        if match:
            props[match.group("key")] = match.group("value")
        elif line.startswith("[") and "]: [" in line:
            key, _, rest = line[1:].partition("]: [")
            pending_key, pending_value = key, [rest]
    return props


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def legacy_tcp_port(props: dict[str, str]) -> int | None:
    for key in ("service.adb.tcp.port", "persist.adb.tcp.port"):
        port = _int(props.get(key))
        if port is not None and 0 < port < 65536:
            return port
    return None


def device_kind(props: dict[str, str], features: str) -> Kind:
    characteristics = (props.get("ro.build.characteristics") or "").lower().split(",")
    feature_set = {line.strip().removeprefix("feature:") for line in features.splitlines()}
    if "tv" in characteristics or "android.software.leanback" in feature_set or "android.hardware.type.television" in feature_set:
        return Kind.TV
    if "watch" in characteristics or "android.hardware.type.watch" in feature_set:
        return Kind.WATCH
    if "tablet" in characteristics:
        return Kind.TABLET
    if props or feature_set:
        return Kind.PHONE
    return Kind.UNKNOWN


def parse_identity(sections: dict[str, str]) -> Identity:
    props = parse_props(sections.get("props", ""))
    name = _clean(sections.get("name"))
    if name in ("null", "NULL"):
        name = None
    serial = _clean(props.get("ro.serialno")) or _clean(props.get("ro.boot.serialno"))
    if serial in ("unknown", "0123456789ABCDEF"):
        serial = None
    return Identity(
        serialno=serial,
        model=_clean(props.get("ro.product.model")),
        manufacturer=_clean(props.get("ro.product.manufacturer")),
        kind=device_kind(props, sections.get("features", "")),
        device_name=name,
        legacy_tcp_port=legacy_tcp_port(props),
    )


def parse_battery(text: str) -> Battery | None:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep:
            values[key.strip().lower()] = value.strip()
    if not values:
        return None
    present = values.get("present", "true").lower() != "false"
    level = _int(values.get("level"))
    scale = _int(values.get("scale")) or 100
    if level is not None and scale and scale != 100:
        level = round(level * 100 / scale)
    temperature = _int(values.get("temperature"))
    status = {
        2: BatteryStatus.CHARGING,
        3: BatteryStatus.DISCHARGING,
        4: BatteryStatus.NOT_CHARGING,
        5: BatteryStatus.FULL,
    }.get(_int(values.get("status")) or 0, BatteryStatus.UNKNOWN)
    powered = tuple(
        source
        for source, key in (("ac", "ac powered"), ("usb", "usb powered"), ("wireless", "wireless powered"), ("dock", "dock powered"))
        if values.get(key, "").lower() == "true"
    )
    return Battery(
        present=present,
        level=level if present else None,
        temperature_c=temperature / 10 if (temperature is not None and present) else None,
        status=status if present else BatteryStatus.UNKNOWN,
        powered_by=powered,
    )


_SIZE = re.compile(r"^(\d+(?:\.\d+)?)([KMGT]?)$", re.I)


def _size_to_kb(token: str) -> int | None:
    match = _SIZE.match(token.strip())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"": 1, "K": 1, "M": 1024, "G": 1024**2, "T": 1024**3}[unit]
    return int(number * factor)


def parse_df(text: str) -> Storage | None:
    """Accepts toybox ``df -k`` output and the older toolbox format."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    header = lines[0].lower()
    tokens = " ".join(lines[1:]).split()
    if not tokens:
        return None
    if "1k-blocks" in header or "1024-blocks" in header:
        numbers = [t for t in tokens if t.isdigit()]
        if len(numbers) >= 3:
            total, used, free = (int(n) for n in numbers[:3])
            return Storage(total, used, free)
        return None
    if "size" in header and "free" in header:  # toolbox: Filesystem Size Used Free Blksize
        sizes = [_size_to_kb(t) for t in tokens[1:4]]
        if all(s is not None for s in sizes):
            total, used, free = sizes  # type: ignore[misc]
            return Storage(total, used, free)
    return None


def parse_meminfo(text: str) -> Memory | None:
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if sep:
            number = _int(rest.strip().split(" ")[0])
            if number is not None:
                values[key.strip()] = number
    if "MemTotal" not in values:
        return None
    return Memory(values["MemTotal"], values.get("MemAvailable"))


def parse_wm(text: str) -> tuple[str | None, int | None]:
    size = density = None
    override_size = override_density = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Physical size:"):
            size = line.split(":", 1)[1].strip()
        elif line.startswith("Override size:"):
            override_size = line.split(":", 1)[1].strip()
        elif line.startswith("Physical density:"):
            density = _int(line.split(":", 1)[1])
        elif line.startswith("Override density:"):
            override_density = _int(line.split(":", 1)[1])
    return override_size or size, override_density or density


_INET = re.compile(r"inet (\d{1,3}(?:\.\d{1,3}){3})/\d+.*?\s(\S+)\s*$")


def parse_ip(text: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _INET.search(line.strip())
        if not match:
            continue
        address, interface = match.group(1), match.group(2)
        if address.startswith("127.") or interface == "lo":
            continue
        found.append((interface, address))

    def rank(item: tuple[str, str]) -> int:
        name = item[0]
        if name.startswith("wlan"):
            return 0
        if name.startswith("eth"):
            return 1
        return 2

    return tuple(sorted(found, key=rank))


def parse_info(output: str) -> DeviceInfo:
    sections = split_sections(output)
    props = parse_props(sections.get("props", ""))
    size, density = parse_wm(sections.get("wm", ""))
    return DeviceInfo(
        identity=parse_identity(sections),
        android_version=_clean(props.get("ro.build.version.release")),
        sdk=_int(props.get("ro.build.version.sdk")),
        security_patch=_clean(props.get("ro.build.version.security_patch")),
        brand=_clean(props.get("ro.product.brand")),
        abi=_clean(props.get("ro.product.cpu.abi")),
        build=_clean(props.get("ro.build.display.id")),
        battery=parse_battery(sections.get("battery", "")),
        storage=parse_df(sections.get("df", "")),
        memory=parse_meminfo(sections.get("mem", "")),
        screen_size=size,
        screen_density=density,
        addresses=parse_ip(sections.get("ip", "")),
        wireless_debugging=(props.get("persist.adb.tls_server.enable") == "1"),
        props=props,
    )


class InfoError(RuntimeError):
    def __init__(self, result: AdbResult):
        super().__init__(result.output or "adb failed")
        self.result = result


def read_identity(runner: AdbRunner, serial: str, log: bool = False, timeout: float = 20) -> Identity:
    result = runner.shell_script(serial, IDENTITY_SCRIPT, timeout=timeout, log=log)
    if not result.ok or "@@end" not in result.stdout:
        raise InfoError(result)
    return parse_identity(split_sections(result.stdout))


def read_info(runner: AdbRunner, serial: str, log: bool = True) -> DeviceInfo:
    result = runner.shell_script(serial, INFO_SCRIPT, timeout=30, log=log)
    if not result.ok or "@@end" not in result.stdout:
        raise InfoError(result)
    return parse_info(result.stdout)
