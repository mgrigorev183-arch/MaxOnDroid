"""Device actions offered on the Overview tab."""

from __future__ import annotations

from maxondroid.core.adb import AdbResult, AdbRunner

REBOOT_TARGETS = ("system", "recovery", "bootloader")


def reboot(runner: AdbRunner, serial: str, target: str = "system") -> AdbResult:
    if target not in REBOOT_TARGETS:
        raise ValueError(f"unknown reboot target: {target}")
    args = ["reboot"] if target == "system" else ["reboot", target]
    return runner.run(args, serial=serial, timeout=20)
