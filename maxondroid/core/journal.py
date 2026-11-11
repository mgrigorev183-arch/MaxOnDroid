"""The command journal: every adb command the user caused, with its result.

Kept in memory for the journal panel and appended to a daily JSON Lines file
(``commands-YYYY-MM-DD.jsonl`` in the logs folder). Secrets such as pairing
codes are masked before anything is stored. Files older than
``KEEP_DAYS`` days are deleted on start.

One line per command::

    {"format": "maxondroid.command", "version": 1, "time": "...",
     "token": 2, "serial": "192.168.1.23:5555", "command": "adb -s ... shell ...",
     "exit": 0, "timed_out": false, "duration_ms": 120, "output": "..."}
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from maxondroid.core.adb import AdbResult

FORMAT = "maxondroid.command"
VERSION = 1
KEEP_DAYS = 14
MAX_OUTPUT_CHARS = 8000
MEMORY_ENTRIES = 1000


@dataclass(frozen=True)
class JournalEntry:
    when: datetime
    token: int | None
    serial: str | None
    command: str
    output: str
    exit_code: int
    timed_out: bool
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


TokenLookup = Callable[[str | None], int | None]
EntryListener = Callable[[JournalEntry], None]


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… ({len(text) - MAX_OUTPUT_CHARS} more characters)"


class Journal:
    def __init__(self, folder: Path | None, token_lookup: TokenLookup = lambda serial: None):
        self.folder = folder
        self.token_lookup = token_lookup
        self.entries: deque[JournalEntry] = deque(maxlen=MEMORY_ENTRIES)
        self._listeners: list[EntryListener] = []
        self._lock = threading.Lock()
        if folder is not None:
            self._cleanup()

    def add_listener(self, listener: EntryListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def record(self, result: AdbResult) -> JournalEntry:
        """Listener for :class:`AdbRunner`. Called from worker threads."""
        entry = JournalEntry(
            when=datetime.now(UTC),
            token=self.token_lookup(result.serial),
            serial=result.serial,
            command=result.display_command().replace("\n", " "),
            output=_truncate(result.display_output()),
            exit_code=result.returncode,
            timed_out=result.timed_out,
            duration_ms=int(result.duration * 1000),
        )
        with self._lock:
            self.entries.append(entry)
            listeners = list(self._listeners)
            self._append_file(entry)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:
                pass
        return entry

    def note(self, command: str, serial: str | None = None, output: str = "", ok: bool = True) -> JournalEntry:
        """Record a command that is not an adb call (starting scrcpy)."""
        entry = JournalEntry(
            when=datetime.now(UTC),
            token=self.token_lookup(serial),
            serial=serial,
            command=command.replace("\n", " "),
            output=_truncate(output),
            exit_code=0 if ok else 1,
            timed_out=False,
            duration_ms=0,
        )
        with self._lock:
            self.entries.append(entry)
            listeners = list(self._listeners)
            self._append_file(entry)
        for listener in listeners:
            try:
                listener(entry)
            except Exception:
                pass
        return entry

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()

    def _file_for(self, day: date) -> Path:
        assert self.folder is not None
        return self.folder / f"commands-{day.isoformat()}.jsonl"

    def _append_file(self, entry: JournalEntry) -> None:
        if self.folder is None:
            return
        line = {
            "format": FORMAT,
            "version": VERSION,
            "time": entry.when.isoformat(timespec="milliseconds"),
            "token": entry.token,
            "serial": entry.serial,
            "command": entry.command,
            "exit": entry.exit_code,
            "timed_out": entry.timed_out,
            "duration_ms": entry.duration_ms,
            "output": entry.output,
        }
        try:
            with self._file_for(entry.when.astimezone().date()).open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logging must never break the app

    def _cleanup(self) -> None:
        assert self.folder is not None
        limit = time.time() - KEEP_DAYS * 86400
        cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        for path in self.folder.glob("commands-*.jsonl"):
            stamp = path.stem.removeprefix("commands-")
            try:
                if stamp < cutoff or path.stat().st_mtime < limit:
                    path.unlink()
            except OSError:
                pass
