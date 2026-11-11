"""Debloat presets: a named list of packages to remove or disable, as a JSON file.

Presets travel between devices and between friends, so loading one is
treated like reading untrusted input: unknown keys are ignored, invalid
package names are dropped, and the size is capped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from maxondroid.core.jsonstore import write_json_atomic
from maxondroid.core.packages import InvalidPackageError, PkgState, Snapshot, check_package

FORMAT = "maxondroid.preset"
VERSION = 1
MAX_ITEMS = 2000
MAX_FILE_BYTES = 2 * 1024 * 1024


class PresetAction(StrEnum):
    REMOVE = "remove"
    DISABLE = "disable"


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    items: tuple[tuple[str, PresetAction], ...]
    created: str = ""


class PresetError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def to_json(preset: Preset) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": preset.name,
        "description": preset.description,
        "created": preset.created or datetime.now(UTC).isoformat(timespec="seconds"),
        "packages": [{"package": p, "action": a.value} for p, a in preset.items],
    }


def save(preset: Preset, path: Path) -> None:
    write_json_atomic(path, to_json(preset))


def load(path: Path) -> Preset:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise PresetError("too_large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PresetError("unreadable", str(exc)) from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise PresetError("not_a_preset")
    raw_items = data.get("packages")
    if not isinstance(raw_items, list):
        raise PresetError("not_a_preset")
    items: list[tuple[str, PresetAction]] = []
    seen = set()
    for raw in raw_items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        try:
            package = check_package(str(raw.get("package", "")))
            action = PresetAction(raw.get("action", "remove"))
        except (InvalidPackageError, ValueError):
            continue
        if package not in seen:
            seen.add(package)
            items.append((package, action))
    if not items:
        raise PresetError("empty")
    name = str(data.get("name") or path.stem)[:80]
    return Preset(name, str(data.get("description") or "")[:500], tuple(items), str(data.get("created") or ""))


class PlanStatus(StrEnum):
    TODO = "todo"  # present and still active: will be changed
    DONE = "done"  # already removed/disabled
    MISSING = "missing"  # not on this device


@dataclass(frozen=True)
class PlanItem:
    package: str
    action: PresetAction
    status: PlanStatus


def plan(preset: Preset, snapshot: Snapshot) -> list[PlanItem]:
    """What applying the preset to this device would do."""
    out = []
    for package, action in preset.items:
        pkg = snapshot.get(package)
        if pkg is None:
            status = PlanStatus.MISSING
        elif pkg.state is PkgState.REMOVED or (action is PresetAction.DISABLE and pkg.state is PkgState.DISABLED):
            status = PlanStatus.DONE
        else:
            status = PlanStatus.TODO
        out.append(PlanItem(package, action, status))
    return out
