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
