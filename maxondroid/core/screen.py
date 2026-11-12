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
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path

from maxondroid.core.adb import AdbRunner
from maxondroid.core.paths import bundled_tools_dir

MIN_VERSION = (2, 0)  # --video-bit-rate and audio forwarding
KEYBOARD_VERSION = (2, 4)  # --keyboard=uhid
MAX_BIT_RATE = 50  # Mbit/s; more does not help over USB and only floods Wi-Fi
PRESETS = ("quality", "speed")
KEYBOARDS = ("sdk", "uhid")
_FPS_LINE = re.compile(r"^INFO:\s+(\d+) fps(?: \(\+(\d+) frames? skipped\))?\s*$")  # --print-fps
FPS_FRESH = 3.0  # seconds a "N fps" line counts as current
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
    keyboard: str = "sdk"  # sdk: Latin letters only; uhid: a physical keyboard, any layout set on the device

    @classmethod
    def for_preset(cls, preset: str, base: ScrcpyOptions | None = None) -> ScrcpyOptions:
        base = base or cls()
        if preset == "speed":
            return replace(base, preset="speed", max_size=1280, bit_rate_mbps=4, max_fps=30)
        return replace(base, preset="quality", max_size=0, bit_rate_mbps=8, max_fps=0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object, fallback: ScrcpyOptions | None = None) -> ScrcpyOptions:
        """Options saved for one device; anything missing or of the wrong type comes from ``fallback``."""
        base = fallback or cls()
        if not isinstance(data, dict):
            return base
        values = {}
        for f in fields(cls):
            value = data.get(f.name)
            default = getattr(base, f.name)
            if isinstance(value, type(default)) and not (isinstance(default, int) and isinstance(value, bool) and not isinstance(default, bool)):
                values[f.name] = value
        return replace(base, **values).normalized()

    def normalized(self) -> ScrcpyOptions:
        return replace(
            self,
            preset=self.preset if self.preset in PRESETS else "quality",
            max_size=min(max(0, int(self.max_size)), 8192),
            bit_rate_mbps=min(max(1, int(self.bit_rate_mbps)), MAX_BIT_RATE),
            max_fps=min(max(0, int(self.max_fps)), 240),
            keyboard=self.keyboard if self.keyboard in KEYBOARDS else "sdk",
        )


def default_options(kind: str, last_used: ScrcpyOptions) -> ScrcpyOptions:
    """Options for a device opened for the first time.

    TVs start on the light preset: their chips usually cannot encode their own
    4K screen in real time, and the picture lags even over a cable.
    """
    if kind == "tv":
        return ScrcpyOptions.for_preset("speed", last_used)
    return last_used

def build_args(serial: str, options: ScrcpyOptions, title: str, record: Path | None = None, print_fps: bool = False) -> list[str]:
    args = [f"--serial={serial}", f"--window-title={title}"]
    if options.max_size > 0:
        args.append(f"--max-size={int(options.max_size)}")
    args.append(f"--video-bit-rate={min(max(1, int(options.bit_rate_mbps)), MAX_BIT_RATE)}M")
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
    elif options.keyboard == "uhid":
        args.append("--keyboard=uhid")
    if print_fps:
        args.append("--print-fps")
    if record is not None:
        if record.suffix.lower() == ".mp4" and options.audio:
            # Windows' own player cannot play Opus, scrcpy's default audio codec, in MP4
            args.append("--audio-codec=aac")
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

    def __init__(self, proc: subprocess.Popen, command: list[str], record: Path | None, serial: str | None = None):
        self.proc = proc
        self.command = command
        self.record = record
        self.serial = serial
        self.started = time.monotonic()
        self.output: deque[str] = deque(maxlen=60)
        self.reported = False  # the UI has told the user how this session ended
        self._fps: tuple[int, int, float] | None = None  # frames, skipped, when
        self.graceful: bool | None = None  # after stop(): True if scrcpy closed itself, False if it had to be killed
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stream = self.proc.stdout
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            match = _FPS_LINE.search(line)
            if match:  # --print-fps writes one of these every second; keep them out of the error tail
                self._fps = (int(match.group(1)), int(match.group(2) or 0), time.monotonic())
                continue
            self.output.append(line)

    @property
    def fps(self) -> tuple[int, int] | None:
        """Frames shown in the last second and frames dropped, while scrcpy keeps reporting them."""
        value = self._fps
        if value is None or not self.running or time.monotonic() - value[2] > FPS_FRESH:
            return None
        return value[0], value[1]

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
        """Close scrcpy the way a user would, so a recording is finished properly; force it if it hangs.

        An MP4 file is only playable once scrcpy has written its index at the
        end. Killing scrcpy (TerminateProcess on Windows) skips that and leaves
        a broken file, so scrcpy is first asked to quit: its window gets
        WM_CLOSE on Windows, SIGINT elsewhere (what Ctrl+C does).
        """
        if not self.running:
            return
        if _ask_to_quit(self.proc):
            try:
                self.proc.wait(timeout=GRACEFUL_STOP if self.record is not None else min(timeout, 3.0))
                self.graceful = True
                return
            except subprocess.TimeoutExpired:
                pass
        self.graceful = False
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass  # killed; Windows reaps it later. Never block the caller for ever.


GRACEFUL_STOP = 15.0  # seconds scrcpy gets to finish a recording file


def _ask_to_quit(proc: subprocess.Popen) -> bool:
    """Ask scrcpy to close itself. False if there was nothing to ask (no window yet)."""
    if sys.platform == "win32":
        return _post_close(proc.pid)
    try:
        proc.send_signal(signal.SIGINT)
    except OSError:
        return False
    return True


def _post_close(pid: int) -> bool:
    """Send WM_CLOSE to the visible top-level windows of a process (Windows)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(collect), 0)
    for hwnd in found:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    return bool(found)


Listener = Callable[[str], None]


class Scrcpy:
    """Starts scrcpy windows. One session per device key."""

    def __init__(self, executable: str, adb_executable: str | None, command_prefix: list[str] | None = None):
        self.executable = executable
        self.adb_executable = adb_executable
        self._prefix = command_prefix or [executable]
        self.sessions: dict[str, Session] = {}
        self.listeners: list[Listener] = []
        # start and stop also run in worker threads (restart, close). The lock covers only the dict and
        # spawning; waiting for a window to close happens outside it, so the UI thread never waits on it.
        self._lock = threading.Lock()

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
        with self._lock:
            current = self.sessions.get(key)
            if current is not None and current.running:
                return current
            if record is not None:
                record.parent.mkdir(parents=True, exist_ok=True)
            args = build_args(serial, options, title, record, print_fps=record is None)
            try:
                session = self._spawn(args)
            except OSError as exc:
                raise ScrcpyError("missing", str(exc)) from exc
            session.record = record
            session.serial = serial
            self.sessions[key] = session
        display = " ".join(_quote(a) for a in [Path(self.executable).name, *args])
        for listener in list(self.listeners):
            try:
                listener(display)
            except Exception:
                pass
        return session

    def restart(self, key: str, serial: str, options: ScrcpyOptions, title: str) -> Session:
        """Close the window and open it again with new options (scrcpy reads them only at start)."""
        self.stop(key)
        return self.start(key, serial, options, title)

    def get(self, key: str) -> Session | None:
        return self.sessions.get(key)

    def running_serials(self) -> set[str]:
        return {s.serial for s in list(self.sessions.values()) if s.serial and s.running}

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
