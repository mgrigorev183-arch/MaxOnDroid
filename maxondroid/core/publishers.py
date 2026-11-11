"""Who made a package: Android itself, the device maker, Google, Yandex, …

Android has no "publisher" field that adb can read, so the publisher is
derived from the package name (``com.google.…`` is Google, ``ru.yandex.…`` is
Yandex). The UAD-ng list is used only to recognise Android and Google
components and carrier apps whose names do not say so. Its "Oem" list is not
used: it marks what the maker preinstalled, and a preinstalled Netflix is
still Netflix's app. Vendors that have only one package on the device are
folded into "Others".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from maxondroid.core.uad import Entry


class Kind(StrEnum):
    ANDROID = "android"
    DEVICE_MAKER = "device_maker"  # the maker of this particular device
    MAKER = "maker"  # other phone/TV/chip makers (Qualcomm, MediaTek, …)
    GOOGLE = "google"
    VENDOR = "vendor"  # app publishers: Yandex, Meta, Telegram, …
    CARRIER = "carrier"
    OTHERS = "others"


@dataclass(frozen=True)
class Publisher:
    id: str
    name: str  # brand name; "android", "carrier" and "others" are translated by the UI
    kind: Kind


# Longest prefix wins. Names are brand spellings that do not need translation.
_KNOWN: list[tuple[str, str, str, Kind]] = [
    # (prefix, id, name, kind)
    ("com.android.vending", "google", "Google", Kind.GOOGLE),
    ("com.android.chrome", "google", "Google", Kind.GOOGLE),
    ("com.google.", "google", "Google", Kind.GOOGLE),
    ("com.android.", "android", "Android", Kind.ANDROID),
    ("android.", "android", "Android", Kind.ANDROID),
    ("org.lineageos.", "android", "Android", Kind.ANDROID),
    ("com.samsung.", "samsung", "Samsung", Kind.MAKER),
    ("com.sec.", "samsung", "Samsung", Kind.MAKER),
    ("com.xiaomi.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.miui.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.mi.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.duokan.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.milink.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.mitv.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("mitv.", "xiaomi", "Xiaomi", Kind.MAKER),
    ("com.huawei.", "huawei", "Huawei", Kind.MAKER),
    ("com.hihonor.", "honor", "Honor", Kind.MAKER),
    ("com.sony.", "sony", "Sony", Kind.MAKER),
    ("com.sonymobile.", "sony", "Sony", Kind.MAKER),
    ("com.lge.", "lg", "LG", Kind.MAKER),
    ("com.motorola.", "motorola", "Motorola", Kind.MAKER),
    ("com.oneplus.", "oneplus", "OnePlus", Kind.MAKER),
    ("com.oppo.", "oppo", "OPPO", Kind.MAKER),
    ("com.coloros.", "oppo", "OPPO", Kind.MAKER),
    ("com.heytap.", "oppo", "OPPO", Kind.MAKER),
    ("com.realme.", "realme", "realme", Kind.MAKER),
    ("com.vivo.", "vivo", "vivo", Kind.MAKER),
    ("com.bbk.", "vivo", "vivo", Kind.MAKER),
    ("com.iqoo.", "vivo", "vivo", Kind.MAKER),
    ("com.asus.", "asus", "ASUS", Kind.MAKER),
    ("com.lenovo.", "lenovo", "Lenovo", Kind.MAKER),
    ("com.motorola", "motorola", "Motorola", Kind.MAKER),
    ("com.zte.", "zte", "ZTE", Kind.MAKER),
    ("com.htc.", "htc", "HTC", Kind.MAKER),
    ("com.nokia.", "nokia", "Nokia", Kind.MAKER),
    ("com.hmdglobal.", "nokia", "Nokia", Kind.MAKER),
    ("com.tcl.", "tcl", "TCL", Kind.MAKER),
    ("org.droidtv.", "philips", "Philips", Kind.MAKER),
    ("com.tpvision.", "philips", "Philips", Kind.MAKER),
    ("com.hisense.", "hisense", "Hisense", Kind.MAKER),
    ("com.nvidia.", "nvidia", "NVIDIA", Kind.MAKER),
    ("com.qualcomm.", "qualcomm", "Qualcomm", Kind.MAKER),
    ("com.qti.", "qualcomm", "Qualcomm", Kind.MAKER),
    ("vendor.qti.", "qualcomm", "Qualcomm", Kind.MAKER),
    ("org.codeaurora.", "qualcomm", "Qualcomm", Kind.MAKER),
    ("com.mediatek.", "mediatek", "MediaTek", Kind.MAKER),
    ("com.mtk.", "mediatek", "MediaTek", Kind.MAKER),
    ("com.amlogic.", "amlogic", "Amlogic", Kind.MAKER),
    ("com.realtek.", "realtek", "Realtek", Kind.MAKER),
    ("ru.yandex.", "yandex", "Yandex", Kind.VENDOR),
    ("com.yandex.", "yandex", "Yandex", Kind.VENDOR),
    ("com.vkontakte.", "vk", "VK", Kind.VENDOR),
    ("com.vk.", "vk", "VK", Kind.VENDOR),
    ("ru.vk.", "vk", "VK", Kind.VENDOR),
    ("ru.mail.", "vk", "VK", Kind.VENDOR),
    ("ru.ok.", "vk", "VK", Kind.VENDOR),
    ("ru.sberbank", "sber", "Sber", Kind.VENDOR),
    ("ru.sber.", "sber", "Sber", Kind.VENDOR),
    ("com.facebook.", "meta", "Meta", Kind.VENDOR),
    ("com.instagram.", "meta", "Meta", Kind.VENDOR),
    ("com.whatsapp", "meta", "Meta", Kind.VENDOR),
    ("com.microsoft.", "microsoft", "Microsoft", Kind.VENDOR),
    ("com.skype.", "microsoft", "Microsoft", Kind.VENDOR),
    ("com.linkedin.", "microsoft", "Microsoft", Kind.VENDOR),
    ("com.amazon.", "amazon", "Amazon", Kind.VENDOR),
    ("com.kaspersky.", "kaspersky", "Kaspersky", Kind.VENDOR),
    ("com.kms.", "kaspersky", "Kaspersky", Kind.VENDOR),
]
_KNOWN.sort(key=lambda item: len(item[0]), reverse=True)

# Generic first segments that say nothing about the publisher.
_TLDS = {"com", "org", "net", "ru", "io", "me", "app", "tv", "de", "uk", "co", "fr", "it", "es", "jp", "cn", "info", "dev", "xyz", "us", "su", "by", "ua", "kz"}

# How a device's ro.product.manufacturer maps to a publisher id.
_MAKER_ALIASES = {
    "samsung": "samsung", "xiaomi": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi", "huawei": "huawei", "honor": "honor",
    "sony": "sony", "lge": "lg", "lg": "lg", "lg electronics": "lg", "motorola": "motorola", "oneplus": "oneplus",
    "oppo": "oppo", "realme": "realme", "vivo": "vivo", "asus": "asus", "lenovo": "lenovo", "zte": "zte", "htc": "htc",
    "hmd global": "nokia", "nokia": "nokia", "tcl": "tcl", "philips": "philips", "tp vision": "philips", "hisense": "hisense",
    "nvidia": "nvidia", "google": "google",
}

ANDROID = Publisher("android", "Android", Kind.ANDROID)
GOOGLE = Publisher("google", "Google", Kind.GOOGLE)
CARRIER = Publisher("carrier", "Carrier", Kind.CARRIER)
OTHERS = Publisher("others", "Others", Kind.OTHERS)


def maker_id(manufacturer: str | None) -> str | None:
    if not manufacturer:
        return None
    key = manufacturer.strip().lower()
    return _MAKER_ALIASES.get(key, key.split()[0] if key else None)


def raw_publisher(package: str, entry: Entry | None = None, device_maker: str | None = None) -> Publisher:
    """The publisher of one package, before single-app vendors are folded into Others."""
    if package == "android":
        return ANDROID
    for prefix, pid, name, kind in _KNOWN:
        if package == prefix.rstrip(".") or package.startswith(prefix):
            return Publisher(pid, name, kind)
    group = entry.list if entry else None
    if group == "Aosp":
        return ANDROID
    if group == "Google":
        return GOOGLE
    if group == "Carrier":
        return CARRIER
    parts = package.split(".")
    segment = parts[1] if len(parts) > 1 and parts[0] in _TLDS else parts[0]
    return Publisher(segment.lower(), segment.capitalize(), Kind.VENDOR)


_ORDER = {Kind.ANDROID: 0, Kind.DEVICE_MAKER: 1, Kind.GOOGLE: 2, Kind.MAKER: 3, Kind.VENDOR: 4, Kind.CARRIER: 5, Kind.OTHERS: 6}


def group_packages(
    packages: list[str],
    entries: dict[str, Entry | None] | None = None,
    manufacturer: str | None = None,
) -> dict[str, Publisher]:
    """Publisher of every package on one device, with single-app vendors folded into Others."""
    entries = entries or {}
    device_maker = maker_id(manufacturer)
    raw = {p: raw_publisher(p, entries.get(p), device_maker) for p in packages}
    counts: dict[str, int] = defaultdict(int)
    for pub in raw.values():
        counts[pub.id] += 1
    result = {}
    for package, pub in raw.items():
        if pub.kind is Kind.MAKER and pub.id == device_maker:
            pub = Publisher(pub.id, pub.name, Kind.DEVICE_MAKER)
        elif pub.kind in (Kind.VENDOR, Kind.MAKER) and counts[pub.id] < 2:
            pub = OTHERS
        result[package] = pub
    return result


def sort_key(publisher: Publisher) -> tuple[int, str]:
    return _ORDER[publisher.kind], publisher.name.lower()
