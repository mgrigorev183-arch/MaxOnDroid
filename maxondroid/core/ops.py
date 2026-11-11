"""Package changes with a safety net: blocked packages refused, backups taken, undo recorded."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from maxondroid.core import apk, packages, safety
from maxondroid.core.adb import AdbRunner
from maxondroid.core.changes import Change, ChangeJournal
from maxondroid.core.packages import Action, Package, PkgState, Snapshot


@dataclass(frozen=True)
class OpResult:
    ok: bool
    package: str
    action: Action
    message: str = ""  # raw adb text
    code: str | None = None  # stable error key: blocked, backup_failed, no_backup, INSTALL_FAILED_...


class PackageOps:
    def __init__(
        self,
        runner: AdbRunner,
        serial: str,
        device_key: str,
        journal: ChangeJournal,
        backup_root: Path,
        snapshot: Snapshot | None = None,
    ):
        self.runner = runner
        self.serial = serial
        self.device_key = device_key
        self.journal = journal
        self.backup_root = backup_root
        self.snapshot = snapshot

    @property
    def backup_dir(self) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", self.device_key)[:80] or "device"
        return self.backup_root / safe

    def _blocked(self, package: str, action: Action) -> OpResult | None:
        if package in safety.BLOCKED:
            return OpResult(False, package, action, code="blocked")
        return None

    def remove(self, pkg: Package, backup: bool = True) -> OpResult:
        if (blocked := self._blocked(pkg.name, Action.REMOVE_FOR_USER)) is not None:
            return blocked
        if pkg.system:
            result = packages.remove_for_user(self.runner, self.serial, pkg.name)
            if result.ok:
                self.journal.record(self.device_key, pkg.name, Action.REMOVE_FOR_USER, pkg.version_name)
            return OpResult(result.ok, pkg.name, Action.REMOVE_FOR_USER, result.message)
        saved: str | None = None
        if backup:
            extracted = apk.extract_apk(self.runner, self.serial, pkg.name, self.backup_dir, pkg.version_name)
            if not extracted.ok or extracted.file is None:
                return OpResult(False, pkg.name, Action.UNINSTALL, extracted.message, code="backup_failed")
            saved = str(extracted.file)
        result = packages.uninstall(self.runner, self.serial, pkg.name)
        if result.ok:
            self.journal.record(self.device_key, pkg.name, Action.UNINSTALL, pkg.version_name, saved)
        return OpResult(result.ok, pkg.name, Action.UNINSTALL, result.message)

    def disable(self, pkg: Package) -> OpResult:
        if (blocked := self._blocked(pkg.name, Action.DISABLE)) is not None:
            return blocked
        result = packages.disable(self.runner, self.serial, pkg.name)
        if result.ok:
            self.journal.record(self.device_key, pkg.name, Action.DISABLE, pkg.version_name)
        return OpResult(result.ok, pkg.name, Action.DISABLE, result.message)

    def _settle(self, package: str, actions: tuple[Action, ...]) -> None:
        for change in self.journal.pending(self.device_key):
            if change.package == package and Action(change.action) in actions:
                self.journal.mark_undone(change.id)

    def enable(self, pkg: Package) -> OpResult:
        result = packages.enable(self.runner, self.serial, pkg.name)
        if result.ok:
            self._settle(pkg.name, (Action.DISABLE,))
        return OpResult(result.ok, pkg.name, Action.ENABLE, result.message)

    def restore(self, pkg: Package) -> OpResult:
        """Bring back a removed system app; for a disabled app, enable it."""
        if pkg.state is PkgState.DISABLED:
            return self.enable(pkg)
        sdk = self.snapshot.sdk if self.snapshot else None
        result = packages.restore(self.runner, self.serial, pkg.name, sdk)
        if result.ok:
            self._settle(pkg.name, (Action.REMOVE_FOR_USER,))
        return OpResult(result.ok, pkg.name, Action.RESTORE, result.message)

    def undo(self, change: Change) -> OpResult:
        action = Action(change.action)
        if action is Action.DISABLE:
            result = packages.enable(self.runner, self.serial, change.package)
            outcome = OpResult(result.ok, change.package, Action.ENABLE, result.message)
        elif action is Action.REMOVE_FOR_USER:
            sdk = self.snapshot.sdk if self.snapshot else None
            result = packages.restore(self.runner, self.serial, change.package, sdk)
            outcome = OpResult(result.ok, change.package, Action.RESTORE, result.message)
        else:
            if not change.backup or not Path(change.backup).is_file():
                return OpResult(False, change.package, Action.RESTORE, change.backup or "", code="no_backup")
            abis = self.snapshot.abis if self.snapshot else ()
            density = self.snapshot.density if self.snapshot else None
            installed = apk.install(self.runner, self.serial, Path(change.backup), abis, density)
            outcome = OpResult(installed.ok, change.package, Action.RESTORE, installed.message, None if installed.ok else installed.error_code)
        if outcome.ok:
            self.journal.mark_undone(change.id)
        return outcome

    def undo_all(self) -> list[OpResult]:
        """Undo every change still in effect on this device, newest first."""
        return [self.undo(change) for change in self.journal.pending(self.device_key)]
