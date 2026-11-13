"""Entry script for the PyInstaller build (the same start as ``python -m maxondroid``)."""

import sys

from maxondroid.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
