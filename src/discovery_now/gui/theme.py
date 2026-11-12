"""The look of the desktop app: colours, metrics and the style sheet.

Every colour the app draws comes from a :class:`Tokens` built here, so the light
and the dark appearance stay in step and no widget invents a colour of its own.

Three things are the user's to choose: the appearance (follow the system, or pin
light or dark), the accent, and the density. The accent colours the primary
action and the current selection, and nothing else: the colours that carry meaning
(online, offline, new, warning) keep their own hue whatever the accent is, because
a state that changed colour with a preference would stop meaning anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# -- colour arithmetic -------------------------------------------------------


def _parse(colour: str) -> tuple[int, int, int]:
    raw = colour.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def mix(top: str, bottom: str, amount: float) -> str:
    """``top`` laid over ``bottom`` at ``amount`` (0 to 1), as a hex colour."""
    a, b = _parse(top), _parse(bottom)
    blended = (round(x * amount + y * (1 - amount)) for x, y in zip(a, b, strict=True))
    return "#{:02x}{:02x}{:02x}".format(*blended)


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Relative luminance, as WCAG defines it."""
    red, green, blue = (_channel(part) for part in _parse(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """The WCAG contrast ratio between two colours, from 1 to 21."""
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# -- what the user chooses ---------------------------------------------------


class Mode(StrEnum):
    """Which appearance to draw."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"
    #: Dark with a true black background, which an OLED screen switches off.
    BLACK = "black"

    @property
    def label(self) -> str:
        return {
            Mode.SYSTEM: "Follow the system",
            Mode.LIGHT: "Light",
            Mode.DARK: "Dark",
            Mode.BLACK: "Black",
        }[self]


class Density(StrEnum):
    """How much room the lists and panels take."""

    COMFORTABLE = "comfortable"
    COMPACT = "compact"

    @property
    def label(self) -> str:
        return {Density.COMFORTABLE: "Comfortable", Density.COMPACT: "Compact"}[self]


@dataclass(frozen=True, slots=True)
class Accent:
    """One accent colour, in the two shades the two appearances need."""

    key: str
    name: str
    #: Deep enough that white text on it passes AA.
    light: str
    #: Bright enough to read on a dark surface, with near-black text on it.
    dark: str
    on_dark: str

    def fill(self, *, dark: bool) -> str:
        return self.dark if dark else self.light

    def on_fill(self, *, dark: bool) -> str:
        return self.on_dark if dark else "#ffffff"


ACCENTS: tuple[Accent, ...] = (
    Accent("teal", "Teal", "#0a6e78", "#35c0ce", "#04212a"),
    Accent("blue", "Blue", "#1a5bc4", "#6fadff", "#06203d"),
    Accent("violet", "Violet", "#6a3fc9", "#b89bff", "#190f33"),
    Accent("rose", "Rose", "#b22a5f", "#ff92b6", "#39091d"),
    Accent("amber", "Amber", "#8a5600", "#f0b64a", "#2b1900"),
    Accent("green", "Green", "#166e3c", "#56d08b", "#042313"),
)

DEFAULT_ACCENT = ACCENTS[0]


def accent_for(key: str) -> Accent:
    """The accent with this key, or the default when the name is not one of ours."""
    for accent in ACCENTS:
        if accent.key == key:
            return accent
    return DEFAULT_ACCENT


# -- the tokens every widget reads -------------------------------------------


@dataclass(frozen=True, slots=True)
class Tokens:
    """Every colour and measurement the app draws with."""

    dark: bool
    #: True black rather than dark grey: the dark appearance, with the grey taken out.
    black: bool
    accent_key: str
    density: Density

    # Surfaces, from the furthest back to the nearest.
    rail: str
    window: str
    surface: str
    raised: str
    sunken: str
    border: str
    border_strong: str

    # Text, from the most to the least important.
    text: str
    muted: str
    faint: str

    # The accent, and what sits on it.
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    on_accent: str
    focus: str

    # Meaning, independent of the accent.
    online: str
    offline: str
    new: str
    warn: str

    # Interaction.
    selection: str
    hover: str
    shadow: str

    # Measurements.
    row_height: int
    gap: int
    pad: int
    radius: int
    font_pt: float


_LIGHT_NEUTRALS = {
    "window": "#f1f4f7",
    "surface": "#ffffff",
    "raised": "#e8edf2",
    "sunken": "#f7f9fb",
    "border": "#d6dee6",
    "border_strong": "#b6c2ce",
    "text": "#141d27",
    "muted": "#55616f",
    "faint": "#697482",
    "online": "#126b3c",
    "offline": "#b32618",
    "new": "#6833b0",
    "warn": "#8c5405",
    "shadow": "#0d1a26",
}

_DARK_NEUTRALS = {
    "window": "#0e1217",
    "surface": "#161b22",
    "raised": "#1e252e",
    "sunken": "#11161c",
    "border": "#2a323d",
    "border_strong": "#3d4855",
    "text": "#e6eaf0",
    "muted": "#9ba7b5",
    "faint": "#818e9d",
    "online": "#4fd390",
    "offline": "#ff8f86",
    "new": "#bfa3ff",
    "warn": "#f0b757",
    "shadow": "#000000",
}

#: Pure black for the window, so an OLED screen leaves those pixels off. The
#: cards sit a hair above it and the borders do the separating, because a card
#: that is the same black as the page would simply disappear.
_BLACK_NEUTRALS = {
    "rail": "#000000",
    "window": "#000000",
    "surface": "#0b0b0c",
    "raised": "#161617",
    "sunken": "#000000",
    "border": "#252528",
    "border_strong": "#3c3c42",
    "text": "#ececf0",
    "muted": "#9c9ca5",
    "faint": "#80808a",
    "online": "#4fd390",
    "offline": "#ff8f86",
    "new": "#bfa3ff",
    "warn": "#f0b757",
    "shadow": "#000000",
}

_METRICS = {
    Density.COMFORTABLE: {"row_height": 44, "gap": 14, "pad": 18, "radius": 8, "font_pt": 10.5},
    Density.COMPACT: {"row_height": 30, "gap": 7, "pad": 10, "radius": 6, "font_pt": 9.0},
}


def tokens_for(
    *,
    dark: bool,
    accent: Accent = DEFAULT_ACCENT,
    density: Density = Density.COMFORTABLE,
    black: bool = False,
) -> Tokens:
    """Build the whole palette from the choices the user makes.

    ``black`` only means something on a dark appearance, and is ignored on a light
    one.
    """
    black = black and dark
    base = dict(_BLACK_NEUTRALS if black else _DARK_NEUTRALS if dark else _LIGHT_NEUTRALS)
    # The side rail is one step above the page, except on black, where it is black.
    base.setdefault("rail", str(base["raised"]))
    fill = accent.fill(dark=dark)
    surface = str(base["surface"])
    # Hover and pressed move towards the text colour, so they stay visible in both
    # appearances instead of darkening into the background of one of them.
    towards = "#ffffff" if dark else "#000000"
    metrics = _METRICS[density]
    return Tokens(
        dark=dark,
        black=black,
        accent_key=accent.key,
        density=density,
        accent=fill,
        accent_hover=mix(towards, fill, 0.12),
        accent_pressed=mix(towards, fill, 0.22),
        accent_soft=mix(fill, surface, 0.16 if dark else 0.11),
        on_accent=accent.on_fill(dark=dark),
        focus=fill,
        selection=mix(fill, surface, 0.22 if dark else 0.16),
        hover=mix(str(base["text"]), surface, 0.06),
        **base,  # type: ignore[arg-type]
        **metrics,  # type: ignore[arg-type]
    )


_current = tokens_for(dark=False)


def current() -> Tokens:
    """The tokens in use right now."""
    return _current


def system_is_dark(app: QApplication) -> bool:
    """What the operating system is asking for."""
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def resolve_dark(app: QApplication, mode: Mode) -> bool:
    """Whether to draw a dark appearance, given the user's choice."""
    if mode is Mode.LIGHT:
        return False
    if mode in (Mode.DARK, Mode.BLACK):
        return True
    return system_is_dark(app)


def check_mark(colour: str) -> str:
    """Path to a tick drawn in ``colour``, for the checkbox style sheet."""
    from .icons import write_check_mark

    return write_check_mark(colour)


def arrow(colour: str, *, up: bool) -> str:
    """Path to a small chevron, for the arrows on a number box."""
    from .icons import write_glyph

    return write_glyph("chevron", colour, size=11, width=2.6, turn=180.0 if up else 0.0)


def _palette(t: Tokens) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.surface,
        QPalette.ColorRole.AlternateBase: t.sunken,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.raised,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Highlight: t.selection,
        QPalette.ColorRole.HighlightedText: t.text,
        QPalette.ColorRole.PlaceholderText: t.faint,
        QPalette.ColorRole.Link: t.accent,
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.faint))
    return palette


def stylesheet(t: Tokens) -> str:
    """The style sheet, built from the tokens.

    Everything the user can see is themed here, the parts Qt would otherwise draw
    in its own colours included: scrollbars, menus, tooltips, the text cursor and
    the focus ring.
    """
    tick = check_mark(t.on_accent)
    up, down = arrow(t.muted, up=True), arrow(t.muted, up=False)
    return f"""
* {{ outline: 0; }}

QToolTip {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    padding: 5px 8px; border-radius: {t.radius - 2}px;
}}

QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius - 2}px;
    color: {t.text}; selection-background-color: {t.selection}; selection-color: {t.text};
}}
QLineEdit, QComboBox, QSpinBox {{ padding: 6px 9px; }}
QPlainTextEdit {{ padding: 7px 9px; }}
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QSpinBox:hover {{
    border-color: {t.border_strong};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {{
    border-color: {t.focus};
}}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    background: {t.sunken}; color: {t.faint};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.border}; padding: 4px;
    selection-background-color: {t.selection}; selection-color: {t.text};
}}

QTableView {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius}px;
    gridline-color: transparent; selection-background-color: {t.selection};
    selection-color: {t.text}; alternate-background-color: {t.sunken};
}}
QTableView::item {{ padding: 0 10px; border: none; }}
QHeaderView::section {{
    background: {t.window}; color: {t.muted}; border: none;
    border-bottom: 1px solid {t.border}; padding: 8px 10px; font-weight: 600;
}}
QHeaderView::section:hover {{ color: {t.text}; }}
QTableCornerButton::section {{ background: {t.window}; border: none; }}

QPushButton {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius - 2}px;
    padding: 7px 14px; color: {t.text};
}}
QPushButton:hover {{ background: {t.hover}; border-color: {t.border_strong}; }}
QPushButton:pressed {{ background: {t.raised}; }}
QPushButton:focus {{ border-color: {t.focus}; }}
QPushButton:disabled {{ color: {t.faint}; background: {t.sunken}; }}

QPushButton#primary {{
    background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#primary:pressed {{ background: {t.accent_pressed}; }}
QPushButton#primary:disabled {{
    background: {t.raised}; color: {t.faint}; border-color: {t.border};
}}
QPushButton#danger:hover {{ border-color: {t.offline}; color: {t.offline}; }}
QPushButton#quiet {{ background: transparent; border-color: transparent; color: {t.muted}; }}
QPushButton#quiet:hover {{ background: {t.hover}; color: {t.text}; }}

QPushButton#chip {{
    background: transparent; border: 1px solid {t.border}; border-radius: 14px;
    padding: 5px 13px; color: {t.muted};
}}
QPushButton#chip:hover {{ border-color: {t.border_strong}; color: {t.text}; }}
QPushButton#chip:checked {{
    background: {t.accent_soft}; border-color: {t.accent}; color: {t.text}; font-weight: 600;
}}

QPushButton#nav {{
    background: transparent; border: 1px solid transparent; border-radius: {t.radius - 2}px;
    padding: 9px 11px; color: {t.muted}; text-align: left; font-weight: 600;
}}
QPushButton#nav:hover {{ background: {t.hover}; color: {t.text}; }}
QPushButton#nav:checked {{ background: {t.accent_soft}; color: {t.text}; }}

QFrame#rail {{ background: {t.rail}; border: none; border-right: 1px solid {t.border}; }}
QFrame#panel {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius}px;
}}
QFrame#card {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius}px;
}}
QFrame#banner {{
    background: {t.surface}; border: 1px solid {t.offline}; border-radius: {t.radius - 2}px;
}}
QFrame#bar {{
    background: {t.accent_soft}; border: 1px solid {t.accent}; border-radius: {t.radius - 2}px;
}}
QFrame[rule="true"] {{ background: {t.border}; border: none; }}

QLabel {{ color: {t.text}; background: transparent; }}
QLabel#muted {{ color: {t.muted}; }}
QLabel#faint {{ color: {t.faint}; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; letter-spacing: -0.2px; }}
QLabel#title {{ font-size: 15pt; font-weight: 700; letter-spacing: -0.3px; }}
QLabel#section {{ font-size: 11pt; font-weight: 700; }}
QLabel#heading {{ color: {t.muted}; font-weight: 600; }}

QCheckBox, QRadioButton {{ color: {t.text}; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; }}
QCheckBox::indicator {{
    border: 1px solid {t.border_strong}; border-radius: 4px; background: {t.surface};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{
    background: {t.accent}; border-color: {t.accent}; image: url("{tick}");
}}
QCheckBox::indicator:disabled {{ background: {t.sunken}; border-color: {t.border}; }}
QRadioButton::indicator {{
    border: 1px solid {t.border_strong}; border-radius: 9px; background: {t.surface};
}}
QRadioButton::indicator:checked {{ border: 5px solid {t.accent}; }}

QSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 17px; border: none; background: transparent; margin: 3px 4px 0 0;
    image: url("{up}");
}}
QSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 17px; border: none; background: transparent; margin: 0 4px 3px 0;
    image: url("{down}");
}}

QStatusBar {{ background: {t.window}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{
    background: {t.raised}; border: none; border-radius: 3px; max-height: 6px;
}}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {t.border}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {t.border_strong}; border-radius: 4px; min-height: 30px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {t.border_strong}; border-radius: 4px; min-width: 30px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 5px; }}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: {t.radius - 3}px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.selection}; }}
QMenu::item:disabled {{ color: {t.faint}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}

QListWidget {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius - 2}px;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 4px; color: {t.text}; }}

QGraphicsView {{
    background: {t.sunken}; border: 1px solid {t.border}; border-radius: {t.radius}px;
}}
"""


def apply(
    app: QApplication,
    *,
    mode: Mode = Mode.SYSTEM,
    accent: Accent = DEFAULT_ACCENT,
    density: Density = Density.COMFORTABLE,
) -> Tokens:
    """Style the whole application, and return the tokens it now uses."""
    # One appearance at a time, read from everywhere.
    global _current
    _current = tokens_for(
        dark=resolve_dark(app, mode),
        accent=accent,
        density=density,
        black=mode is Mode.BLACK,
    )
    app.setStyle("Fusion")
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    font = QFont(app.font())
    font.setPointSizeF(_current.font_pt)
    app.setFont(font)
    return _current
