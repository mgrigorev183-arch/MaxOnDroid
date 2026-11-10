"""Interface strings in Russian and English, switchable while the app runs.

Raw adb output is never translated: people compare it with English
documentation.
"""

from __future__ import annotations

from collections.abc import Callable

from maxondroid.i18n import en, ru

LANGUAGES = {"ru": ru.STRINGS, "en": en.STRINGS}
_current = "ru"
_listeners: list[Callable[[], None]] = []


def current() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        code = "en"
    if code == _current:
        return
    _current = code
    for listener in list(_listeners):
        listener()


def on_change(listener: Callable[[], None]) -> None:
    _listeners.append(listener)


def remove_listener(listener: Callable[[], None]) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def resolve(setting: str, system_languages: list[str]) -> str:
    """``system`` picks Russian for a Russian-language Windows, otherwise English."""
    if setting in LANGUAGES:
        return setting
    for lang in system_languages:
        code = lang.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def tr(key: str, **values: object) -> str:
    text = LANGUAGES[_current].get(key) or LANGUAGES["en"].get(key) or key
    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text
    return text
