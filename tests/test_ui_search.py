"""Search in the Files tab: one index from the device, instant filtering, actions on results."""

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QWidget  # noqa: E402

from maxondroid.core import files, search  # noqa: E402
from maxondroid.core.adb import sh_quote  # noqa: E402
from maxondroid.ui import files_tab  # noqa: E402
from tests.test_ui_files import BASE, PHONE, listing, make_window, script  # noqa: E402

INDEX = (
    "directory|4096|1700000000|./DCIM\n"
    "directory|4096|1700000000|./DCIM/Camera\n"
    "regular file|2400000|1700000300|./DCIM/Camera/IMG_1.JPG\n"
    "regular file|9000000|1700000400|./DCIM/Camera/clip.mp4\n"
    "directory|4096|1700000000|./DCIM/Отпуск 2025\n"
    "regular file|1500000|1700000500|./DCIM/Отпуск 2025/Море.jpeg\n"
    "directory|4096|1700000100|./Download\n"
    "regular file|300000|1700000600|./Download/Отпуск.pdf\n"
    "regular file|5000000|1700000700|./Download/app.apk\n"
    "regular file|5|1700000200|./notes.txt\n"
    "@@end\n"
)


def index_rule(root, output=INDEX, **extra):
    follow = search.FOLLOW_FROM_ROOT if root == "/" else ()
    command = " ".join(sh_quote(a) for a in ["sh", "-c", search.INDEX_SCRIPT, "sh", root, *follow])
    return {"args": ["-s", PHONE, "shell", command], "stdout": output, **extra}


RULES = [*BASE, index_rule("/sdcard")]


@pytest.fixture
def win(qtbot, fake_adb):
    w = make_window(qtbot, fake_adb, RULES)
    qtbot.waitUntil(lambda: bool(w.files.entries), timeout=10000)
    yield w
    w.timer.stop()
    w.ctx.tasks.shutdown()


def index_calls(fake_adb):
    return [c for c in fake_adb.calls() if c[:3] == ["-s", PHONE, "shell"] and 'find . "$@"' in c[3]]


def result_names(win):
    proxy = win.files.result_proxy
    return [proxy.index(r, 0).data() for r in range(proxy.rowCount())]


def type_query(win, qtbot, text):
    win.files.search_edit.setText(text)
    qtbot.waitUntil(lambda: win.files.searching and win.files.index is not None and not win.files._search_timer.isActive(), timeout=8000)
    qtbot.wait(50)


def test_typing_builds_the_index_once_then_filters_instantly(win, qtbot, fake_adb):
    tab = win.files
    type_query(win, qtbot, "отпуск")
    assert result_names(win) == ["Отпуск 2025", "Отпуск.pdf"]
    assert tab.views.currentWidget() is tab.result_table
    assert tab.result_model.headerData(1, Qt.Orientation.Horizontal) == "Расположение"
    proxy = tab.result_proxy
    assert proxy.index(1, 1).data() == "/sdcard/Download" and proxy.index(1, 2).data() == "293 КБ"
    assert "Найдено: 2 из 10 в /sdcard" in tab.status.text()
    started = time.monotonic()
    type_query(win, qtbot, "IMG")
    assert result_names(win) == ["IMG_1.JPG"]
    assert time.monotonic() - started < 2
    assert len(index_calls(fake_adb)) == 1  # the device was asked once


def test_type_groups_and_own_extensions(win, qtbot):
    tab = win.files
    tab.type_combo.setCurrentIndex(tab.type_combo.findData("photos"))
    qtbot.waitUntil(lambda: tab.index is not None and len(result_names(win)) == 2, timeout=8000)
    assert set(result_names(win)) == {"IMG_1.JPG", "Море.jpeg"}
    tab.type_combo.setCurrentIndex(tab.type_combo.findData("folders"))
    qtbot.waitUntil(lambda: set(result_names(win)) == {"DCIM", "Camera", "Отпуск 2025", "Download"}, timeout=3000)
    tab.type_combo.setCurrentIndex(tab.type_combo.findData("custom"))
    assert tab.custom_edit.isVisible()
    tab.custom_edit.setText("apk, .mp4")
    qtbot.waitUntil(lambda: set(result_names(win)) == {"app.apk", "clip.mp4"}, timeout=3000)
    tab.search_edit.setText(".jpg")
    tab.type_combo.setCurrentIndex(tab.type_combo.findData("all"))
    qtbot.waitUntil(lambda: result_names(win) == ["IMG_1.JPG"], timeout=3000)


def test_double_click_opens_the_folder_with_the_file_selected(win, qtbot):
    tab = win.files
    type_query(win, qtbot, "море")
    assert result_names(win) == ["Море.jpeg"]
    tab._result_activated(tab.result_proxy.index(0, 0))
    qtbot.waitUntil(lambda: tab.folder == "/sdcard/DCIM/Отпуск 2025" and not tab._loading, timeout=5000)
    assert not tab.searching and tab.search_edit.text() == ""
    assert tab.views.currentWidget() is tab.table


@pytest.fixture
def win_more(qtbot, fake_adb):
    holiday = "regular file|1500000|1700000500|Море.jpeg\n@@end\n"
    w = make_window(qtbot, fake_adb, [*RULES, listing("/sdcard/DCIM/Отпуск 2025", holiday), listing("/sdcard/Download", "regular file|1|1|Отпуск.pdf\n@@end\n")])
    qtbot.waitUntil(lambda: bool(w.files.entries), timeout=10000)
    yield w
    w.timer.stop()
    w.ctx.tasks.shutdown()


def test_folder_result_opens_that_folder(win_more, qtbot):
    tab = win_more.files
    type_query(win_more, qtbot, "отпуск 2025")
    tab._result_activated(tab.result_proxy.index(0, 0))
    qtbot.waitUntil(lambda: tab.folder == "/sdcard/DCIM/Отпуск 2025" and [e.name for e in tab.entries] == ["Море.jpeg"], timeout=5000)


def test_double_click_selects_the_file_in_its_folder(win_more, qtbot):
    tab = win_more.files
    type_query(win_more, qtbot, "море")
    tab._result_activated(tab.result_proxy.index(0, 0))
    qtbot.waitUntil(lambda: [e.name for e in tab.selected()] == ["Море.jpeg"], timeout=5000)


def test_rename_delete_and_download_from_results_keep_the_index(win, qtbot, fake_adb, tmp_path, monkeypatch):
    tab = win.files
    fake_adb.set_rules(RULES + [
        {"args": ["-s", PHONE, "shell", script(files.RENAME_SCRIPT, "/sdcard/Download/Отпуск.pdf", "/sdcard/Download/Отпуск-2.pdf")], "stdout": "@@ok\n"},
        {"args": ["-s", PHONE, "shell", script(files.REMOVE_SCRIPT, "/sdcard/DCIM/Отпуск 2025")], "stdout": "@@ok\n"},
        {"args": ["-s", PHONE, "pull", "*"], "stdout": "1 file pulled, 0 skipped.\n"},
    ])
    type_query(win, qtbot, "отпуск")
    tab.result_table.selectRow(result_names(win).index("Отпуск.pdf"))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Отпуск-2.pdf", True)))
    tab.rename()
    qtbot.waitUntil(lambda: "Отпуск-2.pdf" in result_names(win), timeout=5000)
    assert [e.name for e in tab.selected()] == ["Отпуск-2.pdf"]  # still selected after the rename
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    tab.download()
    qtbot.waitUntil(lambda: "Скачано" in tab.transfer_label.text(), timeout=5000)
    assert ["-s", PHONE, "pull", "/sdcard/Download/Отпуск-2.pdf", str(tmp_path)] in fake_adb.calls()
    tab.result_table.clearSelection()
    tab.result_table.selectRow(result_names(win).index("Отпуск 2025"))
    asked = []
    monkeypatch.setattr(files_tab, "confirm", lambda *a, **k: (asked.append(a[2]), (True, False))[1])
    tab.delete()
    qtbot.waitUntil(lambda: result_names(win) == ["Отпуск-2.pdf"], timeout=5000)
    assert "/sdcard/DCIM/Отпуск 2025/" in asked[0]  # results show full paths in the confirmation
    type_query(win, qtbot, "море")
    assert result_names(win) == []  # the folder's contents went with it
    assert len(index_calls(fake_adb)) == 1  # all this without asking the device again
    tab.clear_search()
    qtbot.waitUntil(lambda: not tab._loading, timeout=5000)
    assert tab.views.currentWidget() is tab.table


def test_subfolder_search_reuses_the_index_and_refresh_asks_again(win, qtbot, fake_adb):
    tab = win.files
    type_query(win, qtbot, "отпуск")
    tab.clear_search()
    tab.open_folder_path("/sdcard/DCIM")
    qtbot.waitUntil(lambda: tab.folder == "/sdcard/DCIM" and not tab._loading, timeout=5000)
    type_query(win, qtbot, "отпуск")
    assert result_names(win) == ["Отпуск 2025"]  # only below /sdcard/DCIM
    assert "в /sdcard/DCIM" in tab.status.text()
    assert len(index_calls(fake_adb)) == 1
    tab.refresh_button.click()
    qtbot.waitUntil(lambda: len(index_calls(fake_adb)) == 2, timeout=5000)


def test_indexing_can_be_cancelled_and_device_switch_drops_the_index(qtbot, fake_adb):
    w = make_window(qtbot, fake_adb, [*BASE, index_rule("/sdcard", sleep=30)])
    try:
        tab = w.files
        qtbot.waitUntil(lambda: bool(tab.entries), timeout=10000)
        tab.search_edit.setText("x")
        qtbot.waitUntil(lambda: tab.cancel_button.isVisible(), timeout=5000)
        assert "один раз" in tab.transfer_label.text()
        tab.cancel_button.click()
        qtbot.waitUntil(lambda: "остановлен" in tab.transfer_label.text(), timeout=8000)
        assert tab.index is None and not tab.cancel_button.isVisible()
        tab.index = search.Index("/sdcard", ())
        tab._index_key = PHONE
        tab.set_device(None)
        assert tab.index is None and not tab.searching and tab.search_edit.text() == ""
    finally:
        w.timer.stop()
        w.ctx.tasks.shutdown()


def test_escape_and_clearing_return_to_the_folder(win, qtbot):
    tab = win.files
    type_query(win, qtbot, "отпуск")
    tab.search_edit.clear()
    qtbot.waitUntil(lambda: not tab.searching, timeout=3000)
    assert tab.views.currentWidget() is tab.table and "Объектов: 3" in tab.status.text()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_files_tab_with_search_fits_the_smallest_window(win, qtbot, language):
    win._set_language(language)
    type_query(win, qtbot, "отпуск")
    win.files.type_combo.setCurrentIndex(win.files.type_combo.findData("custom"))
    win.resize(win.minimumWidth(), 700)
    qtbot.wait(200)
    page = win.files.stack.widget(1)
    widest = sorted(((w.minimumSizeHint().width(), type(w).__name__) for w in page.findChildren(QWidget) if w.isVisible()), reverse=True)[:5]
    assert page.minimumSizeHint().width() <= page.width(), (page.minimumSizeHint().width(), page.width(), widest)


def test_screenshots(win, qtbot):
    folder = os.environ.get("SCREENSHOT_DIR")
    if not folder:
        pytest.skip("set SCREENSHOT_DIR to save screenshots")
    Path(folder).mkdir(parents=True, exist_ok=True)
    win.resize(960, 760)
    type_query(win, qtbot, "отпуск")
    for theme in ("light", "dark"):
        win._set_theme(theme)
        win.files.result_table.selectRow(0)
        qtbot.wait(150)
        win.grab().save(str(Path(folder) / f"search-{theme}.png"))
    QApplication.processEvents()


def test_going_to_the_top_and_back_keeps_the_right_results(qtbot, fake_adb):
    """The report: photos in /sdcard (1161), then / (12), then /sdcard again showed nothing."""
    top_listing = "directory|4096|1|sdcard\ndirectory|4096|1|system\n@@end\n"
    top_index = "directory|4096|1|./system\nregular file|1300|1|./system/etc/default_screenshot.png\n@@end\n"
    w = make_window(qtbot, fake_adb, [*RULES, listing("/", top_listing), index_rule("/", top_index)])
    try:
        tab = w.files
        qtbot.waitUntil(lambda: bool(tab.entries), timeout=10000)
        photos = tab.type_combo.findData("photos")
        tab.type_combo.setCurrentIndex(photos)
        qtbot.waitUntil(lambda: set(result_names(w)) == {"IMG_1.JPG", "Море.jpeg"}, timeout=8000)
        tab.open_folder_path("/")  # ends the search
        qtbot.waitUntil(lambda: tab.folder == "/" and not tab._loading, timeout=5000)
        tab.type_combo.setCurrentIndex(photos)
        qtbot.waitUntil(lambda: result_names(w) == ["default_screenshot.png"], timeout=8000)
        tab.open_folder_path("/sdcard")
        qtbot.waitUntil(lambda: tab.folder == "/sdcard" and not tab._loading, timeout=5000)
        tab.type_combo.setCurrentIndex(photos)
        qtbot.waitUntil(lambda: set(result_names(w)) == {"IMG_1.JPG", "Море.jpeg"}, timeout=8000)
        assert len(index_calls(fake_adb)) == 2  # /sdcard came back from memory, / was asked once
    finally:
        w.timer.stop()
        w.ctx.tasks.shutdown()
