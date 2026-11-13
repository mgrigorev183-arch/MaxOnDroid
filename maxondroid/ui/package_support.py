"""Shared by the Apps and Debloat tabs: the package cache, confirmations, batch runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from maxondroid.core import apk, packages, safety
from maxondroid.core.manager import DeviceView
from maxondroid.core.ops import OpResult, PackageOps
from maxondroid.core.packages import Action, Package, Snapshot
from maxondroid.i18n import tr
from maxondroid.ui.context import AppContext

MAX_LISTED = 12


class PackageCache(QObject):
    """One package snapshot per device, shared by both tabs."""

    changed = Signal(str)  # device key

    def __init__(self, ctx: AppContext, parent: QObject | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.snapshots: dict[str, Snapshot] = {}
        self.errors: dict[str, str] = {}
        self.loading: set[str] = set()

    def get(self, key: str | None) -> Snapshot | None:
        return self.snapshots.get(key) if key else None

    def ensure(self, view: DeviceView | None) -> None:
        if view is not None and view.online and view.key not in self.snapshots:
            self.load(view)

    def load(self, view: DeviceView) -> None:
        runner = self.ctx.runner
        if runner is None or not view.online or view.key in self.loading:
            return
        key, serial = view.key, view.serial
        self.loading.add(key)
        self.errors.pop(key, None)
        self.changed.emit(key)

        def done(snapshot: Snapshot) -> None:
            self.loading.discard(key)
            self.snapshots[key] = snapshot
            self.changed.emit(key)

        def failed(exc: BaseException) -> None:
            self.loading.discard(key)
            self.errors[key] = exc.result.display_output() if isinstance(exc, packages.PackageError) else str(exc)
            self.changed.emit(key)

        self.ctx.tasks.submit(lambda: packages.read_snapshot(runner, serial), done, failed)


def describe_reasons(verdict: safety.Verdict) -> str:
    return "; ".join(tr(f"safety.reason.{r.value}") for r in verdict.reasons)


def _listed(names: list[str]) -> str:
    shown = names[:MAX_LISTED]
    text = "\n".join("• " + n for n in shown)
    if len(names) > MAX_LISTED:
        text += "\n" + tr("pkg.more_items", count=len(names) - MAX_LISTED)
    return text


def confirm(parent: QWidget, title: str, text: str, ok_text: str, danger: bool = False, checkbox: str | None = None) -> tuple[bool, bool]:
    """Returns (accepted, checkbox state). The safe choice is the default button."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)  # lists names that come from the device
    box.setText(text)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    check = None
    if checkbox:
        check = QCheckBox(checkbox)
        check.setChecked(True)
        box.setCheckBox(check)
    box.exec()
    return box.clickedButton() is ok, bool(check and check.isChecked())


@dataclass(frozen=True)
class Plan:
    """What the user asked for, split by how carefully it must be confirmed."""

    allowed: list[Package]
    blocked: list[Package]
    critical: list[tuple[Package, safety.Verdict]]


def plan_changes(ctx: AppContext, items: list[Package], snapshot: Snapshot | None) -> Plan:
    allowed, blocked, critical = [], [], []
    for pkg in items:
        verdict = safety.classify(pkg.name, ctx.uad.get(pkg.name) if ctx.uad else None, snapshot)
        if verdict.level is safety.Level.BLOCKED:
            blocked.append(pkg)
            continue
        allowed.append(pkg)
        if verdict.level is safety.Level.CRITICAL:
            critical.append((pkg, verdict))
    return Plan(allowed, blocked, critical)


def confirm_destructive(parent: QWidget, ctx: AppContext, action: Action, items: list[Package], snapshot: Snapshot | None) -> tuple[list[Package], bool]:
    """Ask before removing or disabling. Returns (packages to change, keep APK backup)."""
    plan = plan_changes(ctx, items, snapshot)
    if plan.blocked:
        QMessageBox.information(parent, tr("pkg.blocked.title"), tr("pkg.blocked.body") + "\n\n" + _listed([p.name for p in plan.blocked]))
    if not plan.allowed:
        return [], False
    if plan.critical:
        lines = [f"{p.name} — {describe_reasons(v)}" for p, v in plan.critical]
        ok, _ = confirm(
            parent,
            tr("pkg.critical.title"),
            tr("pkg.critical.body") + "\n\n" + _listed(lines),
            tr(f"pkg.critical.do.{action.value}"),
            danger=True,
        )
        if not ok:
            return [], False
    names = [p.name for p in plan.allowed]
    user_apps = [p for p in plan.allowed if not p.system]
    if action is Action.DISABLE:
        text = tr("pkg.confirm.disable", count=len(names)) + "\n\n" + _listed(names)
        ok, _ = confirm(parent, tr("pkg.action.disable"), text, tr("pkg.action.disable"))
        return (plan.allowed if ok else []), False
    text = tr("pkg.confirm.remove", count=len(names)) + "\n\n" + _listed(names)
    if user_apps:
        text += "\n\n" + tr("pkg.confirm.remove_user_apps", count=len(user_apps))
    ok, backup = confirm(
        parent,
        tr("pkg.action.remove"),
        text,
        tr("pkg.action.remove"),
        danger=True,
        checkbox=tr("pkg.confirm.backup") if user_apps else None,
    )
    return (plan.allowed if ok else []), (backup if user_apps else False)


def make_ops(ctx: AppContext, view: DeviceView, snapshot: Snapshot | None) -> PackageOps:
    from maxondroid.core import paths

    return PackageOps(ctx.runner, view.serial, view.key, ctx.changes, paths.data_dir() / "backups", snapshot)


def op_error_text(result: OpResult) -> str:
    if result.code:
        key = f"ops.error.{result.code}"
        text = tr(key)
        if text == key:
            text = install_error_text(result.code)
        return text
    return result.message or tr("ops.error.generic")


def install_error_text(code: str | None) -> str:
    if not code:
        return ""
    key = f"install.error.{code}"
    text = tr(key)
    return text if text != key else tr("install.error.other", code=code)


def summarize(results: list[OpResult]) -> tuple[str, str]:
    """(banner kind, text) for the outcome of a batch."""
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    if not failed:
        return "info", tr("pkg.done", count=len(ok))
    lines = [f"{r.package}: {op_error_text(r)}" for r in failed[:MAX_LISTED]]
    text = tr("pkg.partial", ok=len(ok), failed=len(failed)) + "\n" + "\n".join(lines)
    return "error", text


def run_batch(ctx: AppContext, work: Callable[[], list], on_done: Callable[[list], None], on_error: Callable[[BaseException], None]) -> None:
    ctx.tasks.submit(work, on_done, on_error)


def install_queue(runner, serial: str, files: list[Path], snapshot: Snapshot | None, progress: Callable[[int, int, str], None] | None = None) -> list[apk.InstallResult]:
    """Install files one by one (worker thread)."""
    results = []
    abis = snapshot.abis if snapshot else ()
    density = snapshot.density if snapshot else None
    for index, file in enumerate(files):
        if progress:
            progress(index + 1, len(files), file.name)
        results.append(apk.install(runner, serial, file, abis, density))
    return results
