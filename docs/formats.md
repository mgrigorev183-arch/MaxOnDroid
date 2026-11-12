# MaxOnDroid file formats

All files are UTF-8 JSON. Each carries a `format` name and an integer `version`; readers must ignore unknown keys and treat a file with an unknown `format` as absent. Future front ends (for example an Android version) read these same files.

## devices.json — saved devices

Location: `%APPDATA%\MaxOnDroid\devices.json`.

```json
{
  "format": "maxondroid.devices",
  "version": 1,
  "devices": [
    {
      "key": "R58M12ABCDE",
      "token": 1,
      "alias": "Телефон Маши",
      "model": "SM-G973F",
      "manufacturer": "samsung",
      "kind": "phone",
      "network": {"host": "192.168.1.23", "port": 37159, "mode": "paired"},
      "mdns_name": "adb-R58M12ABCDE-Xy12Ab",
      "first_seen": "2026-11-10T20:00:00+00:00",
      "last_seen": "2026-11-10T21:00:00+00:00"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `key` | Stable identity: the device's `ro.serialno` when it can be read, otherwise the adb serial. |
| `token` | The device's number, 1–99, unique in the file. Freed numbers are reused, smallest first. |
| `alias` | Name the user gave the device in MaxOnDroid; empty when not set. |
| `kind` | `phone`, `tablet`, `tv`, `watch` or `unknown`. |
| `network` | Last network address, or `null`. `mode` is `paired` (Android 11+ wireless debugging) or `legacy` (`adb tcpip`, open to the whole network). |
| `mdns_name` | Instance name the device announces over mDNS, used to find its new port after a restart. |

Entries with a missing key, a token outside 1–99 or a duplicate token are dropped when the file is read.

## settings.json — user settings

Location: `%APPDATA%\MaxOnDroid\settings.json`.

```json
{
  "format": "maxondroid.settings",
  "version": 1,
  "settings": {
    "language": "system",
    "theme": "system",
    "adb_path": "",
    "journal_visible": true,
    "auto_reconnect": true,
    "window_geometry": "",
    "window_state": ""
  }
}
```

`language` is `system`, `ru` or `en`; `theme` is `system`, `light` or `dark`; an empty `adb_path` means "bundled adb, otherwise the one on PATH". Values of the wrong type fall back to the defaults.

The Screen tab adds `scrcpy_path`, `capture_dir`, `capture_format` (`mp4` or `mkv`), the last used options (`screen_preset`, `screen_max_size`, `screen_bit_rate` 1–50, `screen_max_fps`, `screen_audio`, `screen_turn_off`, `screen_on_top`, `screen_stay_awake`, `screen_view_only`, `screen_keyboard` `sdk` or `uhid`) and `screen_devices`, the options of each device by its key (at most 64, the oldest dropped first):

```json
"screen_devices": {
  "28041SKV0123": {"preset": "speed", "max_size": 1280, "bit_rate_mbps": 4, "max_fps": 30, "audio": true,
                   "turn_screen_off": false, "always_on_top": false, "stay_awake": false, "view_only": false,
                   "keyboard": "sdk"}
}
```

A device without an entry starts from the last used options, a TV from the Speed preset.

## console.json — console history and saved commands

Location: next to `settings.json`. Written atomically after each run and each change.

```json
{
  "format": "maxondroid.console",
  "version": 1,
  "history": [{"mode": "adb", "text": "devices -l"}, {"mode": "shell", "text": "pm list packages -3"}],
  "saved": [{"name": "Сторонние приложения", "mode": "shell", "text": "pm list packages -3"}]
}
```

`mode` is `adb` (what follows `adb` in cmd) or `shell` (one line for the device shell). At most 200 history entries (oldest dropped) and 100 saved commands; entries of the wrong shape are skipped when loading. Settings also keep `console_mode` (the last mode) and `files_download_dir` (where the Files tab last copied to).

## diag-YYYY-MM-DD.log — diagnostics

Location: `%LOCALAPPDATA%\MaxOnDroid\logs\`, next to the command journal, kept 14 days, at most 2 MB a day. Plain text, one entry per event:

```
21:04:11.532 slow command 5.0 s (TIMEOUT): adb connect 192.168.1.31:41000
21:06:02.118 window not responding for 1.4 s
  File ".../maxondroid/ui/main_window.py", line 512, in _set_theme
    self._apply_theme(code)
```

Commands quicker than one second are not written; command output never is.

## commands-YYYY-MM-DD.jsonl — command journal

Location: `%LOCALAPPDATA%\MaxOnDroid\logs\`. One JSON object per line, one file per local day, files older than 14 days are deleted on start.

```json
{"format": "maxondroid.command", "version": 1, "time": "2026-11-10T20:45:30.120+00:00",
 "token": 2, "serial": "192.168.1.40:5555", "command": "adb -s 192.168.1.40:5555 usb",
 "exit": 0, "timed_out": false, "duration_ms": 312, "output": "restarting in USB mode"}
```

`token` is `null` for commands not tied to a saved device. Pairing codes are replaced with `•` before anything is written. `output` is cut at 8000 characters.

## changes.json — undo journal

Location: `%APPDATA%\MaxOnDroid\changes.json`. Every package change MaxOnDroid makes that takes something away is appended here, so it can be undone from Debloat → Change history.

```json
{
  "format": "maxondroid.changes",
  "version": 1,
  "changes": [
    {"id": "3f2a9c1b7e10", "device": "28041SKV0123", "package": "com.google.android.youtube.tv",
     "action": "remove_for_user", "time": "2026-11-11T08:40:00+00:00", "version": "4.01.345",
     "backup": null, "undone": null}
  ]
}
```

| Field | Meaning |
|---|---|
| `device` | Registry key of the device (see `devices.json`). |
| `action` | `remove_for_user` (system app, `pm uninstall -k --user 0`; undone with `cmd package install-existing`), `uninstall` (app the user installed; undone by reinstalling `backup`), or `disable` (`pm disable-user --user 0`; undone with `pm enable`). |
| `backup` | Path of the `.apk` or `.apks` saved before a full uninstall, or `null`. |
| `undone` | Time the change was undone, or `null` while it is in effect. |

Entries with an invalid package name or an action outside the three above are dropped when the file is read.

APK backups live in `%LOCALAPPDATA%\MaxOnDroid\data\backups\<device>\`.

## Debloat presets (*.json)

Default folder: `%APPDATA%\MaxOnDroid\presets\`. A preset can be saved anywhere and shared.

```json
{
  "format": "maxondroid.preset",
  "version": 1,
  "name": "Телевизор: реклама",
  "description": "",
  "created": "2026-11-11T08:40:00+00:00",
  "packages": [
    {"package": "com.google.android.tvrecommendations", "action": "remove"},
    {"package": "com.google.android.youtube.tv", "action": "disable"}
  ]
}
```

`action` is `remove` or `disable`. When a preset is applied, each package is reported as "to change", "already done" or "not on this device" before anything happens, and the usual confirmations for important packages still apply. Files over 2 MB, entries with invalid package names and duplicates are ignored; at most 2000 packages are read.

## UAD-ng package database

The bundled snapshot is `maxondroid/data/uad/uad_lists.json` (provenance in `SOURCE.json`, licence note in `NOTICE.md`). "Update database" stores a downloaded copy as `%LOCALAPPDATA%\MaxOnDroid\data\uad_lists.json` with `uad_lists.meta.json` holding its SHA-256; the copy is used only while its checksum matches and it parses with at least 500 entries.
