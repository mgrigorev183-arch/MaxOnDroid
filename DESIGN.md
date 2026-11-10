---
name: MaxOnDroid
description: The cloakroom counter for the Android devices in a home
colors:
  walnut-rail: "#2B201B"
  walnut-rail-hover: "#382A23"
  walnut-rail-selected: "#4A3830"
  rail-text: "#F3EBE2"
  rail-muted: "#BFB0A1"
  brass-light: "#AD7F1C"
  brass-light-hover: "#BD8E2A"
  brass-light-pressed: "#946C14"
  brass-dark: "#C99A3A"
  brass-dark-hover: "#D8AA4C"
  brass-on: "#1E1712"
  brass-text-light: "#7E5910"
  brass-text-dark: "#DDB25C"
  token-off: "#8C7B6C"
  ground-light: "#F3F0EC"
  surface-light: "#FFFFFF"
  surface-alt-light: "#EAE5DF"
  border-light: "#D3CAC0"
  text-light: "#1E1916"
  text-muted-light: "#5A5049"
  ground-dark: "#171210"
  surface-dark: "#201916"
  surface-alt-dark: "#2A221E"
  border-dark: "#41362F"
  text-dark: "#EEE7E0"
  text-muted-dark: "#B4A699"
  warning-ring-light: "#E09A12"
  warning-bg-light: "#FBEBC6"
  warning-text-light: "#5E3D00"
  warning-ring-dark: "#E8A32A"
  warning-bg-dark: "#3A2B0E"
  warning-text-dark: "#F4CB72"
  danger-light: "#A3241B"
  danger-dark: "#F28B82"
typography:
  display:
    fontFamily: "Bahnschrift, DejaVu Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "17pt"
    fontWeight: 600
  headline:
    fontFamily: "Bahnschrift, DejaVu Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "15pt"
    fontWeight: 700
  title:
    fontFamily: "Bahnschrift, DejaVu Sans Condensed, Arial Narrow, sans-serif"
    fontSize: "11.5pt"
    fontWeight: 600
  body:
    fontFamily: "Segoe UI, DejaVu Sans, Arial, sans-serif"
    fontSize: "9.5pt"
    fontWeight: 400
  label:
    fontFamily: "Segoe UI, DejaVu Sans, Arial, sans-serif"
    fontSize: "9pt"
    fontWeight: 400
  code:
    fontFamily: "Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"
    fontSize: "9pt"
    fontWeight: 400
rounded:
  control: "4px"
  card: "6px"
  row: "5px"
  token: "50%"
spacing:
  xs: "8px"
  sm: "12px"
  md: "14px"
  lg: "18px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.brass-light}"
    textColor: "{colors.brass-on}"
    rounded: "{rounded.control}"
    padding: "5px 14px"
  button-primary-hover:
    backgroundColor: "{colors.brass-light-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-light}"
    textColor: "{colors.text-light}"
    rounded: "{rounded.control}"
    padding: "5px 14px"
  card:
    backgroundColor: "{colors.surface-light}"
    rounded: "{rounded.card}"
    padding: "14px 16px 16px"
  device-row-selected:
    backgroundColor: "{colors.walnut-rail-selected}"
    textColor: "{colors.rail-text}"
    rounded: "{rounded.row}"
    height: "58px"
  token-connected:
    backgroundColor: "{colors.brass-light}"
    textColor: "{colors.brass-on}"
    size: "34px"
  banner-warning:
    backgroundColor: "{colors.warning-bg-light}"
    textColor: "{colors.warning-text-light}"
    rounded: "{rounded.card}"
    padding: "10px 10px 10px 14px"
---

# Design System: MaxOnDroid

## Overview

**Creative North Star: "The Cloakroom Counter."** Every device in the home is handed in like a coat and gets a numbered token; the token follows it everywhere in the app, from the device rail to the journal line of every command it ran. The window is a working tool first: standard desktop layout (rail, tabs, journal), native controls, Windows conventions. The world contributes four things only: the walnut-and-brass palette, condensed Bahnschrift numerals and headings, a compact density, and the token as its signature.

Anti-references: a grey device table keyed by long serial numbers; a terminal costume; neon-on-black "hacker" styling.

## Colors

Restrained strategy with a committed shell: the walnut rail owns the left side in both themes; brass is the one accent and carries meaning (connected device, selected tab, primary action).

### Primary
- **Cloakroom Brass** (#AD7F1C light, #C99A3A dark): connected tokens, the primary button, the selected-tab underline, progress fills. Text placed on brass is always Brass-On Ink (#1E1712).
- **Brass Ink** (#7E5910 light, #DDB25C dark): brass used as text or a focus border on the work-area ground.

### Neutral
- **Walnut Rail** (#2B201B): the device rail, identical in both themes so the device list always reads as the same place. Hover #382A23, selected #4A3830.
- **Rail Linen** (#F3EBE2) and **Rail Felt** (#BFB0A1): primary and secondary text on the rail.
- **Light work area:** ground #F3F0EC, surfaces #FFFFFF, alternate rows and journal header #EAE5DF, borders #D3CAC0, text #1E1916, secondary text #5A5049.
- **Dark work area:** ground #171210, surfaces #201916, alternate #2A221E, borders #41362F, text #EEE7E0, secondary text #B4A699.
- **Unclaimed Token** (#8C7B6C): offline and unauthorized tokens.

### State
- **Amber** (ring #E09A12 / #E8A32A, banner #FBEBC6 / #3A2B0E, text #5E3D00 / #F4CB72): only for open legacy network adb and other security warnings.
- **Danger** (#A3241B light, #F28B82 dark): failed commands and errors, always next to words that say what failed.

### Named Rules
**The Brass Means Something Rule.** Brass marks a connected device, the current tab, or the one primary action on screen. It is never decoration.

**The Same Rail Rule.** The rail stays walnut in light and dark themes.

Every text pair meets WCAG AA and every graphic pair meets 3:1; `tests/test_theme.py` enforces it.

## Typography

**Display, headline and title:** Bahnschrift (ships with Windows 10), condensed sans fallback elsewhere. **Body and labels:** Segoe UI. **Code and adb output:** Cascadia Mono or Consolas.

### Hierarchy
- **Display** (600, 17pt): the device name in the Overview header; empty-state titles (16pt).
- **Headline** (700, 15pt): the app name at the top of the rail.
- **Title** (600, 11.5pt): card headings; the journal title (10.5pt).
- **Body** (400, 9.5pt): field values, banners, dialogs.
- **Label** (400, 9pt): field names and secondary lines, in the muted text colour.
- **Code** (400, 9pt): commands and adb output in the journal.

### Named Rules
**The Numeral Rule.** Token numbers are always two digits (01, 02) in Bahnschrift; an unregistered device shows an em dash.

## Layout

Three fixed regions: the device rail on the left (240–360px, default 280px), the tabbed work area on the right, and the command journal below the work area (collapsible to its header). The Overview stacks a header (token, name, subtitle, action row), banners, then a two-column grid of cards that collapses gracefully by wrapping text; the work area never scrolls horizontally. Spacing steps are 8, 12, 14, 18 and 24px; cards sit 14px apart inside 24px page margins.

## Elevation & Depth

Flat. Depth comes from tonal layering (ground, surface, alternate surface) and 1px borders, never shadows.

## Shapes

Small, quiet radii: 4px controls, 6px cards and banners, 5px device rows. The token is the one round form in the system and should stay the only circle.

## Components

### Buttons
- **Shape:** 4px radius, 1px border.
- **Primary:** brass with ink text, semibold; one per screen region (the rail's "Connect a device", the dialog's main action).
- **Secondary:** surface background, border colour; hover moves to the alternate surface.
- **Focus:** brass-ink border on the work area; a linen 2px border on brass buttons.

### Cards
- **Background:** surface, 1px border, 6px radius, 14/16px padding.
- **Content:** a Bahnschrift title, then a label/value form; values are selectable.

### Inputs
- **Style:** surface background, 1px border, 4px radius; focus switches the border to brass ink.

### Navigation
- **Tabs:** text-only, muted until selected; the selected tab gets a 2px brass underline.
- **Device rail rows:** 58px, token on the left, name and a secondary line with kind and transport icons, amber warning icon on the right when network adb is open.

### The Token (signature component)
A disc that carries the connection state by shape, not only by colour: solid brass for connected, an outline ring for offline, a solid muted disc with a notch for "waiting for permission", a dashed ring while connecting, and an extra amber ring when legacy network adb is open. It appears at 34px in the rail, 52px in the Overview header, and as the two-digit number in the journal's first column.

### Banners
Full-width strips with a drawn warning icon, a bold title, a body and at most one action button. Amber for security, neutral for state guidance, danger outline for errors.

## Do's and Don'ts

- **Do** show the adb command behind every action in the journal, prefixed with the device token.
- **Do** keep state readable without colour: shapes on tokens, words in status text.
- **Do** draw icons in code from `ui/icons.py`, one stroke weight.
- **Don't** add shadows, gradients, or glass.
- **Don't** use brass for anything that is not connected, selected, or primary.
- **Don't** use emoji or Unicode glyphs as icons.
