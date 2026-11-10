"""Combines what adb sees right now with the saved devices.

A phone connected by USB and by Wi-Fi at the same time is one device here:
devices are keyed by their hardware serial number (``ro.serialno``) whenever
it can be read, so the token number follows the device, not the cable.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from maxondroid.core import connection, mdns
from maxondroid.core.adb import AdbRunner
from maxondroid.core.devices import AdbDevice, State, Transport, parse_devices
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


class DeviceManager:
    RECONNECT_STEPS = (20.0, 60.0, 180.0, 300.0)

    def __init__(self, runner: AdbRunner, registry: Registry):
        self.runner = runner
        self.registry = registry
        self._identities: dict[str, Identity] = {}
        self._lock = threading.Lock()
        self._backoff: dict[str, tuple[float, int]] = {}  # key -> (next attempt, step)

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

    def _identity_for(self, device: AdbDevice) -> Identity | None:
        cached = self.identity(device.serial)
        if cached is not None:
            return cached
        try:
            found = read_identity(self.runner, device.serial)
        except InfoError:
            return None
        with self._lock:
            self._identities[device.serial] = found
        return found

    # -- snapshot -------------------------------------------------------------
    def list_adb_devices(self) -> list[AdbDevice]:
        result = self.runner.run(["devices", "-l"], timeout=15, log=False)
        if not result.ok:
            raise ManagerError(result.output or "adb devices failed")
        return parse_devices(result.stdout)

    def _key_for_offline(self, device: AdbDevice) -> str:
        endpoint = device.network_endpoint
        instance = device.mdns_instance
        for saved in self.registry.all():
            if endpoint and saved.network and (saved.network.host, saved.network.port) == endpoint:
                return saved.key
            if instance and saved.mdns_name == instance:
                return saved.key
        if instance and instance.count("-") >= 2:
            return instance[4:].rsplit("-", 1)[0]
        return device.serial

    def refresh(self) -> list[DeviceView]:
        adb_devices = self.list_adb_devices()
        present = {d.serial for d in adb_devices}
        with self._lock:
            for serial in list(self._identities):
                if serial not in present:
                    del self._identities[serial]

        groups: dict[str, list[tuple[AdbDevice, Identity | None, Transport]]] = {}
        for device in adb_devices:
            if device.state is State.HOST:
                continue
            identity = self._identity_for(device) if device.state is State.ONLINE else None
            if identity and identity.serialno:
                key = identity.serialno
            elif device.state is State.ONLINE:
                key = device.serial
            else:
                key = self._key_for_offline(device)
            transport = device.transport
            if transport is Transport.WIFI:
                endpoint = device.network_endpoint
                if identity and identity.legacy_tcp_port and endpoint and endpoint[1] == identity.legacy_tcp_port:
                    transport = Transport.WIFI_LEGACY
                elif identity is not None:
                    transport = Transport.WIFI_PAIRED
            groups.setdefault(key, []).append((device, identity, transport))

        views: list[DeviceView] = []
        for key, members in groups.items():
            members.sort(key=lambda m: (m[0].state is not State.ONLINE, _TRANSPORT_RANK.get(m[2], 9)))
            device, identity, transport = members[0]
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
                )
            )
        views.sort(key=lambda v: (v.token is None, v.token or 0, v.name.lower()))
        return views

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
                step = connection.connect(self.runner, host, port, timeout=8, log=False)
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
