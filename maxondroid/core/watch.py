"""Device change notifications from ``adb track-devices``.

adb keeps this command running and writes the full device list every time
something changes, each list prefixed with its length as four hex digits.
MaxOnDroid uses it to refresh the device rail at once instead of waiting for
the next poll. When adb exits (server restarted, adb replaced) the watcher
starts it again after a short pause; the slow poll covers the gap.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable

from maxondroid.core.adb import AdbNotFoundError, AdbRunner

RESTART_DELAYS = (1.0, 2.0, 5.0, 10.0)
MAX_BLOCK = 1 << 20  # a device list is a few hundred bytes; anything bigger is garbage


def read_block(stream) -> str | None:
    """One length-prefixed block, or None at the end of the stream or on garbage."""
    head = _read_exact(stream, 4)
    if head is None:
        return None
    try:
        size = int(head.decode("ascii"), 16)
    except (UnicodeDecodeError, ValueError):
        return None
    if size > MAX_BLOCK:
        return None
    if size == 0:
        return ""
    body = _read_exact(stream, size)
    if body is None:
        return None
    return body.decode("utf-8", errors="replace")


def _read_exact(stream, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class DeviceWatcher:
    """Runs ``adb track-devices -l`` in a thread and calls ``on_change(text)`` for every list.

    ``on_change`` is called from the watcher thread; the UI hands it over to its
    own thread with a queued signal.
    """

    def __init__(self, runner: AdbRunner, on_change: Callable[[str], None]):
        self.runner = runner
        self.on_change = on_change
        self.starts = 0
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        """True while adb is running and delivering lists."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="adb-track-devices", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
        if self._thread is not None:
            self._thread.join(timeout)

    def _loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                proc = self.runner.open_stream(["track-devices", "-l"])
            except AdbNotFoundError:
                proc = None
            if proc is not None:
                with self._lock:
                    self._proc = proc
                self.starts += 1
                delivered = False
                try:
                    while not self._stop.is_set():
                        block = read_block(proc.stdout)
                        if block is None:
                            break
                        delivered = True
                        try:
                            self.on_change(block)
                        except Exception:  # a broken callback must not stop the watcher
                            pass
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
                    with self._lock:
                        self._proc = None
                failures = 0 if delivered else failures + 1
            else:
                failures += 1
            delay = RESTART_DELAYS[min(max(failures - 1, 0), len(RESTART_DELAYS) - 1)]
            self._stop.wait(delay)
