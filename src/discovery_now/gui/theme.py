"""Colours and the style sheet, for a light and a dark appearance.

The app follows the system setting. Every colour is a named token so the two
appearances stay in step, and nothing else in the package hard-codes one.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Tokens:
    """One appearance."""

    window: str
    surface: str
    raised: str
    border: str
    text: str
    muted: str
    accent: str
    on_accent: str
    online: str
    offline: str
    new: str
    warn: str
    selection: str


LIGHT = Tokens(
    window="#f4f6f8",
    surface="#ffffff",
    raised="#eef1f4",
    border="#d9dee4",
    text="#1a2230",
    muted="#5f6b7a",
    accent="#0b7a86",
    on_accent="#ffffff",
    online="#17794a",
    offline="#b42318",
    new="#6d3bb8",
    warn="#a15c07",
    selection="#d7eef1",
)

DARK = Tokens(
    window="#12161c",
    surface="#1a2028",
    raised="#232a34",
    border="#2e3743",
    text="#e7eaf0",
    muted="#97a3b3",
    accent="#38b6c3",
    on_accent="#06232a",
    online="#47d08a",
    offline="#ff8a80",
    new="#b997f5",
    warn="#f0b44c",
    selection="#1f3a41",
)

_current = LIGHT


def current() -> Tokens:
    """The appearance in use right now."""
    return _current


def is_dark(app: QApplication) -> bool:
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _palette(tokens: Tokens) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.window,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.surface,
        QPalette.ColorRole.AlternateBase: tokens.raised,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.raised,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.ToolTipBase: tokens.surface,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.Highlight: tokens.selection,
        QPalette.ColorRole.HighlightedText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.muted,
        QPalette.ColorRole.Link: tokens.accent,
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens.muted))
    return palette


def stylesheet(t: Tokens) -> str:
    """The few widgets that need more than a palette."""
    return f"""
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    padding: 4px 6px; }}

QTableView, QListWidget, QPlainTextEdit, QLineEdit, QComboBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px;
}}
QLineEdit, QComboBox {{ padding: 5px 8px; }}
QPlainTextEdit {{ padding: 6px 8px; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.border};
    selection-background-color: {t.selection}; selection-color: {t.text};
}}

QTableView {{ gridline-color: transparent; selection-background-color: {t.selection};
    selection-color: {t.text}; outline: 0; }}
QTableView::item {{ padding: 0 8px; border: none; }}
QHeaderView::section {{
    background: {t.window}; color: {t.muted}; border: none;
    border-bottom: 1px solid {t.border}; padding: 7px 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {t.window}; border: none; }}

QPushButton {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px;
    padding: 6px 14px; color: {t.text};
}}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.muted}; }}
QPushButton#primary {{
    background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent};
    font-weight: 600;
}}
QPushButton#primary:disabled {{
    background: {t.raised}; color: {t.muted}; border-color: {t.border};
}}
QPushButton#danger {{ color: {t.offline}; }}
QPushButton#danger:hover {{ border-color: {t.offline}; }}

QPushButton#chip {{
    background: transparent; border: 1px solid {t.border}; border-radius: 14px;
    padding: 4px 12px; color: {t.muted};
}}
QPushButton#chip:hover {{ border-color: {t.accent}; color: {t.text}; }}
QPushButton#chip:checked {{
    background: {t.accent}; border-color: {t.accent}; color: {t.on_accent};
    font-weight: 600;
}}

QPushButton#tab {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    border-radius: 0; padding: 8px 4px; margin-right: 18px; color: {t.muted};
    font-weight: 600;
}}
QPushButton#tab:hover {{ color: {t.text}; }}
QPushButton#tab:checked {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}

QFrame#panel {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; }}
QFrame#banner {{ background: {t.raised}; border: 1px solid {t.offline}; border-radius: 6px; }}
QLabel#muted {{ color: {t.muted}; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#heading {{ color: {t.muted}; font-weight: 600; }}

QStatusBar {{ background: {t.window}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QProgressBar {{ background: {t.raised}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}

QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {t.border}; border-radius: 4px; min-height: 28px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; }}
QScrollBar::handle:horizontal {{
    background: {t.border}; border-radius: 4px; min-width: 28px; margin: 2px;
}}
QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.selection}; color: {t.text}; }}
"""


def apply(app: QApplication) -> Tokens:
    """Style the whole application for the system's current appearance."""
    global _current
    _current = DARK if is_dark(app) else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    font = QFont(app.font())
    font.setPointSizeF(max(font.pointSizeF(), 10.0))
    app.setFont(font)
    return _current
