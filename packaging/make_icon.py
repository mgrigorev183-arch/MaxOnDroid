"""Draws packaging/maxondroid.ico from the same token the window uses (ui/app.py app_icon).

Run after changing the token's look: ``python packaging/make_icon.py``. Needs Pillow,
which only this script uses; the build itself reads the committed .ico file.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from maxondroid.ui.app import app_icon

    icon = app_icon()
    images = []
    for size in SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        icon.pixmap(size, size).toImage().save(buffer, "PNG")
        images.append(Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA"))
    target = ROOT / "packaging" / "maxondroid.ico"
    largest = images[-1]
    largest.save(target, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
