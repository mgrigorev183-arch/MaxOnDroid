"""Which packages need a red confirmation, and which ones MaxOnDroid refuses to touch.

Blocked packages would cut off adb itself or leave the device without a
working system, so there would be nothing left to undo the change with.
Critical packages can be removed, but only after a separate warning that
says what will break.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from maxondroid.core.packages import Snapshot
from maxondroid.core.uad import Entry, Removal

BLOCKED = frozenset({
    "android",
    "com.android.shell",  # adb shell runs as this package
    "com.android.systemui",
    "com.android.providers.settings",
})

CORE = frozenset({
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.vending",
    "com.android.settings",
    "com.android.tv.settings",
    "com.android.phone",
    "com.android.providers.telephony",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.google.android.webview",
    "com.android.webview",
    "com.google.android.trichromelibrary",
    "com.android.bluetooth",
    "com.android.networkstack",
    "com.google.android.networkstack",
    "com.android.externalstorage",
    "com.android.providers.media",
    "com.google.android.providers.media.module",
    "com.android.inputdevices",
    "com.android.server.telecom",
})

LAUNCHERS = frozenset({
    "com.google.android.tvlauncher",
    "com.google.android.apps.tv.launcherx",
    "com.google.android.leanbacklauncher",
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",
    "com.sec.android.app.launcher",
    "com.miui.home",
})

UPDATERS_HINTS = ("ota", "update", "upgrade", "fota")


class Level(StrEnum):
    NORMAL = "normal"
    CRITICAL = "critical"
    BLOCKED = "blocked"


class Reason(StrEnum):
    ADB = "adb"  # removing it cuts off adb or the system UI
    CORE = "core"  # Play services, settings, installer, webview...
    LAUNCHER = "launcher"
    KEYBOARD = "keyboard"
    UNSAFE = "unsafe"  # UAD-ng marks it Unsafe
    UPDATER = "updater"


@dataclass(frozen=True)
class Verdict:
    level: Level
    reasons: tuple[Reason, ...] = ()


def classify(package: str, entry: Entry | None, snapshot: Snapshot | None) -> Verdict:
    if package in BLOCKED:
        return Verdict(Level.BLOCKED, (Reason.ADB,))
    reasons: list[Reason] = []
    if package in CORE:
        reasons.append(Reason.CORE)
    if package in LAUNCHERS or (snapshot is not None and snapshot.home == package):
        reasons.append(Reason.LAUNCHER)
    if snapshot is not None and snapshot.ime == package:
        reasons.append(Reason.KEYBOARD)
    if entry is not None and entry.removal is Removal.UNSAFE:
        reasons.append(Reason.UNSAFE)
    tail = package.rsplit(".", 1)[-1].lower()
    if entry is None and any(hint in tail for hint in UPDATERS_HINTS):
        reasons.append(Reason.UPDATER)
    if reasons:
        return Verdict(Level.CRITICAL, tuple(reasons))
    return Verdict(Level.NORMAL)
