"""Device screens: scrcpy windows, recordings and screenshots.

scrcpy (https://github.com/Genymobile/scrcpy, Apache 2.0) shows the device
screen in a window and passes the mouse and keyboard back. MaxOnDroid starts
it with an argument list (never a shell) and points it at the same adb
executable through the ``ADB`` environment variable, so the two programs do
not fight over different adb server versions.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from maxondroid.core.adb import AdbRunner
from maxondroid.core.paths import bundled_tools_dir

MIN_VERSION = (2, 0)  # --video-bit-rate and audio forwarding
PRESETS = ("quality", "speed")
_CREATE_NO_WINDOW = 0x08000000
_VERSION = re.compile(r"scrcpy\s+v?(\d+)\.(\d+)(?:\.(\d+))?")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def find_scrcpy(custom_path: str | None = None, adb_path: str | None = None) -> str | None:
    """The user's choice, then next to the adb in use, then the bundled copy, then PATH."""
    exe = "scrcpy.exe" if sys.platform == "win32" else "scrcpy"
    if custom_path:
        return custom_path if Path(custom_path).is_file() else None
    candidates = []
    if adb_path:
        candidates.append(Path(adb_path).parent / exe)  # the scrcpy zip ships adb.exe next to scrcpy.exe
    candidates.append(bundled_tools_dir() / "scrcpy" / exe)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("scrcpy")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _popen_kwargs(capture: bool) -> dict:
    kwargs: dict = {"stdin": subprocess.DEVNULL, "shell": False}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW  # no console window behind the scrcpy window
    return kwargs


@dataclass(frozen=True)
class ScrcpyOptions:
    preset: str = "quality"  # quality | speed
    max_size: int = 0  # longest side in pixels, 0 = device resolution
    bit_rate_mbps: int = 8
    max_fps: int = 0  # 0 = no limit
    audio: bool = True
    turn_screen_off: bool = False
    always_on_top: bool = False
    stay_awake: bool = False
    view_only: bool = False

    @classmethod
    def for_preset(cls, preset: str, base: ScrcpyOptions | None = None) -> ScrcpyOptions:
        base = base or cls()
        if preset == "speed":
            return replace(base, preset="speed", max_size=1280, bit_rate_mbps=4, max_fps=30)
        return replace(base, preset="quality", max_size=0, bit_rate_mbps=8, max_fps=0)


def build_args(serial: str, options: ScrcpyOptions, title: str, record: Path | None = None) -> list[str]:
    args = [f"--serial={serial}", f"--window-title={title}"]
    if options.max_size > 0:
        args.append(f"--max-size={int(options.max_size)}")
    args.append(f"--video-bit-rate={max(1, int(options.bit_rate_mbps))}M")
    if options.max_fps > 0:
        args.append(f"--max-fps={int(options.max_fps)}")
    if not options.audio:
        args.append("--no-audio")
    if options.turn_screen_off:
        args.append("--turn-screen-off")
    if options.always_on_top:
        args.append("--always-on-top")
    if options.stay_awake:
        args.append("--stay-awake")
    if options.view_only:
        args.append("--no-control")
    if record is not None:
        args.append(f"--record={record}")
    for arg in args:
        if "\x00" in arg or "\n" in arg:
            raise ValueError("scrcpy arguments must be single-line text")
    return args


class ScrcpyError(RuntimeError):
    """``code`` is a stable key the UI translates: missing, too_old, broken."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class Session:
    """One running scrcpy window (optionally recording)."""

    def __init__(self, proc: subprocess.Popen, command: list[str], record: Path | None):
        self.proc = proc
        self.command = command
        self.record = record
        self.started = time.monotonic()
        self.output: deque[str] = deque(maxlen=60)
        self.reported = False  # the UI has told the user how this session ended
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stream = self.proc.stdout
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            self.output.append(raw.decode("utf-8", errors="replace").rstrip())

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    @property
    def returncode(self) -> int | None:
        return self.proc.poll()

    def tail(self, lines: int = 8) -> str:
        if not self.running:
            self._reader.join(timeout=0.5)  # let the reader catch the last lines
        return "\n".join(list(self.output)[-lines:])

    def stop(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=timeout)


Listener = Callable[[str], None]


class Scrcpy:
    """Starts scrcpy windows. One session per device key."""

    def __init__(self, executable: str, adb_executable: str | None, command_prefix: list[str] | None = None):
        self.executable = executable
        self.adb_executable = adb_executable
        self._prefix = command_prefix or [executable]
        self.sessions: dict[str, Session] = {}
        self.listeners: list[Listener] = []

    def version(self) -> tuple[int, int, int] | None:
        """``scrcpy --version``; raises OSError when the file cannot be started."""
        session = self._spawn(["--version"], capture=True)
        try:
            session.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            session.stop()
            return None
        session._reader.join(timeout=2)
        return parse_version("\n".join(session.output))

    def check(self) -> tuple[int, int, int]:
        try:
            version = self.version()
        except OSError as exc:
            raise ScrcpyError("missing", str(exc)) from exc
        if version is None:
            raise ScrcpyError("broken", self.executable)
        if version[:2] < MIN_VERSION:
            raise ScrcpyError("too_old", ".".join(map(str, version)))
        return version

    def _spawn(self, args: list[str], capture: bool = True) -> Session:
        env = dict(os.environ)
        if self.adb_executable:
            env["ADB"] = self.adb_executable
        command = self._prefix + args
        proc = subprocess.Popen(command, env=env, **_popen_kwargs(capture))
        return Session(proc, command, None)

    def start(self, key: str, serial: str, options: ScrcpyOptions, title: str, record: Path | None = None) -> Session:
        current = self.sessions.get(key)
        if current is not None and current.running:
            return current
        if record is not None:
            record.parent.mkdir(parents=True, exist_ok=True)
        args = build_args(serial, options, title, record)
        try:
            session = self._spawn(args)
        except OSError as exc:
            raise ScrcpyError("missing", str(exc)) from exc
        session.record = record
        self.sessions[key] = session
        display = " ".join(_quote(a) for a in [Path(self.executable).name, *args])
        for listener in list(self.listeners):
            try:
                listener(display)
            except Exception:
                pass
        return session

    def get(self, key: str) -> Session | None:
        return self.sessions.get(key)

    def stop(self, key: str) -> None:
        session = self.sessions.get(key)
        if session is not None:
            session.stop()

    def stop_all(self) -> None:
        for session in list(self.sessions.values()):
            session.stop(timeout=3)


def _quote(arg: str) -> str:
    return f'"{arg}"' if any(c.isspace() for c in arg) else arg


# --- screenshots and file names ------------------------------------------------


def capture_name(device_name: str, kind: str, suffix: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", device_name).strip(" .")[:60] or "device"
    return f"{safe} {kind} {when.strftime('%Y-%m-%d %H-%M-%S')}.{suffix}"


class ScreenshotError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)


def screenshot(runner: AdbRunner, serial: str, target: Path) -> Path:
    """``adb exec-out screencap -p`` into a PNG file. Raises ScreenshotError with adb's words."""
    result, data = runner.run_bytes(["exec-out", "screencap", "-p"], serial=serial, timeout=30)
    if not result.ok or not data.startswith(PNG_MAGIC):
        message = result.stderr.strip() or (data[:200].decode("utf-8", errors="replace").strip() if data else "") or "screencap failed"
        raise ScreenshotError(message)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def default_capture_dir() -> Path:
    """``Pictures\\MaxOnDroid`` (the Windows "Изображения" folder)."""
    pictures = Path.home() / "Pictures"
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0027, None, 0, buffer) == 0:  # CSIDL_MYPICTURES
                pictures = Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return pictures / "MaxOnDroid"
