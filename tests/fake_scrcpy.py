"""A stand-in for scrcpy used by the tests.

FAKE_SCRCPY_MODE: "run" (default) stays open until killed (printing "N fps" lines
with --print-fps), "fail" exits at once
with an error like real scrcpy, "old" reports version 1.25.
Every start is appended to FAKE_SCRCPY_LOG as {"argv": [...], "adb": $ADB}.
"""

import json
import os
import sys
import time


def main(argv):
    mode = os.environ.get("FAKE_SCRCPY_MODE", "run")
    if argv == ["--version"]:
        print("scrcpy 1.25 <https://github.com/Genymobile/scrcpy>" if mode == "old" else "scrcpy 3.1 <https://github.com/Genymobile/scrcpy>")
        print("Dependencies (compiled / linked):\n - SDL: 2.30.3 / 2.30.3")
        return 0
    log = os.environ.get("FAKE_SCRCPY_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "adb": os.environ.get("ADB")}, ensure_ascii=False) + "\n")
    print("scrcpy 3.1 <https://github.com/Genymobile/scrcpy>", flush=True)
    if mode == "fail":
        print("ERROR: Could not find any ADB device", flush=True)
        return 1
    for arg in argv:
        if arg.startswith("--record="):
            with open(arg.split("=", 1)[1], "wb") as handle:
                handle.write(b"\x1aE\xdf\xa3")  # mkv magic
    print("INFO: Renderer: direct3d", flush=True)
    if "--print-fps" in argv:  # like scrcpy: one line a second (faster here), sometimes with skipped frames
        for i in range(600):
            print("INFO: 59 fps" if i % 2 else "INFO: 57 fps (+2 frames skipped)", flush=True)
            time.sleep(0.1)
    time.sleep(60)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
