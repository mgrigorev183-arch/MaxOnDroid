"""Remote control: key presses and text, sent with ``adb shell input``.

Only key codes from the table below can be sent, so a button or a shortcut
can never turn into an arbitrary shell command.
"""

from __future__ import annotations

from dataclasses import dataclass

from maxondroid.core.adb import AdbResult, AdbRunner

#: Keys the Remote tab offers. Values are Android KeyEvent names.
KEYS: dict[str, str] = {
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "ok": "KEYCODE_DPAD_CENTER",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "menu": "KEYCODE_MENU",
    "recents": "KEYCODE_APP_SWITCH",
    "settings": "KEYCODE_SETTINGS",
    "search": "KEYCODE_SEARCH",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "mute": "KEYCODE_VOLUME_MUTE",
    "power": "KEYCODE_POWER",
    "sleep": "KEYCODE_SLEEP",
    "wakeup": "KEYCODE_WAKEUP",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "stop": "KEYCODE_MEDIA_STOP",
    "previous": "KEYCODE_MEDIA_PREVIOUS",
    "next": "KEYCODE_MEDIA_NEXT",
    "rewind": "KEYCODE_MEDIA_REWIND",
    "fast_forward": "KEYCODE_MEDIA_FAST_FORWARD",
    "channel_up": "KEYCODE_CHANNEL_UP",
    "channel_down": "KEYCODE_CHANNEL_DOWN",
    "input": "KEYCODE_TV_INPUT",
    "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL",
}

#: ``input text`` types through a virtual keyboard that only knows ASCII.
MAX_TEXT_CHUNK = 80


class UnknownKeyError(ValueError):
    pass


class TextNotSupportedError(ValueError):
    """The text has characters ``input text`` cannot type (Cyrillic, emoji, …)."""

    def __init__(self, characters: str):
        super().__init__(characters)
        self.characters = characters


def press(runner: AdbRunner, serial: str, key: str, long: bool = False) -> AdbResult:
    if key not in KEYS:
        raise UnknownKeyError(key)
    args = ["input", "keyevent"] + (["--longpress"] if long else []) + [KEYS[key]]
    return runner.shell(serial, *args, timeout=15)


def unsupported_characters(text: str) -> str:
    bad = []
    for ch in text:
        if not (32 <= ord(ch) < 127) and ch not in bad:
            bad.append(ch)
    return "".join(bad)


def text_chunks(text: str) -> list[str]:
    """Split text for ``input text``: spaces become ``%s``, at most MAX_TEXT_CHUNK characters per call."""
    bad = unsupported_characters(text)
    if bad:
        raise TextNotSupportedError(bad)
    chunks = []
    for start in range(0, len(text), MAX_TEXT_CHUNK):
        part = text[start : start + MAX_TEXT_CHUNK]
        # Android's input tool turns "%s" into a space and leaves any other "%" alone,
        # so a literal "%s" cannot be typed; everything else arrives as written.
        chunks.append(part.replace(" ", "%s"))
    return chunks


@dataclass(frozen=True)
class TextResult:
    ok: bool
    results: tuple[AdbResult, ...]


def type_text(runner: AdbRunner, serial: str, text: str) -> TextResult:
    """Type text into the focused field on the device. Latin letters, digits and symbols only."""
    results = []
    for chunk in text_chunks(text):
        result = runner.shell(serial, "input", "text", chunk, timeout=20)
        results.append(result)
        if not result.ok or "Exception" in result.output:
            return TextResult(False, tuple(results))
    return TextResult(True, tuple(results))
