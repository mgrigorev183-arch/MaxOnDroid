# Third-party software in MaxOnDroid

MaxOnDroid itself is licensed under the GNU General Public License v3.0 only (GPL-3.0-only, see `LICENSE`).
The Windows installer also contains the components below. Each keeps its own licence;
this file lists them with where to get their source code.

## Shipped in the installer

| Component | Version | Licence | Where it is | Source |
|---|---|---|---|---|
| scrcpy | 5.0.1 | Apache-2.0 | `tools\scrcpy\` (its own `LICENSE.txt` is there) | https://github.com/Genymobile/scrcpy |
| adb, AdbWinApi.dll, AdbWinUsbApi.dll (Android SDK Platform-Tools, shipped by scrcpy) | as in scrcpy 5.0.1 | Apache-2.0 (AOSP source) | `tools\scrcpy\` | https://android.googlesource.com/platform/packages/modules/adb |
| FFmpeg libraries (avcodec, avformat, avutil, swresample, shipped by scrcpy) | as in scrcpy 5.0.1 | LGPL-2.1-or-later | `tools\scrcpy\` | https://ffmpeg.org/download.html |
| SDL 3 (shipped by scrcpy) | as in scrcpy 5.0.1 | zlib | `tools\scrcpy\` | https://github.com/libsdl-org/SDL |
| libusb (shipped by scrcpy) | as in scrcpy 5.0.1 | LGPL-2.1-or-later | `tools\scrcpy\` | https://github.com/libusb/libusb |
| Qt 6 (QtCore, QtGui, QtWidgets and their plugins) | 6.12.0 | LGPL-3.0-only | `_internal\PySide6\` | https://download.qt.io/official_releases/qt/ |
| Qt for Python: PySide6-Essentials, shiboken6 | 6.12.0 | LGPL-3.0-only | `_internal\PySide6\`, `_internal\shiboken6\` | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Python runtime and standard library | 3.11 | PSF-2.0 | `_internal\` | https://www.python.org/downloads/source/ |
| OpenSSL, libffi, zlib, bzip2, xz, expat, sqlite (parts of the Python runtime that the build collects) | as in Python 3.11 for Windows | Apache-2.0, MIT, zlib, bzip2, 0BSD/public domain, MIT, public domain | `_internal\` | https://www.python.org/downloads/source/ |
| segno (QR codes for wireless pairing) | 1.6.6 | BSD-3-Clause | `_internal\` | https://github.com/heuer/segno |
| PyInstaller bootloader (starts `MaxOnDroid.exe`) | 6.22.3 | GPL-2.0-or-later with the bootloader exception | `MaxOnDroid.exe` | https://github.com/pyinstaller/pyinstaller |
| Universal Android Debloater Next Generation package lists | snapshot in `maxondroid/data/uad/SOURCE.json` | GPL-3.0 | `_internal\maxondroid\data\uad\` | https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation |

## Notes on the LGPL components

Qt, PySide6, FFmpeg and libusb are dynamically linked libraries in separate files. You may
replace them with your own builds of compatible versions: put them in the same place in the
program folder. Their source code is available at the links above; on request we will also
point to the exact source of the versions in a given release.

## Used only to build the installer (not shipped)

- Inno Setup 6.7.3 (Inno Setup License): https://jrsoftware.org/isinfo.php
- PyInstaller 6.22.3 and pyinstaller-hooks-contrib (GPL-2.0-or-later with exception, Apache-2.0)
- altgraph, packaging, pefile, pywin32-ctypes, setuptools (MIT, Apache-2.0/BSD, MIT, BSD-3-Clause, MIT)

## Full licence texts

- GNU GPL v3: `LICENSE` in this program folder and https://www.gnu.org/licenses/gpl-3.0.html
- GNU LGPL v3: https://www.gnu.org/licenses/lgpl-3.0.html
- GNU LGPL v2.1: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- Apache License 2.0: `tools\scrcpy\LICENSE.txt` and https://www.apache.org/licenses/LICENSE-2.0
- PSF License: https://docs.python.org/3/license.html
- BSD-3-Clause (segno): https://github.com/heuer/segno/blob/master/LICENSE
- zlib License: https://zlib.net/zlib_license.html
