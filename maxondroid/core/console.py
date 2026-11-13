"""The console: run adb commands typed by the user, see their output as it comes.

Two modes:

* **adb** — the text is what follows ``adb`` in cmd. It is split into
  arguments here (quotes group, backslashes stay, as Windows users write
  paths) and adb gets them as a list; nothing runs through cmd.exe. When a
  device is selected and the command does not name one, ``-s SERIAL`` is
  added.
* **shell** — the text is one command line for the device's own shell, sent
  as a single argument to ``adb -s SERIAL shell``. The device shell does
  interpret it: that is the point of this mode.

Each command gets its own adb process with no input, so commands that wait
for typing (a bare ``adb shell``) are refused with a hint instead of hanging.
"""

from __future__ import annotations

import codecs
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from maxondroid.core.adb import AdbRunner, _check_args, sh_quote
from maxondroid.core.jsonstore import read_json, write_json_atomic

MODES = ("adb", "shell")
FORMAT = "maxondroid.console"
MAX_HISTORY = 200
MAX_SAVED = 100
MAX_TEXT = 4000
MASK = "••••••"
# adb commands that are about adb itself or the network, not about one device
NO_SERIAL = frozenset({
    "devices", "version", "help", "start-server", "kill-server", "connect", "disconnect", "pair", "mdns", "keygen",
    "track-devices", "host-features",
})
DEVICE_OPTIONS = frozenset({"-s", "-d", "-e", "-t"})


class ConsoleError(ValueError):
    """``code`` is a stable key the UI translates: empty, quote, too_long, no_device, interactive, bad_char."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def tokenize(text: str) -> list[str]:
    """Split like cmd users expect: spaces separate, "..." and '...' group, backslashes are kept."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    started = False
    for char in text:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
            started = True
        elif char.isspace():
            if started:
                tokens.append("".join(current))
                current, started = [], False
        else:
            current.append(char)
            started = True
    if quote:
        raise ConsoleError("quote")
    if started:
        tokens.append("".join(current))
    return tokens


@dataclass(frozen=True)
class Command:
    mode: str
    text: str
    args: tuple[str, ...]  # after "adb"
    secrets: tuple[str, ...] = ()

    def display(self) -> str:
        """As the user would type it, with pairing codes masked.

        Only arguments with spaces or quotes are quoted. A ``|`` stays bare: in
        adb mode it is one more argument that adb hands to the device shell, so
        the line reads as typed instead of a puzzling ``"|"``.
        """
        shown = []
        for arg in self.args:
            value = MASK if arg in self.secrets else arg
            plain = value and not any(c.isspace() or c in "\"'" for c in value)
            shown.append(value if plain else '"' + value.replace('"', '\\"') + '"')
        return " ".join(["adb", *shown])


def _strip_prefix(tokens: list[str], *words: str) -> list[str]:
    for word in words:
        if tokens and tokens[0].lower() in (word, word + ".exe"):
            tokens = tokens[1:]
    return tokens


def build(mode: str, text: str, serial: str | None) -> Command:
    """Turn what the user typed into adb's arguments, or explain why not."""
    if mode not in MODES:
        raise ValueError(mode)
    text = text.strip()
    if not text:
        raise ConsoleError("empty")
    if len(text) > MAX_TEXT:
        raise ConsoleError("too_long")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ConsoleError("bad_char")
    if mode == "shell":
        if not serial:
            raise ConsoleError("no_device")
        words = [w.lower() for w in text.split()]
        skip = 2 if words[:2] == ["adb", "shell"] else 1 if words[:1] == ["shell"] else 0
        line = text  # pasted from cmd: the device line is what follows "adb shell"
        if skip:
            line = text.split(None, skip)[skip].strip() if len(words) > skip else ""
        if not line:
            raise ConsoleError("interactive")
        return Command(mode, text, tuple(_check_args(["-s", serial, "shell", line])))

    tokens = _strip_prefix(tokenize(text), "adb")
    if not tokens:
        raise ConsoleError("empty")
    # the command is the first word that is neither an adb option nor an option's value
    position = 0
    while position < len(tokens) and tokens[position].startswith("-"):
        position += 2 if tokens[position] in ("-s", "-t", "-H", "-P", "-L") else 1
    first = tokens[position] if position < len(tokens) else ""
    rest = tokens[position + 1:]
    names_device = any(t in DEVICE_OPTIONS for t in tokens[:position])  # adb's own -s/-d/-e/-t, not logcat -d
    if first == "shell" and not [t for t in rest if not t.startswith("-")]:
        raise ConsoleError("interactive")
    args = list(tokens)
    if serial and not names_device and first not in NO_SERIAL:
        args = ["-s", serial, *args]
    secrets: tuple[str, ...] = ()
    if first == "pair":
        after = [t for t in rest if not t.startswith("-")]
        if len(after) >= 2:
            secrets = (after[1],)
    return Command(mode, text, tuple(_check_args(args)), secrets)


def shell_preview(line: str) -> str:
    """How a shell-mode line looks quoted for the device, for the tooltip."""
    return sh_quote(line)


class Run:
    """One running console command: output arrives in ``on_output`` from a reader thread."""

    def __init__(self, runner: AdbRunner, command: Command, on_output: Callable[[str], None], on_exit: Callable[[Run], None]):
        self.command = command
        self.on_output = on_output
        self.on_exit = on_exit
        self.started = time.monotonic()
        self.finished: float | None = None
        self.returncode: int | None = None
        self.stopped = False
        self.tail: list[str] = []  # last output, for the journal
        self._tail_size = 0
        self._proc: subprocess.Popen = runner.open_stream(list(command.args), merge_stderr=True)
        self._thread = threading.Thread(target=self._read, name="console", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return self.finished is None

    @property
    def duration(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    def _keep(self, text: str) -> None:
        self.tail.append(text)
        self._tail_size += len(text)
        while self._tail_size > 16000 and len(self.tail) > 1:
            self._tail_size -= len(self.tail.pop(0))

    def _read(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stream = self._proc.stdout
        try:
            while True:
                chunk = stream.read1(8192) if hasattr(stream, "read1") else stream.read(8192)
                if not chunk:
                    break
                text = decoder.decode(chunk).replace("\r\n", "\n").replace("\r", "\n")
                if text:
                    self._keep(text)
                    self.on_output(text)
            rest = decoder.decode(b"", final=True)
            if rest:
                self._keep(rest)
                self.on_output(rest)
        finally:
            try:
                self.returncode = self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self.returncode = -1
            self.finished = time.monotonic()
            self.on_exit(self)

    def stop(self) -> None:
        """Stop a command that runs too long (logcat, top). The reader thread reports the exit."""
        if self.running:
            self.stopped = True
            try:
                self._proc.kill()
            except OSError:
                pass

    def wait(self, timeout: float | None = None) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def output_tail(self) -> str:
        return "".join(self.tail)


@dataclass
class Saved:
    name: str
    mode: str
    text: str


@dataclass
class ConsoleStore:
    """History and saved commands in console.json next to the settings."""

    path: Path
    history: list[tuple[str, str]] = field(default_factory=list)  # (mode, text), oldest first
    saved: list[Saved] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> ConsoleStore:
        store = cls(Path(path))
        data = read_json(store.path)
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return store
        for item in data.get("history", [])[-MAX_HISTORY:] if isinstance(data.get("history"), list) else []:
            if isinstance(item, dict) and item.get("mode") in MODES and isinstance(item.get("text"), str) and item["text"].strip():
                store.history.append((item["mode"], item["text"][:MAX_TEXT]))
        for item in data.get("saved", [])[:MAX_SAVED] if isinstance(data.get("saved"), list) else []:
            if (
                isinstance(item, dict) and item.get("mode") in MODES and isinstance(item.get("text"), str)
                and isinstance(item.get("name"), str) and item["name"].strip() and item["text"].strip()
            ):
                store.saved.append(Saved(item["name"].strip()[:80], item["mode"], item["text"][:MAX_TEXT]))
        return store

    def save(self) -> None:
        write_json_atomic(self.path, {
            "format": FORMAT,
            "version": 1,
            "history": [{"mode": m, "text": t} for m, t in self.history[-MAX_HISTORY:]],
            "saved": [{"name": s.name, "mode": s.mode, "text": s.text} for s in self.saved[:MAX_SAVED]],
        })

    def remember(self, mode: str, text: str, secrets: tuple[str, ...] = ()) -> None:
        """Add to the history. Pairing codes are masked: console.json is a plain file on disk."""
        text = text.strip()
        for secret in secrets:
            if secret:
                text = text.replace(secret, MASK)
        if not text:
            return
        if self.history and self.history[-1] == (mode, text):
            return
        self.history.append((mode, text))
        del self.history[:-MAX_HISTORY]

    def add_saved(self, name: str, mode: str, text: str) -> Saved:
        name = name.strip()[:80]
        if not name or not text.strip():
            raise ConsoleError("empty")
        if mode not in MODES:
            raise ValueError(mode)
        others = [s for s in self.saved if s.name != name]
        if len(others) >= MAX_SAVED:
            raise ConsoleError("too_long")
        item = Saved(name, mode, text.strip())
        self.saved = sorted([*others, item], key=lambda s: s.name.casefold())
        return item

    def remove_saved(self, name: str) -> None:
        self.saved = [s for s in self.saved if s.name != name]
