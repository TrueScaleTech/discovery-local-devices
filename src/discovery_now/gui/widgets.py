"""The small pieces every screen is built from.

One place for the shapes that repeat, so a card, a heading or a row of settings
looks the same wherever it turns up.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme


class Icon(QWidget):
    """One drawn icon, at a fixed size, in a colour from the palette."""

    def __init__(
        self,
        name: str,
        *,
        size: int = 18,
        role: str = "muted",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._role = role
        self.setFixedSize(size, size)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        colour = str(getattr(theme.current(), self._role))
        icons.paint(painter, self._name, QRectF(self.rect()).adjusted(1, 1, -1, -1), colour)


def heading(text: str, *, role: str = "heading") -> QLabel:
    """A small heading over a group of controls."""
    label = QLabel(text)
    label.setObjectName(role)
    return label


def hint(text: str) -> QLabel:
    """The sentence under a control that says what it will do."""
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def rule() -> QFrame:
    """A hairline between groups."""
    line = QFrame()
    line.setProperty("rule", "true")
    line.setFixedHeight(1)
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


class Card(QFrame):
    """A titled panel. Everything on the settings and topology screens sits in one."""

    def __init__(
        self, title: str, icon_name: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        tokens = theme.current()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(tokens.pad, tokens.pad, tokens.pad, tokens.pad)
        outer.setSpacing(tokens.gap)
        self._outer = outer

        top = QHBoxLayout()
        top.setSpacing(9)
        if icon_name:
            top.addWidget(Icon(icon_name, size=18, role="muted"))
        label = QLabel(title)
        label.setObjectName("section")
        top.addWidget(label)
        top.addStretch(1)
        outer.addLayout(top)

        self._body = QVBoxLayout()
        self._body.setSpacing(tokens.gap)
        outer.addLayout(self._body)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def restyle(self) -> None:
        """Take the spacing now in use."""
        tokens = theme.current()
        self._outer.setContentsMargins(tokens.pad, tokens.pad, tokens.pad, tokens.pad)
        self._outer.setSpacing(tokens.gap)
        self._body.setSpacing(tokens.gap)

    def add(self, widget: QWidget) -> None:
        self._body.addWidget(widget)

    def add_row(
        self,
        label: str,
        control: QWidget,
        note: str | None = None,
        *,
        wide: bool = False,
    ) -> QWidget:
        """A labelled control, with an optional sentence underneath.

        The control keeps its own width and sits at the right, so a row of
        settings reads as one column of labels and one of answers. ``wide`` is for
        the few that hold something long, such as a list of networks.
        """
        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        line = QHBoxLayout()
        line.setSpacing(12)
        name = QLabel(label)
        name.setMinimumWidth(190)
        line.addWidget(name)
        if wide:
            line.addWidget(control, 1)
        else:
            line.addStretch(1)
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignRight)
        column.addLayout(line)
        if note:
            under = hint(note)
            under.setContentsMargins(0, 0, 0, 0)
            column.addWidget(under)
        self._body.addWidget(row)
        return row


class Segmented(QWidget):
    """A row of chips where exactly one is chosen.

    Used where a dropdown would hide two or three short choices that are worth
    seeing side by side. It reports the choice as a key through ``picked``, so a
    caller never has to bind a value into a callback.

    That matters: Qt's ``clicked`` signal passes whether the button is checked,
    and a lambda with a default argument receives that in place of its default.
    Binding the value in the caller silently handed ``False`` to the handler.
    """

    picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self._row.addStretch(1)
        self._buttons: dict[str, QPushButton] = {}

    def add(self, key: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("chip")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, k=key: self.picked.emit(k))
        self._row.insertWidget(self._row.count() - 1, button)
        self._buttons[key] = button
        return button

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def choose(self, key: str) -> None:
        for name, button in self._buttons.items():
            button.setChecked(name == key)

    def chosen(self) -> str | None:
        for name, button in self._buttons.items():
            if button.isChecked():
                return name
        return None
