"""Stage 2 in the window: risk acknowledgment, Apps tab, Debloat tab, history and presets."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from maxondroid.core import presets  # noqa: E402
from maxondroid.core.packages import LIST_SCRIPT  # noqa: E402
from maxondroid.core.presets import Preset, PresetAction  # noqa: E402
from maxondroid.ui import apps_tab, debloat_tab, package_support  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

TV = "192.168.1.40:5555"
TV_KEY = "28041SKV0123"
TV_INFO = fx.info_output(fx.TV_PROPS, fx.TV_BATTERY, fx.FEATURES_TV, "Телевизор в зале")
DEVICES = "List of devices attached\n192.168.1.40:5555      device product:aquaman model:MiTV_AFKR0 device:aquaman transport_id:5\n\n"


def sh(command, stdout):
    return {"args": ["-s", TV, "shell", command], "stdout": stdout}


RULES = [
    {"args": ["devices", "-l"], "stdout": DEVICES},
    {"args": ["-s", TV, "shell", LIST_SCRIPT], "stdout": fx.PACKAGES_OUTPUT},
    sh("pm uninstall -k --user 0 com.google.android.youtube.tv", "Success\n"),
    sh("pm uninstall -k --user 0 com.google.android.apps.tv.launcherx", "Success\n"),
    sh("pm disable-user --user 0 com.google.android.youtube.tv", "Package com.google.android.youtube.tv new state: disabled-user\n"),
    sh("cmd package install-existing --user 0 com.google.android.youtube.tv", "Package com.google.android.youtube.tv installed for user: 0\n"),
    sh("cmd package install-existing --user 0 com.google.android.apps.tv.launcherx", "Package com.google.android.apps.tv.launcherx installed for user: 0\n"),
    sh("cmd package install-existing --user 0 com.google.android.tvrecommendations", "Package com.google.android.tvrecommendations installed for user: 0\n"),
    sh("pm enable --user 0 com.google.android.youtube.tv", "Package com.google.android.youtube.tv new state: enabled\n"),
    sh("pm enable --user 0 com.netflix.ninja", "Package com.netflix.ninja new state: enabled\n"),
    sh("monkey -p org.videolan.vlc -c android.intent.category.LEANBACK_LAUNCHER 1", "Events injected: 1\n"),
    {"args": ["-s", TV, "install", "-r", "*"], "stdout": "Performing Streamed Install\nSuccess\n"},
    {"args": ["-s", TV, "shell", "*"], "stdout": TV_INFO},
]


@pytest.fixture
def win(qtbot, fake_adb):
    fake_adb.set_rules(RULES)
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w._set_language("ru")
    w._set_theme("light")
    w.ctx.settings.settings.auto_reconnect = False
    w.resize(1180, 760)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 1 and w.ctx.packages.get(TV_KEY) is not None, timeout=10000)
    yield w
    w.timer.stop()
    w.ctx.tasks.shutdown()


@pytest.fixture
def accept_all(monkeypatch):
    seen = []

    def fake_confirm(parent, title, text, ok_text, danger=False, checkbox=None):
        seen.append((title, text, ok_text, danger))
        return True, True

    for module in (package_support, apps_tab, debloat_tab):
        monkeypatch.setattr(module, "confirm", fake_confirm)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: infos.append(a)))
    return seen, infos


def shell_calls(fake_adb):
    return [c[3] for c in fake_adb.calls() if len(c) > 3 and c[2] == "shell"]


def test_risk_acknowledgment_collapses_and_persists(win, qtbot):
    banner = win.overview.security_banner
    qtbot.waitUntil(lambda: banner.isVisible() and banner.button2.isVisible(), timeout=5000)
    assert banner.button2.text() == "Я понимаю риск, это моё устройство"
    banner.button2.click()
    qtbot.waitUntil(lambda: "Риск принят" in banner.title.text(), timeout=5000)
    assert not banner.body.isVisible() and banner.button.text() == "Подробнее"
    assert win.ctx.registry.get(TV_KEY).legacy_risk_accepted is True
    reloaded = type(win.ctx.registry)(win.ctx.registry.path)
    assert reloaded.get(TV_KEY).legacy_risk_accepted is True
    banner.button.click()  # details
    assert banner.button2.text() == "Снова предупреждать"
    assert banner.button.text() == "Выключить сетевой adb"
    banner.button2.click()
    assert win.ctx.registry.get(TV_KEY).legacy_risk_accepted is False
    # the ring on the token stays: the device list still reports the open port
    assert win.views[0].legacy_network_open


def test_apps_tab_lists_filters_and_shows_descriptions(win, qtbot):
    win.tabs.setCurrentWidget(win.apps)
    tab = win.apps
    qtbot.waitUntil(lambda: tab.stack.currentIndex() == 1, timeout=5000)
    assert tab.model.rowCount() == 9
    assert tab.proxy.rowCount() == 8  # removed tvrecommendations hidden by default
    tab.search.setText("youtube")
    assert tab.proxy.rowCount() == 1
    index = tab.proxy.index(0, 4)
    assert index.data() == "YouTube app"
    tab.search.clear()
    tab.kind.setCurrentIndex(tab.kind.findData("user"))
    assert [tab.proxy.index(r, 0).data() for r in range(tab.proxy.rowCount())] == ["org.videolan.vlc"]
    tab.kind.setCurrentIndex(tab.kind.findData("all"))
    tab.state.setCurrentIndex(tab.state.findData("removed"))
    assert tab.proxy.index(0, 0).data() == "com.google.android.tvrecommendations"
    assert "Показано 1 из 9" == tab.count_label.text()


def select(tab, name):
    for row in range(tab.proxy.rowCount()):
        if tab.proxy.index(row, 0).data() == name:
            tab.table.selectRow(row)
            return
    raise AssertionError(name)


def test_apps_actions(win, qtbot, fake_adb, accept_all):
    seen, _ = accept_all
    win.tabs.setCurrentWidget(win.apps)
    tab = win.apps
    qtbot.waitUntil(lambda: tab.stack.currentIndex() == 1, timeout=5000)
    select(tab, "org.videolan.vlc")
    assert tab.launch_button.isEnabled()
    tab.launch_button.click()
    qtbot.waitUntil(lambda: "запущено" in tab.banner.body.text(), timeout=5000)
    select(tab, "com.google.android.youtube.tv")
    assert tab.toggle_button.text() == "Отключить"
    tab.toggle_button.click()
    qtbot.waitUntil(lambda: "pm disable-user --user 0 com.google.android.youtube.tv" in shell_calls(fake_adb), timeout=5000)
    qtbot.waitUntil(lambda: tab.banner.body.text().startswith("Готово"), timeout=5000)
    assert win.ctx.changes.pending(TV_KEY)[0].action == "disable"
    tab.state.setCurrentIndex(tab.state.findData("removed"))
    select(tab, "com.google.android.tvrecommendations")
    assert tab.remove_button.text() == "Вернуть"
    tab.remove_button.click()
    qtbot.waitUntil(lambda: "cmd package install-existing --user 0 com.google.android.tvrecommendations" in shell_calls(fake_adb), timeout=5000)


def test_drag_and_drop_installs(win, qtbot, fake_adb, tmp_path):
    apk_file = tmp_path / "Kodi 21.apk"
    apk_file.write_bytes(b"apk")
    (tmp_path / "notes.txt").write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(apk_file)), QUrl.fromLocalFile(str(tmp_path / "notes.txt"))])
    assert apps_tab.AppsTab.dropped_files(mime) == [apk_file]
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.dropEvent(event)
    assert win.tabs.currentWidget() is win.apps
    qtbot.waitUntil(lambda: any(c[:4] == ["-s", TV, "install", "-r"] for c in fake_adb.calls()), timeout=5000)
    qtbot.waitUntil(lambda: win.apps.banner.body.text() == "Установлено: 1.", timeout=5000)
    call = next(c for c in fake_adb.calls() if c[:3] == ["-s", TV, "install"])
    assert Path(call[4]) == apk_file


def tick(tab, name):
    for row in range(tab.proxy.rowCount()):
        index = tab.proxy.index(row, 0)
        if tab.proxy.index(row, 1).data() == name:
            tab.proxy.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
            return
    raise AssertionError(name)


def test_debloat_remove_critical_blocked_and_undo(win, qtbot, fake_adb, accept_all):
    seen, infos = accept_all
    win.tabs.setCurrentWidget(win.debloat)
    tab = win.debloat
    qtbot.waitUntil(lambda: tab.stack.currentIndex() == 1, timeout=5000)
    assert "База UAD-ng" in tab.db_label.text() and "встроенная" in tab.db_label.text()
    names = {tab.proxy.index(r, 1).data() for r in range(tab.proxy.rowCount())}
    assert "com.google.android.youtube.tv" in names and "com.android.systemui" not in names  # Unsafe hidden by default
    tab.table.selectRow(0)
    assert tab.details.toPlainText()
    tab.level_buttons[debloat_tab.uad.Removal.UNSAFE].setChecked(True)
    tab.level_buttons[debloat_tab.uad.Removal.EXPERT].setChecked(True)
    tab.unlisted.setChecked(True)
    tick(tab, "com.google.android.youtube.tv")
    tick(tab, "com.google.android.apps.tv.launcherx")
    tick(tab, "com.android.shell")
    assert tab.count_label.text().endswith("отмечено 3")
    tab.remove_button.click()
    assert len(infos) == 1  # blocked package explained, not removed
    titles = [s[0] for s in seen]
    assert titles[0] == "Важные системные пакеты"  # the launcher needs the red confirmation
    assert "главный экран" in seen[0][1] and seen[0][3] is True
    qtbot.waitUntil(lambda: "pm uninstall -k --user 0 com.google.android.apps.tv.launcherx" in shell_calls(fake_adb), timeout=5000)
    qtbot.waitUntil(lambda: tab.banner.body.text().startswith("Готово: 2"), timeout=5000)
    assert not any("com.android.shell" in c for c in shell_calls(fake_adb))
    assert tab.history_button.text() == "История изменений (2)"

    dialog = debloat_tab.HistoryDialog(win.ctx, win.views[0], tab.snapshot(), tab)
    assert dialog.tree.topLevelItemCount() == 2
    dialog.undo_all()
    qtbot.waitUntil(lambda: "cmd package install-existing --user 0 com.google.android.youtube.tv" in shell_calls(fake_adb), timeout=5000)
    qtbot.waitUntil(lambda: dialog.changed, timeout=5000)
    assert win.ctx.changes.pending(TV_KEY) == []
    dialog.close()


def test_preset_apply(win, qtbot, fake_adb, accept_all, tmp_path):
    seen, _ = accept_all
    path = tmp_path / "tv.json"
    presets.save(Preset("Телевизор", "", (("com.google.android.youtube.tv", PresetAction.DISABLE), ("com.absent.app", PresetAction.REMOVE))), path)
    win.tabs.setCurrentWidget(win.debloat)
    qtbot.waitUntil(lambda: win.debloat.stack.currentIndex() == 1, timeout=5000)
    win.debloat.apply_preset(path)
    assert "изменить 1" in seen[0][1] and "нет на этом устройстве 1" in seen[0][1]
    qtbot.waitUntil(lambda: "pm disable-user --user 0 com.google.android.youtube.tv" in shell_calls(fake_adb), timeout=5000)
    qtbot.waitUntil(lambda: not win.debloat._busy, timeout=5000)
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "other"}')
    win.debloat.apply_preset(bad)
    assert "не пресет" in win.debloat.banner.body.text()


def test_offline_device_shows_placeholder(win, qtbot):
    from dataclasses import replace

    from maxondroid.core.devices import State

    view = replace(win.views[0], state=State.DISCONNECTED, serial=None)
    win.apps.set_device(view)
    win.debloat.set_device(view)
    assert win.apps.stack.currentIndex() == 0 and "не подключено" in win.apps.placeholder.text.text()
    assert win.debloat.stack.currentIndex() == 0


def test_stage2_screenshots(win, qtbot):
    import os

    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("SCREENSHOT_DIR not set")
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for code in ("light", "dark"):
        win._set_theme(code)
        win.tabs.setCurrentWidget(win.overview)
        qtbot.wait(200)
        win.grab().save(str(out / f"stage2-overview-risk-{code}.png"))
        win.tabs.setCurrentWidget(win.apps)
        qtbot.wait(100)
        win.grab().save(str(out / f"stage2-apps-{code}.png"))
        win.tabs.setCurrentWidget(win.debloat)
        win.debloat.table.selectRow(1)
        qtbot.wait(100)
        win.grab().save(str(out / f"stage2-debloat-{code}.png"))
    win._set_theme("light")


def test_failed_package_list_offers_retry(win, qtbot, fake_adb):
    fake_adb.set_rules([{"args": ["-s", TV, "shell", LIST_SCRIPT], "stderr": "error: closed", "rc": 1}] + RULES)
    win.ctx.packages.snapshots.clear()
    win.ctx.packages.load(win.views[0])
    qtbot.waitUntil(lambda: TV_KEY in win.ctx.packages.errors, timeout=5000)
    placeholder = win.apps.placeholder
    assert win.apps.stack.currentIndex() == 0
    assert "error: closed" in placeholder.text.text() and placeholder.button.text() == "Повторить"
    fake_adb.set_rules(RULES)
    placeholder.button.click()
    qtbot.waitUntil(lambda: win.apps.stack.currentIndex() == 1, timeout=5000)
    assert win.debloat.stack.currentIndex() == 1
