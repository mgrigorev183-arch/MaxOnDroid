"""Files on the device: list a folder, create, rename, delete, copy to and from the computer.

Every device path reaches the device shell as a separately quoted argument
(``sh -c SCRIPT sh PATH``, scripts read ``"$1"``), so a file called
``a; rm -rf /`` is just a strange name. Copies use ``adb push`` and
``adb pull`` with argument lists on the computer side.
"""

from __future__ import annotations

import posixpath
import threading
from dataclasses import dataclass
from pathlib import Path

from maxondroid.core.adb import AdbResult, AdbRunner

HOME = "/sdcard"
LIST_TIMEOUT = 30.0
TRANSFER_TIMEOUT = 6 * 3600.0  # a phone's whole camera folder over Wi-Fi; the user can cancel

# Lists one folder: type|size|modified|name per entry, following links (/sdcard is one).
# One stat call for all entries (a camera folder has thousands; a stat per file took seconds),
# then links whose target is gone, which stat -L skips, are listed without following.
# Without a stat command (old Android) names come from ls, folders marked by the trailing slash.
LIST_SCRIPT = (
    # entering is not reading: /data lets the shell user in but not list it
    'cd "$1" 2>/dev/null && [ -r . ] || { echo "@@denied"; exit 0; }; '
    "if ! command -v stat >/dev/null 2>&1; then "
    'ls -1Ap | while read -r f; do case "$f" in */) echo "directory|0|0|${f%/}";; *) echo "regular file|0|0|$f";; esac; done; '
    "echo @@end; exit 0; fi; "
    "stat -L -c '%F|%s|%Y|%n' -- * .[!.]* ..?* 2>/dev/null; "
    'for f in * .[!.]* ..?*; do if [ -L "$f" ] && [ ! -e "$f" ]; then '
    "stat -c '%F|%s|%Y|%n' -- \"$f\" 2>/dev/null || echo \"?|0|0|$f\"; fi; done; echo @@end"
)
MKDIR_SCRIPT = '[ -e "$1" ] && { echo "@@exists"; exit 0; }; mkdir -- "$1" && echo @@ok'
RENAME_SCRIPT = '[ -e "$2" ] && { echo "@@exists"; exit 0; }; mv -- "$1" "$2" && echo @@ok'
REMOVE_SCRIPT = 'rm -rf -- "$@" && echo @@ok'

# Never deleted from here, whatever is selected: the roots of storage and of the system.
PROTECTED = frozenset({
    "/", "/sdcard", "/storage", "/storage/emulated", "/storage/emulated/0", "/storage/self",
    "/storage/self/primary", "/mnt", "/mnt/sdcard", "/data", "/data/local", "/data/local/tmp",
    "/system", "/vendor", "/product", "/apex", "/proc", "/sys", "/dev", "/odm", "/cache",
})
MAX_NAME = 255


class FilesError(RuntimeError):
    """``code`` is a stable key the UI translates: denied, exists, bad_name, protected, failed, missing."""

    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    kind: str  # dir, file, link, other
    size: int
    modified: int  # unix time

    @property
    def is_dir(self) -> bool:
        return self.kind == "dir"


def normalize(path: str) -> str:
    """An absolute device path without ``.``/``..``/double slashes; empty means the home folder."""
    text = (path or "").strip().replace("\\", "/")
    if not text:
        return HOME
    if not text.startswith("/"):
        text = "/" + text
    clean = posixpath.normpath(text)
    return "/" if clean in ("", "//") else clean


def parent(path: str) -> str:
    return posixpath.dirname(normalize(path)) or "/"


def join(folder: str, name: str) -> str:
    return normalize(posixpath.join(normalize(folder), name))


def check_name(name: str) -> str:
    """A new file or folder name typed by the user."""
    value = name.strip()
    if not value or value in (".", "..") or len(value.encode("utf-8")) > MAX_NAME:
        raise FilesError("bad_name", name)
    if any(c in value for c in "/\x00\n\r"):
        raise FilesError("bad_name", name)
    return value


def is_protected(path: str) -> bool:
    clean = normalize(path)
    return clean in PROTECTED or clean.count("/") < 2  # nothing directly under / either


def _kind(text: str) -> str:
    if text == "directory":
        return "dir"
    if "regular" in text:
        return "file"
    if text == "symbolic link":
        return "link"
    return "other"


def parse_listing(text: str, folder: str) -> list[RemoteEntry]:
    """Parse LIST_SCRIPT output; folders first, then names in a case-insensitive order."""
    folder = normalize(folder)
    if text.lstrip().startswith("@@denied"):
        raise FilesError("denied", folder)
    entries = []
    for line in text.splitlines():
        if line == "@@end" or line.count("|") < 3:
            continue
        kind_text, size, modified, name = line.split("|", 3)
        name = posixpath.basename(name.rstrip("/")) or name
        if not name or name in (".", ".."):
            continue
        try:
            size_value, modified_value = int(size), int(modified)
        except ValueError:
            size_value, modified_value = 0, 0
        entries.append(RemoteEntry(name, join(folder, name), _kind(kind_text), size_value, modified_value))
    entries.sort(key=lambda e: (not e.is_dir, e.name.casefold()))
    return entries


def _script(runner: AdbRunner, serial: str, script: str, *args: str, timeout: float = LIST_TIMEOUT) -> AdbResult:
    return runner.shell(serial, "sh", "-c", script, "sh", *args, timeout=timeout)


def list_folder(runner: AdbRunner, serial: str, folder: str) -> list[RemoteEntry]:
    folder = normalize(folder)
    result = _script(runner, serial, LIST_SCRIPT, folder)
    if not result.ok or "@@end" not in result.stdout and "@@denied" not in result.stdout:
        raise FilesError("failed", result.output)
    return parse_listing(result.stdout, folder)


def make_folder(runner: AdbRunner, serial: str, folder: str, name: str) -> str:
    path = join(folder, check_name(name))
    result = _script(runner, serial, MKDIR_SCRIPT, path)
    if "@@exists" in result.stdout:
        raise FilesError("exists", path)
    if not result.ok or "@@ok" not in result.stdout:
        raise FilesError("failed", result.output)
    return path


def rename(runner: AdbRunner, serial: str, path: str, new_name: str) -> str:
    source = normalize(path)
    if is_protected(source):
        raise FilesError("protected", source)
    target = join(parent(source), check_name(new_name))
    if target == source:
        return source
    result = _script(runner, serial, RENAME_SCRIPT, source, target)
    if "@@exists" in result.stdout:
        raise FilesError("exists", target)
    if not result.ok or "@@ok" not in result.stdout:
        raise FilesError("failed", result.output)
    return target


def remove(runner: AdbRunner, serial: str, paths: list[str]) -> None:
    targets = [normalize(p) for p in paths]
    if not targets:
        return
    blocked = [p for p in targets if is_protected(p)]
    if blocked:
        raise FilesError("protected", ", ".join(blocked))
    result = _script(runner, serial, REMOVE_SCRIPT, *targets, timeout=600)
    if not result.ok or "@@ok" not in result.stdout:
        raise FilesError("failed", result.output)


def push(runner: AdbRunner, serial: str, local: list[Path], folder: str, cancel: threading.Event | None = None) -> AdbResult:
    """Copy files and folders from the computer into a device folder."""
    sources = [Path(p) for p in local]
    missing = [str(p) for p in sources if not p.exists()]
    if missing:
        raise FilesError("missing", ", ".join(missing))
    target = normalize(folder).rstrip("/") + "/"
    return runner.run(["push", *[str(p) for p in sources], target], serial=serial, timeout=TRANSFER_TIMEOUT, cancel=cancel)


def pull(runner: AdbRunner, serial: str, paths: list[str], local_folder: Path, cancel: threading.Event | None = None) -> AdbResult:
    """Copy device files and folders into a folder on the computer."""
    local_folder = Path(local_folder)
    local_folder.mkdir(parents=True, exist_ok=True)
    sources = [normalize(p) for p in paths]
    return runner.run(["pull", *sources, str(local_folder)], serial=serial, timeout=TRANSFER_TIMEOUT, cancel=cancel)


def transfer_summary(result: AdbResult) -> str:
    """adb's last line: '3 files pulled, 0 skipped. 31.2 MB/s (...)' or its error."""
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    return lines[-1] if lines else ""
