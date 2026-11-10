# tools/

The installer build (stage 5) puts the scrcpy Windows release here (`tools/scrcpy/`, which includes `adb.exe`). MaxOnDroid looks for adb in this order: the path set in Settings, `tools/scrcpy/adb.exe`, `tools/platform-tools/adb.exe`, `tools/adb.exe`, then `adb` on PATH.

Nothing in this folder except this file is committed.
