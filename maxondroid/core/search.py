"""Find files and folders on the device by name and type.

The device sends one list of everything below a folder (``find`` with
``stat``), and the matching happens here: the device's own case-insensitive
matching (``find -iname``) folds only Latin letters, so "отпуск" would not
find "Отпуск.jpg" there. With the list here, every keystroke filters it
instantly without another adb command; "Refresh" asks the device again.
"""

from __future__ import annotations

import posixpath
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from maxondroid.core.adb import AdbResult, AdbRunner, sh_quote
from maxondroid.core.files import FilesError, RemoteEntry, _kind, normalize

INDEX_TIMEOUT = 600.0
MAX_SHOWN = 2000  # rows in the results table; the rest are counted, not shown (keeps typing smooth)

# Everything below "$1": type|size|modified|./relative/path, one stat call per batch of files.
# Unreadable subfolders are skipped by find (errors to /dev/null). Without stat (old Android)
# names come from find alone, folders and files from two passes.
INDEX_SCRIPT = (
    'cd "$1" 2>/dev/null && [ -r . ] || { echo "@@denied"; exit 0; }; '
    "if command -v stat >/dev/null 2>&1; then "
    "find . -mindepth 1 \\( -type d -o -type f \\) -exec stat -c '%F|%s|%Y|%n' {} + 2>/dev/null; "
    "else "
    'find . -mindepth 1 -type d 2>/dev/null | while read -r f; do echo "directory|0|0|$f"; done; '
    'find . -mindepth 1 -type f 2>/dev/null | while read -r f; do echo "regular file|0|0|$f"; done; '
    "fi; echo @@end"
)

# Type groups offered in the Files tab; "folders" and "custom" are handled apart.
TYPES: dict[str, tuple[str, ...]] = {
    "photos": ("jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "bmp", "dng", "raw"),
    "videos": ("mp4", "mkv", "mov", "3gp", "webm", "avi", "m4v", "ts"),
    "music": ("mp3", "flac", "m4a", "aac", "ogg", "opus", "wav", "wma", "amr"),
    "documents": ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "txt", "rtf", "csv", "epub", "fb2", "djvu"),
    "apk": ("apk", "apks", "xapk", "apkm"),
    "archives": ("zip", "rar", "7z", "tar", "gz", "bz2", "xz"),
}
KINDS = ("all", "folders", *TYPES, "custom")


@dataclass(frozen=True)
class Index:
    root: str
    entries: tuple[RemoteEntry, ...]

    def covers(self, folder: str) -> bool:
        """True if a search in ``folder`` can use this index (it is the root or below it)."""
        folder = normalize(folder)
        return folder == self.root or folder.startswith(self.root.rstrip("/") + "/")

    def below(self, folder: str) -> list[RemoteEntry]:
        folder = normalize(folder)
        if folder == self.root:
            return list(self.entries)
        prefix = folder.rstrip("/") + "/"
        return [e for e in self.entries if e.path.startswith(prefix)]

    def without(self, paths: Iterable[str]) -> Index:
        """The index after deleting these paths (and everything inside the folders among them)."""
        gone = [normalize(p) for p in paths]
        keep = [e for e in self.entries if not any(e.path == g or e.path.startswith(g.rstrip("/") + "/") for g in gone)]
        return Index(self.root, tuple(keep))

    def renamed(self, old: str, new: str) -> Index:
        old, new = normalize(old), normalize(new)
        moved = []
        for e in self.entries:
            if e.path == old or e.path.startswith(old + "/"):
                path = new + e.path[len(old):]
                e = RemoteEntry(posixpath.basename(path), path, e.kind, e.size, e.modified)
            moved.append(e)
        return Index(self.root, tuple(moved))


def parse_index(text: str, root: str) -> list[RemoteEntry]:
    root = normalize(root)
    if text.lstrip().startswith("@@denied"):
        raise FilesError("denied", root)
    entries = []
    for line in text.splitlines():
        if line == "@@end" or line.count("|") < 3:
            continue
        kind_text, size, modified, rel = line.split("|", 3)
        if rel.startswith("./"):
            rel = rel[2:]
        rel = rel.strip("/")
        if not rel or rel in (".", ".."):
            continue
        path = normalize(posixpath.join(root, rel))
        try:
            size_value, modified_value = int(size), int(modified)
        except ValueError:
            size_value, modified_value = 0, 0
        entries.append(RemoteEntry(posixpath.basename(path), path, _kind(kind_text), size_value, modified_value))
    return entries


def build_index(runner: AdbRunner, serial: str, root: str, cancel: threading.Event | None = None) -> tuple[Index | None, AdbResult]:
    """Ask the device for everything below ``root``. ``None`` if cancelled."""
    root = normalize(root)
    command = " ".join(sh_quote(a) for a in ["sh", "-c", INDEX_SCRIPT, "sh", root])
    result = runner.run(["shell", command], serial=serial, timeout=INDEX_TIMEOUT, cancel=cancel)
    if result.cancelled:
        return None, result
    if not result.ok or "@@end" not in result.stdout and "@@denied" not in result.stdout:
        raise FilesError("failed", result.output[-2000:])
    return Index(root, tuple(parse_index(result.stdout, root))), result


def extension(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    return ext.casefold() if dot and stem else ""


def stem(name: str) -> str:
    """The name without its extension; a dot file ('.nomedia') keeps its whole name."""
    base, dot, _ext = name.rpartition(".")
    return base if dot and base else name


def parse_extensions(text: str) -> tuple[str, ...]:
    """'jpg, .PNG  heic' -> ('jpg', 'png', 'heic')."""
    parts = text.replace(",", " ").replace(";", " ").split()
    return tuple(dict.fromkeys(p.strip().lstrip("*").lstrip(".").casefold() for p in parts if p.strip(" .*")))


def matches(entry: RemoteEntry, query: str, kind: str, custom: tuple[str, ...] = ()) -> bool:
    if kind == "folders" and not entry.is_dir:
        return False
    if kind in TYPES or kind == "custom":
        wanted = TYPES[kind] if kind in TYPES else custom
        if entry.is_dir or extension(entry.name) not in wanted:
            return False
    text = query.strip().casefold()
    if not text:
        return True
    if text.startswith(".") and " " not in text and len(text) > 1:  # ".jpg": by extension
        return not entry.is_dir and extension(entry.name) == text[1:]
    name = entry.name if entry.is_dir else stem(entry.name)
    return text in name.casefold()


def search(entries: Iterable[RemoteEntry], query: str, kind: str = "all", custom: tuple[str, ...] = ()) -> list[RemoteEntry]:
    """Matching entries, folders first, then by name."""
    if kind not in KINDS:
        raise ValueError(kind)
    found = [e for e in entries if matches(e, query, kind, custom)]
    found.sort(key=lambda e: (not e.is_dir, e.name.casefold(), e.path.casefold()))
    return found


def location(entry: RemoteEntry, root: str | None = None) -> str:
    """The folder an entry is in, shown relative to the search root when below it."""
    folder = posixpath.dirname(entry.path) or "/"
    if root:
        root = normalize(root)
        if folder == root:
            return "."
        if folder.startswith(root.rstrip("/") + "/"):
            return "./" + folder[len(root.rstrip("/")) + 1:]
    return folder
