"""Combines what adb sees right now with the saved devices.

A phone connected by USB and by Wi-Fi at the same time is one device here:
devices are keyed by their hardware serial number (``ro.serialno``) whenever
it can be read, so the token number follows the device, not the cable.

adb also keeps entries it can no longer talk to: the old address of a phone
whose wireless debugging port changed, or a state this code does not know.
Those cannot be asked for a serial number, so they are matched to a device by
address (same IP, any port) and folded into it instead of becoming a second
row; :meth:`DeviceManager.prune` then tells adb to drop them.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from maxondroid.core import connection, mdns
from maxondroid.core.adb import AdbRunner
from maxondroid.core.devices import AdbDevice, State, Transport, guess_transport, parse_devices
from maxondroid.core.info import Identity, InfoError, Kind, read_identity
from maxondroid.core.registry import NetworkAddress, Registry, SavedDevice


class ManagerError(RuntimeError):
    """adb itself is not working (server cannot start, binary broken)."""


@dataclass(frozen=True)
class DeviceView:
    key: str
    token: int | None
    name: str
    model: str | None
    manufacturer: str | None
    kind: Kind
    state: State
    transport: Transport | None
    serial: str | None  # adb serial to send commands to; None when not connected
    serials: tuple[str, ...]
    legacy_network_open: bool
    saved: bool
    alias: str = ""
    network: NetworkAddress | None = None
    state_detail: str = ""
    risk_accepted: bool = False

    @property
    def online(self) -> bool:
        return self.state is State.ONLINE and self.serial is not None


_TRANSPORT_RANK = {
    Transport.USB: 0,
    Transport.EMULATOR: 1,
    Transport.WIFI_PAIRED: 2,
    Transport.WIFI: 3,
    Transport.WIFI_LEGACY: 4,
}


def display_name(alias: str, identity: Identity | None, saved: SavedDevice | None, fallback: str) -> str:
    if alias:
        return alias
    if identity and identity.device_name:
        return identity.device_name
    model = (identity.model if identity else None) or (saved.model if saved else None)
    maker = (identity.manufacturer if identity else None) or (saved.manufacturer if saved else None)
    if model:
        if maker and not model.lower().startswith(maker.lower()):
            return f"{maker.capitalize()} {model}"
        return model
    return fallback


def _is_network(serial: str) -> bool:
    return guess_transport(serial) in (Transport.WIFI, Transport.WIFI_PAIRED)


class DeviceManager:
    RECONNECT_STEPS = (20.0, 60.0, 180.0, 300.0)
    IDENTITY_TIMEOUT = 10.0
    IDENTITY_RETRY = (5.0, 15.0, 30.0)  # waits after the 1st, 2nd, 3rd+ failed read: not on every poll
    CONNECT_TIMEOUT = 5.0

    def __init__(self, runner: AdbRunner, registry: Registry):
        self.runner = runner
        self.registry = registry
        self._identities: dict[str, Identity] = {}
        self._failed: dict[str, tuple[float, int]] = {}  # serial -> (when its identity read failed, how often)
        self._lock = threading.Lock()
        self._backoff: dict[str, tuple[float, int]] = {}  # key -> (next attempt, step)
        self._stale: list[str] = []  # network serials adb keeps for a device that answers elsewhere
        self._duplicates: list[str] = []  # ip:port connections of a phone that is also connected by its mDNS name

    # -- identity cache -------------------------------------------------------
    def invalidate(self, serial: str | None = None) -> None:
        with self._lock:
            if serial is None:
                self._identities.clear()
            else:
                self._identities.pop(serial, None)

    def identity(self, serial: str) -> Identity | None:
        with self._lock:
            return self._identities.get(serial)

    def _identity_for(self, device: AdbDevice, now: float) -> Identity | None:
        cached = self.identity(device.serial)
        if cached is not None:
            return cached
        with self._lock:
            failed = self._failed.get(device.serial)
        if failed is not None:
            failed_at, count = failed
            if now - failed_at < self.IDENTITY_RETRY[min(count, len(self.IDENTITY_RETRY)) - 1]:
                return None
        try:
            found = read_identity(self.runner, device.serial, timeout=self.IDENTITY_TIMEOUT)
        except InfoError:
            with self._lock:
                self._failed[device.serial] = (now, (failed[1] if failed else 0) + 1)
            return None
        with self._lock:
            self._identities[device.serial] = found
            self._failed.pop(device.serial, None)
        return found

    # -- snapshot -------------------------------------------------------------
    def list_adb_devices(self) -> list[AdbDevice]:
        result = self.runner.run(["devices", "-l"], timeout=15, log=False)
        if not result.ok:
            raise ManagerError(result.output or "adb devices failed")
        return parse_devices(result.stdout)

    def _key_for_offline(self, device: AdbDevice, hosts: dict[str, str]) -> str:
        """A key for an entry that cannot be asked for its serial number.

        ``hosts`` maps the IP address of every device that answers to its key: a
        phone keeps its IP when wireless debugging picks a new port, so an old
        ``ip:port`` entry belongs to the device now answering on that IP.
        """
        endpoint = device.network_endpoint
        instance = device.mdns_instance
        saved_all = self.registry.all()
        for saved in saved_all:
            if endpoint and saved.network and (saved.network.host, saved.network.port) == endpoint:
                return saved.key
            if instance and saved.mdns_name == instance:
                return saved.key
        if endpoint and endpoint[0] in hosts:
            return hosts[endpoint[0]]
        if endpoint:
            for saved in saved_all:
                if saved.network and saved.network.host == endpoint[0]:
                    return saved.key
        if instance and instance.count("-") >= 2:
            return instance[4:].rsplit("-", 1)[0]
        return device.serial

    def refresh(self, now: float | None = None) -> list[DeviceView]:
        now = time.monotonic() if now is None else now
        adb_devices = self.list_adb_devices()
        present = {d.serial for d in adb_devices if d.state is State.ONLINE}  # a device that drops and returns is asked again at once
        with self._lock:
            for serial in list(self._identities):
                if serial not in present:
                    del self._identities[serial]
            for serial in list(self._failed):
                if serial not in present:
                    del self._failed[serial]

        # devices that answer first, so entries that do not can be matched to them by address
        groups: dict[str, list[tuple[AdbDevice, Identity | None, Transport]]] = {}
        keyed: list[tuple[AdbDevice, Identity | None, str]] = []
        hosts: dict[str, str] = {}
        for device in adb_devices:
            if device.state is not State.ONLINE:
                continue
            identity = self._identity_for(device, now)
            key = identity.serialno if identity and identity.serialno else device.serial
            keyed.append((device, identity, key))
            if device.network_endpoint:
                hosts[device.network_endpoint[0]] = key
            saved = self.registry.get(key)
            if saved is not None and saved.network is not None:
                hosts.setdefault(saved.network.host, key)  # answering by its mDNS name, known IP
        for device in adb_devices:
            if device.state in (State.ONLINE, State.HOST):
                continue
            keyed.append((device, None, self._key_for_offline(device, hosts)))

        for device, identity, key in keyed:
            transport = device.transport
            if transport is Transport.WIFI:
                endpoint = device.network_endpoint
                if identity and identity.legacy_tcp_port and endpoint and endpoint[1] == identity.legacy_tcp_port:
                    transport = Transport.WIFI_LEGACY
                elif identity is not None:
                    transport = Transport.WIFI_PAIRED
            groups.setdefault(key, []).append((device, identity, transport))

        views: list[DeviceView] = []
        stale: list[str] = []
        duplicates: list[str] = []
        for key, members in groups.items():
            # answering entries first, then by transport; among Wi-Fi ones the mDNS name adb reconnects by itself
            members.sort(key=lambda m: (m[0].state is not State.ONLINE, _TRANSPORT_RANK.get(m[2], 9), m[0].mdns_instance is None))
            device, identity, transport = members[0]
            if device.state is State.ONLINE:
                stale += [m[0].serial for m in members if m[0].state is not State.ONLINE and _is_network(m[0].serial)]
                if any(m[0].mdns_instance and m[0].state is State.ONLINE for m in members):
                    duplicates += [
                        m[0].serial for m in members
                        if m[0].state is State.ONLINE and m[0].network_endpoint and m[2] is Transport.WIFI_PAIRED
                    ]
            identity = identity or next((m[1] for m in members if m[1]), None)
            saved = self.registry.get(key)
            if device.state is State.ONLINE and identity is not None:
                network = None
                mdns_name = None
                for member, _, member_transport in members:
                    endpoint = member.network_endpoint
                    if endpoint and member.state is State.ONLINE:
                        mode = "legacy" if member_transport is Transport.WIFI_LEGACY else "paired"
                        network = NetworkAddress(endpoint[0], endpoint[1], mode)
                    mdns_name = member.mdns_instance or mdns_name
                saved = self.registry.remember(
                    key,
                    model=identity.model,
                    manufacturer=identity.manufacturer,
                    kind=identity.kind.value,
                    network=network,
                    mdns_name=mdns_name,
                )
                self._backoff.pop(key, None)
            alias = saved.alias if saved else ""
            kind = identity.kind if identity else Kind(saved.kind) if saved and saved.kind in Kind._value2member_map_ else Kind.UNKNOWN
            views.append(
                DeviceView(
                    key=key,
                    token=saved.token if saved else None,
                    name=display_name(alias, identity, saved, device.model or device.serial),
                    model=(identity.model if identity else None) or (saved.model if saved else None) or device.model,
                    manufacturer=(identity.manufacturer if identity else None) or (saved.manufacturer if saved else None),
                    kind=kind,
                    state=device.state,
                    transport=transport,
                    serial=device.serial,
                    serials=tuple(m[0].serial for m in members),
                    legacy_network_open=bool(identity and identity.legacy_network_open),
                    saved=saved is not None,
                    alias=alias,
                    network=saved.network if saved else None,
                    state_detail=device.state_detail,
                    risk_accepted=bool(saved and saved.legacy_risk_accepted),
                )
            )

        for saved in self.registry.all():
            if saved.key in groups:
                continue
            kind = Kind(saved.kind) if saved.kind in Kind._value2member_map_ else Kind.UNKNOWN
            views.append(
                DeviceView(
                    key=saved.key,
                    token=saved.token,
                    name=display_name(saved.alias, None, saved, saved.key),
                    model=saved.model,
                    manufacturer=saved.manufacturer,
                    kind=kind,
                    state=State.DISCONNECTED,
                    transport=None,
                    serial=None,
                    serials=(),
                    legacy_network_open=False,
                    saved=True,
                    alias=saved.alias,
                    network=saved.network,
                    risk_accepted=saved.legacy_risk_accepted,
                )
            )
        views.sort(key=lambda v: (v.token is None, v.token or 0, v.name.lower()))
        with self._lock:
            self._stale = stale
            self._duplicates = duplicates
        return views

    def prune(self, in_use: set[str] | frozenset[str] = frozenset()) -> list[str]:
        """Disconnect what the last refresh found redundant; returns the serials dropped.

        * old network entries of a device that answers on another serial;
        * an ``ip:port`` connection of a phone that is also connected by its mDNS
          name (adb reconnects that one by itself), unless something uses it now
          (``in_use``: serials of open scrcpy windows).
        """
        with self._lock:
            targets = list(self._stale) + [s for s in self._duplicates if s not in in_use]
            self._stale, self._duplicates = [], []
        dropped = []
        for serial in targets:
            try:
                connection.disconnect(self.runner, serial)
            except Exception:
                continue
            dropped.append(serial)
            self.invalidate(serial)
        return dropped

    # -- auto reconnect -------------------------------------------------------
    def reconnect(self, views: list[DeviceView], now: float | None = None) -> list[str]:
        """Try to reconnect saved Wi-Fi devices that dropped. Returns keys tried."""
        now = time.monotonic() if now is None else now
        due = []
        for view in views:
            if view.state is not State.DISCONNECTED or view.network is None:
                continue
            next_at, _ = self._backoff.get(view.key, (0.0, 0))
            if now >= next_at:
                due.append(view)
        if not due:
            return []
        services = mdns.discover(self.runner) if any(v.network.mode == "paired" for v in due) else []
        tried = []
        for view in due:
            saved = self.registry.get(view.key)
            if saved is None or saved.network is None:
                continue
            host, port = saved.network.host, saved.network.port
            if saved.network.mode == "paired":
                for service in services:
                    if service.kind is mdns.ServiceKind.CONNECT and (
                        service.device_serial == saved.key or (saved.mdns_name and service.name == saved.mdns_name)
                    ):
                        host, port = service.host, service.port
                        break
            tried.append(view.key)
            try:
                step = connection.connect(self.runner, host, port, timeout=self.CONNECT_TIMEOUT, log=False)
            except Exception:
                step = None
            if step is not None and step.ok:
                self._backoff.pop(view.key, None)
            else:
                _, index = self._backoff.get(view.key, (0.0, 0))
                delay = self.RECONNECT_STEPS[min(index, len(self.RECONNECT_STEPS) - 1)]
                self._backoff[view.key] = (now + delay, index + 1)
        return tried

    def forget(self, view: DeviceView) -> None:
        for serial in view.serials:
            if ":" in serial or "._adb-tls-connect" in serial:
                connection.disconnect(self.runner, serial)
        self.registry.forget(view.key)
        self._backoff.pop(view.key, None)

    def token_for_serial(self, serial: str | None) -> int | None:
        if serial is None:
            return None
        identity = self.identity(serial)
        key = identity.serialno if identity and identity.serialno else serial
        saved = self.registry.get(key)
        return saved.token if saved else None
