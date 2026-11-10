"""Connecting, pairing and disconnecting network devices."""

from __future__ import annotations

import re
import secrets
import string
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from maxondroid.core import mdns, validate
from maxondroid.core.adb import AdbResult, AdbRunner

LEGACY_PORT = 5555


class Outcome(StrEnum):
    OK = "ok"
    ALREADY = "already"
    REFUSED = "refused"  # nothing listening / wrong port / device asleep
    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    BAD_CODE = "bad_code"
    NOT_FOUND = "not_found"  # mDNS service never appeared
    FAILED = "failed"


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    message: str = ""  # raw adb text, shown untranslated
    endpoint: str | None = None
    guid: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in (Outcome.OK, Outcome.ALREADY)


_PAIRED = re.compile(r"Successfully paired to (\S+)(?: \[guid=([^\]]+)\])?")


def _classify_failure(result: AdbResult) -> Outcome:
    if result.timed_out:
        return Outcome.TIMEOUT
    text = result.output.lower()
    if "unauthorized" in text:
        return Outcome.UNAUTHORIZED
    if "timed out" in text or "timeout" in text:
        return Outcome.TIMEOUT
    if "refused" in text or "10061" in text or "unable to connect" in text or "cannot connect" in text:
        return Outcome.REFUSED
    return Outcome.FAILED


def connect(runner: AdbRunner, host: str, port: int, timeout: float = 15, *, log: bool = True) -> StepResult:
    """``adb connect``. Older adb versions exit 0 even on failure, so read the text."""
    host = validate.host(host)
    port = validate.port(port)
    target = validate.endpoint(host, port)
    result = runner.run(["connect", target], timeout=timeout, log=log)
    text = result.output.strip()
    lowered = text.lower()
    if lowered.startswith("already connected"):
        return StepResult(Outcome.ALREADY, text, target)
    if lowered.startswith("connected to") and not result.timed_out:
        return StepResult(Outcome.OK, text, target)
    return StepResult(_classify_failure(result), text, target)


def disconnect(runner: AdbRunner, serial: str) -> StepResult:
    result = runner.run(["disconnect", serial], timeout=10)
    text = result.output.strip()
    if result.ok and "error" not in text.lower():
        return StepResult(Outcome.OK, text, serial)
    return StepResult(_classify_failure(result), text, serial)


def pair(runner: AdbRunner, host: str, port: int, code: str, timeout: float = 30) -> StepResult:
    """``adb pair HOST:PORT CODE``. The code is masked in every log line."""
    host = validate.host(host)
    port = validate.port(port)
    target = validate.endpoint(host, port)
    result = runner.run(["pair", target, code], timeout=timeout, secrets=[code])
    text = result.display_output().strip()
    match = _PAIRED.search(result.output)
    if match:
        return StepResult(Outcome.OK, text, match.group(1), match.group(2))
    lowered = result.output.lower()
    if "wrong password" in lowered or "incorrect" in lowered or "protocol fault" in lowered:
        return StepResult(Outcome.BAD_CODE, text, target)
    return StepResult(_classify_failure(result), text, target)


Sleep = Callable[[float], None]
Cancelled = Callable[[], bool]


def wait_for_service(
    runner: AdbRunner,
    predicate: Callable[[mdns.MdnsService], bool],
    timeout: float,
    *,
    interval: float = 1.5,
    sleep: Sleep = time.sleep,
    cancelled: Cancelled = lambda: False,
    clock: Callable[[], float] = time.monotonic,
) -> mdns.MdnsService | None:
    deadline = clock() + timeout
    while True:
        for service in mdns.discover(runner):
            if predicate(service):
                return service
        if cancelled() or clock() >= deadline:
            return None
        sleep(interval)


def find_connect_service(
    runner: AdbRunner,
    host: str,
    guid: str | None,
    timeout: float = 12,
    **kwargs,
) -> mdns.MdnsService | None:
    """After pairing, find the port to connect to (it differs from the pairing port)."""

    def matches(service: mdns.MdnsService) -> bool:
        if service.kind is not mdns.ServiceKind.CONNECT:
            return False
        return (guid is not None and service.name == guid) or service.host == host

    return wait_for_service(runner, matches, timeout, **kwargs)


def pair_and_connect(
    runner: AdbRunner,
    host: str,
    pair_port: int,
    code: str,
    connect_port: int | None = None,
    **kwargs,
) -> tuple[StepResult, StepResult | None]:
    """Pair, then connect. Returns (pair step, connect step or None if not reached)."""
    paired = pair(runner, host, pair_port, code)
    if not paired.ok:
        return paired, None
    if connect_port is None:
        service = find_connect_service(runner, validate.host(host), paired.guid, **kwargs)
        if service is None:
            return paired, StepResult(Outcome.NOT_FOUND)
        return paired, connect(runner, service.host, service.port)
    return paired, connect(runner, host, connect_port)


# --- QR pairing -------------------------------------------------------------

_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True)
class QrSession:
    """What the phone needs to scan. Android Studio uses the same format."""

    name: str
    password: str

    @property
    def payload(self) -> str:
        return f"WIFI:T:ADB;S:{self.name};P:{self.password};;"


def new_qr_session() -> QrSession:
    name = "maxondroid-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))
    password = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return QrSession(name, password)


def qr_pair_and_connect(
    runner: AdbRunner,
    session: QrSession,
    timeout: float = 120,
    **kwargs,
) -> tuple[StepResult, StepResult | None]:
    """Wait for the phone to scan the code, then pair and connect.

    After scanning, the phone announces a pairing service whose instance name
    equals ``session.name``; we pair with it using ``session.password``.
    """
    service = wait_for_service(
        runner,
        lambda s: s.kind is mdns.ServiceKind.PAIRING and s.name == session.name,
        timeout,
        **kwargs,
    )
    if service is None:
        return StepResult(Outcome.NOT_FOUND), None
    return pair_and_connect(runner, service.host, service.port, session.password, **kwargs)


# --- legacy network mode ----------------------------------------------------


def enable_legacy_tcpip(runner: AdbRunner, serial: str, port: int = LEGACY_PORT) -> StepResult:
    """``adb tcpip PORT``: opens adb to the whole network until disabled or reboot."""
    port = validate.port(port)
    result = runner.run(["tcpip", str(port)], serial=serial, timeout=20)
    text = result.output.strip()
    if result.ok and "error" not in text.lower():
        return StepResult(Outcome.OK, text)
    return StepResult(_classify_failure(result), text)


def disable_network_adb(runner: AdbRunner, serial: str) -> StepResult:
    """``adb usb``: restart adbd listening on USB only. Drops a network connection."""
    result = runner.run(["usb"], serial=serial, timeout=20)
    text = result.output.strip()
    if result.ok and "error" not in text.lower():
        return StepResult(Outcome.OK, text)
    return StepResult(_classify_failure(result), text)
