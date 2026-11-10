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

## commands-YYYY-MM-DD.jsonl — command journal

Location: `%LOCALAPPDATA%\MaxOnDroid\logs\`. One JSON object per line, one file per local day, files older than 14 days are deleted on start.

```json
{"format": "maxondroid.command", "version": 1, "time": "2026-11-10T20:45:30.120+00:00",
 "token": 2, "serial": "192.168.1.40:5555", "command": "adb -s 192.168.1.40:5555 usb",
 "exit": 0, "timed_out": false, "duration_ms": 312, "output": "restarting in USB mode"}
```

`token` is `null` for commands not tied to a saved device. Pairing codes are replaced with `•` before anything is written. `output` is cut at 8000 characters.
