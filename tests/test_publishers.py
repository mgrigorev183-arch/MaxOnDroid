import pytest

from maxondroid.core import paths, uad
from maxondroid.core.publishers import Kind, group_packages, maker_id, raw_publisher, sort_key

DB = uad.load(paths.package_data_dir() / "uad", paths.data_dir())


@pytest.mark.parametrize(
    "package, pid, kind",
    [
        ("android", "android", Kind.ANDROID),
        ("com.android.systemui", "android", Kind.ANDROID),
        ("com.android.vending", "google", Kind.GOOGLE),
        ("com.android.chrome", "google", Kind.GOOGLE),
        ("com.google.android.youtube.tv", "google", Kind.GOOGLE),
        ("com.miui.home", "xiaomi", Kind.MAKER),
        ("com.xiaomi.mitv.upgrade", "xiaomi", Kind.MAKER),
        ("com.sec.android.app.launcher", "samsung", Kind.MAKER),
        ("ru.yandex.searchplugin", "yandex", Kind.VENDOR),
        ("com.yandex.browser", "yandex", Kind.VENDOR),
        ("ru.yandex.music", "yandex", Kind.VENDOR),
        ("com.vkontakte.android", "vk", Kind.VENDOR),
        ("org.telegram.messenger", "telegram", Kind.VENDOR),
        ("com.discord", "discord", Kind.VENDOR),
        ("org.videolan.vlc", "videolan", Kind.VENDOR),
        ("tv.twitch.android.app", "twitch", Kind.VENDOR),
        ("com.qualcomm.qti.services.secureui", "qualcomm", Kind.MAKER),
    ],
)
def test_raw_publisher(package, pid, kind):
    pub = raw_publisher(package, DB.get(package))
    assert (pub.id, pub.kind) == (pid, kind)


def test_uad_list_hints_for_unfamiliar_names():
    netflix = DB.get("com.netflix.ninja")
    assert netflix is not None and netflix.list == "Oem"  # preinstalled by the maker…
    assert raw_publisher("com.netflix.ninja", netflix, "xiaomi").id == "netflix"  # …but published by Netflix
    assert raw_publisher("com.foo.bar", uad.Entry("com.foo.bar", "Aosp", "x", uad.Removal.EXPERT)).kind is Kind.ANDROID
    assert raw_publisher("com.foo.bar", uad.Entry("com.foo.bar", "Carrier", "x", uad.Removal.ADVANCED)).kind is Kind.CARRIER


def test_grouping_folds_single_app_vendors_and_marks_the_device_maker():
    names = [
        "com.android.systemui", "com.google.android.youtube.tv", "com.android.vending",
        "com.xiaomi.mitv.upgrade", "ru.yandex.searchplugin", "com.yandex.browser", "ru.yandex.music",
        "org.telegram.messenger", "com.discord", "com.qualcomm.qti.services.secureui",
    ]
    groups = group_packages(names, {n: DB.get(n) for n in names}, "Xiaomi")
    assert groups["com.xiaomi.mitv.upgrade"].kind is Kind.DEVICE_MAKER  # one app, still its own group
    assert {groups[n].id for n in ("ru.yandex.searchplugin", "com.yandex.browser", "ru.yandex.music")} == {"yandex"}
    assert groups["org.telegram.messenger"].id == groups["com.discord"].id == "others"
    assert groups["com.qualcomm.qti.services.secureui"].id == "others"  # a single chip-maker package
    assert groups["com.android.vending"].kind is Kind.GOOGLE and groups["com.android.systemui"].kind is Kind.ANDROID
    order = sorted({p.id: p for p in groups.values()}.values(), key=sort_key)
    assert [p.id for p in order] == ["android", "xiaomi", "google", "yandex", "others"]


@pytest.mark.parametrize("manufacturer, expected", [("Xiaomi", "xiaomi"), ("samsung", "samsung"), ("LGE", "lg"), ("HMD Global", "nokia"), ("Acme TV Co", "acme"), (None, None), ("", None)])
def test_maker_id(manufacturer, expected):
    assert maker_id(manufacturer) == expected
