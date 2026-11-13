# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop: native Windows application (Qt / PySide6, native controls). Not a web surface.

## Stack

Python 3.11+ with PySide6, packaged with PyInstaller and an Inno Setup per-user installer. Bundles the scrcpy Windows release (which ships `adb.exe`). Chosen by the owner during the planning interview.

## Users

The owner: a technically capable person (comfortable with C++ and with `adb` from `cmd`) who manages the Android devices on a home network from a Windows 10 Pro PC: an Android TV (Android 12) and two Android phones. After testing at home, the app is shared with friends, who may be less technical and who run it on their own home networks with their own devices.

The job: install APKs, remove vendor bloat and advertising from the TV and phones, operate the TV like a remote, look at device screens, move files, and run ad-hoc `adb` commands without typing everything into `cmd`.

## Product Purpose

A graphical front end for `adb` that turns the owner's existing command-line workflow into a few clicks while keeping every command visible. Success: the owner never needs to open `cmd` for routine device work, and a friend can install the app, pair a device, and debloat it safely without reading `adb` documentation.

## Positioning

One window for every Android device in the home, with every action reversible where Android allows it and every underlying `adb` command shown in a journal, so the tool teaches the command line instead of hiding it. Open source (GPL-3.0), no telemetry, no account, no cloud. The only network requests go to GitHub over HTTPS: the daily release-number check (can be turned off) and the UAD-ng list download on request.

## Operating Context

- Runs on the same PC and home Wi-Fi as the devices; devices connect over USB or Wi-Fi (Android 11+ wireless debugging with pairing by code or QR; the legacy `adb tcpip` mode on older devices, with a warning).
- The TV is across the room: the remote tab is used while looking at the TV, not at the PC.
- Users read English `adb` documentation, so raw `adb` output stays untranslated; the interface itself is Russian or English.

## Capabilities and Constraints

Version 1, delivered in stages:

1. Shell, device list, connection (USB, IP, pairing by code and QR, mDNS discovery, saved devices with auto-reconnect), command journal, languages, themes, Overview tab.
2. Apps tab (list, search, filters, install including split APKs, uninstall for user 0, disable/enable/restore, clear data, force-stop, launch, extract APK) and Debloat tab (UAD-ng package list snapshot plus on-demand update, custom presets in JSON, journal and undo).
3. Remote tab (on-screen buttons, text input, PC keyboard shortcuts) and Screen tab (scrcpy with presets, screenshot, recording).
4. Files tab (device browser, push, pull, drag and drop, new folder, rename, delete with confirmation, cancellable copies) and Console tab (adb and shell modes, exact command preview, streaming output with Stop, history, saved commands).
5. Installer, GitHub Actions build, security review, first release (0.9.0): per-user Inno Setup installer without administrator rights, scrcpy 5.0.1 with adb bundled and checked by SHA-256, a release built, installed, self-tested and uninstalled by GitHub Actions on a version tag and published with its SHA-256 (unsigned), and a daily update check that only links to the release page.

Deferred to v2: batch actions across several devices, permission management, console autocompletion. Out of scope: iPhones, Windows PCs, fastboot flashing.

Terminology: "device", "pairing", "wireless debugging", "legacy network mode (adb tcpip)", "remove for user" (`pm uninstall --user 0`), "disable", "restore", "journal".

## Brand Commitments

- Name: MaxOnDroid.
- Interface languages: Russian and English, switchable at runtime; default follows Windows.
- Light and dark themes; default follows Windows.
- Voice: plain, precise, honest about risk. Dangerous actions say what will happen and how to undo it.

## Evidence on Hand

No screenshots, logos, testimonials, or user counts exist yet. Do not invent them.

## Product Principles

1. Show the command. Every button maps to a visible `adb` command in the journal.
2. Reversible by default. Prefer the undoable variant of every action and keep a record that can restore it.
3. Safe on someone else's network. Warn about open legacy network adb, never scan subnets, never phone home.
4. Familiar before clever. Standard desktop controls, predictable layout, keyboard support.
5. Works for a friend. Errors explain the problem and the next step in plain language.

## Accessibility & Inclusion

Full keyboard operation, visible focus, text contrast at WCAG AA in both themes, and no information carried by colour alone (status also has text or an icon shape).
