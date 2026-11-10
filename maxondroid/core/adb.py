"""Running adb safely.

Rules this module enforces (see SECURITY notes in README):

* adb is always started with an argument list, never through a host shell, so
  a device name or path can never turn into a second command on the PC.
* Text that ends up in ``adb shell`` is interpreted by the *device's* shell.
  Values that come from the user or from a device must go through
  :func:`sh_quote` (or :meth:`AdbRunner.shell`, which quotes every argument).
  Only fixed scripts written in this code base use :meth:`AdbRunner.shell_script`.
* Secrets on the command line (pairing codes) are masked before anything is
  logged or shown.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from maxondroid.core.paths import bundled_tools_dir

#: How long an ordinary adb call may take before it is killed.
DEFAULT_TIMEOUT = 30.0

_CREATE_NO_WINDOW = 0x08000000  # keep Windows from flashing a console window


class AdbNotFoundError(RuntimeError):
    """adb could not be started (missing file, no permission)."""


@dataclass(frozen=True)
class AdbResult:
    argv: tuple[str, ...]
    """Arguments after the adb executable, already including ``-s SERIAL``."""
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    serial: str | None = None
    secrets: tuple[str, ...] = field(default=(), repr=False)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """stdout and stderr together, as a person would see them in cmd."""
        parts = [p for p in (self.stdout.rstrip("\n"), self.stderr.rstrip("\n")) if p]
        return "\n".join(parts)

    def display_command(self) -> str:
        """The command as it would be typed, with secrets masked."""
        return "adb " + " ".join(_display_arg(mask_secrets(a, self.secrets)) for a in self.argv)

    def display_output(self) -> str:
        return mask_secrets(self.output, self.secrets)


def mask_secrets(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "•" * len(secret))
    return text


def _display_arg(arg: str) -> str:
    if arg == "" or any(ch.isspace() or ch in "\"'&|<>^%" for ch in arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def sh_quote(value: str) -> str:
    """Quote one argument for the device's POSIX shell (``adb shell``)."""
    if value == "":
        return "''"
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@%+=:,./-_")
    if all(ch in safe for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _check_args(args: Sequence[str]) -> list[str]:
    out = []
    for arg in args:
        if not isinstance(arg, str):
            raise TypeError(f"adb arguments must be str, got {type(arg).__name__}")
        if "\x00" in arg:
            raise ValueError("adb arguments must not contain NUL characters")
        out.append(arg)
    return out


def find_adb(custom_path: str | None = None) -> str | None:
    """Locate adb: the user's choice first, then the bundled copy, then PATH."""
    candidates: list[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))
    exe = "adb.exe" if sys.platform == "win32" else "adb"
    tools = bundled_tools_dir()
    candidates += [tools / "scrcpy" / exe, tools / "platform-tools" / exe, tools / exe]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    if custom_path:
        return None  # the user pointed somewhere specific; do not silently swap it
    found = shutil.which("adb")
    return found


Listener = Callable[[AdbResult], None]


class AdbRunner:
    """Starts adb processes. Safe to use from several threads at once."""

    def __init__(self, command: Sequence[str] | str, default_timeout: float = DEFAULT_TIMEOUT):
        self._command = [command] if isinstance(command, str) else list(command)
        if not self._command:
            raise ValueError("adb command must not be empty")
        self.default_timeout = default_timeout
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()

    @property
    def executable(self) -> str:
        return self._command[-1] if len(self._command) == 1 else " ".join(self._command)

    def add_listener(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def run(
        self,
        args: Sequence[str],
        serial: str | None = None,
        timeout: float | None = None,
        *,
        log: bool = True,
        secrets: Sequence[str] = (),
    ) -> AdbResult:
        argv = (["-s", serial] if serial else []) + _check_args(args)
        if serial is not None:
            _check_args([serial])
        full = self._command + argv
        limit = self.default_timeout if timeout is None else timeout
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        env = dict(os.environ)
        env.setdefault("ADB_MDNS_AUTO_CONNECT", "adb-tls-connect")
        kwargs["env"] = env

        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.Popen(full, **kwargs)
        except OSError as exc:
            raise AdbNotFoundError(str(exc)) from exc
        try:
            out_b, err_b = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            out_b, err_b = proc.communicate()
        duration = time.monotonic() - started
        result = AdbResult(
            argv=tuple(argv),
            returncode=proc.returncode if not timed_out else -1,
            stdout=_decode(out_b),
            stderr=_decode(err_b),
            duration=duration,
            timed_out=timed_out,
            serial=serial,
            secrets=tuple(s for s in secrets if s),
        )
        if log:
            with self._lock:
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener(result)
                except Exception:  # a broken listener must never break adb calls
                    pass
        return result

    def shell(self, serial: str, *argv: str, timeout: float | None = None, log: bool = True) -> AdbResult:
        """Run one command on the device; every argument is quoted for the device shell."""
        command = " ".join(sh_quote(a) for a in _check_args(argv))
        return self.run(["shell", command], serial=serial, timeout=timeout, log=log)

    def shell_script(self, serial: str, script: str, timeout: float | None = None, log: bool = True) -> AdbResult:
        """Run a fixed script written in this code base. Never pass user input here."""
        return self.run(["shell", script], serial=serial, timeout=timeout, log=log)

    def version(self) -> str | None:
        try:
            result = self.run(["version"], timeout=10, log=False)
        except AdbNotFoundError:
            return None
        if not result.ok:
            return None
        first = result.stdout.strip().splitlines()
        return first[0] if first else None


def _decode(data: bytes | None) -> str:
    if not data:
        return ""
    text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")
