---
version: 1
slug: "maxondroid-ui-main-window-py"
primary_target: "maxondroid/ui/main_window.py"
related_targets: []
---

# Surface: MaxOnDroid main window

Scope: the main application window (device rail, tabs, journal panel) and its dialogs. Mode: Operate.

Audience and job: the owner and friends managing home Android devices (TV, phones) from a Windows PC: connect, read device state, act, and see the adb command behind every action.

Constraints: native Qt controls only; Russian and English; light and dark themes following Windows; WCAG AA contrast; keyboard operable; status never by colour alone.

## Direction contract

THESIS: Every device in the home is a coat in the cloakroom: it gets a numbered token, and that number follows it everywhere. Refuses the category default of a grey device table keyed by long serial numbers.

OWN-WORLD: Theatre cloakroom. Dark walnut device rail (#2E221C light theme and dark), brass accent (#B8892B family) for the selected device, primary action and connected tokens; content ground a quiet warm grey in light (#F4F2EF) and walnut-black in dark (#1C1714). Bahnschrift for token numerals and section headings, Segoe UI for body, tabular figures in data.

STORY: The visitor sees which devices are present and safe at a glance, picks one by its token, reads its state, acts, and sees the matching numbered command in the journal.

FIRST VIEWPORT: Left rail 260px: app name, device list of rows each led by a round 32px numbered token (01, 02...), device name, type and transport, warning icon; "Подключить" button at the rail bottom. Right: tab bar (Обзор first), Overview as label/value groups with actions on the right. Bottom: collapsible journal, each line prefixed by the device token number.

FORM: candidate 7 of 7 (cloakroom token), seed:18855298fa15c338. Signature move: the numbered token carries connection state (solid brass connected, outline offline, notched unauthorized, amber ring legacy network adb) and tags journal lines.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
