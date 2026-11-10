import re
import string
from pathlib import Path

from maxondroid import i18n
from maxondroid.core.actions import REBOOT_TARGETS
from maxondroid.core.connection import Outcome
from maxondroid.core.devices import State, Transport
from maxondroid.core.info import BatteryStatus, Kind
from maxondroid.core.settings import LANGUAGES, THEMES
from maxondroid.i18n import en, ru

SOURCE = Path(__file__).resolve().parents[1] / "maxondroid"


def static_keys() -> set[str]:
    keys = set()
    for path in SOURCE.rglob("*.py"):
        keys |= set(re.findall(r'\btr\(\s*"([a-z0-9_.\-]+)"', path.read_text(encoding="utf-8")))
    return keys


def dynamic_keys() -> set[str]:
    from maxondroid.ui.connect_dialog import TABS
    from maxondroid.ui.overview_tab import FIELD_KEYS

    keys = set()
    keys |= {f"kind.{k.value}" for k in Kind}
    keys |= {f"transport.{t.value}" for t in Transport}
    keys |= {"state." + s.value.replace(" ", "_") for s in State}
    keys |= {f"overview.section.{s}" for s in FIELD_KEYS}
    keys |= {f"overview.field.{f}" for fields in FIELD_KEYS.values() for f in fields if f != "storage_bar"}
    keys |= {f"overview.battery.{b.value}" for b in BatteryStatus}
    keys |= {f"overview.power.{s}" for s in ("ac", "usb", "wireless", "dock")}
    keys |= {f"overview.reboot.{kind}.{t}" for kind in ("confirm", "do") for t in REBOOT_TARGETS}
    keys |= {f"connect.tab.{t}" for t in TABS}
    keys |= {f"connect.field.{f}" for f in ("host", "pair_port", "code", "connect_port")}
    keys |= {f"connect.result.{o.value}" for o in Outcome}
    keys |= {f"connect.found.kind.{k}" for k in ("connect", "pairing", "legacy")}
    validate_src = (SOURCE / "core" / "validate.py").read_text(encoding="utf-8")
    keys |= {f"validate.{c}" for c in re.findall(r'ValidationError\("(\w+)"\)', validate_src)}
    keys |= {f"settings.language.{c}" for c in LANGUAGES} | {f"settings.theme.{c}" for c in THEMES}
    return keys


def test_both_languages_have_the_same_keys():
    assert set(ru.STRINGS) == set(en.STRINGS), set(ru.STRINGS) ^ set(en.STRINGS)


def test_every_used_key_exists():
    missing = sorted((static_keys() | dynamic_keys()) - set(ru.STRINGS))
    assert missing == []
    assert len(static_keys()) > 100


def test_placeholders_match():
    fmt = string.Formatter()
    for key in ru.STRINGS:
        ru_names = {name for _, name, _, _ in fmt.parse(ru.STRINGS[key]) if name}
        en_names = {name for _, name, _, _ in fmt.parse(en.STRINGS[key]) if name}
        assert ru_names == en_names, key


def test_russian_words_are_not_mixed_script():
    mixed = re.compile(r"\b(?=\w*[а-яё])(?=\w*[a-z])\w+\b", re.IGNORECASE)
    bad = {key: mixed.findall(text) for key, text in ru.STRINGS.items() if mixed.search(text)}
    assert bad == {}


def test_switching_language_notifies_and_falls_back():
    seen = []
    i18n.on_change(lambda: seen.append(i18n.current()))
    i18n.set_language("en")
    assert i18n.tr("tab.overview") == "Overview"
    i18n.set_language("ru")
    assert i18n.tr("tab.overview") == "Обзор"
    assert seen[-2:] == ["en", "ru"]
    assert i18n.tr("no.such.key") == "no.such.key"
    assert i18n.tr("status.devices", online=1, total=3) == "В сети: 1 из 3"


def test_resolve_system_language():
    assert i18n.resolve("system", ["ru-RU", "en-US"]) == "ru"
    assert i18n.resolve("system", ["de-DE"]) == "en"
    assert i18n.resolve("en", ["ru-RU"]) == "en"
