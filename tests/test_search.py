"""File search: the index script for real in sh, and the filtering done in the app."""

import shutil
import threading

import pytest

from maxondroid.core import search
from maxondroid.core.files import FilesError, RemoteEntry
from maxondroid.core.search import Index, build_index, matches, parse_index
from tests.test_files import NASTY, SERIAL, LocalShell, needs_sh, no_injection, nobody_device


@pytest.fixture
def device(tmp_path):
    sd = tmp_path / "sdcard"
    for folder in ("DCIM/Camera", "DCIM/Отпуск 2025", "Download/old", "Music"):
        (sd / folder).mkdir(parents=True)
    for rel, data in {
        "DCIM/Camera/IMG_1.JPG": b"x" * 10,
        "DCIM/Camera/clip.mp4": b"v" * 20,
        "DCIM/Отпуск 2025/Море.jpeg": b"m",
        "Download/Отпуск.pdf": b"p",
        "Download/old/app.apk": b"a",
        "Download/" + NASTY + ".txt": b"n",
        "Music/song.flac": b"s",
        ".nomedia": b"",
    }.items():
        (sd / rel).write_bytes(data)
    return LocalShell(tmp_path)


@needs_sh
def test_index_lists_everything_below_for_real(device):
    index, result = build_index(device, SERIAL, "/sdcard")
    paths = {e.path: e for e in index.entries}
    assert "/sdcard/DCIM/Camera/IMG_1.JPG" in paths and paths["/sdcard/DCIM/Camera/IMG_1.JPG"].size == 10
    assert paths["/sdcard/DCIM/Отпуск 2025"].is_dir
    assert "/sdcard/Download/" + NASTY + ".txt" in paths
    assert "/sdcard/.nomedia" in paths
    assert len(index.entries) == 14  # 6 folders and 8 files, each once
    assert no_injection(device.root)
    sub, _ = build_index(device, SERIAL, "/sdcard/Download")
    assert {e.name for e in sub.entries} == {"old", "Отпуск.pdf", "app.apk", NASTY + ".txt"}


@needs_sh
def test_index_without_stat_falls_back_to_find(device, tmp_path):
    bin_dir = tmp_path / "oldbin"
    bin_dir.mkdir()
    for tool in ("sh", "find"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    index, _ = build_index(LocalShell(device.root, path_env=str(bin_dir)), SERIAL, "/sdcard")
    by_path = {e.path: e for e in index.entries}
    assert by_path["/sdcard/DCIM/Camera"].is_dir and by_path["/sdcard/Music/song.flac"].kind == "file"
    assert by_path["/sdcard/Music/song.flac"].size == 0  # sizes come only from stat: this came from find


def test_unreadable_folder_cannot_be_indexed():
    device, base = nobody_device()
    try:
        with pytest.raises(FilesError) as denied:
            build_index(device, SERIAL, "/sdcard/data")
        assert denied.value.code == "denied"
        index, _ = build_index(device, SERIAL, "/sdcard")  # the locked folder is listed, its inside is skipped
        assert {e.path for e in index.entries} == {"/sdcard/Pictures", "/sdcard/Pictures/a.jpg", "/sdcard/data"}
    finally:
        (base / "sdcard" / "data").chmod(0o755)
        shutil.rmtree(base)


def test_index_can_be_cancelled(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stdout": "", "sleep": 30}])
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    index, result = build_index(fake_adb.runner, SERIAL, "/sdcard", cancel=cancel)
    assert index is None and result.cancelled


def entry(path, kind="file", size=1):
    return RemoteEntry(path.rsplit("/", 1)[1], path, kind, size, 1700000000)


ENTRIES = [
    entry("/sdcard/DCIM/Camera/IMG_1.JPG"),
    entry("/sdcard/DCIM/Camera/clip.mp4"),
    entry("/sdcard/DCIM/Отпуск 2025", "dir"),
    entry("/sdcard/DCIM/Отпуск 2025/Море.jpeg"),
    entry("/sdcard/Download/Отпуск.pdf"),
    entry("/sdcard/Download/отпуск.jpg.txt"),
    entry("/sdcard/Download/old/app.apk"),
    entry("/sdcard/Music/song.flac"),
    entry("/sdcard/.nomedia"),
    entry("/sdcard/Download/jpg-notes.doc"),
]


def names(found):
    return [e.name for e in found]


def test_name_part_without_case_or_extension():
    assert names(search.search(ENTRIES, "ОТПУСК")) == ["Отпуск 2025", "отпуск.jpg.txt", "Отпуск.pdf"]
    assert names(search.search(ENTRIES, "pdf")) == []  # the extension is not part of the name
    assert names(search.search(ENTRIES, "img_")) == ["IMG_1.JPG"]
    assert names(search.search(ENTRIES, "nomedia")) == [".nomedia"]  # a dot file is all name


def test_extension_queries_and_type_groups():
    assert names(search.search(ENTRIES, ".jpg")) == ["IMG_1.JPG"]
    assert names(search.search(ENTRIES, "", "photos")) == ["IMG_1.JPG", "Море.jpeg"]
    assert names(search.search(ENTRIES, "", "videos")) == ["clip.mp4"]
    assert names(search.search(ENTRIES, "", "music")) == ["song.flac"]
    assert names(search.search(ENTRIES, "", "documents")) == ["jpg-notes.doc", "отпуск.jpg.txt", "Отпуск.pdf"]
    assert names(search.search(ENTRIES, "", "apk")) == ["app.apk"]
    assert names(search.search(ENTRIES, "", "folders")) == ["Отпуск 2025"]
    assert names(search.search(ENTRIES, "море", "photos")) == ["Море.jpeg"]
    custom = search.parse_extensions(" .PDF, flac;*.mp4 ")
    assert custom == ("pdf", "flac", "mp4")
    assert names(search.search(ENTRIES, "", "custom", custom)) == ["clip.mp4", "song.flac", "Отпуск.pdf"]
    assert not matches(entry("/sdcard/a.JPG", "dir"), "", "photos")  # a folder is never a photo
    with pytest.raises(ValueError):
        search.search(ENTRIES, "", "nonsense")


def test_index_reuse_and_updates():
    index = Index("/sdcard", tuple(ENTRIES))
    assert index.covers("/sdcard/DCIM") and index.covers("/sdcard") and not index.covers("/storage") and not index.covers("/sdcardx")
    assert {e.name for e in index.below("/sdcard/DCIM")} == {"IMG_1.JPG", "clip.mp4", "Отпуск 2025", "Море.jpeg"}
    smaller = index.without(["/sdcard/DCIM/Отпуск 2025", "/sdcard/Music/song.flac"])
    assert "Море.jpeg" not in names(smaller.entries) and "song.flac" not in names(smaller.entries)
    moved = index.renamed("/sdcard/DCIM/Отпуск 2025", "/sdcard/DCIM/Море 2025")
    assert "/sdcard/DCIM/Море 2025/Море.jpeg" in {e.path for e in moved.entries}
    assert search.location(ENTRIES[0]) == "/sdcard/DCIM/Camera"
    assert search.location(ENTRIES[0], "/sdcard") == "./DCIM/Camera"


def test_parse_index_handles_junk_and_denied():
    text = "directory|4096|1|./A\nregular file|5|2|./A/b|c.txt\ngarbage\nregular file|x|y|./bad\n@@end\n"
    found = parse_index(text, "/sdcard")
    assert [(e.path, e.size) for e in found] == [("/sdcard/A", 4096), ("/sdcard/A/b|c.txt", 5), ("/sdcard/bad", 0)]
    with pytest.raises(FilesError):
        parse_index("@@denied\n", "/data")


def test_an_index_of_root_does_not_answer_for_a_folder_it_could_not_enter():
    """The report: search /sdcard (1161 photos), then /, then /sdcard again showed nothing."""
    root_index = Index("/", (entry("/system/etc/a.png"), entry("/system", "dir")))
    assert root_index.covers("/") and root_index.covers("/system")
    assert not root_index.covers("/sdcard")  # nothing of /sdcard in it: ask the device
    assert not root_index.covers("/system/etc/a.png/x")
    with_storage = Index("/", (entry("/sdcard", "dir"), entry("/sdcard/DCIM/p.jpg")))
    assert with_storage.covers("/sdcard") and with_storage.covers("/sdcard/DCIM")


@needs_sh
def test_index_from_the_top_enters_the_sdcard_link_and_skips_kernel_trees(tmp_path):
    top = tmp_path / "top"
    (top / "storage" / "emulated" / "0" / "DCIM").mkdir(parents=True)
    (top / "storage" / "emulated" / "0" / "DCIM" / "p.jpg").write_text("p")
    (top / "system" / "etc").mkdir(parents=True)
    (top / "system" / "etc" / "a.png").write_text("a")
    (top / "proc" / "1").mkdir(parents=True)
    (top / "proc" / "1" / "status").write_text("s")
    (top / "sdcard").symlink_to(top / "storage" / "emulated" / "0")
    device = LocalShell(tmp_path)
    index, _ = build_index(device, SERIAL, str(top), follow=search.FOLLOW_FROM_ROOT)
    paths = {e.path for e in index.entries}
    assert str(top / "sdcard" / "DCIM" / "p.jpg") in paths  # entered through the link
    assert str(top / "system" / "etc" / "a.png") in paths
    assert not any("/proc" in p for p in paths)  # skipped
    plain, _ = build_index(device, SERIAL, str(top), follow=())
    assert str(top / "sdcard" / "DCIM" / "p.jpg") not in {e.path for e in plain.entries}  # control: find alone does not


def test_the_link_to_user_storage_is_followed_only_from_the_top(fake_adb):
    fake_adb.set_rules([{"args": ["-s", SERIAL, "shell", "*"], "stdout": "@@end\n"}])
    build_index(fake_adb.runner, SERIAL, "/")
    build_index(fake_adb.runner, SERIAL, "/sdcard")
    top, sd = [c[3] for c in fake_adb.calls()]
    assert top.endswith(" / sdcard/") and sd.endswith(" /sdcard")
