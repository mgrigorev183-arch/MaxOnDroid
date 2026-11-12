"""Running adb work off the UI thread so the window never freezes."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals):
        super().__init__()
        self.fn = fn
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            value = self.fn()
        except BaseException as exc:  # handed to the UI thread, never lost
            exc.__traceback_text__ = traceback.format_exc()  # type: ignore[attr-defined]
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(value)


class TaskRunner(QObject):
    """Submit a function; get its result back on the UI thread."""

    def __init__(self, parent: QObject | None = None, max_threads: int = 4):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._alive: set[_Signals] = set()
        self._closed = False  # after shutdown, results are dropped: the widgets they would update are gone

    def submit(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        signals = _Signals()
        self._alive.add(signals)

        def finished(value: Any) -> None:
            self._alive.discard(signals)
            if self._closed:
                return
            if on_done is not None:
                on_done(value)

        def failed(exc: BaseException) -> None:
            self._alive.discard(signals)
            if self._closed:
                return
            if on_error is not None:
                on_error(exc)
            else:
                print(getattr(exc, "__traceback_text__", repr(exc)))

        signals.done.connect(finished)
        signals.failed.connect(failed)
        self.pool.start(_Task(fn, signals))

    def busy(self) -> bool:
        return bool(self._alive)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._closed = True
        self.pool.clear()
        self.pool.waitForDone(timeout_ms)
