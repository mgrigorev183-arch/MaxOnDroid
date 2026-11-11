"""The undo journal: every package change MaxOnDroid made, per device.

File: ``changes.json`` in the config folder (format in docs/formats.md).
Only changes that take something away are recorded (remove, uninstall,
disable); each one knows how to be undone.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from maxondroid.core.jsonstore import read_json, write_json_atomic
from maxondroid.core.packages import Action, check_package

FORMAT = "maxondroid.changes"
VERSION = 1
RECORDED = (Action.REMOVE_FOR_USER, Action.UNINSTALL, Action.DISABLE)


@dataclass
class Change:
    id: str
    device: str  # registry key of the device
    package: str
    action: str  # Action value
    time: str
    version: str | None = None
    backup: str | None = None  # APK or .apks saved before a full uninstall
    undone: str | None = None  # time the change was undone

    @property
    def pending(self) -> bool:
        return self.undone is None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ChangeJournal:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._changes: list[Change] = []
        self.load()

    def load(self) -> None:
        data = read_json(self.path)
        changes = []
        if isinstance(data, dict) and data.get("format") == FORMAT and isinstance(data.get("changes"), list):
            for raw in data["changes"]:
                if not isinstance(raw, dict):
                    continue
                try:
                    change = Change(
                        id=str(raw["id"]),
                        device=str(raw["device"]),
                        package=check_package(str(raw["package"])),
                        action=Action(raw["action"]).value,
                        time=str(raw.get("time", "")),
                        version=raw.get("version"),
                        backup=raw.get("backup"),
                        undone=raw.get("undone"),
                    )
                except (KeyError, ValueError):
                    continue
                if Action(change.action) in RECORDED:
                    changes.append(change)
        with self._lock:
            self._changes = changes

    def save(self) -> None:
        with self._lock:
            payload = {"format": FORMAT, "version": VERSION, "changes": [asdict(c) for c in self._changes]}
        write_json_atomic(self.path, payload)

    def record(self, device: str, package: str, action: Action, version: str | None = None, backup: str | None = None) -> Change:
        if action not in RECORDED:
            raise ValueError(f"{action} is not an undoable change")
        change = Change(uuid.uuid4().hex[:12], device, check_package(package), action.value, _now(), version, backup)
        with self._lock:
            self._changes.append(change)
        self.save()
        return change

    def mark_undone(self, change_id: str) -> None:
        with self._lock:
            for change in self._changes:
                if change.id == change_id:
                    change.undone = _now()
        self.save()

    def for_device(self, device: str) -> list[Change]:
        """Newest first."""
        with self._lock:
            return [c for c in reversed(self._changes) if c.device == device]

    def pending(self, device: str) -> list[Change]:
        """Changes still in effect, newest first: the order to undo them in."""
        return [c for c in self.for_device(device) if c.pending]

    def latest_pending(self, device: str, package: str) -> Change | None:
        return next((c for c in self.pending(device) if c.package == package), None)
