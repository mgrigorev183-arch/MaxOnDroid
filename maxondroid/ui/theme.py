"""Colours, fonts and the Qt style sheet.

The visual world is a theatre cloakroom: a dark walnut device rail, brass for
the numbered tokens and the main action, quiet warm greys for the work area.
Every text/background pair used below is checked for WCAG AA contrast in
tests/test_theme.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    name: str
    ground: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    rail: str
    rail_hover: str
    rail_selected: str
    rail_border: str
    rail_text: str
    rail_muted: str
    brass: str
    brass_hover: str
    brass_pressed: str
    brass_on: str
    brass_text: str
    token_off: str
    warning: str
    warning_bg: str
    warning_text: str
    info_bg: str
    info_text: str
    danger: str
    danger_text: str
    selection: str
    selection_text: str


LIGHT = Palette(
    name="light",
    ground="#F3F0EC",
    surface="#FFFFFF",
    surface_alt="#EAE5DF",
    border="#D3CAC0",
    text="#1E1916",
    text_muted="#5A5049",
    rail="#2B201B",
    rail_hover="#382A23",
    rail_selected="#4A3830",
    rail_border="#3F3029",
    rail_text="#F3EBE2",
    rail_muted="#BFB0A1",
    brass="#AD7F1C",
    brass_hover="#BD8E2A",
    brass_pressed="#946C14",
    brass_on="#1E1712",
    brass_text="#7E5910",
    token_off="#8C7B6C",
    warning="#E09A12",
    warning_bg="#FBEBC6",
    warning_text="#5E3D00",
    info_bg="#EAE5DF",
    info_text="#2E2620",
    danger="#B3261E",
    danger_text="#A3241B",
    selection="#EAD7AE",
    selection_text="#1E1916",
)

DARK = Palette(
    name="dark",
    ground="#171210",
    surface="#201916",
    surface_alt="#2A221E",
    border="#41362F",
    text="#EEE7E0",
    text_muted="#B4A699",
    rail="#2B201B",
    rail_hover="#382A23",
    rail_selected="#4A3830",
    rail_border="#3F3029",
    rail_text="#F3EBE2",
    rail_muted="#BFB0A1",
    brass="#C99A3A",
    brass_hover="#D8AA4C",
    brass_pressed="#AE8226",
    brass_on="#1E1712",
    brass_text="#DDB25C",
    token_off="#8C7B6C",
    warning="#E8A32A",
    warning_bg="#3A2B0E",
    warning_text="#F4CB72",
    info_bg="#2A221E",
    info_text="#E6DDD4",
    danger="#E5675C",
    danger_text="#F28B82",
    selection="#4D3B1F",
    selection_text="#F6EFE7",
)

#: Faces in order of preference. Bahnschrift and Segoe UI ship with Windows 10.
TOKEN_FAMILIES = ["Bahnschrift", "Bahnschrift SemiCondensed", "DejaVu Sans Condensed", "Arial Narrow", "Arial"]
UI_FAMILIES = ["Segoe UI", "Segoe UI Variable Text", "DejaVu Sans", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]


def font(families: list[str], point_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPointSizeF(point_size)
    f.setWeight(weight)
    return f


def token_font(point_size: float, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    f = font(TOKEN_FAMILIES, point_size, weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def mono_font(point_size: float = 9) -> QFont:
    f = font(MONO_FAMILIES, point_size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is None:
        return False
    return scheme() == Qt.ColorScheme.Dark


def resolve(setting: str) -> Palette:
    if setting == "dark":
        return DARK
    if setting == "light":
        return LIGHT
    return DARK if system_prefers_dark() else LIGHT


def qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    pairs = {
        role.Window: p.ground,
        role.WindowText: p.text,
        role.Base: p.surface,
        role.AlternateBase: p.surface_alt,
        role.Text: p.text,
        role.Button: p.surface,
        role.ButtonText: p.text,
        role.ToolTipBase: p.text,
        role.ToolTipText: p.surface,
        role.Highlight: p.selection,
        role.HighlightedText: p.selection_text,
        role.PlaceholderText: p.text_muted,
        role.Link: p.brass_text,
        role.BrightText: p.danger_text,
        role.Mid: p.border,
        role.Midlight: p.surface_alt,
        role.Dark: p.border,
        role.Shadow: "#000000",
        role.Light: p.surface,
    }
    for r, value in pairs.items():
        pal.setColor(r, QColor(value))
    disabled = QColor(p.text_muted)
    for r in (role.WindowText, role.Text, role.ButtonText):
        pal.setColor(group.Disabled, r, disabled)
    return pal


def stylesheet(p: Palette) -> str:
    return f"""
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog {{ background: {p.ground}; }}
QToolTip {{ background: {p.text}; color: {p.surface}; border: none; padding: 5px 8px; }}

#Rail {{ background: {p.rail}; border: none; }}
#Rail QLabel {{ color: {p.rail_text}; background: transparent; }}
#Rail QLabel[role="muted"] {{ color: {p.rail_muted}; }}
#RailTitle {{ color: {p.rail_text}; }}
#DeviceList {{ background: transparent; border: none; outline: none; }}
#RailFooter {{ border-top: 1px solid {p.rail_border}; }}
#Rail QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px; color: {p.rail_text}; }}
#Rail QToolButton:hover {{ background: {p.rail_hover}; }}
#Rail QToolButton:focus {{ border-color: {p.brass}; }}

QPushButton {{
    background: {p.surface}; color: {p.text};
    border: 1px solid {p.border}; border-radius: 4px;
    padding: 5px 14px; min-height: 20px;
}}
QPushButton:hover {{ background: {p.surface_alt}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:focus {{ border-color: {p.brass_text}; }}
QPushButton:disabled {{ color: {p.text_muted}; background: {p.ground}; }}
QPushButton::menu-indicator {{ subcontrol-position: right center; right: 6px; }}
QPushButton[menu="true"] {{ padding-right: 24px; }}
QPushButton#Primary {{ background: {p.brass}; color: {p.brass_on}; border-color: {p.brass_pressed}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {p.brass_hover}; }}
QPushButton#Primary:pressed {{ background: {p.brass_pressed}; }}
QPushButton#Primary:focus {{ border: 2px solid {p.rail_text}; }}
QPushButton#Primary:disabled {{ background: {p.token_off}; color: {p.brass_on}; }}
QPushButton#Danger {{ color: {p.danger_text}; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 4px;
    padding: 4px 8px; min-height: 20px;
    selection-background-color: {p.selection}; selection-color: {p.selection_text};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p.brass_text}; }}
QLineEdit[invalid="true"] {{ border-color: {p.danger}; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; selection-background-color: {p.selection}; selection-color: {p.selection_text}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {p.border}; background: {p.ground}; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p.text_muted}; padding: 8px 16px; border: none; border-bottom: 2px solid transparent; margin-right: 2px; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.brass}; }}
QTabBar::tab:disabled {{ color: {p.border}; }}

QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="title"] {{ color: {p.text}; }}
QLabel[role="section"] {{ color: {p.text}; }}
QLabel[role="value"] {{ color: {p.text}; }}
QLabel[role="error"] {{ color: {p.danger_text}; }}
QLabel[role="success"] {{ color: {p.text}; }}
QLabel a {{ color: {p.brass_text}; }}

#Banner {{ border-radius: 6px; }}
#Banner[kind="warning"] {{ background: {p.warning_bg}; border: 1px solid {p.warning}; }}
#Banner[kind="warning"] QLabel {{ color: {p.warning_text}; }}
#Banner[kind="info"] {{ background: {p.info_bg}; border: 1px solid {p.border}; }}
#Banner[kind="info"] QLabel {{ color: {p.info_text}; }}
#Banner[kind="error"] {{ background: {p.surface}; border: 1px solid {p.danger}; }}
#Banner[kind="error"] QLabel {{ color: {p.danger_text}; }}

#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 6px; }}
#Card QLabel {{ background: transparent; }}

#JournalHeader {{ background: {p.surface_alt}; border-top: 1px solid {p.border}; }}
QTreeWidget, QListWidget, QPlainTextEdit {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 4px;
    alternate-background-color: {p.surface_alt};
    selection-background-color: {p.selection}; selection-color: {p.selection_text};
}}
#Journal {{ border: none; border-radius: 0; }}
QHeaderView::section {{ background: {p.surface_alt}; color: {p.text_muted}; border: none; border-bottom: 1px solid {p.border}; padding: 4px 8px; }}

QMenuBar {{ background: {p.ground}; color: {p.text}; }}
QMenuBar::item:selected {{ background: {p.surface_alt}; }}
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 3px; }}
QMenu::item:selected {{ background: {p.selection}; color: {p.selection_text}; }}
QMenu::item:disabled {{ color: {p.text_muted}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}

QStatusBar {{ background: {p.surface_alt}; color: {p.text_muted}; border-top: 1px solid {p.border}; }}
QStatusBar QLabel {{ color: {p.text_muted}; }}
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 4px; min-width: 28px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
#Rail QScrollBar::handle:vertical {{ background: {p.rail_selected}; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QProgressBar {{ background: {p.surface_alt}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {p.brass}; border-radius: 3px; }}
"""


def apply(app: QApplication, p: Palette) -> None:
    app.setPalette(qpalette(p))
    app.setStyleSheet(stylesheet(p))
