# PyInstaller spec for MaxOnDroid: a one-folder windowed build.
#   pyinstaller --noconfirm --clean packaging/maxondroid.spec
# Output: dist/MaxOnDroid/ (MaxOnDroid.exe and _internal/). The release workflow then
# copies the checked scrcpy release into dist/MaxOnDroid/tools/scrcpy/, where
# core/paths.bundled_tools_dir() looks, and Inno Setup packs the whole folder.
# The same spec builds on Linux; the local checks use that to test the packaging.

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH is set by PyInstaller)
VERSION = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', (ROOT / "maxondroid" / "__init__.py").read_text(encoding="utf-8")).group(1)
WINDOWS = sys.platform == "win32"

# Qt modules MaxOnDroid never imports. PySide6-Essentials already leaves most of Qt out;
# this keeps PyInstaller from pulling the rest in through optional imports.
QT_EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtPrintSupport", "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtUiTools",
    "PySide6.QtConcurrent", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtPdf", "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts",
]
EXCLUDES = QT_EXCLUDES + ["tkinter", "unittest", "pydoc", "pytest", "PIL"]


def version_info():
    """Windows file properties: name, version and licence shown in Explorer."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    numbers = tuple(int(part) for part in VERSION.split(".")) + (0,)
    strings = [
        StringStruct("CompanyName", "MaxOnDroid"),
        StringStruct("FileDescription", "MaxOnDroid: Android devices on your home network"),
        StringStruct("FileVersion", VERSION),
        StringStruct("InternalName", "MaxOnDroid"),
        StringStruct("LegalCopyright", "GPL-3.0-only"),
        StringStruct("OriginalFilename", "MaxOnDroid.exe"),
        StringStruct("ProductName", "MaxOnDroid"),
        StringStruct("ProductVersion", VERSION),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "maxondroid" / "data" / "uad"), "maxondroid/data/uad")],
    hiddenimports=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MaxOnDroid",
    console=False,
    upx=False,
    icon=str(ROOT / "packaging" / "maxondroid.ico") if WINDOWS else None,
    version=version_info() if WINDOWS else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="MaxOnDroid",
)
