"""Self-test of an installed or built copy: ``MaxOnDroid.exe --self-test REPORT.json``.

The release workflow runs it twice: on the fresh PyInstaller build and on the copy
the installer put on disk. It checks what a broken build would get wrong: the
bundled adb and scrcpy start, the bundled package list loads, both languages are
complete, and the main window opens. It never talks to devices or the network and
keeps its settings in a temporary folder, so it leaves the user's files alone.

``--require-bundled`` makes it fail when adb or scrcpy come from anywhere but the
``tools`` folder next to the program (a copy on PATH must not hide a broken build).

The report is JSON: ``{"ok": bool, "version": str, "frozen": bool, "checks": [...]}``.
The exit code is 0 only when every check passed. A windowed program has no console,
so the file is the way to read the result.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path

from maxondroid import __version__

MIN_UAD_ENTRIES = 1000  # the bundled snapshot has a few thousand; a handful means a broken copy


class CheckFailed(Exception):
    pass


def _command(exe: str) -> list[str]:
    """How to start a found tool. The tests replace this to run their Python stand-ins."""
    return [exe]


def _inside(path: str | None, folder: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def check_adb(require_bundled: bool) -> str:
    from maxondroid.core import adb, paths

    exe = adb.find_adb()
    if exe is None:
        raise CheckFailed("adb not found")
    if require_bundled and not _inside(exe, paths.bundled_tools_dir()):
        raise CheckFailed(f"adb is not the bundled copy: {exe}")
    version = adb.AdbRunner(_command(exe)).version()
    if not version or "Android Debug Bridge" not in version:
        raise CheckFailed(f"{exe} did not report a version")
    return f"{exe}: {version}"


def check_scrcpy(require_bundled: bool) -> str:
    from maxondroid.core import adb, paths, screen

    adb_exe = adb.find_adb()
    exe = screen.find_scrcpy(adb_path=adb_exe)
    if exe is None:
        raise CheckFailed("scrcpy not found")
    if require_bundled and not _inside(exe, paths.bundled_tools_dir()):
        raise CheckFailed(f"scrcpy is not the bundled copy: {exe}")
    try:
        version = screen.Scrcpy(exe, adb_exe, command_prefix=_command(exe)).check()
    except screen.ScrcpyError as exc:
        raise CheckFailed(f"{exe}: {exc.code} {exc.detail}".strip()) from exc
    return f"{exe}: {'.'.join(map(str, version))}"


def check_uad() -> str:
    from maxondroid.core import paths, uad

    folder = paths.package_data_dir() / "uad"
    db = uad._load_file(folder / "uad_lists.json", uad.Source.BUNDLED, "")
    if len(db.entries) < MIN_UAD_ENTRIES:
        raise CheckFailed(f"only {len(db.entries)} packages in {folder}")
    if not (folder / "SOURCE.json").is_file() or not (folder / "NOTICE.md").is_file():
        raise CheckFailed(f"SOURCE.json or NOTICE.md missing in {folder}")
    return f"{len(db.entries)} packages, sha256 {db.sha256[:12]}"


def check_i18n() -> str:
    from maxondroid.i18n import LANGUAGES

    keys = {code: set(strings) for code, strings in LANGUAGES.items()}
    ru, en = keys["ru"], keys["en"]
    if ru != en:
        raise CheckFailed(f"keys differ: only ru {sorted(ru - en)[:5]}, only en {sorted(en - ru)[:5]}")
    empty = [f"{code}:{key}" for code, strings in LANGUAGES.items() for key, text in strings.items() if not str(text).strip()]
    if empty:
        raise CheckFailed(f"empty strings: {empty[:5]}")
    return f"{len(en)} strings in ru and en"


def check_window() -> str:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from maxondroid import APP_NAME, i18n
    from maxondroid.ui import app as ui_app

    qt = QApplication.instance() or QApplication([sys.argv[0]])  # QT_QPA_PLATFORM still applies
    qt.setApplicationName(APP_NAME)
    window = ui_app.create_window(qt)
    try:
        window.show()
        for _ in range(20):
            QCoreApplication.processEvents()
        if not window.isVisible():
            raise CheckFailed("the main window did not show")
        titles = []
        for code in ("en", "ru"):
            i18n.set_language(code)
            QCoreApplication.processEvents()
            titles.append(window.tabs.tabText(0))
        if titles[0] == titles[1] or not all(titles):
            raise CheckFailed(f"tab titles did not switch language: {titles}")
        return f"opened on '{qt.platformName()}', first tab {titles}"
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.processEvents()


CHECKS: list[tuple[str, Callable[[bool], str]]] = [
    ("adb", check_adb),
    ("scrcpy", check_scrcpy),
    ("uad", lambda _req: check_uad()),
    ("i18n", lambda _req: check_i18n()),
    ("window", lambda _req: check_window()),
]


def run(require_bundled: bool = False) -> dict:
    checks = []
    for name, check in CHECKS:
        try:
            checks.append({"name": name, "ok": True, "detail": check(require_bundled)})
        except CheckFailed as exc:
            checks.append({"name": name, "ok": False, "detail": str(exc)})
        except Exception as exc:  # a crash is a failed check, never a silent pass
            checks.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=6)})
    return {
        "ok": bool(checks) and all(c["ok"] for c in checks),
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "checks": checks,
    }


def parse_args(argv: list[str]) -> tuple[Path, bool] | None:
    """``[--self-test REPORT.json] [--require-bundled]``; None when this is a normal start."""
    if "--self-test" not in argv:
        return None
    index = argv.index("--self-test")
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise SystemExit("usage: MaxOnDroid --self-test REPORT.json [--require-bundled]")
    return Path(argv[index + 1]), "--require-bundled" in argv


def main(report: Path, require_bundled: bool = False) -> int:
    report = report.resolve()
    with tempfile.TemporaryDirectory(prefix="maxondroid-selftest-", ignore_cleanup_errors=True) as home:
        previous = os.environ.get("MAXONDROID_HOME")
        os.environ["MAXONDROID_HOME"] = home  # settings, logs and data go here, not to the user's folders
        try:
            result = run(require_bundled)
        finally:
            if previous is None:
                os.environ.pop("MAXONDROID_HOME", None)
            else:
                os.environ["MAXONDROID_HOME"] = previous
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if sys.stdout is not None:  # a console build or python -m: also print a summary
        for check in result["checks"]:
            print(f"{'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
        print("SELF-TEST " + ("OK" if result["ok"] else "FAILED"))
    return 0 if result["ok"] else 1
