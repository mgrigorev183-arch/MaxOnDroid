"""Diagnostics log: slow adb commands and moments when the window stopped responding.

Plain text, one file per day (``diag-YYYY-MM-DD.log``) next to the command
journal, kept for :data:`KEEP_DAYS`. It records only how long things took and
where the program was, never command output, so it can be sent along with a
bug report. Pairing codes are masked the same way as in the journal.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from maxondroid.core.adb import AdbResult

KEEP_DAYS = 14
SLOW_COMMAND = 1.0  # seconds; quicker commands are not worth a line
MAX_FILE_BYTES = 2 * 1024 * 1024


class Diagnostics:
    def __init__(self, folder: Path | None):
        self.folder = folder
        self._lock = threading.Lock()
        if folder is not None:
            self._cleanup()

    def path_for(self, day: date) -> Path | None:
        return self.folder / f"diag-{day.isoformat()}.log" if self.folder is not None else None

    def command(self, result: AdbResult) -> None:
        """Tracer for :class:`AdbRunner`: every command, including the quiet polling ones."""
        if result.duration < SLOW_COMMAND and not result.timed_out:
            return
        status = "TIMEOUT" if result.timed_out else f"exit {result.returncode}"
        self.write(f"slow command {result.duration:.1f} s ({status}): {result.display_command()}")

    def stall(self, seconds: float, where: str) -> None:
        self.write(f"window not responding for {seconds:.1f} s\n{where.rstrip()}")

    def write(self, text: str) -> None:
        now = datetime.now()
        path = self.path_for(now.date())
        if path is None:
            return
        line = f"{now.strftime('%H:%M:%S.%f')[:-3]} {text}\n"
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size > MAX_FILE_BYTES:
                    return
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
            except OSError:
                pass

    def _cleanup(self) -> None:
        cutoff = date.today() - timedelta(days=KEEP_DAYS)
        try:
            for path in self.folder.glob("diag-*.log"):
                try:
                    day = date.fromisoformat(path.stem[5:])
                except ValueError:
                    continue
                if day < cutoff:
                    path.unlink(missing_ok=True)
        except OSError:
            pass
