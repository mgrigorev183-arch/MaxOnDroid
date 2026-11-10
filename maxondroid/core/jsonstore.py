"""Small helpers for the JSON files MaxOnDroid keeps on disk."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any | None:
    """Return parsed JSON, or None when the file is missing or unreadable."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON so that a crash never leaves a half-written file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
