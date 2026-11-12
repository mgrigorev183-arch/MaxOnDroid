"""A stand-in for scrcpy used by the tests.

FAKE_SCRCPY_MODE: "run" (default) stays open until killed (printing "N fps" lines
with --print-fps). A recording file gets "END" only when it is closed properly:
SIGINT, or WM_CLOSE to its window when FAKE_SCRCPY_WINDOW is set on Windows; "fail" exits at once
with an error like real scrcpy, "old" reports version 1.25.
Every start is appended to FAKE_SCRCPY_LOG as {"argv": [...], "adb": $ADB}.
"""

import json
import os
import sys
import threading
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
    record = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--record=")), None)
    if record:
        with open(record, "wb") as handle:
            handle.write(b"FAKEREC\n")  # like a real file: only complete once scrcpy closes properly

    def finish():
        if record:
            with open(record, "ab") as handle:
                handle.write(b"END\n")

    print("INFO: Renderer: direct3d", flush=True)
    if "--print-fps" in argv:  # like scrcpy: one line a second (faster here), sometimes with skipped frames
        def fps():
            for i in range(600):
                print("INFO: 59 fps" if i % 2 else "INFO: 57 fps (+2 frames skipped)", flush=True)
                time.sleep(0.1)

        threading.Thread(target=fps, daemon=True).start()
    if os.environ.get("FAKE_SCRCPY_WINDOW") and sys.platform == "win32":
        # a real window, so closing it with WM_CLOSE can be tested like with scrcpy's SDL window
        import tkinter

        root = tkinter.Tk()
        root.title(next((a.split("=", 1)[1] for a in argv if a.startswith("--window-title=")), "scrcpy"))

        def close():
            finish()
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close)
        root.mainloop()
        return 0
    if os.environ.get("FAKE_SCRCPY_STUBBORN"):  # ignores being asked to quit, like a hung scrcpy
        import signal

        signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        time.sleep(60)
    except KeyboardInterrupt:  # Ctrl+C / SIGINT: scrcpy finishes the recording and exits
        finish()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
