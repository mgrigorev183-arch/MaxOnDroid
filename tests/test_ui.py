"""The window, driven against the fake adb. Runs headless (QT_QPA_PLATFORM=offscreen).

Set SCREENSHOT_DIR to save PNGs of the window in both themes and languages.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from maxondroid.core.devices import State  # noqa: E402
from maxondroid.ui import theme  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

PHONE_INFO = fx.info_output(fx.PHONE_PROPS, fx.PHONE_BATTERY, fx.FEATURES_PHONE, "Galaxy S10 Маши")
TV_INFO = fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV, "Телевизор в зале")

DEVICES = """List of devices attached
R58M12ABCDE            device usb:1-4 product:beyond1lteeea model:SM_G973F device:beyond1 transport_id:3
192.168.1.40:5555      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5
ZY22BXYZ12             unauthorized usb:1-2 transport_id:7

"""

RULES = [
    {"args": ["devices", "-l"], "stdout": DEVICES},
    {"args": ["-s", "R58M12ABCDE", "shell", "*"], "stdout": PHONE_INFO},
    {"args": ["-s", "192.168.1.40:5555", "shell", "*"], "stdout": TV_INFO},
    {"args": ["-s", "192.168.1.40:5555", "usb"], "stdout": "restarting in USB mode\n"},
    {"args": ["mdns", "services"], "stdout": fx.MDNS_SERVICES},
    {"args": ["version"], "stdout": "Android Debug Bridge version 1.0.41\nVersion 35.0.2\n"},
]


@pytest.fixture
def window(qtbot, fake_adb, monkeypatch):
    fake_adb.set_rules(RULES)
    app = QApplication.instance()
    app.setStyle("Fusion")
    win = create_window(app)
    qtbot.addWidget(win)
    win._set_language("ru")
    win._set_theme("light")
    win.ctx.settings.settings.auto_reconnect = False
    win.resize(1180, 760)
    win.show()
    win.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(win.views) == 3, timeout=10000)
    qtbot.waitUntil(lambda: win.overview.info is not None, timeout=10000)
    yield win
    win.timer.stop()
    win.ctx.tasks.shutdown()


def test_devices_get_tokens_and_states(window):
    by_key = {v.key: v for v in window.views}
    assert by_key["R58M12ABCDE"].token == 1
    assert by_key["28041SKV0123"].token == 2
    assert by_key["28041SKV0123"].legacy_network_open
    assert by_key["ZY22BXYZ12"].state is State.UNAUTHORIZED
    model = window.device_list.model_
    texts = [model.data(model.index(r), Qt.ItemDataRole.AccessibleTextRole) for r in range(model.rowCount())]
    assert texts[0].startswith("01 Galaxy S10 Маши")
    assert "сетевой adb открыт" in texts[1]


def test_overview_shows_phone_details(window):
    ov = window.overview
    assert ov.title.text() == "Galaxy S10 Маши"
    assert ov.cards["device"].values["patch"].text() == "2024-01-01"
    assert ov.cards["power"].values["battery"].text() == "87 %"
    assert "по USB" in ov.cards["power"].values["status"].text()
    assert ov.cards["memory"].values["storage"].text() == "Свободно 83 ГБ из 110 ГБ"
    assert "192.168.1.23" in ov.cards["screen_network"].values["ip"].text()
    assert not ov.security_banner.isVisible()


def test_tv_shows_security_banner_and_can_close_network_adb(window, qtbot, fake_adb, monkeypatch):
    window.device_list.select_key("28041SKV0123")
    qtbot.waitUntil(lambda: window.overview.info is not None and window.overview.info.identity.serialno == "28041SKV0123", timeout=10000)
    ov = window.overview
    assert ov.security_banner.isVisible()
    assert "5555" in ov.security_banner.body.text()
    assert ov.cards["power"].values["battery"].text() == "Нет батареи"
    monkeypatch.setattr(ov, "_confirm", lambda *a, **k: True)
    ov.security_banner.button.click()
    qtbot.waitUntil(lambda: ["-s", "192.168.1.40:5555", "usb"] in fake_adb.calls(), timeout=10000)
    qtbot.waitUntil(lambda: any(e.command == "adb -s 192.168.1.40:5555 usb" for e in window.ctx.journal.entries), timeout=5000)
    entry = next(e for e in window.ctx.journal.entries if e.command.endswith(" usb"))
    assert entry.token == 2


def test_unauthorized_device_explains_what_to_do(window, qtbot):
    window.device_list.select_key("ZY22BXYZ12")
    qtbot.waitUntil(lambda: window.overview.view is not None and window.overview.view.key == "ZY22BXYZ12", timeout=5000)
    assert window.overview.state_banner.isVisible()
    assert "Разрешить" in window.overview.state_banner.body.text()
    assert not window.overview.reboot_button.isEnabled()


def test_language_and_theme_switch_live(window):
    window._set_language("en")
    assert window.tabs.tabText(0) == "Overview"
    assert window.connect_button.text() == "Connect a device"
    assert window.overview.cards["power"].heading.text() == "Power"
    window._set_theme("dark")
    assert window.ctx.palette is theme.DARK
    assert window.device_list.delegate.palette is theme.DARK
    window._set_language("ru")
    window._set_theme("light")
    assert window.tabs.tabText(0) == "Обзор"


def test_connect_dialog_validates_and_finds_services(window, qtbot):
    window.open_connect("code")
    dialog = window._connect_dialog
    dialog.code_host.setText("192.168.1.23")
    dialog.code_port.setText("41231")
    dialog.code_value.setText("12")
    dialog.pair_with_code()
    assert "шести цифр" in dialog.status.text()
    dialog.tabs.setCurrentIndex(3)  # found on the network
    qtbot.waitUntil(lambda: dialog.found_list.count() == 3, timeout=10000)
    dialog.found_list.setCurrentRow(1)  # the pairing service
    assert dialog.found_use.text() == "Ввести код"
    dialog.use_found()
    assert dialog.tabs.currentIndex() == 0
    assert dialog.code_port.text() == "41231"
    dialog.tabs.setCurrentIndex(1)  # QR starts waiting
    assert dialog._qr_session is not None
    assert dialog.qr._matrix
    dialog.reject()
    assert dialog._qr_cancel is None


def test_screenshots(window, qtbot):
    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("SCREENSHOT_DIR not set")
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for lang in ("ru", "en"):
        window._set_language(lang)
        for code in ("light", "dark"):
            window._set_theme(code)
            for key, name in (("R58M12ABCDE", "phone"), ("28041SKV0123", "tv")):
                window.device_list.select_key(key)
                qtbot.waitUntil(lambda k=key: window.overview.info is not None and window.overview.view.key == k and not window.overview._loading, timeout=10000)
                qtbot.wait(150)
                window.grab().save(str(out / f"main-{name}-{code}-{lang}.png"))
    window._set_language("ru")
    window._set_theme("light")
    window.open_connect("code")
    qtbot.wait(100)
    window._connect_dialog.grab().save(str(out / "connect-code.png"))
    window._connect_dialog.tabs.setCurrentIndex(1)
    qtbot.wait(100)
    window._connect_dialog.grab().save(str(out / "connect-qr.png"))
    window._connect_dialog.reject()
