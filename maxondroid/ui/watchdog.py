"""Notices when the window stops responding and writes down where it was stuck.

A timer on the UI thread ticks every 100 ms. A small background thread checks
the last tick; when the UI thread has been silent for longer than
:data:`THRESHOLD`, it takes the UI thread's Python stack at that moment and,
once the window responds again, writes the stack and the total time to the
diagnostics log (see core/diag.py).
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

from maxondroid.core.diag import Diagnostics

THRESHOLD = 0.5
TICK_MS = 100
IGNORE_LONGER = 120.0  # the PC was asleep, not the window
STACK_FRAMES = 14


class StallWatchdog(QObject):
    def __init__(self, diag: Diagnostics, parent: QObject | None = None, threshold: float = THRESHOLD):
        super().__init__(parent)
        self.diag = diag
        self.threshold = threshold
        self.stalls: list[tuple[float, str]] = []  # what was written, for tests and the About box later
        self._beat = time.monotonic()
        self._ui_thread = threading.get_ident()
        self._stop = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._thread = threading.Thread(target=self._watch, name="ui-watchdog", daemon=True)

    def start(self) -> None:
        self._beat = time.monotonic()
        self._timer.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()

    def _tick(self) -> None:
        self._beat = time.monotonic()

    def _stack(self) -> str:
        frame = sys._current_frames().get(self._ui_thread)
        if frame is None:
            return "(no Python frame: stuck inside Qt)"
        lines = traceback.format_stack(frame)[-STACK_FRAMES:]
        return "".join(lines)

    def _watch(self) -> None:
        stuck_since: float | None = None
        stack = ""
        while not self._stop.wait(TICK_MS / 1000 / 2):
            beat = self._beat
            lag = time.monotonic() - beat
            if stuck_since is None:
                if lag > self.threshold:
                    stuck_since = beat
                    stack = self._stack()
                continue
            if beat > stuck_since:  # the UI thread ticked again: the stall is over
                seconds = beat - stuck_since
                stuck_since = None
                if seconds <= IGNORE_LONGER:
                    self.stalls.append((seconds, stack))
                    self.diag.stall(seconds, stack)
