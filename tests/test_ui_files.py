"""Files tab: browsing, changes behind confirmations, copies both ways, drag and drop, cancel."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QWidget  # noqa: E402

from maxondroid.core import files  # noqa: E402
from maxondroid.core.adb import sh_quote  # noqa: E402
from maxondroid.ui import files_tab  # noqa: E402
from maxondroid.ui.app import create_window  # noqa: E402
from tests import fixtures as fx  # noqa: E402

PHONE = "R58M12ABCDE"
DEVICES = f"List of devices attached\n{PHONE}\tdevice usb:1-1 product:beyond1 model:SM_G973F device:beyond1 transport_id:3\n\n"
SDCARD = "directory|4096|1700000000|DCIM\ndirectory|4096|1700000100|Download\nregular file|5|1700000200|notes.txt\n@@end\n"
DCIM = "directory|4096|1700000000|Camera\nregular file|2400000|1700000300|IMG_1.jpg\n@@end\n"


def script(text, *args):
    """The exact line adb shell gets for a files.py script."""
    return " ".join(sh_quote(a) for a in ["sh", "-c", text, "sh", *args])


def listing(folder, output, **extra):
    return {"args": ["-s", PHONE, "shell", script(files.LIST_SCRIPT, folder)], "stdout": output, **extra}


BASE = [
    {"args": ["devices", "-l"], "stdout": DEVICES},
    listing("/sdcard", SDCARD),
    listing("/sdcard/DCIM", DCIM),
    listing("/data", "@@denied\n"),
]


def make_window(qtbot, fake_adb, rules, devices=DEVICES):
    rules = [{"args": ["devices", "-l"], "stdout": devices}, *rules[1:]]
    rules.append({"args": ["-s", PHONE, "shell", "*"], "stdout": fx.info_output(fx.PHONE_PROPS, fx.PHONE_BATTERY, fx.FEATURES_PHONE)})
    fake_adb.set_rules(rules)
    app = QApplication.instance()
    app.setStyle("Fusion")
    w = create_window(app)
    qtbot.addWidget(w)
    w._set_language("ru")
    w._set_theme("light")
    w.ctx.settings.settings.auto_reconnect = False
    w.resize(1180, 820)
    w.show()
    w.setup_adb(fake_adb.runner)
    qtbot.waitUntil(lambda: len(w.views) == 1, timeout=10000)
    w.tabs.setCurrentWidget(w.files)
    return w


@pytest.fixture
def win(qtbot, fake_adb):
    w = make_window(qtbot, fake_adb, BASE)
    qtbot.waitUntil(lambda: [e.name for e in w.files.entries] == ["DCIM", "Download", "notes.txt"], timeout=10000)
    yield w
    w.timer.stop()
    w.ctx.tasks.shutdown()


def names(win):
    return [win.files.proxy.index(r, 0).data() for r in range(win.files.proxy.rowCount())]


def select(win, *wanted):
    tab = win.files
    tab.table.clearSelection()
    for row in range(tab.proxy.rowCount()):
        if tab.proxy.index(row, 0).data() in wanted:
            tab.table.selectionModel().select(tab.proxy.index(row, 0), tab.table.selectionModel().SelectionFlag.Select | tab.table.selectionModel().SelectionFlag.Rows)


def test_browse_in_and_out(win, qtbot):
    tab = win.files
    assert names(win) == ["DCIM", "Download", "notes.txt"]
    assert tab.proxy.index(2, 1).data() == "5 Б" and tab.path_edit.text() == "/sdcard"
    tab._activated(tab.proxy.index(0, 0))  # double-click DCIM
    qtbot.waitUntil(lambda: tab.folder == "/sdcard/DCIM", timeout=5000)
    assert names(win) == ["Camera", "IMG_1.jpg"]
    assert tab.proxy.index(1, 1).data() == "2,3 МБ"
    tab.go_up()
    qtbot.waitUntil(lambda: tab.folder == "/sdcard", timeout=5000)
    assert [e.name for e in tab.selected()] == ["DCIM"]  # back where we came from
    tab.path_edit.setText("/data")
    tab.path_edit.returnPressed.emit()
    qtbot.waitUntil(lambda: "Нет доступа" in tab.transfer_label.text(), timeout=5000)
    assert tab.folder == "/sdcard" and tab.path_edit.text() == "/sdcard"


def test_sorting_keeps_folders_first(win):
    tab = win.files
    tab.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    assert names(win)[:2] == ["DCIM", "Download"] or names(win)[-2:] == ["DCIM", "Download"]
    assert names(win).index("notes.txt") in (0, 2)


def test_new_folder_rename_and_delete(win, qtbot, fake_adb, monkeypatch):
    tab = win.files
    odd = "Отчёт; rm -rf ~ $(id)"
    rules = BASE + [
        {"args": ["-s", PHONE, "shell", script(files.MKDIR_SCRIPT, "/sdcard/" + odd)], "stdout": "@@ok\n"},
        {"args": ["-s", PHONE, "shell", script(files.RENAME_SCRIPT, "/sdcard/notes.txt", "/sdcard/заметки.txt")], "stdout": "@@ok\n"},
        {"args": ["-s", PHONE, "shell", script(files.REMOVE_SCRIPT, "/sdcard/DCIM", "/sdcard/notes.txt")], "stdout": "@@ok\n"},
    ]
    fake_adb.set_rules(rules)
    answers = iter([(odd, True), ("заметки.txt", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    tab.new_folder()
    qtbot.waitUntil(lambda: "Создана папка" in tab.transfer_label.text(), timeout=5000)
    select(win, "notes.txt")
    tab.rename()
    qtbot.waitUntil(lambda: "Переименовано" in tab.transfer_label.text() and not tab._loading, timeout=5000)

    asked = []
    monkeypatch.setattr(files_tab, "confirm", lambda *a, **k: (asked.append(a[2]), (False, False))[1])
    select(win, "DCIM", "notes.txt")
    tab.delete()
    assert asked and "DCIM/" in asked[0] and "notes.txt" in asked[0] and "содержимым" in asked[0]
    qtbot.wait(300)
    assert not any(files.REMOVE_SCRIPT in " ".join(c) for c in fake_adb.calls())  # cancelled: nothing ran
    monkeypatch.setattr(files_tab, "confirm", lambda *a, **k: (True, False))
    tab.delete()
    qtbot.waitUntil(lambda: "Удалено: 2" in tab.transfer_label.text(), timeout=5000)
    assert ["-s", PHONE, "shell", script(files.REMOVE_SCRIPT, "/sdcard/DCIM", "/sdcard/notes.txt")] in fake_adb.calls()


def test_storage_root_is_refused_before_asking(qtbot, fake_adb, monkeypatch):
    root = "directory|4096|1700000000|sdcard\ndirectory|4096|1700000000|storage\n@@end\n"
    w = make_window(qtbot, fake_adb, [*BASE, listing("/", root)])
    try:
        tab = w.files
        qtbot.waitUntil(lambda: bool(tab.entries), timeout=10000)
        tab.open_folder_path("/")
        qtbot.waitUntil(lambda: tab.folder == "/", timeout=5000)
        warned, asked = [], []
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
        monkeypatch.setattr(files_tab, "confirm", lambda *a, **k: (asked.append(a), (True, False))[1])
        select(w, "sdcard")
        tab.delete()
        assert warned and not asked
        assert "/sdcard" in warned[0][2]
    finally:
        w.timer.stop()
        w.ctx.tasks.shutdown()


def test_dropping_files_on_the_files_tab_copies_them_even_apks(win, qtbot, fake_adb, tmp_path):
    photo = tmp_path / "фото.jpg"
    photo.write_bytes(b"1")
    app_file = tmp_path / "app.apk"
    app_file.write_bytes(b"PK")
    fake_adb.set_rules(BASE + [{"args": ["-s", PHONE, "push", "*"], "stdout": "2 files pushed, 0 skipped.\n"}])
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(photo)), QUrl.fromLocalFile(str(app_file))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    win.dropEvent(event)
    qtbot.waitUntil(lambda: "Скопировано в /sdcard" in win.files.transfer_label.text(), timeout=5000)
    assert ["-s", PHONE, "push", str(photo), str(app_file), "/sdcard/"] in fake_adb.calls()
    assert not any("install" in c for c in fake_adb.calls())
    assert win.tabs.currentWidget() is win.files
    # the list itself takes drops too
    win.files.table.on_drop([photo])
    qtbot.waitUntil(lambda: fake_adb.calls().count(["-s", PHONE, "push", str(photo), "/sdcard/"]) == 1, timeout=5000)


def test_upload_by_dialog_and_download(win, qtbot, fake_adb, tmp_path, monkeypatch):
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF")
    out = tmp_path / "Загрузки"
    fake_adb.set_rules(BASE + [
        {"args": ["-s", PHONE, "push", "*"], "stdout": "1 file pushed, 0 skipped.\n"},
        {"args": ["-s", PHONE, "pull", "*"], "stdout": "2 files pulled, 0 skipped. 30.1 MB/s\n"},
    ])
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(doc)], "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    tab = win.files
    tab.upload_files()
    qtbot.waitUntil(lambda: "1 file pushed" in tab.transfer_label.text(), timeout=5000)
    select(win, "DCIM", "notes.txt")
    assert tab.download_button.isEnabled()
    tab.download()
    qtbot.waitUntil(lambda: "Скачано" in tab.transfer_label.text(), timeout=5000)
    assert ["-s", PHONE, "pull", "/sdcard/DCIM", "/sdcard/notes.txt", str(out)] in fake_adb.calls()
    assert tab.result_open.isVisible() and tab.last_download == out
    assert win.ctx.settings.settings.files_download_dir == str(out)


def test_cancel_a_long_copy(win, qtbot, fake_adb, tmp_path, monkeypatch):
    fake_adb.set_rules(BASE + [{"args": ["-s", PHONE, "pull", "*"], "stdout": "", "sleep": 30}])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    tab = win.files
    select(win, "DCIM")
    tab.download()
    qtbot.waitUntil(lambda: tab.cancel_button.isVisible(), timeout=3000)
    assert not tab.upload_button.isEnabled() and not tab.download_button.isEnabled()
    tab.upload([tmp_path])  # a second copy is refused while one runs
    assert "Дождитесь" in tab.transfer_label.text()
    tab.cancel_button.click()
    qtbot.waitUntil(lambda: "отменено" in tab.transfer_label.text(), timeout=8000)
    assert not tab.cancel_button.isVisible() and tab.upload_button.isEnabled()


def test_offline_device_shows_a_placeholder(qtbot, fake_adb):
    w = make_window(qtbot, fake_adb, BASE, devices=f"List of devices attached\n{PHONE}\toffline transport_id:3\n\n")
    try:
        assert w.files.stack.currentIndex() == 0
        assert "не подключено" in w.files.placeholder.text.text()
    finally:
        w.timer.stop()
        w.ctx.tasks.shutdown()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_files_tab_fits_the_smallest_window(win, qtbot, language):
    win._set_language(language)
    win.resize(win.minimumWidth(), 700)
    qtbot.wait(200)
    page = win.files.stack.widget(1)
    widest = sorted(((w.minimumSizeHint().width(), type(w).__name__, getattr(w, "text", lambda: "")()[:30]) for w in page.findChildren(QWidget) if w.isVisible()), reverse=True)[:6]
    rows = [page.layout().itemAt(i).minimumSize().width() for i in range(page.layout().count())]
    assert page.minimumSizeHint().width() <= page.width(), (page.minimumSizeHint().width(), page.width(), widest, rows)
    buttons = [win.files.upload_button, win.files.download_button, win.files.rename_button, win.files.delete_button]
    assert all(b.geometry().right() <= page.width() for b in buttons)


def test_screenshots(win, qtbot):
    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("set SCREENSHOT_DIR to save screenshots")
    Path(folder).mkdir(parents=True, exist_ok=True)
    win.resize(960, 760)
    for theme in ("light", "dark"):
        win._set_theme(theme)
        select(win, "notes.txt")
        qtbot.wait(150)
        win.grab().save(str(Path(folder) / f"stage4-files-{theme}.png"))


def test_flow_layout_wraps_buttons(qtbot):
    from PySide6.QtWidgets import QPushButton

    from maxondroid.ui.common import FlowLayout

    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host)
    buttons = [QPushButton(f"Довольно длинная кнопка {i}") for i in range(4)]
    for b in buttons:
        flow.addWidget(b)
    host.resize(260, flow.heightForWidth(260))
    host.show()
    qtbot.wait(50)
    assert all(b.geometry().right() <= 260 for b in buttons)
    assert len({b.geometry().top() for b in buttons}) == 4  # one per line at this width
    assert flow.minimumSize().width() == max(b.minimumSizeHint().width() for b in buttons)
    host.resize(2000, flow.heightForWidth(2000))
    qtbot.wait(50)
    assert len({b.geometry().top() for b in buttons}) == 1
