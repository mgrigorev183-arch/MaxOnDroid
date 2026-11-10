"""WCAG AA contrast for every text/background pair the style sheet uses."""

import pytest

from maxondroid.ui import theme


def luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [
    ("text", "ground"),
    ("text", "surface"),
    ("text", "surface_alt"),
    ("text_muted", "ground"),
    ("text_muted", "surface"),
    ("text_muted", "surface_alt"),
    ("rail_text", "rail"),
    ("rail_text", "rail_selected"),
    ("rail_muted", "rail"),
    ("rail_muted", "rail_selected"),
    ("brass_on", "brass"),
    ("brass_on", "brass_hover"),
    ("brass_text", "ground"),
    ("brass_text", "surface"),
    ("warning_text", "warning_bg"),
    ("info_text", "info_bg"),
    ("danger_text", "surface"),
    ("danger_text", "ground"),
    ("selection_text", "selection"),
    ("surface", "text"),  # tooltips
]

GRAPHIC_PAIRS = [  # non-text UI parts need 3:1
    ("brass", "rail"),
    ("token_off", "rail"),
    ("warning", "rail"),
    ("brass", "ground"),
    ("token_off", "ground"),
]


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg", TEXT_PAIRS)
def test_text_contrast(palette, fg, bg):
    ratio = contrast(getattr(palette, fg), getattr(palette, bg))
    assert ratio >= 4.5, f"{palette.name}: {fg} on {bg} = {ratio:.2f}"


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg", GRAPHIC_PAIRS)
def test_graphic_contrast(palette, fg, bg):
    ratio = contrast(getattr(palette, fg), getattr(palette, bg))
    assert ratio >= 3.0, f"{palette.name}: {fg} on {bg} = {ratio:.2f}"


def test_numeral_on_offline_token_is_readable():
    # offline tokens draw the numeral in rail_text inside an outline ring on the rail
    assert contrast(theme.LIGHT.rail_text, theme.LIGHT.rail) >= 4.5
